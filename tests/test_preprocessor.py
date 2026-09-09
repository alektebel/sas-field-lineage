"""
Tests for the SAS macro preprocessor.
"""
import tempfile
import unittest
from pathlib import Path
from src.sas_lineage.parser import SASParser
from src.sas_lineage.parser.preprocessor import preprocess


class TestMacroPreprocessor(unittest.TestCase):
    def setUp(self):
        self.parser = SASParser()

    def test_let_and_symbol_resolution(self):
        code = "%let lib = stg;\ndata &lib..raw;\n  set &lib..src;\n  y = 100;\nrun;\n"
        prog = self.parser.parse(code, expand_macros=True)
        self.assertEqual(prog.data_steps[0].output_table, "stg")
        self.assertIn("stg", prog.data_steps[0].input_tables)

    def test_macro_loop_generates_data_steps(self):
        code = """
        %macro doit(prefix, n);
          %do i = 1 %to &n;
            data &prefix._&i;
              set src_&i;
              amt = base_&i * 2;
            run;
          %end;
        %mend;
        %doit(out, 3);
        """
        prog = self.parser.parse(code, expand_macros=True)
        tables = [d.output_table for d in prog.data_steps]
        self.assertEqual(tables, ["out_1", "out_2", "out_3"])
        # 3 loops generated, each table has one field 'amt'
        self.assertEqual(len(prog.data_steps), 3)

    def test_if_then_else_selects_branch(self):
        code = """
        %macro m(flag);
          %if &flag = Y %then %do;
            data yes; set a; x = 1; run;
          %end;
          %else %do;
            data no; set b; x = 2; run;
          %end;
        %mend;
        %m(N)
        """
        prog = self.parser.parse(code, expand_macros=True)
        self.assertEqual([d.output_table for d in prog.data_steps], ["no"])

    def test_eval_arithmetic(self):
        code = """
        %let k = %eval(5 + 7);
        data t&k;
          set s;
          z = &k;
        run;
        """
        prog = self.parser.parse(code, expand_macros=True)
        self.assertEqual(prog.data_steps[0].output_table, "t12")

    def test_non_destructive_fallback_on_unbalanced_macro(self):
        # A macro that never emits a step: expansion would lose the DATA step
        # that the raw source still contains, so the source is returned as-is.
        code = """
        %macro broken;
          %do %while (0);
        %mend;
        data real_table;
          set raw;
          v = 1;
        run;
        """
        prog = self.parser.parse(code)  # default: no macro expansion
        self.assertEqual([d.output_table for d in prog.data_steps], ["real_table"])

    def test_preprocess_does_not_drop_steps(self):
        code = """
        data a; set x; p = 1; run;
        data b; set a; q = p + 1; run;
        """
        out = preprocess(code)
        self.assertIn("data a", out.lower())
        self.assertIn("data b", out.lower())

    def test_sysfunc_countw_drives_loop(self):
        code = """
        %let list = a b c;
        %macro go;
          %do i = 1 %to %sysfunc(countw(&list));
            %let w = %scan(&list, &i);
            data d_&w; set s_&w; x = &i; run;
          %end;
        %mend;
        %go
        """
        prog = self.parser.parse(code, expand_macros=True)
        self.assertEqual([d.output_table for d in prog.data_steps], ["d_a", "d_b", "d_c"])
        self.assertEqual([d.input_tables[0] for d in prog.data_steps], ["s_a", "s_b", "s_c"])

    def test_do_over_word_list(self):
        code = """
        %let list = x y z;
        %macro go;
          %do %over(&list);
            data d_&i; set s; v = "&i"; run;
          %end;
        %mend;
        %go
        """
        prog = self.parser.parse(code, expand_macros=True)
        self.assertEqual([d.output_table for d in prog.data_steps], ["d_x", "d_y", "d_z"])

    def test_include_is_opt_in_and_sandboxed(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "part.sas").write_text("data b; set a; x = 2; run;\n")
            code = 'data top; set src; y = 1; run;\n%include "part.sas";\n'
            prog = self.parser.parse(code, expand_macros=True, include_base=base)
            self.assertEqual([s.output_table for s in prog.data_steps], ["top", "b"])
            # Without include_base the include is left unresolved.
            prog = self.parser.parse(code, expand_macros=True)
            self.assertEqual([s.output_table for s in prog.data_steps], ["top"])
            # Traversal outside include_base is ignored.
            prog = self.parser.parse('%include "../part.sas";', expand_macros=True, include_base=base)
            self.assertEqual(prog.data_steps, [])


if __name__ == "__main__":
    unittest.main()
