"""Tests for the deterministic fact packets shared with the SLM explainer."""
import unittest

from src.sas_lineage.parser import SASParser
from src.sas_lineage.ui.facts import FieldFacts, user_message, make_question

CODE = """
DATA raw_sales;
    SET input_data;
    revenue = quantity * price;
    discount_amount = revenue * discount_rate;
RUN;

DATA final_sales;
    SET raw_sales;
    net_revenue = revenue - discount_amount;
    profit = net_revenue - cost;
RUN;

DATA summary;
    SET final_sales;
    total_profit = SUM(profit);
RUN;
"""


class TestFieldFacts(unittest.TestCase):
    def setUp(self):
        self.facts = FieldFacts(SASParser().parse(CODE))

    def test_construction_gold_cites_only_packet_fields(self):
        pack = self.facts.packet("construction", "final_sales.profit")
        gold = self.facts.render_answer(pack)
        universe = {t.lower() for t in self.facts.packet_universe(pack)}
        import re
        cited = {t.lower() for t in re.findall(r"[A-Za-z_]\w*\.[A-Za-z_]\w*", gold)}
        self.assertTrue(cited <= universe)
        self.assertEqual(self.facts.expected_entities(pack)[0] & cited, cited)
        self.assertIn("net_revenue - cost", gold)

    def test_affected_yes_gives_path(self):
        pack = self.facts.packet("affected", "summary.total_profit", "final_sales.net_revenue")
        gold = self.facts.render_answer(pack)
        ents, yn = self.facts.expected_entities(pack)
        self.assertEqual(yn, "YES")
        self.assertTrue(gold.startswith("YES."))
        self.assertIn("final_sales.profit", ents)

    def test_affected_no(self):
        pack = self.facts.packet("affected", "raw_sales.revenue", "final_sales.profit")
        gold = self.facts.render_answer(pack)
        self.assertEqual(self.facts.expected_entities(pack)[1], "NO")
        self.assertTrue(gold.startswith("NO."))

    def test_downstream_terminal_field(self):
        pack = self.facts.packet("downstream", "summary.total_profit")
        gold = self.facts.render_answer(pack)
        self.assertIn("No downstream use", gold)

    def test_unknown_fields_rejected(self):
        self.assertIsNone(self.facts.packet("construction", "nope.field"))
        self.assertIsNone(self.facts.packet("affected", "final_sales.profit", "nope.field"))

    def test_user_message_and_question_roundtrip(self):
        import random
        pack = self.facts.packet("downstream", "final_sales.net_revenue")
        q = make_question("downstream", "final_sales.net_revenue", None, random.Random(3))
        msg = user_message(pack, q)
        self.assertIn("QUESTION:", msg)
        self.assertIn('"flows"', msg)



class TestModelAnswerGuard(unittest.TestCase):
    """The leak check must not reject an answer for naming a real table."""

    def test_token_regex_matches_a_three_part_field_id(self):
        from src.sas_lineage.ui.server import _FIELD_TOKEN_RE
        # Now that two-level table names are kept, a field id is
        # libref.member.field; a two-part pattern captured only libref.member.
        self.assertIn("bsgl.c20.revenue",
                      _FIELD_TOKEN_RE.findall("1. bsgl.c20.revenue = qty * price"))

    def test_a_faithful_answer_passes_the_guard(self):
        from src.sas_lineage.parser import SASParser
        from src.sas_lineage.ui.facts import FieldFacts
        from src.sas_lineage.ui.server import _FIELD_TOKEN_RE
        prog = SASParser().parse(
            "data bsgl.c19; set raw.feed; qty = units; run;\n"
            "data bsgl.c20; set bsgl.c19; revenue = qty; run;")
        facts = FieldFacts(prog)
        pack = facts.packet("construction", "bsgl.c20.revenue")
        self.assertIsNotNone(pack)
        universe = {u.lower() for u in facts.packet_universe(pack)}
        cited = {t.lower() for t in _FIELD_TOKEN_RE.findall(facts.render_answer(pack))}
        self.assertTrue(cited)
        # Before the fix this set difference was non-empty for every program
        # using librefs, so the SLM answer was always thrown away.
        self.assertTrue(cited <= universe, f"rejected: {sorted(cited - universe)}")


if __name__ == "__main__":
    unittest.main()
