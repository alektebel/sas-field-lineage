"""Behavioral fixtures for the first table-resolution compatibility milestone."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.sas_lineage.analysis import build_table_report
from src.sas_lineage.cli import main
from src.sas_lineage.parser import SASParser, SASCodeCleaner
from src.sas_lineage.parser.scanner import scan_statements


class TestTableAnalysis(unittest.TestCase):
    def parse(self, code, **kwargs):
        return SASParser().parse(code, **kwargs)

    def test_qualified_names_options_and_multiple_outputs(self):
        program = self.parse('''data mart.sales(keep=id) mart.audit;
            merge raw.orders(in=a) raw.customers(rename=(cid=id));
            by id; run;''')
        step = program.data_steps[0]
        self.assertEqual(step.output_tables, ['mart.sales', 'mart.audit'])
        self.assertEqual(step.input_tables, ['raw.orders', 'raw.customers'])
        self.assertEqual(program.get_tables(), {'mart.sales', 'mart.audit', 'raw.orders', 'raw.customers'})
        self.assertEqual(program.diagnostics, [])

    def test_proc_header_and_step_interleaving(self):
        program = self.parse('''data work.stage; set raw.orders; run;
            proc sort data=work.stage out=work.sorted; by id; run;
            data mart.sales; set work.sorted; run;''')
        self.assertEqual(program.steps, [program.data_steps[0], program.proc_steps[0], program.data_steps[1]])
        self.assertEqual(program.proc_steps[0].input_table, 'work.stage')
        self.assertEqual(program.proc_steps[0].output_table, 'work.sorted')
        report = build_table_report(program)
        self.assertEqual(report['status'], 'static_subset')
        self.assertEqual([(x['producer'], x['consumer']) for x in report['graph']['step_dependencies']],
                         [('step:1', 'step:2'), ('step:2', 'step:3')])

    def test_semicolons_comments_and_keyword_prefixes_in_strings(self):
        program = self.parse('''/* ignored */ data out; * inline comment;
            set raw;
            label="a; /* literal */ it's fine";
            other='it''s; valid'; running=1;
            run; data next; set out; run;''')
        self.assertEqual([x.output_table for x in program.data_steps], ['out', 'next'])
        fields = program.data_steps[0].fields
        self.assertEqual([x.name for x in fields], ['label', 'other', 'running'])
        self.assertEqual(fields[0].expression, '"a; /* literal */ it\'s fine"')
        self.assertEqual(fields[0].source_line, 3)

    def test_name_literals_and_options_do_not_become_tables(self):
        program = self.parse("data mart.'Sales; report'n; set raw.'Order history'n(keep=id) end=done; run;")
        self.assertEqual(program.get_tables(), {"mart.'Sales; report'n", "raw.'Order history'n"})
        report = build_table_report(program)
        self.assertEqual({x['member'] for x in report['graph']['datasets']}, {'sales; report', 'order history'})

    def test_datalines4_is_opaque_until_four_semicolons(self):
        code = '''data rows; input text $;
        datalines4;
        data fake; set secret; run;
        text;with;semicolons;
        ;;;;
        run;
        data real; set rows; run;'''
        program = self.parse(code)
        self.assertEqual(program.get_tables(), {'rows', 'real'})
        self.assertEqual(len(program.steps), 2)
        self.assertEqual(program.data_steps[1].source_line, 7)

    def test_datalines_ends_on_its_delimiter_line(self):
        code = 'data rows; input id; datalines;\n1\n2\n;\nrun; data out; set rows; run;'
        self.assertEqual(self.parse(code).get_tables(), {'rows', 'out'})

    def test_unknown_name_is_symbolic_and_never_a_concrete_graph_node(self):
        program = self.parse('data sales_&period.; set raw.sales; run;', expand_macros=True)
        self.assertEqual(program.data_steps[0].output_table, 'sales_&period.')
        report = build_table_report(program)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['summary']['symbolic_references'], 1)
        self.assertEqual([x['member'] for x in report['graph']['datasets']], ['sales'])
        self.assertIn('unresolved_table_name', {x['code'] for x in report['diagnostics']})

    def test_runtime_symput_is_reported_and_null_is_not_a_dataset(self):
        code = "data _null_; call symputx('target', 'sales_202609'); run; data &target; set raw; run;"
        program = self.parse(code, expand_macros=True)
        self.assertEqual(program.get_tables(), {'&target', 'raw'})
        self.assertEqual(len(program.steps), 2)
        self.assertIn('runtime_macro_effect', {x.code for x in program.diagnostics})
        self.assertEqual(program.steps[1].table_references[0].resolution, 'symbolic')

    def test_double_quoted_symbolic_name_literal(self):
        program = self.parse('data mart."sales_&period"n; run;')
        self.assertEqual(program.steps[0].table_references[0].resolution, 'symbolic')
        literal = self.parse("data mart.'sales_&period'n; run;")
        self.assertEqual(literal.steps[0].table_references[0].resolution, 'literal')

    def test_uninvoked_macro_body_is_not_an_executed_step(self):
        program = self.parse('%macro m; data phantom; set secret; run; %mend; data real; run;')
        self.assertEqual(program.get_tables(), {'real'})
        self.assertIn('unexpanded_macro', {x.code for x in program.diagnostics})

    def test_repeated_writes_create_versions_without_self_dependency(self):
        program = self.parse('data work.x; set raw.x; run; data work.x; set work.x; run; proc sort data=work.x; by id; run;')
        report = build_table_report(program)
        versions = [x['version'] for x in report['graph']['datasets'] if x['library'] == 'work']
        self.assertEqual(versions, [1, 2, 3])
        self.assertEqual([(x['producer'], x['consumer']) for x in report['graph']['step_dependencies']],
                         [('step:1', 'step:2'), ('step:2', 'step:3')])
        self.assertFalse(report['graph']['safe_to_schedule'])

    def test_library_default_is_explicit_and_case_insensitive(self):
        program = self.parse('data X; run; data out; set WORK.x; run;')
        self.assertEqual(build_table_report(program)['graph']['step_dependencies'], [])
        report = build_table_report(program, default_library='WORK')
        self.assertEqual(len(report['graph']['step_dependencies']), 1)

    def test_quoted_dots_do_not_alias_qualified_names(self):
        program = self.parse("data 'work.x'n; run; data out; set work.x; run;")
        self.assertEqual(build_table_report(program, default_library='work')['graph']['step_dependencies'], [])

    def test_statement_boundary_can_terminate_a_step(self):
        program = self.parse('data a; set source; data b; set a; proc print data=b; run;')
        self.assertEqual(len(program.steps), 3)
        self.assertEqual(program.data_steps[0].input_tables, ['source'])

    def test_prefix_list_is_not_a_literal_dataset(self):
        program = self.parse('data out; set raw.sales:; run;')
        self.assertEqual(program.data_steps[0].input_tables, [])
        self.assertIn('unsupported_dataset_list', {x.code for x in program.diagnostics})

    def test_sql_recovers_simple_names_but_marks_partial_coverage(self):
        program = self.parse('proc sql; create table mart.out as select a.id from raw.a as a join raw.b as b on a.id=b.id; quit;')
        self.assertEqual(program.get_tables(), {'mart.out', 'raw.a', 'raw.b'})
        self.assertEqual(build_table_report(program)['status'], 'partial')

    def test_sort_dupout_does_not_hide_the_in_place_write(self):
        program = self.parse('proc sort data=work.x dupout=work.duplicates nodupkey; by id; run;')
        self.assertEqual({(x.name, x.access) for x in program.steps[0].table_references},
                         {('work.x', 'read'), ('work.x', 'write'), ('work.duplicates', 'write')})

    def test_conditional_io_and_ods_make_coverage_partial(self):
        program = self.parse('ods output summary=work.stats; data out; if flag then set raw.input; run;')
        self.assertEqual(build_table_report(program)['status'], 'partial')
        self.assertEqual({x.code for x in program.diagnostics}, {'unsupported_io', 'conditional_dataset_io'})

    def test_scanner_retains_offsets_and_reports_malformed_input(self):
        source = '/* comment */\ndata work.x;\nx="not closed'
        statements, issues = scan_statements(source)
        self.assertEqual(source[statements[0].start:statements[0].end], 'data work.x;')
        self.assertEqual(statements[0].line, 2)
        self.assertEqual({x.code for x in issues}, {'unterminated_string', 'unterminated_statement'})

    def test_trailing_escape_is_not_a_closing_quote(self):
        _, issues = scan_statements("data x; value='unclosed''")
        self.assertIn('unterminated_string', {x.code for x in issues})

    def test_unsupported_and_session_dependent_names_never_become_literal_nodes(self):
        program = self.parse('data server.schema.table; set _last_; run;')
        report = build_table_report(program)
        self.assertEqual(report['summary']['unknown_references'], 2)
        self.assertEqual(report['graph']['datasets'], [])
        self.assertEqual(report['status'], 'partial')

    def test_comment_cleaner_preserves_offsets_and_literal_comments(self):
        code = 'data x; /* comment\nline */ x="/*not comment*/"; run;'
        clean = SASCodeCleaner.remove_comments(code)
        self.assertEqual(len(clean), len(code))
        self.assertEqual(clean.count('\n'), code.count('\n'))
        self.assertIn('"/*not comment*/"', clean)

    def test_parser_reuse_does_not_leak_diagnostics(self):
        parser = SASParser()
        parser.parse('data &unknown; run;')
        self.assertEqual(parser.parse('data known; run;').diagnostics, [])


class TestTableReportCLI(unittest.TestCase):
    def test_cli_help_formats_macro_percent_signs(self):
        stdout = io.StringIO()
        with patch('sys.argv', ['sas-lineage', '--help']):
            with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as result:
                main()
        self.assertEqual(result.exception.code, 0)
        self.assertIn('%macro', stdout.getvalue())
        self.assertIn('--tables', stdout.getvalue())

    def test_json_stdout_and_strict_exit_with_saved_report(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'job.sas'
            output = Path(directory) / 'report.json'
            source.write_text('data out_&period.; set raw.sales; run;', encoding='utf-8')
            stdout = io.StringIO()
            with patch('sys.argv', ['sas-lineage', str(source), '--tables', '--strict', '-o', str(output)]):
                with contextlib.redirect_stdout(stdout):
                    status = main()
            self.assertEqual(status, 2)
            report = json.loads(stdout.getvalue())
            self.assertEqual(report['status'], 'partial')
            self.assertEqual(report, json.loads(output.read_text()))


if __name__ == '__main__':
    unittest.main()
