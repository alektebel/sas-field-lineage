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

    def test_unsupported_data_statement_warns(self):
        code = "data out; set src; drop temp; x = 1; run;\n"
        warnings = self.parser.parse(code).get_warnings()
        self.assertIn("unsupported", {w["kind"] for w in warnings})
        self.assertTrue(any("drop temp" in w["message"] for w in warnings))

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

    def test_two_level_name_warns(self):
        code = "data mrt.out; set mrt.src; x = 1; run;\n"
        warnings = self.parser.parse(code).get_warnings()
        self.assertTrue(any(w["kind"] == "two-level-name" for w in warnings))

    def test_unknown_top_level_statement_warns(self):
        code = "FOOBAR something;\ndata out; set src; x = 1; run;\n"
        kinds = self._kinds(code)
        self.assertIn("unknown-statement", kinds)

    def test_repeated_unsupported_statement_is_deduplicated(self):
        body = "".join(f"drop t{i};\n" for i in range(50))
        code = "data out; set src;\n" + body + "run;\n"
        unsupported = [w for w in self.parser.parse(code).get_warnings()
                       if w["kind"] == "unsupported"]
        self.assertEqual(len(unsupported), 1)


if __name__ == '__main__':
    unittest.main()
