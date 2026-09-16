"""Build a table-resolution report and versioned logical dataset graph.

The graph describes extracted effects in source order. It is not a scheduler:
physical library aliases, control flow, external effects and runtime state
must be resolved before independent execution can be inferred.
"""
from typing import Dict, Optional, Tuple

from ..ast.field_ast import DataStepNode, SASProgram
from ..parser.scanner import tokenize


def _identity(name: str, default_library: Optional[str]) -> Tuple[Optional[str], str]:
    parts = []
    for token in tokenize(name):
        if token.text == '.':
            continue
        part = token.text
        if token.kind == 'name_literal':
            quote = part[0]
            part = part[1:-2].replace(quote * 2, quote)
        parts.append(part.lower())
    if len(parts) == 1:
        return default_library.lower() if default_library else None, parts[0]
    return parts[0], parts[1]


def build_table_report(program: SASProgram, source_name: Optional[str] = None,
                       default_library: Optional[str] = None) -> Dict:
    """Serialize ordered table evidence and read-before-write dataset versions.

    One-level names are kept in an unspecified default library unless the
    caller supplies it. Distinct library aliases are not guessed equivalent.
    Symbolic references never create concrete dataset nodes or graph edges.
    """
    if default_library and (len(tokenize(default_library)) != 1
                            or tokenize(default_library)[0].kind != 'word'):
        raise ValueError('default_library must be a literal SAS library identifier')
    steps, datasets, edges, dependencies = [], [], [], []
    versions = {}
    counters = {}
    producers = {}
    literal_count = symbolic_count = unknown_count = 0
    partial = bool(program.diagnostics)
    evidence = 'heuristic_expansion' if program.coordinate_space == 'expanded' else 'source'

    def dataset(key, version, external):
        node_id = 'dataset:' + str(len(datasets) + 1)
        datasets.append({'id': node_id, 'library': key[0], 'member': key[1],
                         'version': version, 'external': external})
        return node_id

    for index, step in enumerate(program.steps):
        step_id = 'step:' + str(index + 1)
        references = []
        # All reads see the state at step entry, even though a DATA header
        # syntactically mentions its output before its SET input.
        for reference in step.table_references:
            item = reference.to_dict()
            item['evidence'] = evidence
            item['dataset_version'] = None
            references.append(item)
            if reference.resolution != 'literal':
                if reference.resolution == 'symbolic':
                    symbolic_count += 1
                else:
                    unknown_count += 1
                continue
            literal_count += 1
            if reference.access != 'read':
                continue
            key = _identity(reference.name, default_library)
            if key not in versions:
                versions[key] = dataset(key, 0, True)
                counters[key] = 0
            node_id = versions[key]
            item['dataset_version'] = node_id
            edges.append({'from': node_id, 'to': step_id, 'kind': 'read'})
            if key in producers:
                dependency = {'producer': producers[key], 'consumer': step_id, 'dataset_version': node_id}
                if dependency not in dependencies:
                    dependencies.append(dependency)
        written = {}
        for reference, item in zip(step.table_references, references):
            if reference.resolution != 'literal' or reference.access != 'write':
                continue
            key = _identity(reference.name, default_library)
            if key not in written:
                counters[key] = counters.get(key, 0) + 1
                node_id = dataset(key, counters[key], False)
                written[key] = node_id
                edges.append({'from': step_id, 'to': node_id, 'kind': 'write'})
            item['dataset_version'] = written[key]
        for key, node_id in written.items():
            versions[key] = node_id
            producers[key] = step_id
        steps.append({'id': step_id, 'kind': 'data' if isinstance(step, DataStepNode) else 'proc',
                      'operation': 'DATA' if isinstance(step, DataStepNode) else step.proc_name,
                      'source_line': step.source_line, 'references': references})

    return {
        'schema_version': 1,
        'source': source_name,
        'status': 'partial' if partial or symbolic_count or unknown_count else 'static_subset',
        'coordinate_space': program.coordinate_space,
        'default_library': default_library,
        'summary': {'steps': len(steps), 'literal_references': literal_count,
                    'symbolic_references': symbolic_count, 'unknown_references': unknown_count,
                    'diagnostics': len(program.diagnostics)},
        'steps': steps,
        'diagnostics': [diagnostic.to_dict() for diagnostic in program.diagnostics],
        'graph': {'identity': 'logical_library_and_member',
                  'status': 'candidate' if partial or symbolic_count or unknown_count else 'static_subset',
                  'datasets': datasets, 'edges': edges, 'step_dependencies': dependencies,
                  'source_order': [step['id'] for step in steps], 'safe_to_schedule': False},
        'limitations': [
            'Literal names are source evidence, not observations of runtime execution.',
            'Physical library aliases and session configuration are not resolved.',
            'This graph does not establish safe program scheduling or parallel execution.',
            'Field expressions remain heuristic and are outside this table-resolution report.',
        ],
    }
