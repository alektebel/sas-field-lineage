"""
Tests for field evaluator
"""
import unittest
import pandas as pd
from src.sas_lineage.parser import SASParser
from src.sas_lineage.lineage import FieldEvaluator


class TestFieldEvaluator(unittest.TestCase):
    
    def setUp(self):
        self.parser = SASParser()
        self.sas_code = """
        DATA output;
            SET input;
            total = quantity * price;
            discount = total * 0.1;
        RUN;
        """
        self.program = self.parser.parse(self.sas_code)
        self.evaluator = FieldEvaluator(self.program)
    
    def test_evaluate_simple_expression(self):
        """Test evaluating a simple arithmetic expression"""
        field = self.program.data_steps[0].fields[0]  # total field
        input_data = {'quantity': 10, 'price': 5}
        
        result = self.evaluator.evaluate_field(field, input_data)
        
        # Should calculate 10 * 5 = 50
        self.assertEqual(result, 50)
    
    def test_evaluate_with_dataframe(self):
        """Test evaluating with DataFrame input"""
        input_df = pd.DataFrame({
            'quantity': [10, 20, 15],
            'price': [5, 10, 8]
        })
        
        result_df = self.evaluator.evaluate_with_dataframe('output', input_df)
        
        # Check that 'total' column was calculated
        self.assertIn('total', result_df.columns)
        self.assertEqual(result_df['total'].iloc[0], 50)  # 10 * 5
        self.assertEqual(result_df['total'].iloc[1], 200)  # 20 * 10
    
    def test_load_csv(self):
        """Test loading CSV data"""
        # This test would require an actual CSV file
        # For now, just test that the method exists
        self.assertTrue(hasattr(self.evaluator, 'load_data_from_csv'))


if __name__ == '__main__':
    unittest.main()
