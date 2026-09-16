"""
Tests for resolving table names to literals.

Two things have to hold for a lineage graph to be trustworthy: the macro pass
must resolve every name it *can* resolve regardless of where the definition
sits in the file, and the parser must read the whole literal it is handed --
libref included -- instead of the first word of it.
"""
import unittest

from src.sas_lineage.parser import SASParser
from src.sas_lineage.parser.preprocessor import preprocess, preprocess_ex


class TestTopologicalMacroResolution(unittest.TestCase):
    """Phase 1: order of appearance must stop deciding what resolves."""

    def setUp(self):
        self.parser = SASParser()

    def test_let_resolves_forward_reference(self):
        # &b is used above its own %let. SAS stores the unresolved text and
        # resolves it at use time, so the literal is core_x, not _x.
        code = "%let a = &b._x;\n%let b = core;\ndata &a; set z; q = 1; run;\n"
        prog = self.parser.parse(code, expand_macros=True)
        self.assertEqual(prog.data_steps[0].output_table, "core_x")

    def test_let_chain_resolves_in_dependency_order(self):
        code = ("%let full = &mid._f;\n%let mid = &base._m;\n%let base = risk;\n"
                "data &full; set s; q = 1; run;\n")
        out, report = preprocess_ex(code)
        self.assertEqual(report["symbol_order"], ["base", "mid", "full"])
        self.assertIn("data risk_m_f", out)

    def test_reassigned_symbol_keeps_sequential_semantics(self):
        # A name assigned twice is state, not a definition: a topological order
        # would have to pick one assignment and would be wrong for the other.
        code = ("%let x = 1;\ndata a&x; set s; v = 1; run;\n"
                "%let x = 2;\ndata b&x; set s; v = 1; run;\n")
        prog = self.parser.parse(code, expand_macros=True)
        self.assertEqual([d.output_table for d in prog.data_steps], ["a1", "b2"])

    def test_macro_invoked_above_its_definition(self):
        code = ("%cargar(a)\n"
                "%macro cargar(x);\n  data out_&x; set in_&x; v = 1; run;\n%mend;\n")
        prog = self.parser.parse(code, expand_macros=True)
        self.assertEqual([d.output_table for d in prog.data_steps], ["out_a"])
        self.assertEqual(prog.data_steps[0].input_tables, ["in_a"])

    def test_double_ampersand_indirection_names_the_variable(self):
        # &&tab&i must resolve the variable called tab1, not concatenate two
        # separate lookups.
        code = "%let tab1 = ventas;\n%let i = 1;\ndata &&tab&i; set s; v = 1; run;\n"
        prog = self.parser.parse(code, expand_macros=True)
        self.assertEqual(prog.data_steps[0].output_table, "ventas")

    def test_symbol_cycle_is_reported_and_survivable(self):
        code = "%let p = &q;\n%let q = &p;\ndata t; set s; v = 1; run;\n"
        out, report = preprocess_ex(code)
        self.assertEqual(sorted(report["symbol_cycles"]), ["p", "q"])
        self.assertIn("data t", out)

    def test_recursive_macro_is_reported_as_a_cycle(self):
        code = ("%macro r(n);\n  %if &n > 0 %then %do;\n    data d&n; set s; v = 1; run;\n"
                "    %r(%eval(&n - 1))\n  %end;\n%mend;\n%r(2)\n")
        out, report = preprocess_ex(code)
        self.assertIn("r", report["macro_cycles"])
        self.assertIn("data d2", out)

    def test_local_scope_does_not_leak_between_invocations(self):
        code = ("%macro m(t);\n  %local tmp;\n  %let tmp = &t._w;\n"
                "  data &tmp; set s; v = 1; run;\n%mend;\n%m(a) %m(b)\n")
        prog = self.parser.parse(code, expand_macros=True)
        self.assertEqual([d.output_table for d in prog.data_steps], ["a_w", "b_w"])

    def test_unresolved_symbol_keeps_its_text_and_is_reported(self):
        # Collapsing an unknown &name to "" silently invents a table name;
        # keeping the text makes the gap visible instead.
        out, report = preprocess_ex("data &nodef._t; set s; v = 1; run;\n")
        self.assertIn("&nodef._t", out)
        self.assertIn("nodef", report["unresolved_symbols"])

    def test_unknown_macro_call_is_not_deleted(self):
        out, report = preprocess_ex("%autocall_thing(x)\ndata t; set s; v = 1; run;\n")
        self.assertIn("%autocall_thing(x)", out)
        self.assertIn("autocall_thing", report["unresolved_macros"])

    def test_str_resolves_while_nrstr_masks(self):
        # %str masks special characters but still resolves &; %nrstr is the
        # one that keeps the reference literal.
        self.assertIn("data stg.tab", preprocess(
            "%let lib = stg;\n%let t = %str(&lib..tab);\ndata &t; set s; v = 1; run;\n"))
        self.assertIn("&notme", preprocess(
            "%let raw = %nrstr(&notme);\ndata &raw; set s; v = 1; run;\n"))

    def test_global_declaration_does_not_leak_into_the_code(self):
        code = "%global outlib;\n%let outlib = mart;\ndata &outlib..res; set s; v = 1; run;\n"
        out = preprocess(code)
        self.assertNotIn("outlib;", out)
        self.assertIn("data mart.res", out)


class TestDataStepTableNames(unittest.TestCase):
    """Phase 2: read the whole literal, not its first word."""

    def setUp(self):
        self.parser = SASParser()

    def test_two_level_names_are_kept_whole(self):
        prog = self.parser.parse("data stg.raw; set src.base; x = 1; run;")
        self.assertEqual(prog.data_steps[0].output_table, "stg.raw")
        self.assertEqual(prog.data_steps[0].input_tables, ["src.base"])

    def test_multiple_outputs_are_all_captured(self):
        prog = self.parser.parse("data mart.a mart.b; set raw.c; x = 1; run;")
        self.assertEqual(prog.data_steps[0].output_tables, ["mart.a", "mart.b"])
        self.assertEqual(prog.data_steps[0].output_table, "mart.a")

    def test_dataset_options_are_not_table_names(self):
        prog = self.parser.parse(
            "data mart.res(keep=x y); set raw.src(where=(x>0)) raw.b(in=b); x = 1; run;")
        self.assertEqual(prog.data_steps[0].output_tables, ["mart.res"])
        self.assertEqual(prog.data_steps[0].input_tables, ["raw.src", "raw.b"])

    def test_set_options_are_not_table_names(self):
        prog = self.parser.parse("data t; set src end=eof nobs=n; x = 1; run;")
        self.assertEqual(prog.data_steps[0].input_tables, ["src"])

    def test_merge_reads_every_dataset(self):
        prog = self.parser.parse(
            "data m; merge a.one (in=i1) a.two (in=i2); by k; x = 1; run;")
        self.assertEqual(prog.data_steps[0].input_tables, ["a.one", "a.two"])
        self.assertEqual(prog.data_steps[0].merge_keys, ["k"])

    def test_explicit_work_libref_is_folded(self):
        # work.sales and sales are the same dataset; two nodes would be a lie.
        prog = self.parser.parse("data work.sales; set sales_in; x = 1; run;\n"
                                 "data downstream; set sales; y = 2; run;")
        self.assertEqual(prog.data_steps[0].output_table, "sales")
        self.assertIn("sales", prog.data_steps[1].input_tables)

    def test_step_options_after_slash_are_not_tables(self):
        prog = self.parser.parse("data v / view=v; set src; x = 1; run;")
        self.assertEqual(prog.data_steps[0].output_tables, ["v"])

    def test_names_are_case_folded(self):
        prog = self.parser.parse("DATA MART.Res; SET RAW.Src; x = 1; RUN;")
        self.assertEqual(prog.data_steps[0].output_table, "mart.res")
        self.assertEqual(prog.data_steps[0].input_tables, ["raw.src"])

    def test_unresolved_table_name_is_flagged(self):
        prog = self.parser.parse("data &missing._t; set src; x = 1; run;", expand_macros=True)
        step = prog.data_steps[0]
        self.assertEqual(step.metadata["unresolved_tables"], ["&missing._t"])


class TestProcTableNames(unittest.TestCase):

    def setUp(self):
        self.parser = SASParser()

    def test_options_on_the_proc_statement_itself(self):
        # data=/out= live on the PROC line; scanning from the next statement
        # missed them entirely.
        prog = self.parser.parse("proc sort data=lib.a out=lib.b nodupkey; by k; run;")
        step = prog.proc_steps[0]
        self.assertEqual(step.input_table, "lib.a")
        self.assertEqual(step.output_table, "lib.b")

    def test_output_out_with_dataset_options(self):
        prog = self.parser.parse(
            "proc summary data=lib.c nway; class k; output out=lib.d (drop=_type_) sum=; run;")
        step = prog.proc_steps[0]
        self.assertEqual(step.input_tables, ["lib.c"])
        self.assertEqual(step.output_tables, ["lib.d"])

    def test_proc_append_base_is_an_output(self):
        prog = self.parser.parse("proc append base=hist.all data=stg.new; run;")
        step = prog.proc_steps[0]
        self.assertEqual(step.output_tables, ["hist.all"])
        self.assertEqual(step.input_tables, ["stg.new"])

    def test_sql_create_table_with_join(self):
        prog = self.parser.parse(
            "proc sql;\n"
            "  create table out.t as select a.k from in.s as a inner join in.u b on a.k=b.k;\n"
            "quit;")
        step = prog.proc_steps[0]
        self.assertEqual(step.output_tables, ["out.t"])
        self.assertEqual(step.input_tables, ["in.s", "in.u"])

    def test_sql_statements_do_not_share_sources(self):
        prog = self.parser.parse(
            "proc sql;\n"
            "  create table out.t as select * from in.s;\n"
            "  insert into out.log select * from audit.rows;\n"
            "quit;")
        pairs = [(s.output_tables, s.input_tables) for s in prog.proc_steps]
        self.assertEqual(pairs, [(["out.t"], ["in.s"]), (["out.log"], ["audit.rows"])])

    def test_sql_subquery_source_is_found(self):
        prog = self.parser.parse(
            "proc sql;\n"
            "  create table agg as select k from (select * from deep.src) where k > 0;\n"
            "quit;")
        self.assertEqual(prog.proc_steps[0].input_tables, ["deep.src"])

    def test_macro_resolved_proc_names_reach_the_graph(self):
        code = ("%let env = prod;\n%let mart = &env._mart;\n"
                "proc sort data=stg.ventas out=&mart..ventas; by k; run;\n")
        prog = self.parser.parse(code, expand_macros=True)
        self.assertEqual(prog.proc_steps[0].output_table, "prod_mart.ventas")
        self.assertIn("prod_mart.ventas", prog.get_tables())


if __name__ == "__main__":
    unittest.main()
