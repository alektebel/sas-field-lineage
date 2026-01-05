"""
Tests for lineage tracker
"""
import unittest
from src.sas_lineage.parser import SASParser
from src.sas_lineage.lineage import LineageTracker


class TestLineageTracker(unittest.TestCase):
    
    def setUp(self):
        self.parser = SASParser()
        self.sas_code = """
        DATA step1;
            SET input;
            revenue = quantity * price;
        RUN;
        
        DATA step2;
            SET step1;
            profit = revenue - cost;
        RUN;
        """
        self.program = self.parser.parse(self.sas_code)
        self.tracker = LineageTracker(self.program)
    
    def test_query_field_found(self):
        """Test querying a field that exists"""
        result = self.tracker.query_field('revenue')
        
        self.assertTrue(result['found'])
        self.assertEqual(result['field_name'], 'revenue')
        self.assertTrue(result['count'] > 0)
    
    def test_query_field_not_found(self):
        """Test querying a field that doesn't exist"""
        result = self.tracker.query_field('nonexistent')
        
        self.assertFalse(result['found'])
    
    def test_browse_fields(self):
        """Test browsing all fields"""
        result = self.tracker.browse_fields()
        
        self.assertIn('stats', result)
        self.assertIn('fields_by_table', result)
        self.assertTrue(result['stats']['total_fields'] > 0)
    
    def test_lineage_graph_creation(self):
        """Test that lineage graph is created"""
        self.assertIsNotNone(self.tracker.graph)
        self.assertTrue(len(self.tracker.graph.nodes()) > 0)
    
    def test_export_graph_dot(self):
        """Test DOT graph export"""
        dot_output = self.tracker.export_graph_dot()
        
        self.assertIn('digraph lineage', dot_output)
        self.assertIn('revenue', dot_output)


if __name__ == '__main__':
    unittest.main()
