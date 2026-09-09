"""
Tests for the web explorer payload builder.
"""
import unittest
from src.sas_lineage.parser import SASParser
from src.sas_lineage.ui import payload


class TestPayloadBuilder(unittest.TestCase):
    def setUp(self):
        self.parser = SASParser()
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
        self.program = self.parser.parse(self.sas_code)
        self.p = payload.build_payload(self.program)

    def test_nodes_edges_layers(self):
        names = {n["name"] for n in self.p["N"]}
        self.assertIn("INPUT_DATA", names)
        self.assertIn("FINAL_SALES", names)
        # golden source has no producer
        golden = [n for n in self.p["N"] if n["golden"]]
        self.assertEqual(len(golden), 1)
        # data flows source -> raw -> final -> summary
        self.assertIn(["input_data", "raw_sales"], self.p["E"])
        self.assertIn(["final_sales", "summary"], self.p["E"])
        # layers ordered source -> sink
        labels = [l["label"] for l in self.p["LAYERS"]]
        self.assertEqual(labels[0], "Golden sources")

    def test_fields_have_steps_and_inputs(self):
        self.assertTrue(self.p["F"])
        for f in self.p["F"]:
            self.assertTrue(f["steps"])
            self.assertIn("node", f)
            self.assertIn("golden", f)

    def test_profit_chain_goes_source_to_terminal(self):
        f = next((x for x in self.p["F"] if x["node"] == "final_sales" and x["name"] == "profit"), None)
        self.assertIsNotNone(f)
        fields = [s["field"] for s in f["steps"]]
        self.assertEqual(fields[-1], "profit")
        self.assertIn("revenue", fields)   # derived earlier
        self.assertIn("INPUT_DATA", f["golden"])

    def test_registers_ordered_by_column(self):
        cols = {n["register"]: n["col"] for n in self.p["N"]}
        order = [cols[r] for r in self.p["registers"]]
        self.assertEqual(order, sorted(order))


if __name__ == "__main__":
    unittest.main()
