"""
Tests for the table inventory (persistence, stage), the persistent-table
diagnostics, and the single-sheet Excel export.
"""
import tempfile
import unittest
from pathlib import Path

from src.sas_lineage.excel import HEADERS, build_rows, write_workbook
from src.sas_lineage.parser import SASParser
from src.sas_lineage.tables import (
    build_inventory, diagnose, is_persistent, libref_of, stage_of, table_graph,
)
from src.sas_lineage.ui.facts import FieldFacts

PIPELINE = """
%let lib = BSGL;
data &lib..c19; set raw.feed; qty = units; price = amt; run;
data &lib..c20; set &lib..c19; revenue = qty * price; run;
data scratch; set &lib..c20; tmp = revenue; run;
proc sort data=&lib..c20 out=&lib..c20_sorted; by revenue; run;
"""


class TestPersistence(unittest.TestCase):
    """A table is persistent when it lives outside WORK."""

    def test_libref_of(self):
        self.assertEqual(libref_of("bsgl.c20"), "bsgl")
        self.assertEqual(libref_of("sales"), "work")       # one level means WORK
        self.assertEqual(libref_of("bsgl.&tab"), "bsgl")   # member unknown, library known
        self.assertIsNone(libref_of("&lib..c20"))          # library itself unknown
        self.assertIsNone(libref_of("&out"))               # could expand to either

    def test_is_persistent(self):
        self.assertTrue(is_persistent("bsgl.c20"))
        self.assertFalse(is_persistent("sales"))
        # Unknown is a third answer: calling it transient would be a guess.
        self.assertIsNone(is_persistent("&lib..c20"))

    def test_work_prefix_is_not_persistent(self):
        # The parser folds work., so this arrives one-level.
        prog = SASParser().parse("data work.t; set src; x = 1; run;")
        self.assertIs(is_persistent(prog.data_steps[0].output_table), False)


class TestInventory(unittest.TestCase):

    def setUp(self):
        self.program = SASParser().parse(PIPELINE, expand_macros=True)
        self.inv = build_inventory(self.program)

    def test_stage_counts_from_the_golden_source(self):
        self.assertEqual(self.inv["raw.feed"].stage, 0)
        self.assertEqual(self.inv["bsgl.c19"].stage, 1)
        self.assertEqual(self.inv["bsgl.c20"].stage, 2)
        self.assertEqual(self.inv["scratch"].stage, 3)

    def test_records_who_writes_and_reads(self):
        self.assertEqual(self.inv["bsgl.c19"].written_by, ["DATA step #1"])
        self.assertEqual(self.inv["bsgl.c19"].read_by, ["DATA step #2"])
        self.assertTrue(self.inv["bsgl.c20_sorted"].is_written)
        self.assertFalse(self.inv["bsgl.c20_sorted"].is_read)

    def test_work_and_persistent_are_separated(self):
        self.assertIs(self.inv["scratch"].persistent, False)
        self.assertIs(self.inv["bsgl.c20"].persistent, True)

    def test_null_dataset_is_not_a_table(self):
        prog = SASParser().parse("data _null_; set ctrl; run;")
        self.assertNotIn("_null_", build_inventory(prog))

    def test_stage_survives_a_cycle(self):
        _tables, edges = table_graph(SASParser().parse(
            "data a; set b; x = 1; run;\ndata b; set a; y = 1; run;"))
        self.assertEqual(set(stage_of(edges)), {"a", "b"})


class TestDiagnostics(unittest.TestCase):

    def test_clean_program_reports_no_errors(self):
        prog = SASParser().parse(PIPELINE, expand_macros=True)
        report = diagnose(prog)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["libraries"], ["bsgl", "raw"])

    def test_unresolved_persistent_table_is_an_error(self):
        prog = SASParser().parse(
            "%let lib = BSGL;\ndata &lib..&tab; set &lib..c19; v = 1; run;\n",
            expand_macros=True)
        report = diagnose(prog)
        self.assertEqual([e["table"] for e in report["errors"]], ["bsgl.&tab"])
        self.assertEqual(report["errors"][0]["causes"]["tab"],
                         "never assigned in this source")

    def test_unknown_library_is_not_counted_as_a_persistent_error(self):
        # &lib..c30 may be persistent or may be WORK; claiming either is a guess.
        prog = SASParser().parse("data &lib..c30; set src; v = 1; run;", expand_macros=True)
        report = diagnose(prog)
        self.assertEqual(report["errors"], [])
        self.assertEqual([e["table"] for e in report["unknown"]], ["&lib..c30"])

    def test_causes_name_the_run_time_and_automatic_symbols(self):
        code = ("data _null_; call symput('dyn', trim(nm)); run;\n"
                "data &dyn..c30; set s; v = 1; run;\n"
                "data &syslast; set s; w = 1; run;\n")
        report = diagnose(SASParser().parse(code, expand_macros=True))
        causes = {row["table"]: row["causes"] for row in report["unknown"]}
        self.assertEqual(causes["&dyn..c30"]["dyn"], "set at run time by call symput")
        self.assertEqual(causes["&syslast"]["syslast"],
                         "SAS automatic variable, never static")

    def test_literal_symput_resolves_instead_of_erroring(self):
        code = ("data _null_; call symputx('lib', 'BSGL'); run;\n"
                "data &lib..c20; set &lib..c19; v = 1; run;\n")
        prog = SASParser().parse(code, expand_macros=True)
        self.assertEqual(prog.data_steps[1].output_table, "bsgl.c20")
        self.assertEqual(diagnose(prog)["errors"], [])

    def test_rendered_summary_is_readable(self):
        prog = SASParser().parse(
            "%let lib = BSGL;\ndata &lib..&tab; set &lib..c19; v = 1; run;\n",
            expand_macros=True)
        facts = FieldFacts(prog)
        text = facts.render_diagnostics(facts.diagnostics_packet())
        self.assertIn("Unresolved persistent tables:", text)
        self.assertIn("bsgl.&tab", text)
        self.assertIn("never assigned in this source", text)

    def test_summary_universe_covers_what_it_names(self):
        # The SLM answer is rejected unless every name it cites is in the
        # universe, so the universe must hold everything the facts expose.
        prog = SASParser().parse(PIPELINE, expand_macros=True)
        facts = FieldFacts(prog)
        pack = facts.diagnostics_packet()
        universe = facts.diagnostics_universe(pack)
        self.assertIn("bsgl.c20", universe)
        self.assertIn("bsgl", universe)


class TestExcelExport(unittest.TestCase):

    def setUp(self):
        self.program = SASParser().parse(PIPELINE, expand_macros=True)
        self.rows = build_rows(self.program)

    def test_every_table_is_in_the_one_sheet(self):
        tables = {r["table"] for r in self.rows}
        self.assertEqual(
            tables,
            {"raw.feed", "bsgl.c19", "bsgl.c20", "scratch", "bsgl.c20_sorted"})

    def test_rows_carry_stage_and_persistence(self):
        row = next(r for r in self.rows if r["field"] == "revenue")
        self.assertEqual(row["table"], "bsgl.c20")
        self.assertEqual(row["stage"], 2)
        self.assertEqual(row["persistent"], "yes")
        self.assertEqual(row["libref"], "bsgl")

    def test_flow_runs_from_the_golden_source_to_the_field(self):
        row = next(r for r in self.rows if r["field"] == "revenue")
        flow = row["flow"].split(" -> ")
        self.assertEqual(flow[-1], "bsgl.c20.revenue")
        self.assertIn("raw.feed.units", flow)
        self.assertEqual(flow[row["hop"] - 1], "bsgl.c20.revenue")

    def test_table_without_fields_still_gets_a_row(self):
        row = next(r for r in self.rows if r["table"] == "bsgl.c20_sorted")
        self.assertEqual(row["field"], "")
        self.assertIn("PROC SORT #1", row["written_by"])

    def test_rows_are_ordered_by_stage(self):
        stages = [r["stage"] for r in self.rows]
        self.assertEqual(stages, sorted(stages))

    def test_workbook_round_trips(self):
        openpyxl = __import__("openpyxl")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "lineage.xlsx"
            write_workbook(self.program, str(path))
            ws = openpyxl.load_workbook(path).active
            self.assertEqual(ws.title, "lineage")
            self.assertEqual([c.value for c in ws[1]], HEADERS)
            self.assertEqual(ws.max_row, len(self.rows) + 1)


if __name__ == "__main__":
    unittest.main()
