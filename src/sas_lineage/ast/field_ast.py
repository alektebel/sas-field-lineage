"""
Abstract Syntax Tree representation for SAS field dependencies
"""
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field
from enum import Enum


class FieldOperationType(Enum):
    """Types of operations on fields"""
    ASSIGNMENT = "assignment"
    CALCULATION = "calculation"
    FUNCTION = "function"
    MERGE = "merge"
    FILTER = "filter"
    RENAME = "rename"
    DROP = "drop"
    KEEP = "keep"


@dataclass
class FieldNode:
    """
    Represents a field in the lineage tree with its dependencies
    """
    name: str
    table: Optional[str] = None
    operation: Optional[FieldOperationType] = None
    expression: Optional[str] = None
    dependencies: List['FieldNode'] = field(default_factory=list)
    source_line: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __hash__(self):
        return hash((self.name, self.table))
    
    def __eq__(self, other):
        if not isinstance(other, FieldNode):
            return False
        return self.name == other.name and self.table == other.table
    
    def add_dependency(self, field_node: 'FieldNode'):
        """Add a dependency to this field"""
        if field_node not in self.dependencies:
            self.dependencies.append(field_node)
    
    def get_all_dependencies(self) -> Set['FieldNode']:
        """Recursively get all dependencies"""
        deps = set()
        for dep in self.dependencies:
            deps.add(dep)
            deps.update(dep.get_all_dependencies())
        return deps
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "name": self.name,
            "table": self.table,
            "operation": self.operation.value if self.operation else None,
            "expression": self.expression,
            "dependencies": [dep.name for dep in self.dependencies],
            "source_line": self.source_line,
            "metadata": self.metadata
        }
    
    def __repr__(self):
        table_str = f"{self.table}." if self.table else ""
        return f"FieldNode({table_str}{self.name})"


@dataclass
class DataStepNode:
    """Represents a SAS DATA step"""
    output_table: str
    input_tables: List[str] = field(default_factory=list)
    fields: List[FieldNode] = field(default_factory=list)
    where_clause: Optional[str] = None
    merge_keys: List[str] = field(default_factory=list)
    
    def add_field(self, field_node: FieldNode):
        """Add a field to this data step"""
        self.fields.append(field_node)
    
    def get_field(self, name: str) -> Optional[FieldNode]:
        """Get a field by name"""
        for f in self.fields:
            if f.name == name:
                return f
        return None


@dataclass
class ProcStepNode:
    """Represents a SAS PROC step"""
    proc_name: str
    input_table: Optional[str] = None
    output_table: Optional[str] = None
    fields: List[FieldNode] = field(default_factory=list)
    options: Dict[str, Any] = field(default_factory=dict)


class SASProgram:
    """Represents a complete SAS program with all data and proc steps"""
    
    def __init__(self):
        self.data_steps: List[DataStepNode] = []
        self.proc_steps: List[ProcStepNode] = []
        self.all_fields: Dict[str, List[FieldNode]] = {}  # field_name -> [FieldNode instances]
    
    def add_data_step(self, data_step: DataStepNode):
        """Add a data step to the program"""
        self.data_steps.append(data_step)
        # Index fields for quick lookup
        for field_node in data_step.fields:
            if field_node.name not in self.all_fields:
                self.all_fields[field_node.name] = []
            self.all_fields[field_node.name].append(field_node)
    
    def add_proc_step(self, proc_step: ProcStepNode):
        """Add a proc step to the program"""
        self.proc_steps.append(proc_step)
    
    def find_field(self, field_name: str, table_name: Optional[str] = None) -> List[FieldNode]:
        """Find all instances of a field by name and optionally table"""
        results = self.all_fields.get(field_name, [])
        if table_name:
            results = [f for f in results if f.table == table_name]
        return results
    
    def get_all_fields(self) -> List[FieldNode]:
        """Get all fields from all data steps"""
        all_fields = []
        for field_list in self.all_fields.values():
            all_fields.extend(field_list)
        return all_fields
    
    def get_tables(self) -> Set[str]:
        """Get all table names in the program"""
        tables = set()
        for ds in self.data_steps:
            tables.add(ds.output_table)
            tables.update(ds.input_tables)
        for ps in self.proc_steps:
            if ps.input_table:
                tables.add(ps.input_table)
            if ps.output_table:
                tables.add(ps.output_table)
        return tables
