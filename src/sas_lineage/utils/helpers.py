"""
Utility functions for SAS lineage tracking
"""
import re
from typing import List, Tuple


def normalize_field_name(name: str) -> str:
    """
    Normalize a field name (remove spaces, convert to lowercase)
    """
    return name.strip().lower()


def parse_table_field_reference(ref: str) -> Tuple[str, str]:
    """
    Parse a table.field reference
    Returns (table, field) tuple
    """
    if '.' in ref:
        parts = ref.split('.')
        return parts[0].strip(), parts[1].strip()
    return '', ref.strip()


def extract_function_calls(expression: str) -> List[str]:
    """
    Extract function calls from an expression
    Returns list of function names
    """
    pattern = r'(\w+)\s*\('
    matches = re.findall(pattern, expression)
    return matches


def is_sas_keyword(word: str) -> bool:
    """
    Check if a word is a SAS keyword
    """
    sas_keywords = {
        'data', 'set', 'merge', 'by', 'where', 'if', 'then', 'else',
        'do', 'end', 'run', 'proc', 'quit', 'output', 'delete',
        'keep', 'drop', 'rename', 'retain', 'array', 'length',
        'format', 'informat', 'label', 'sum', 'mean', 'max', 'min',
        'count', 'n', 'first', 'last', 'input', 'put', 'substr',
        'scan', 'trim', 'left', 'right', 'upcase', 'lowcase',
        'compress', 'tranwrd', 'index', 'find', 'catx', 'cats'
    }
    return word.lower() in sas_keywords


def format_field_path(field_name: str, table_name: str = None) -> str:
    """
    Format a field path for display
    """
    if table_name:
        return f"{table_name}.{field_name}"
    return field_name
