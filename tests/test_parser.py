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


if __name__ == '__main__':
    unittest.main()
