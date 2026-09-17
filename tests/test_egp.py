"""
Tests for extracting SAS source from uploaded .egp / archive files.
"""
import base64
import io
import json
import unittest
import zipfile

from src.sas_lineage.parser.egp import extract_sas, _decode
from src.sas_lineage.ui import server


def _make_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in entries.items():
            z.writestr(name, content)
    buf.seek(0)
    return buf.read()


class TestEgpExtraction(unittest.TestCase):
    def test_zip_with_sas_program_is_extracted_verbatim(self):
        sas = "LIBNAME mrt '/x';\ndata mrt.t1; set raw.src; x = a * 2; run;\n"
        data = _make_zip({
            "manifest.json": json.dumps({"name": "t", "detail": "x = 1; y = 2;"}),
            "programs/src.sas": sas,
        })
        source, info = extract_sas(data)
        self.assertEqual(info["format"], "zip")
        self.assertEqual(info["programs"], ["programs/src.sas"])
        self.assertIn("data mrt.t1", source)
        self.assertNotIn("manifest", source)

    def test_zip_without_sas_entry_falls_back_to_text_scan(self):
        sas = "data mylib.t; set raw.src; y = 1; run;\n"
        data = _make_zip({
            "manifest.json": json.dumps({"detail": "EAD_BALANCE = OR_DISPTO; junk"}),
            "code/entry.bin": sas,
        })
        source, info = extract_sas(data)
        self.assertEqual(info["format"], "zip")
        self.assertIn("data mylib.t", source)
        self.assertNotIn("EAD_BALANCE", source)   # manifest noise not treated as code

    def test_raw_bytes_keep_only_sas_step_blocks(self):
        blob = (
            b'{"detail": "EAD = X; Y = Z"}\n'
            b"LIBNAME mrt '/x';\n"
            b"data mrt.t1;\n  set raw.src;\n  v = a + 1;\nrun;\n"
            b"<xml>noise</xml>\n"
            b"proc sql;\n  create table mrt.t2 as select * from mrt.t1;\nquit;\n"
        )
        source, info = extract_sas(blob)
        self.assertEqual(info["format"], "text")
        self.assertIn("data mrt.t1", source)
        self.assertIn("proc sql", source)
        self.assertNotIn("<xml>", source)
        self.assertNotIn('"detail"', source)

    def test_utf16_bytes_are_decoded(self):
        sas = "data mrt.t; set raw.src; y = 1; run;\n"
        source, info = extract_sas(sas.encode("utf-16-le"))
        self.assertIn("data mrt.t", source)
        self.assertGreater(info["chars"], 0)

    def test_zip_manifest_tables_are_read_as_oracle(self):
        data = _make_zip({
            "manifest.json": json.dumps({"name": "p", "tables_produced": ["t1", "t2"]}),
            "programs/src.sas": "data lib.t1; set s; run;\n",
        })
        source, info = extract_sas(data)
        self.assertEqual(info["manifest_tables"], ["t1", "t2"])
        self.assertEqual(info["manifest_name"], "p")

    def test_zip_programs_keep_archive_order_for_cross_file_macros(self):
        use = "%mk(mrt)\n"
        definition = "%macro mk(lib);\ndata &lib..t; set src; run;\n%mend;\n"
        data = _make_zip({
            "programs/01_use.sas": use,
            "programs/02_def.sas": definition,
        })
        source, info = extract_sas(data)
        self.assertEqual(info["programs"], ["programs/01_use.sas", "programs/02_def.sas"])
        from src.sas_lineage.parser import SASParser
        program = SASParser().parse(source, expand_macros=True)
        self.assertEqual([d.output_table for d in program.data_steps], ["mrt.t"])

    def test_garbage_yields_no_source(self):
        source, info = extract_sas(b"\x00\x01\x02 not sas at all")
        self.assertEqual(source, "")
        self.assertEqual(info["chars"], 0)

    def test_decode_prefers_utf16_when_nuls_are_consistent(self):
        self.assertEqual(_decode("data x;".encode("utf-16-le")), "data x;")


class TestImportEndpointHelper(unittest.TestCase):
    def test_import_returns_source_payload_and_info(self):
        sas = "data mrt.out; set raw.src; x = 1; run;\n"
        data = _make_zip({"programs/p.sas": sas})
        payload = server._import("p.egp", base64.b64encode(data).decode(), False)
        self.assertIn("source", payload)
        self.assertIn("data mrt.out", payload["source"])
        self.assertEqual(payload["import"]["format"], "zip")
        self.assertIn("warnings", payload)

    def test_import_empty_upload_flags_a_warning(self):
        payload = server._import("empty.egp", base64.b64encode(b"nothing here").decode(), False)
        self.assertEqual(payload["source"], "")
        self.assertTrue(any(w["kind"] == "import" for w in payload["warnings"]))

    def test_import_reports_malformed_base64_gracefully(self):
        payload = server._import("x.egp", "!!!!not base64!!!!", False)
        self.assertIn("error", payload)
        self.assertNotIn("source", payload)


if __name__ == "__main__":
    unittest.main()
