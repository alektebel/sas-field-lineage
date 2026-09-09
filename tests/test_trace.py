"""
Tests for the per-hop value trace engine.
"""
import unittest
from src.sas_lineage.parser import SASParser
from src.sas_lineage.ui.payload import build_payload, ProgramIndex
from src.sas_lineage.ui.trace import run_field_trace, eval_expr


class TestTraceEngine(unittest.TestCase):
    def setUp(self):
        self.sas_code = """
        DATA raw_sales;
            SET input_data;
            revenue = quantity * price;
            discount_amount = revenue * discount_rate;
        RUN;
        DATA final_sales;
            SET raw_sales;
            net_revenue = revenue - discount_amount;
            profit = net_revenue - cost;
            profit_margin = profit / net_revenue;
        RUN;
        DATA summary;
            SET final_sales;
            total_profit = SUM(profit);
            avg_margin = MEAN(profit_margin);
        RUN;
        """
        self.program = SASParser().parse(self.sas_code)
        self.index = ProgramIndex(self.program)

    def test_eval_expr_arithmetic(self):
        self.assertEqual(eval_expr("quantity * price", {"quantity": 10, "price": 5}), 50)

    def test_eval_expr_sas_function(self):
        self.assertEqual(eval_expr("SUM(profit)", {"profit": 250}), 250)

    def test_profit_value_at_every_hop(self):
        vals = {
            "input_data.quantity": 10, "input_data.price": 50,
            "input_data.discount_rate": 0.1, "raw_sales.cost": 200,
        }
        rows = run_field_trace("final_sales.profit", vals, self.index)
        # rows are ordered source -> terminal
        self.assertEqual(rows[-1]["field"], "profit")
        self.assertEqual(rows[-1]["value"], 250.0)
        # earlier derived field feeds a later one
        self.assertAlmostEqual(rows[0]["value"], 500.0)   # revenue = 10 * 50

    def test_aggregate_propagation(self):
        vals = {
            "input_data.quantity": 10, "input_data.price": 50,
            "input_data.discount_rate": 0.1, "raw_sales.cost": 200,
        }
        rows = run_field_trace("summary.total_profit", vals, self.index)
        self.assertEqual(rows[-1]["field"], "total_profit")
        self.assertEqual(rows[-1]["value"], 250.0)

    def test_unknown_field_returns_empty(self):
        self.assertEqual(run_field_trace("does.not.exist", {}, self.index), [])


if __name__ == "__main__":
    unittest.main()
