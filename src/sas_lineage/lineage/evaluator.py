"""
Field value evaluator - allows manual input of field values to see outputs
"""
from typing import Dict, Any, Optional
import pandas as pd
import re
from ..ast.field_ast import FieldNode, SASProgram, FieldOperationType


class FieldEvaluator:
    """
    Evaluate field expressions with manual input values
    Supports reading from Excel and CSV files
    """
    
    def __init__(self, program: SASProgram):
        self.program = program
    
    def load_data_from_csv(self, filepath: str, table_name: str) -> pd.DataFrame:
        """
        Load data from CSV file
        
        Args:
            filepath: Path to CSV file
            table_name: Name to associate with this data table
        
        Returns:
            DataFrame with the loaded data
        """
        df = pd.read_csv(filepath)
        return df
    
    def load_data_from_excel(self, filepath: str, sheet_name: str = 0, 
                            table_name: Optional[str] = None) -> pd.DataFrame:
        """
        Load data from Excel file
        
        Args:
            filepath: Path to Excel file
            sheet_name: Sheet name or index
            table_name: Name to associate with this data table
        
        Returns:
            DataFrame with the loaded data
        """
        df = pd.read_excel(filepath, sheet_name=sheet_name)
        return df
    
    def evaluate_field(self, field: FieldNode, input_data: Dict[str, Any]) -> Any:
        """
        Evaluate a field expression given input values
        
        Args:
            field: FieldNode to evaluate
            input_data: Dictionary mapping field names to values
        
        Returns:
            Evaluated result
        """
        if not field.expression:
            # If no expression, just return the input value if it exists
            return input_data.get(field.name)
        
        # Simple expression evaluator
        expression = field.expression
        
        # Replace field references with their values
        for field_name, value in input_data.items():
            # Replace qualified references (table.field)
            expression = re.sub(rf'\b\w+\.{field_name}\b', str(value), expression)
            # Replace unqualified references
            expression = re.sub(rf'\b{field_name}\b', str(value), expression)
        
        try:
            # Evaluate simple arithmetic expressions
            # This is a simplified evaluator - a full SAS evaluator would be much more complex
            result = self._safe_eval(expression)
            return result
        except Exception as e:
            return f"Error evaluating: {str(e)}"
    
    def _safe_eval(self, expression: str) -> Any:
        """
        Safely evaluate a mathematical expression
        Only allows basic arithmetic operations
        """
        # Remove any remaining non-numeric characters except operators
        allowed_chars = set('0123456789+-*/(). ')
        
        # Check for SAS functions and handle them
        if any(func in expression.upper() for func in ['SUM', 'MEAN', 'MAX', 'MIN']):
            return self._eval_sas_function(expression)
        
        # For simple arithmetic, use eval with restricted namespace
        try:
            # Only evaluate if it looks safe
            if all(c in allowed_chars for c in expression):
                return eval(expression, {"__builtins__": {}}, {})
        except:
            pass
        
        return expression  # Return as-is if can't evaluate
    
    def _eval_sas_function(self, expression: str) -> Any:
        """
        Evaluate common SAS functions
        """
        expression = expression.upper()
        
        # Extract numbers from the expression
        numbers = re.findall(r'-?\d+\.?\d*', expression)
        numbers = [float(n) for n in numbers if n]
        
        if not numbers:
            return expression
        
        if 'SUM' in expression:
            return sum(numbers)
        elif 'MEAN' in expression:
            return sum(numbers) / len(numbers) if numbers else 0
        elif 'MAX' in expression:
            return max(numbers)
        elif 'MIN' in expression:
            return min(numbers)
        
        return expression
    
    def evaluate_with_dataframe(self, table_name: str, df: pd.DataFrame, 
                                output_fields: Optional[list] = None) -> pd.DataFrame:
        """
        Evaluate all fields for a table using a DataFrame as input
        
        Args:
            table_name: Name of the output table
            df: Input DataFrame with source field values
            output_fields: List of field names to calculate (None = all)
        
        Returns:
            DataFrame with calculated fields
        """
        # Find the data step for this table
        data_step = None
        for ds in self.program.data_steps:
            if ds.output_table == table_name:
                data_step = ds
                break
        
        if not data_step:
            return df
        
        result_df = df.copy()
        
        # Calculate each field
        fields_to_calc = data_step.fields
        if output_fields:
            fields_to_calc = [f for f in fields_to_calc if f.name in output_fields]
        
        for field in fields_to_calc:
            if field.expression:
                # Apply expression to each row
                result_df[field.name] = df.apply(
                    lambda row: self.evaluate_field(field, row.to_dict()),
                    axis=1
                )
        
        return result_df
