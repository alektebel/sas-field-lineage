"""
Field lineage tracker with query and browse capabilities
"""
from typing import List, Dict, Optional, Set, Any
import networkx as nx
from ..ast.field_ast import FieldNode, SASProgram, DataStepNode


class LineageTracker:
    """
    Track and query field-level lineage in SAS programs
    """
    
    def __init__(self, program: SASProgram):
        self.program = program
        self.graph = self._build_lineage_graph()
    
    def _build_lineage_graph(self) -> nx.DiGraph:
        """
        Build a directed graph representing field lineage
        """
        graph = nx.DiGraph()
        
        # Add all fields as nodes
        for field in self.program.get_all_fields():
            node_id = self._get_node_id(field)
            graph.add_node(node_id, field=field)
            
            # Add edges for dependencies
            for dep in field.dependencies:
                dep_id = self._get_node_id(dep)
                graph.add_node(dep_id, field=dep)
                graph.add_edge(dep_id, node_id)
        
        return graph
    
    def _get_node_id(self, field: FieldNode) -> str:
        """Generate unique node ID for a field"""
        table_prefix = f"{field.table}." if field.table else ""
        return f"{table_prefix}{field.name}"
    
    def query_field(self, field_name: str, table_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Query for a specific field and return its lineage information
        
        Args:
            field_name: Name of the field to query
            table_name: Optional table name to narrow the search
        
        Returns:
            Dictionary with field information and lineage
        """
        fields = self.program.find_field(field_name, table_name)
        
        if not fields:
            return {
                "found": False,
                "field_name": field_name,
                "table_name": table_name,
                "message": "Field not found"
            }
        
        results = []
        for field in fields:
            node_id = self._get_node_id(field)
            
            # Get upstream dependencies (fields this field depends on)
            upstream = self._get_upstream_lineage(field)
            
            # Get downstream dependencies (fields that depend on this field)
            downstream = self._get_downstream_lineage(field)
            
            result = {
                "field": field.to_dict(),
                "node_id": node_id,
                "upstream": [self._get_node_id(f) for f in upstream],
                "downstream": [self._get_node_id(f) for f in downstream],
                "depth": self._calculate_lineage_depth(field)
            }
            results.append(result)
        
        return {
            "found": True,
            "field_name": field_name,
            "table_name": table_name,
            "count": len(results),
            "results": results
        }
    
    def _get_upstream_lineage(self, field: FieldNode) -> Set[FieldNode]:
        """Get all upstream dependencies of a field"""
        return field.get_all_dependencies()
    
    def _get_downstream_lineage(self, field: FieldNode) -> Set[FieldNode]:
        """Get all fields that depend on this field"""
        node_id = self._get_node_id(field)
        downstream = set()
        
        if node_id in self.graph:
            # Get all descendants in the graph
            descendants = nx.descendants(self.graph, node_id)
            for desc_id in descendants:
                if 'field' in self.graph.nodes[desc_id]:
                    downstream.add(self.graph.nodes[desc_id]['field'])
        
        return downstream
    
    def _calculate_lineage_depth(self, field: FieldNode) -> int:
        """Calculate the depth of the lineage tree for a field"""
        if not field.dependencies:
            return 0
        return 1 + max((self._calculate_lineage_depth(dep) for dep in field.dependencies), default=0)
    
    def browse_fields(self, table_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Browse all fields in the program
        
        Args:
            table_name: Optional table name to filter fields
        
        Returns:
            Dictionary with all fields information
        """
        all_fields = self.program.get_all_fields()
        
        if table_name:
            all_fields = [f for f in all_fields if f.table == table_name]
        
        # Group fields by table
        fields_by_table = {}
        for field in all_fields:
            table = field.table or "unknown"
            if table not in fields_by_table:
                fields_by_table[table] = []
            fields_by_table[table].append(field.to_dict())
        
        # Get summary statistics
        stats = {
            "total_fields": len(all_fields),
            "total_tables": len(fields_by_table),
            "fields_with_dependencies": sum(1 for f in all_fields if f.dependencies),
            "max_depth": max((self._calculate_lineage_depth(f) for f in all_fields), default=0)
        }
        
        return {
            "stats": stats,
            "fields_by_table": fields_by_table,
            "all_tables": list(self.program.get_tables())
        }
    
    def get_lineage_path(self, from_field: str, to_field: str, 
                         from_table: Optional[str] = None,
                         to_table: Optional[str] = None) -> List[str]:
        """
        Find the lineage path between two fields
        
        Args:
            from_field: Source field name
            to_field: Target field name
            from_table: Optional source table name
            to_table: Optional target table name
        
        Returns:
            List of field node IDs representing the path
        """
        from_fields = self.program.find_field(from_field, from_table)
        to_fields = self.program.find_field(to_field, to_table)
        
        if not from_fields or not to_fields:
            return []
        
        from_id = self._get_node_id(from_fields[0])
        to_id = self._get_node_id(to_fields[0])
        
        try:
            path = nx.shortest_path(self.graph, from_id, to_id)
            return path
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []
    
    def export_graph_dot(self) -> str:
        """
        Export the lineage graph in DOT format for visualization
        """
        dot_lines = ["digraph lineage {"]
        dot_lines.append('  node [shape=box];')
        
        # Add nodes
        for node_id in self.graph.nodes():
            field = self.graph.nodes[node_id].get('field')
            if field:
                label = f"{node_id}\\n{field.operation.value if field.operation else 'source'}"
                dot_lines.append(f'  "{node_id}" [label="{label}"];')
        
        # Add edges
        for source, target in self.graph.edges():
            dot_lines.append(f'  "{source}" -> "{target}";')
        
        dot_lines.append("}")
        return "\n".join(dot_lines)
