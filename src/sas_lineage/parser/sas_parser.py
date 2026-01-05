"""
Simplified SAS parser using regex patterns
This parser handles common SAS DATA step and PROC step patterns
"""
import re
from typing import List, Optional, Tuple, Dict
from ..ast.field_ast import (
    FieldNode, FieldOperationType, DataStepNode, 
    ProcStepNode, SASProgram
)

# Common SAS keywords and functions that should not be treated as field references
SAS_KEYWORDS = {
    'sum', 'mean', 'max', 'min', 'count', 'put', 'input', 
    'substr', 'trim', 'left', 'right', 'upcase', 'lowcase',
    'if', 'then', 'else', 'do', 'end', 'where', 'and', 'or',
    'data', 'set', 'merge', 'by', 'run', 'proc', 'quit'
}


class SASParser:
    """
    Parser for SAS code that extracts field lineage information
    """
    
    def __init__(self):
        self.current_line = 0
        
    def parse(self, sas_code: str) -> SASProgram:
        """
        Parse SAS code and return a SASProgram with field lineage
        """
        program = SASProgram()
        lines = sas_code.split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            self.current_line = i + 1
            
            # Skip comments and empty lines
            if not line or line.startswith('*') or line.startswith('/*'):
                i += 1
                continue
            
            # Detect DATA step
            if line.upper().startswith('DATA '):
                data_step, end_line = self._parse_data_step(lines, i)
                if data_step:
                    program.add_data_step(data_step)
                i = end_line + 1
                continue
            
            # Detect PROC step
            if line.upper().startswith('PROC '):
                proc_step, end_line = self._parse_proc_step(lines, i)
                if proc_step:
                    program.add_proc_step(proc_step)
                i = end_line + 1
                continue
            
            i += 1
        
        return program
    
    def _parse_data_step(self, lines: List[str], start_line: int) -> Tuple[Optional[DataStepNode], int]:
        """
        Parse a DATA step and extract field information
        """
        # Extract output table name
        first_line = lines[start_line].strip()
        match = re.search(r'DATA\s+(\w+)', first_line, re.IGNORECASE)
        if not match:
            return None, start_line
        
        output_table = match.group(1)
        data_step = DataStepNode(output_table=output_table)
        
        # Find the end of the data step
        end_line = start_line
        step_lines = []
        for i in range(start_line, len(lines)):
            line = lines[i].strip()
            step_lines.append(line)
            if line.upper() == 'RUN;' or line.upper().startswith('RUN;'):
                end_line = i
                break
        
        # Parse SET/MERGE statements for input tables
        for line in step_lines:
            # SET statement
            set_match = re.search(r'SET\s+([\w\s]+?);', line, re.IGNORECASE)
            if set_match:
                tables = [t.strip() for t in set_match.group(1).split()]
                data_step.input_tables.extend(tables)
            
            # MERGE statement
            merge_match = re.search(r'MERGE\s+([\w\s]+?);', line, re.IGNORECASE)
            if merge_match:
                tables = [t.strip() for t in merge_match.group(1).split()]
                data_step.input_tables.extend(tables)
            
            # BY statement (for merge keys)
            by_match = re.search(r'BY\s+([\w\s]+?);', line, re.IGNORECASE)
            if by_match:
                keys = [k.strip() for k in by_match.group(1).split()]
                data_step.merge_keys.extend(keys)
        
        # Parse field assignments
        for i, line in enumerate(step_lines):
            # Field assignment: field = expression;
            assignment_match = re.search(r'(\w+)\s*=\s*([^;]+);', line)
            if assignment_match:
                field_name = assignment_match.group(1)
                expression = assignment_match.group(2).strip()
                
                field_node = FieldNode(
                    name=field_name,
                    table=output_table,
                    operation=FieldOperationType.ASSIGNMENT,
                    expression=expression,
                    source_line=start_line + i + 1
                )
                
                # Extract dependencies from expression
                deps = self._extract_field_references(expression, data_step.input_tables)
                for dep_name, dep_table in deps:
                    dep_node = FieldNode(name=dep_name, table=dep_table)
                    field_node.add_dependency(dep_node)
                
                data_step.add_field(field_node)
        
        # Handle implicit field passing (fields from SET/MERGE that aren't reassigned)
        # This is a simplified approach
        
        return data_step, end_line
    
    def _parse_proc_step(self, lines: List[str], start_line: int) -> Tuple[Optional[ProcStepNode], int]:
        """
        Parse a PROC step (simplified)
        """
        first_line = lines[start_line].strip()
        
        # Extract PROC name
        match = re.search(r'PROC\s+(\w+)', first_line, re.IGNORECASE)
        if not match:
            return None, start_line
        
        proc_name = match.group(1).upper()
        proc_step = ProcStepNode(proc_name=proc_name)
        
        # Find end of proc step
        end_line = start_line
        for i in range(start_line, len(lines)):
            line = lines[i].strip()
            if line.upper() == 'RUN;' or line.upper().startswith('RUN;'):
                end_line = i
                break
            
            # Extract DATA= option
            data_match = re.search(r'DATA\s*=\s*(\w+)', line, re.IGNORECASE)
            if data_match:
                proc_step.input_table = data_match.group(1)
            
            # Extract OUT= option
            out_match = re.search(r'OUT\s*=\s*(\w+)', line, re.IGNORECASE)
            if out_match:
                proc_step.output_table = out_match.group(1)
        
        return proc_step, end_line
    
    def _extract_field_references(self, expression: str, source_tables: List[str]) -> List[Tuple[str, Optional[str]]]:
        """
        Extract field references from an expression
        Returns list of (field_name, table_name) tuples
        """
        references = []
        
        # Match field names (simple identifiers)
        # Look for table.field or just field
        qualified_refs = re.findall(r'(\w+)\.(\w+)', expression)
        for table, field in qualified_refs:
            references.append((field, table))
        
        # Find unqualified field references
        # Remove function names and operators
        cleaned_expr = re.sub(r'(\w+)\s*\(', '', expression)  # Remove function calls
        tokens = re.findall(r'\b([a-zA-Z_]\w*)\b', cleaned_expr)
        
        # Filter out SAS keywords and functions
        for token in tokens:
            if token.lower() not in SAS_KEYWORDS and not token.isdigit():
                # Try to infer table from source tables
                # Note: This defaults to first table which may be ambiguous
                table = source_tables[0] if source_tables else None
                if (token, table) not in references:
                    references.append((token, table))
        
        return references


class SASCodeCleaner:
    """
    Utility to clean and preprocess SAS code
    """
    
    @staticmethod
    def remove_comments(code: str) -> str:
        """Remove comments from SAS code"""
        # Remove /* */ style comments
        code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
        # Remove * style comments (line comments)
        code = re.sub(r'^\s*\*[^;]*;', '', code, flags=re.MULTILINE)
        return code
    
    @staticmethod
    def normalize_whitespace(code: str) -> str:
        """Normalize whitespace in SAS code"""
        # Replace multiple spaces with single space
        code = re.sub(r'[ \t]+', ' ', code)
        return code
