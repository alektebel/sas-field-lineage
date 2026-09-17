"""
Tests for the persistent-library table report (inventory + xlsx export).
"""
import io
import unittest
import zipfile

from src.sas_lineage.report import build_inventory, inventory_sheets, write_xlsx
from src.sas_lineage.report.xlsx import _col_letter
from src.sas_lineage.parser.preprocessor import expand_for_report, linear_expand


class TestInventory(unittest.TestCase):
    def _names(self, code):
        inv = build_inventory(code)
        return {t["name"] for t in inv["tables"]}, inv

    def test_libname_declarations_captured(self):
        code = "libname stg BASE '/data/stg';\nlibname mrt \"sasdata/mart\";\n"
        inv = build_inventory(code)
        libs = {l["libref"]: l for l in inv["libraries"]}
        self.assertEqual(libs["stg"]["engine"], "BASE")
        self.assertEqual(libs["stg"]["path"], "/data/stg")
        self.assertEqual(libs["mrt"]["path"], "sasdata/mart")
        self.assertTrue(libs["mrt"]["declared"])

    def test_data_step_persistent_but_not_work(self):
        code = (
            "data work.temp; set a; x = 1; run;\n"
            "data stg.raw; set a; x = 1; run;\n"
            "data local_only; set a; x = 1; run;\n"
        )
        names, inv = self._names(code)
        self.assertEqual(names, {"stg.raw"})
        self.assertEqual(inv["tables"][0]["input_tables"], "a")

    def test_proc_sql_create_table_and_view(self):
        code = (
            "proc sql;\n"
            "  create table mrt.dim as select * from stg.src;\n"
            "  create view mrt.v as select * from mrt.dim;\n"
            "quit;\n"
        )
        names, inv = self._names(code)
        self.assertEqual(names, {"mrt.dim", "mrt.v"})
        kinds = {t["name"]: t["created_by"] for t in inv["tables"]}
        self.assertEqual(kinds["mrt.dim"], "PROC SQL CREATE TABLE")
        self.assertEqual(kinds["mrt.v"], "PROC SQL CREATE VIEW")
        dim = next(t for t in inv["tables"] if t["name"] == "mrt.dim")
        self.assertEqual(dim["input_tables"], "stg.src")

    def test_proc_out_options(self):
        code = (
            "proc sort data=mrt.final out=mrt.sorted; by z; run;\n"
            "proc means data=mrt.sorted; output out=mrt.stats mean=avg; run;\n"
            "proc append base=mrt.acc data=mrt.new; run;\n"
        )
        names, inv = self._names(code)
        self.assertEqual(names, {"mrt.sorted", "mrt.stats", "mrt.acc"})
        by_name = {t["name"]: t for t in inv["tables"]}
        self.assertEqual(by_name["mrt.sorted"]["created_by"], "PROC SORT")
        self.assertEqual(by_name["mrt.stats"]["created_by"], "PROC MEANS")
        self.assertEqual(by_name["mrt.acc"]["created_by"], "PROC APPEND")

    def test_macro_loop_prefix_resolved(self):
        code = """
        libname mrt 'x';
        %let prefix = clm;
        %macro build(lib);
          %do i = 1 %to 2;
            data &lib..&prefix._&i;
              set stg.src_&i;
              amount = value * 2;
            run;
          %end;
        %mend;
        %build(mrt)
        """
        names, inv = self._names(code)
        self.assertEqual(names, {"mrt.clm_1", "mrt.clm_2"})
        for table in inv["tables"]:
            self.assertTrue(table["macro_built"])
            self.assertTrue(table["resolved"])
        self.assertEqual(inv["stats"]["macro_built"], 2)

    def test_unresolved_macro_is_flagged_not_dropped(self):
        code = "data &missinglib..orphan; set stg.x; q = 1; run;\n"
        names, inv = self._names(code)
        self.assertEqual(names, {"&missinglib.orphan"})
        self.assertEqual(inv["stats"]["unresolved"], 1)
        self.assertFalse(inv["tables"][0]["resolved"])

    def test_undeclared_non_work_library_is_persistent(self):
        code = "data otherlib.t; set a; x = 1; run;\n"
        names, inv = self._names(code)
        self.assertEqual(names, {"otherlib.t"})
        self.assertFalse(inv["tables"][0]["declared_library"])

    def test_prefixed_two_level_target_resolves(self):
        code = ("%let prefijo_output = LIBNAME.C111;\n"
                "data &prefijo_output._tabla; set src.a; x = 1; run;\n"
                "proc sql; create table &prefijo_output._tabla2 as select * from src.b; quit;\n")
        names, inv = self._names(code)
        self.assertEqual(names, {"LIBNAME.C111_tabla", "LIBNAME.C111_tabla2"})
        row = next(t for t in inv["tables"] if t["table"] == "C111_tabla")
        self.assertEqual(row["library"], "LIBNAME")

    def test_macro_used_before_definition_is_reported(self):
        code = "%build(mrt)\n%macro build(lib);\ndata &lib..t; set src; run;\n%mend;\n"
        names, inv = self._names(code)
        self.assertEqual(names, {"mrt.t"})

    def test_forward_let_chain_resolves_library(self):
        code = "%let a=&b;\n%let b=&c;\n%let c=mrt;\ndata &a..t; set src; run;\n"
        names, _ = self._names(code)
        self.assertEqual(names, {"mrt.t"})

    def test_audit_is_complete_for_resolvable_macros(self):
        code = ("%let p = LIBNAME.C111;\n"
                "%macro b(l); data &l..&p._t; set s; run; %mend;\n"
                "%b(mrt)\n")
        inv = build_inventory(code)
        self.assertTrue(inv["audit"]["complete"])
        self.assertIn("b", inv["audit"]["macros_defined"])
        self.assertIn("p", inv["audit"]["symbols_defined"])
        self.assertEqual(inv["audit"]["residual_refs"], [])

    def test_audit_flags_unresolved_reference(self):
        inv = build_inventory("data &missinglib.t; set s; run;\n")
        self.assertFalse(inv["audit"]["complete"])
        self.assertIn("&missinglib", inv["audit"]["residual_refs"])

    def test_assurance_classifies_manifest_tables(self):
        from src.sas_lineage.report import assurance, parsed_outputs
        code = ("%let p = LIBNAME.C111;\n"
                "data work.tmp; set s; x = 1; run;\n"
                "data &p._out; set work.tmp; y = 1; run;\n")
        inv = build_inventory(code)
        report = assurance(inv, ["tmp", "C111_out", "never_made"], parsed_outputs(code))
        self.assertTrue(report["substitution_complete"])
        self.assertIn("C111_out", report["matched"])
        self.assertIn("tmp", report["parsed_not_persistent"])
        self.assertIn("never_made", report["missing"])

    def test_expand_disabled_keeps_raw_names(self):
        code = "%let p = clm;\ndata mrt.&p._1; set x; run;\n"
        inv = build_inventory(code, expand=False)
        names = {t["name"] for t in inv["tables"]}
        self.assertIn("mrt.&p._1", names)


class TestMacroLinearExpansion(unittest.TestCase):
    def test_linear_expand_resolves_let_and_prefix(self):
        code = "%let lib = stg;\n%let prefix = clm;\ndata &lib..&prefix._1; set x; run;\n"
        out = linear_expand(code)
        self.assertIn("data stg.clm_1;", out)
        self.assertNotIn("%let", out)

    def test_linear_expand_keeps_unknown(self):
        out = linear_expand("data &missing.base; set x; run;\n")
        self.assertIn("&missing.base", out)

    def test_expand_for_report_expands_macros_and_keeps_unknown(self):
        code = (
            "%macro go(lib);\n"
            "%do i=1 %to 2;\n"
            "data &lib..t_&i; set s_&i; run;\n"
            "%end;\n%mend;\n%go(mrt)\n"
            "data &nope.x; set y; run;\n"
        )
        out = expand_for_report(code)
        self.assertIn("data mrt.t_1;", out)
        self.assertIn("data mrt.t_2;", out)
        self.assertIn("&nope.x", out)


class TestXlsxWriter(unittest.TestCase):
    def _workbook(self, sheets):
        buf = io.BytesIO()
        write_xlsx(buf, sheets)
        buf.seek(0)
        return zipfile.ZipFile(buf)

    def test_writes_valid_zip_with_expected_parts(self):
        z = self._workbook([("Persistent tables", [["A", "B"], ["1", "2"]])])
        self.assertIsNone(z.testzip())
        for part in ("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml",
                     "xl/_rels/workbook.xml.rels", "xl/styles.xml",
                     "xl/worksheets/sheet1.xml"):
            self.assertIn(part, z.namelist())

    def test_cell_values_and_bold_header(self):
        z = self._workbook([("T", [["Library", "Table"], ["mrt", "final"]])])
        xml = z.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn("Library", xml)
        self.assertIn("mrt", xml)
        self.assertIn('s="1"', xml)          # header style
        self.assertIn('t="inlineStr"', xml)

    def test_multiple_sheets(self):
        z = self._workbook([("One", [["x"]]), ("Two", [["y"], ["z"]])])
        self.assertIn("xl/worksheets/sheet2.xml", z.namelist())
        wb = z.read("xl/workbook.xml").decode()
        self.assertIn('name="One"', wb)
        self.assertIn('name="Two"', wb)

    def test_column_letters(self):
        self.assertEqual(_col_letter(1), "A")
        self.assertEqual(_col_letter(26), "Z")
        self.assertEqual(_col_letter(27), "AA")
        self.assertEqual(_col_letter(28), "AB")

    def test_all_tables_share_one_sheet_with_the_division_as_a_column(self):
        inv = build_inventory("libname mrt 'x';\ndata mrt.t; set raw.src; x=1; run;\n")
        sheets = inventory_sheets(inv)
        names = [name for name, _rows in sheets]
        self.assertEqual(names, ["Persistent tables", "Libraries", "Summary", "Assurance"])
        rows = next(rows for name, rows in sheets if name == "Persistent tables")
        self.assertIn("Division", rows[0])
        self.assertIn("Library", rows[0])
        self.assertIn("Table", rows[0])
        # one hop from its source -> Landing, now a cell rather than a tab
        self.assertIn("Landing", rows[1])

    def test_multi_stage_flow_is_ordered_within_the_single_sheet(self):
        code = (
            "libname mrt 'x';\n"
            "data mrt.stg; set golden.src; a = 1; run;\n"
            "data mrt.mart; set mrt.stg; b = a + 1; run;\n"
            "data mrt.rep; set mrt.mart; c = b + 1; run;\n"
        )
        inv = build_inventory(code)
        divisions = [d["name"] for d in inv["divisions"]]
        # Only persistent writes are reported, so the golden input has no sheet.
        self.assertEqual(divisions, ["Landing", "Curated", "Marts"])
        by_name = {t["name"]: t["division"] for t in inv["tables"]}
        self.assertEqual(by_name["mrt.stg"], "Landing")
        self.assertEqual(by_name["mrt.mart"], "Curated")
        self.assertEqual(by_name["mrt.rep"], "Marts")
        sheets = inventory_sheets(inv)
        # Every table lives in one sheet; a division is a column value, not a
        # tab, so sorting and filtering work across the whole pipeline.
        self.assertEqual([name for name, _rows in sheets],
                         ["Persistent tables", "Libraries", "Summary", "Assurance"])
        rows = sheets[0][1]
        self.assertEqual(len(rows), len(inv["tables"]) + 1)
        # ...and the sheet still reads source -> sink.
        div_col = rows[0].index("Division")
        self.assertEqual([r[div_col] for r in rows[1:]],
                         ["Landing", "Curated", "Marts"])


if __name__ == "__main__":
    unittest.main()
