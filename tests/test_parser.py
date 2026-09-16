"""
Tests for SAS parser
"""
import unittest
from src.sas_lineage.parser import SASParser
from src.sas_lineage.ast import FieldOperationType


class TestSASParser(unittest.TestCase):
    
    def setUp(self):
        self.parser = SASParser()
    
    def test_parse_simple_data_step(self):
        """Test parsing a simple DATA step"""
        sas_code = """
        DATA output;
            SET input;
            new_field = old_field * 2;
        RUN;
        """
        
        program = self.parser.parse(sas_code)
        
        self.assertEqual(len(program.data_steps), 1)
        self.assertEqual(program.data_steps[0].output_table, 'output')
        self.assertEqual(program.data_steps[0].input_tables, ['input'])
    
    def test_parse_field_assignment(self):
        """Test parsing field assignments"""
        sas_code = """
        DATA test;
            SET source;
            result = value1 + value2;
        RUN;
        """
        
        program = self.parser.parse(sas_code)
        fields = program.data_steps[0].fields
        
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0].name, 'result')
        self.assertEqual(fields[0].expression, 'value1 + value2')
        self.assertEqual(fields[0].operation, FieldOperationType.ASSIGNMENT)
    
    def test_parse_merge(self):
        """Test parsing MERGE statement"""
        sas_code = """
        DATA merged;
            MERGE table1 table2;
            BY id;
        RUN;
        """
        
        program = self.parser.parse(sas_code)
        data_step = program.data_steps[0]
        
        self.assertEqual(data_step.output_table, 'merged')
        self.assertIn('table1', data_step.input_tables)
        self.assertIn('table2', data_step.input_tables)
        self.assertEqual(data_step.merge_keys, ['id'])
    
    def test_library_qualified_target_kept_whole(self):
        sas_code = "DATA work.contracts; SET raw.contracts; x = 1; RUN;"
        program = self.parser.parse(sas_code)
        self.assertEqual(program.data_steps[0].output_table, "work.contracts")
        self.assertIn("raw.contracts", program.data_steps[0].input_tables)

    def test_merge_reads_every_dataset_despite_options(self):
        # ``[\w.\s]+`` stopped at the first "(", so the second input never
        # reached the graph.
        code = "DATA m; MERGE a.one (IN=i1) a.two (IN=i2); BY k; x = 1; RUN;"
        step = self.parser.parse(code).data_steps[0]
        self.assertEqual(step.input_tables, ["a.one", "a.two"])

    def test_dataset_options_are_not_part_of_the_target_name(self):
        code = "DATA mrt.res(keep=x y); SET raw.src(where=(x>0)); x = 1; RUN;"
        step = self.parser.parse(code).data_steps[0]
        self.assertEqual(step.output_table, "mrt.res")
        self.assertEqual(step.input_tables, ["raw.src"])

    def test_set_options_are_not_table_names(self):
        code = "DATA t; SET src END=eof NOBS=n; x = 1; RUN;"
        self.assertEqual(self.parser.parse(code).data_steps[0].input_tables, ["src"])

    def test_parenthesis_inside_a_literal_does_not_swallow_the_next_dataset(self):
        code = 'DATA t; SET a(where=(x="(")) b; v = 1; RUN;'
        self.assertEqual(self.parser.parse(code).data_steps[0].input_tables, ["a", "b"])

    def test_proc_statement_options_are_read(self):
        # data=/out= sit on the PROC line; the scan used to start after it.
        step = self.parser.parse("PROC SORT DATA=lib.a OUT=lib.b NODUPKEY; BY k; RUN;").proc_steps[0]
        self.assertEqual(step.input_table, "lib.a")
        self.assertEqual(step.output_table, "lib.b")

    def test_proc_append_base_is_the_output(self):
        step = self.parser.parse("PROC APPEND BASE=hist.all DATA=stg.new; RUN;").proc_steps[0]
        self.assertEqual(step.output_table, "hist.all")
        self.assertEqual(step.input_table, "stg.new")

    def test_proc_option_keeps_an_unresolved_macro_name(self):
        step = self.parser.parse("PROC SORT DATA=&lib..a OUT=&lib..b; BY k; RUN;").proc_steps[0]
        self.assertEqual(step.input_table, "&lib..a")

    def test_multiple_data_steps(self):
        """Test parsing multiple DATA steps"""
        sas_code = """
        DATA step1;
            SET input;
            field1 = value * 2;
        RUN;
        
        DATA step2;
            SET step1;
            field2 = field1 + 10;
        RUN;
        """
        
        program = self.parser.parse(sas_code)
        
        self.assertEqual(len(program.data_steps), 2)
        self.assertEqual(program.data_steps[0].output_table, 'step1')
        self.assertEqual(program.data_steps[1].output_table, 'step2')


class TestFieldDependencies(unittest.TestCase):
    
    def setUp(self):
        self.parser = SASParser()
    
    def test_field_dependencies(self):
        """Test extraction of field dependencies"""
        sas_code = """
        DATA output;
            SET input;
            total = price * quantity;
            discount = total * 0.1;
        RUN;
        """
        
        program = self.parser.parse(sas_code)
        fields = program.data_steps[0].fields
        
        # Find the discount field
        discount_field = next(f for f in fields if f.name == 'discount')
        
        # Check that it has dependencies
        self.assertTrue(len(discount_field.dependencies) > 0)


class TestParseWarnings(unittest.TestCase):

    def setUp(self):
        self.parser = SASParser()

    def _kinds(self, code):
        return {w["kind"] for w in self.parser.parse(code).get_warnings()}

    def test_clean_program_has_no_warnings(self):
        code = "data out; set src; x = y * 2; run;\n"
        self.assertEqual(self.parser.parse(code).get_warnings(), [])

    def test_benign_top_level_statements_do_not_warn(self):
        code = "libname mrt '/x';\noptions validvarname=any;\ntitle 't';\nrun;\n"
        self.assertEqual(self.parser.parse(code).get_warnings(), [])

    def test_unsupported_data_statement_warns_once_per_step(self):
        code = "data out; set src; drop temp; keep a; if x then y = 1; run;\n"
        warnings = [w for w in self.parser.parse(code).get_warnings()
                    if w["kind"] == "unsupported"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("drop", warnings[0]["message"])
        self.assertIn("keep", warnings[0]["message"])

    def test_declarative_data_statements_do_not_warn(self):
        code = ("data out; set src; length id $32; format amount 12.2; "
                "label amount='a'; retain total 0; x = 1; run;\n")
        self.assertEqual(self.parser.parse(code).get_warnings(), [])

    def test_read_only_procs_are_not_parsed_or_warned(self):
        code = "proc print data=work.x; var a b; run;\ndata out; set src; v = 1; run;\n"
        program = self.parser.parse(code)
        self.assertEqual([p.proc_name for p in program.proc_steps], [])
        self.assertEqual(program.get_warnings(), [])

    def test_coverage_stat_reported(self):
        code = "FOOBAR x;\ndata out; set src; v = 1; run;\n"
        program = self.parser.parse(code)
        self.assertIn("coverage", program.stats)
        self.assertLess(program.stats["coverage"], 100.0)

    def test_unterminated_step_warns(self):
        code = "data out; set src; x = 1;\n"
        kinds = self._kinds(code)
        self.assertIn("unterminated", kinds)

    def test_missing_terminator_before_next_step_warns(self):
        code = "data a; set x; v = 1;\ndata b; set a; w = 2; run;\n"
        warnings = self.parser.parse(code).get_warnings()
        self.assertTrue(any(w["kind"] == "unterminated" for w in warnings))
        # the following step is still parsed
        self.assertEqual([d.output_table for d in self.parser.parse(code).data_steps], ["a", "b"])

    def test_two_level_name_is_kept_and_not_warned(self):
        code = "data mrt.out; set mrt.src; x = 1; run;\n"
        program = self.parser.parse(code)
        self.assertEqual(program.data_steps[0].output_table, "mrt.out")
        self.assertNotIn("two-level-name", {w["kind"] for w in program.get_warnings()})

    def test_unknown_top_level_statement_warns(self):
        code = "FOOBAR something;\ndata out; set src; x = 1; run;\n"
        kinds = self._kinds(code)
        self.assertIn("unknown-statement", kinds)

    def test_top_level_assignments_are_aggregated(self):
        code = "a = 1;\nb = 2;\nc = 3;\ndata ok; set s; v = 1; run;\n"
        warnings = [w for w in self.parser.parse(code).get_warnings()
                    if w["kind"] == "out-of-step"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("3 statement", warnings[0]["message"])

    def test_repeated_unsupported_statement_is_deduplicated(self):
        body = "".join(f"drop t{i};\n" for i in range(50))
        code = "data out; set src;\n" + body + "run;\n"
        unsupported = [w for w in self.parser.parse(code).get_warnings()
                       if w["kind"] == "unsupported"]
        self.assertEqual(len(unsupported), 1)


if __name__ == '__main__':
    unittest.main()
