"""
Tests for the stage-by-stage parse trace.
"""
import unittest

from src.sas_lineage.debug import (
    expansion_diff, macro_table, suspect_tables, symbol_table, trace, unresolved_refs,
)


class TestSymbolStage(unittest.TestCase):

    def test_reports_what_each_symbol_resolved_to(self):
        syms = symbol_table("%let lib = BSGL;\n%let t = &lib..C20;\ndata &t; set s; x=1; run;")
        self.assertEqual(syms["lib"], "BSGL")
        self.assertEqual(syms["t"], "BSGL.C20")

    def test_literal_symput_shows_up_as_a_symbol(self):
        syms = symbol_table("data _null_; call symputx('env','PROD'); run;\n")
        self.assertEqual(syms["env"], "PROD")

    def test_names_that_never_resolved_are_listed(self):
        self.assertEqual(unresolved_refs("data &nope..C20; set s; x=1; run;"), ["nope"])

    def test_registered_macros_are_listed(self):
        code = "%macro cargar(x); data d_&x; set s; v=1; run; %mend;\n%cargar(a)\n"
        self.assertEqual(macro_table(code), ["cargar"])


class TestExpansionStage(unittest.TestCase):

    def test_diff_shows_only_the_rewritten_lines(self):
        diff = expansion_diff("%let lib = BSGL;\ndata &lib..C20; set s; x=1; run;\n")
        body = "\n".join(diff)
        self.assertIn("+data BSGL.C20", body)
        self.assertIn("-data &lib..C20", body)

    def test_no_macros_means_no_diff(self):
        self.assertEqual(expansion_diff("data a; set b; x=1; run;\n"), [])


class TestSuspectStage(unittest.TestCase):
    """The section worth reading first: names that are not real."""

    def test_detects_a_name_invented_from_an_unresolved_macro(self):
        # &nope. collapses to nothing and the leftover parses as a table, so
        # the graph gains a plausible-looking table that does not exist.
        suspects = suspect_tables("data t; set &nope..C19; x=1; run;")
        self.assertEqual(len(suspects), 1)
        self.assertEqual(suspects[0]["reported"], "C19")
        self.assertEqual(suspects[0]["unresolved_form"], "&nope..C19")
        self.assertEqual(suspects[0]["missing"], ["nope"])

    def test_detects_a_partially_resolved_name(self):
        # The worst case: &per collapses, the trailing dot is trimmed, and the
        # *library* is reported as the table. Nothing downstream can tell
        # "BSGL" here from a real one-level dataset called BSGL.
        code = "%let lib = BSGL;\ndata &lib..&per; set s; x=1; run;"
        suspects = suspect_tables(code)
        self.assertEqual(suspects[0]["reported"], "BSGL")
        self.assertEqual(suspects[0]["unresolved_form"], "BSGL.&per")
        self.assertIn("per", suspects[0]["missing"])

    def test_a_fully_resolved_program_has_no_suspects(self):
        code = "%let lib = BSGL;\ndata &lib..C20; set &lib..C19; x=1; run;"
        self.assertEqual(suspect_tables(code), [])

    def test_a_program_without_macros_has_no_suspects(self):
        self.assertEqual(suspect_tables("data a; set b; x=1; run;"), [])


class TestTraceOutput(unittest.TestCase):

    def test_trace_has_every_stage(self):
        out = trace("%let lib = BSGL;\ndata &lib..C20; set &nope..C19; x=1; run;\n",
                    show_statements=True)
        for heading in ("1. SYMBOLS", "2. EXPANSION", "3. STATEMENTS",
                        "4. TABLES", "5. SUSPECT"):
            self.assertIn(heading, out)

    def test_statements_are_optional(self):
        out = trace("data a; set b; x=1; run;\n")
        self.assertNotIn("3. STATEMENTS", out)

    def test_trace_survives_a_broken_program(self):
        # A trace that crashes on bad input is useless exactly when needed.
        out = trace("%macro broken; data t; set s; x=1;\n")
        self.assertIn("1. SYMBOLS", out)


if __name__ == "__main__":
    unittest.main()
