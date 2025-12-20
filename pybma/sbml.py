"""
SBML-qual import functionality for PyBMA
"""

import System
import clr

import xml.etree.ElementTree as ET
from pathlib import Path

from .core import _assembly

# Try to import libsbml
try:
    import libsbml
    LIBSBML_AVAILABLE = True
except ImportError:
    LIBSBML_AVAILABLE = False

def _extract_formula_from_transition(transition, var_id_map, ns):
    """
    Extract BMA formula from SBML-qual transition function terms.
    Converts MathML to BMA algebraic expression string using only arithmetic operators.
    
    Args:
        transition: XML transition element
        var_id_map: Mapping from SBML IDs to BMA variable IDs
        ns: Namespace dict
    
    Returns:
        str: BMA formula or None
    """
    # Get function terms
    function_terms = transition.findall('.//qual:functionTerm', ns)
    default_term = transition.find('.//qual:defaultTerm', ns)
    
    # Get default result level
    default_result = None
    if default_term is not None:
        default_result = (default_term.get('{http://www.sbml.org/sbml/level3/version1/qual/version1}resultLevel') or
                         default_term.get('qual:resultLevel'))
    
    if not function_terms:
        return str(default_result) if default_result else None
    
    # Build formula as sum of (condition * result_level) terms
    # Formula = sum of all (condition * value) + default * (not any condition)
    terms = []
    
    for term in function_terms:
        result_level = (term.get('{http://www.sbml.org/sbml/level3/version1/qual/version1}resultLevel') or
                       term.get('qual:resultLevel'))
        
        # Find math element
        math = term.find('.//{http://www.w3.org/1998/Math/MathML}math')
        if math is None:
            math = term.find('.//math')
        
        if math is not None and result_level:
            # Get first child of math (the actual expression)
            expr = None
            for child in math:
                if child.tag != '{http://www.w3.org/1998/Math/MathML}annotation':
                    expr = child
                    break
            
            if expr is not None:
                condition = _convert_mathml_to_bma_arithmetic(expr, var_id_map)
                if condition:
                    # Each term is: condition * result_level
                    terms.append(f"({condition} * {result_level})")
    
    if not terms:
        return str(default_result) if default_result else None
    
    # Combine all terms with max to handle mutually exclusive conditions
    # For disjoint conditions: max(cond1*val1, cond2*val2, ..., default)
    if default_result and default_result != "0":
        terms.append(str(default_result))
    
    if len(terms) == 1:
        return terms[0]
    
    # Build nested max
    result = terms[0]
    for term in terms[1:]:
        result = f"max({result}, {term})"
    
    return result


def _convert_mathml_to_bma_arithmetic(math_elem, var_id_map):
    """
    Convert MathML element to BMA formula string using only arithmetic operators.
    Converts boolean conditions to 0/1 values.
    Uses operators: min, max, +, -, *, /, floor, ceil
    Variables referenced as: var(ID)
    
    Args:
        math_elem: XML element with MathML
        var_id_map: Mapping from SBML IDs to BMA variable IDs
    
    Returns:
        str: BMA formula expression (evaluates to 0 or 1 for conditions)
    """
    # Remove namespace if present
    tag = math_elem.tag
    if '}' in tag:
        tag = tag.split('}')[1]
    
    # Constants
    if tag == 'cn':
        value = math_elem.text.strip() if math_elem.text else '0'
        return str(int(float(value)))
    
    # Variables
    if tag == 'ci':
        var_name = math_elem.text.strip() if math_elem.text else ''
        if var_name in var_id_map:
            return f"var({var_id_map[var_name]})"
        return var_name
    
    # True/False
    if tag == 'true':
        return "1"
    
    if tag == 'false':
        return "0"
    
    # Get child elements
    children = [child for child in math_elem if child.tag != '{http://www.w3.org/1998/Math/MathML}annotation']
    
    # Apply (function application)
    if tag == 'apply':
        if len(children) == 0:
            return "0"
        
        operator_elem = children[0]
        operator_tag = operator_elem.tag
        if '}' in operator_tag:
            operator_tag = operator_tag.split('}')[1]
        
        operands = [_convert_mathml_to_bma_arithmetic(child, var_id_map) for child in children[1:]]
        
        # Logical operators - convert to arithmetic
        if operator_tag == 'and':
            # AND: min of all operands (all must be 1)
            if len(operands) == 0:
                return "1"
            result = operands[0]
            for op in operands[1:]:
                result = f"min({result}, {op})"
            return result
        
        if operator_tag == 'or':
            # OR: max of all operands (at least one must be 1)
            if len(operands) == 0:
                return "0"
            result = operands[0]
            for op in operands[1:]:
                result = f"max({result}, {op})"
            return result
        
        if operator_tag == 'not':
            # NOT: 1 - operand
            return f"(1 - {operands[0]})"
        
        # Relational operators - return 0 or 1
        if operator_tag == 'eq':
            # a = b: 1 - min(1, abs(a - b))
            left, right = operands[0], operands[1]
            diff = f"({left} - {right})"
            abs_diff = f"max({diff}, -{diff})"
            return f"(1 - min(1, {abs_diff}))"
        
        if operator_tag == 'neq':
            # a <> b: min(1, abs(a - b))
            left, right = operands[0], operands[1]
            diff = f"({left} - {right})"
            abs_diff = f"max({diff}, -{diff})"
            return f"min(1, {abs_diff})"
        
        if operator_tag == 'gt':
            # a > b: max(0, min(1, a - b))
            left, right = operands[0], operands[1]
            return f"max(0, min(1, {left} - {right}))"
        
        if operator_tag == 'geq':
            # a >= b: max(0, ceil(min(1, a - b + 1)))
            left, right = operands[0], operands[1]
            return f"max(0, ceil(min(1, ({left} - {right}) + 1)))"
        
        if operator_tag == 'lt':
            # a < b: max(0, min(1, b - a))
            left, right = operands[0], operands[1]
            return f"max(0, min(1, {right} - {left}))"
        
        if operator_tag == 'leq':
            # a <= b: max(0, ceil(min(1, b - a + 1)))
            left, right = operands[0], operands[1]
            return f"max(0, ceil(min(1, ({right} - {left}) + 1)))"
        
        # Arithmetic operators
        if operator_tag == 'plus':
            return "(" + " + ".join(operands) + ")"
        
        if operator_tag == 'minus':
            if len(operands) == 1:
                return f"(-{operands[0]})"
            else:
                return f"({operands[0]} - {operands[1]})"
        
        if operator_tag == 'times':
            return "(" + " * ".join(operands) + ")"
        
        if operator_tag == 'divide':
            return f"({operands[0]} / {operands[1]})"
        
        # Min/Max
        if operator_tag == 'min':
            if len(operands) == 0:
                return "0"
            if len(operands) == 1:
                return operands[0]
            result = operands[0]
            for op in operands[1:]:
                result = f"min({result}, {op})"
            return result
        
        if operator_tag == 'max':
            if len(operands) == 0:
                return "0"
            if len(operands) == 1:
                return operands[0]
            result = operands[0]
            for op in operands[1:]:
                result = f"max({result}, {op})"
            return result
        
        # Floor/Ceiling
        if operator_tag == 'floor':
            return f"floor({operands[0]})"
        
        if operator_tag == 'ceiling':
            return f"ceil({operands[0]})"
        
        # Abs
        if operator_tag == 'abs':
            return f"max({operands[0]}, -1*{operands[0]})"
        
        # Power
        if operator_tag == 'power':
            base = operands[0]
            exp = operands[1]
            try:
                exp_val = int(exp)
                if exp_val == 0:
                    return "1"
                elif exp_val == 1:
                    return base
                elif exp_val == 2:
                    return f"({base} * {base})"
                elif exp_val == 3:
                    return f"({base} * {base} * {base})"
                else:
                    # Expand if reasonable
                    if exp_val > 0 and exp_val <= 5:
                        terms = [base] * exp_val
                        return "(" + " * ".join(terms) + ")"
                    return f"({base}^{exp})"
            except:
                return f"({base}^{exp})"
    
    # Piecewise - convert to sum of products
    if tag == 'piecewise':
        pieces = []
        otherwise_value = None
        
        for child in children:
            child_tag = child.tag.split('}')[1] if '}' in child.tag else child.tag
            
            if child_tag == 'piece':
                piece_children = [c for c in child]
                if len(piece_children) >= 2:
                    value = _convert_mathml_to_bma_arithmetic(piece_children[0], var_id_map)
                    condition = _convert_mathml_to_bma_arithmetic(piece_children[1], var_id_map)
                    pieces.append((condition, value))
            
            elif child_tag == 'otherwise':
                otherwise_children = [c for c in child]
                if otherwise_children:
                    otherwise_value = _convert_mathml_to_bma_arithmetic(otherwise_children[0], var_id_map)
        
        # Convert piecewise to: max(cond1*val1, cond2*val2, ..., otherwise)
        terms = []
        for condition, value in pieces:
            terms.append(f"({condition} * {value})")
        
        if otherwise_value:
            terms.append(otherwise_value)
        
        if not terms:
            return "0"
        
        if len(terms) == 1:
            return terms[0]
        
        result = terms[0]
        for term in terms[1:]:
            result = f"max({result}, {term})"
        
        return result
    
    # Unknown
    return "0"


def _extract_formula_from_transition_libsbml(transition, var_id_map):
    """
    Extract BMA formula from libsbml transition function terms.
    Converts MathML AST to BMA algebraic expression using only arithmetic operators.
    
    Args:
        transition: libsbml Transition object
        var_id_map: Mapping from SBML IDs to BMA variable IDs
    
    Returns:
        str: BMA formula or None
    """
    # Get default result level
    default_result = None
    if transition.isSetDefaultTerm():
        default_term = transition.getDefaultTerm()
        default_result = default_term.getResultLevel()
    
    # Get function terms
    num_terms = transition.getNumFunctionTerms()
    
    if num_terms == 0:
        return str(default_result) if default_result is not None else None
    
    # Build formula as max of (condition * result_level) terms
    terms = []
    
    for i in range(num_terms):
        function_term = transition.getFunctionTerm(i)
        result_level = function_term.getResultLevel()
        
        math = function_term.getMath()
        
        if math is not None:
            condition = _convert_mathml_ast_to_bma_arithmetic(math, var_id_map)
            if condition:
                terms.append(f"({condition} * {result_level})")
    
    if not terms:
        return str(default_result) if default_result is not None else None
    
    # Add default if present
    if default_result and default_result != "0":
        terms.append(str(default_result))
    
    if len(terms) == 1:
        return terms[0]
    
    # Build nested max
    result = terms[0]
    for term in terms[1:]:
        result = f"max({result}, {term})"
    
    return result


def _convert_mathml_ast_to_bma_arithmetic(math_ast, var_id_map):
    """
    Convert libsbml MathML AST to BMA formula string using only arithmetic operators.
    Converts boolean conditions to 0/1 values.
    Uses operators: min, max, +, -, *, /, floor, ceil
    Variables referenced as: var(ID)
    
    Args:
        math_ast: libsbml ASTNode
        var_id_map: Mapping from SBML IDs to BMA variable IDs
    
    Returns:
        str: BMA formula expression (evaluates to 0 or 1 for conditions)
    """
    if math_ast is None:
        return None
    
    node_type = math_ast.getType()
    num_children = math_ast.getNumChildren()
    
    # Constants
    if node_type == libsbml.AST_INTEGER:
        return str(math_ast.getInteger())
    
    if node_type == libsbml.AST_REAL:
        return str(int(math_ast.getReal()))
    
    if node_type == libsbml.AST_RATIONAL:
        numerator = math_ast.getNumerator()
        denominator = math_ast.getDenominator()
        return f"({numerator} / {denominator})"
    
    # Variables
    if node_type == libsbml.AST_NAME:
        var_name = math_ast.getName()
        if var_name in var_id_map:
            return f"var({var_id_map[var_name]})"
        return var_name
    
    # Constants
    if node_type == libsbml.AST_CONSTANT_TRUE:
        return "1"
    
    if node_type == libsbml.AST_CONSTANT_FALSE:
        return "0"
    
    # Logical operators - convert to arithmetic
    if node_type == libsbml.AST_LOGICAL_AND:
        # AND: min of all operands
        if num_children == 0:
            return "1"
        result = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(0), var_id_map)
        for i in range(1, num_children):
            operand = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(i), var_id_map)
            result = f"min({result}, {operand})"
        return result
    
    if node_type == libsbml.AST_LOGICAL_OR:
        # OR: max of all operands
        if num_children == 0:
            return "0"
        result = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(0), var_id_map)
        for i in range(1, num_children):
            operand = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(i), var_id_map)
            result = f"max({result}, {operand})"
        return result
    
    if node_type == libsbml.AST_LOGICAL_NOT:
        # NOT: 1 - operand
        operand = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(0), var_id_map)
        return f"(1 - {operand})"
    
    # Relational operators - return 0 or 1
    if node_type == libsbml.AST_RELATIONAL_EQ:
        # a = b: 1 if equal, 0 otherwise
        left = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(0), var_id_map)
        right = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(1), var_id_map)
        diff = f"({left} - {right})"
        abs_diff = f"max({diff}, -1*{diff})"
        return f"(1 - min(1, {abs_diff}))"
    
    if node_type == libsbml.AST_RELATIONAL_NEQ:
        # a <> b: 1 if not equal, 0 otherwise
        left = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(0), var_id_map)
        right = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(1), var_id_map)
        diff = f"({left} - {right})"
        abs_diff = f"max({diff}, -1*{diff})"
        return f"min(1, {abs_diff})"
    
    if node_type == libsbml.AST_RELATIONAL_GT:
        # a > b: 1 if a > b, 0 otherwise
        left = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(0), var_id_map)
        right = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(1), var_id_map)
        return f"max(0, min(1, {left} - {right}))"
    
    if node_type == libsbml.AST_RELATIONAL_GEQ:
        # a >= b
        left = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(0), var_id_map)
        right = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(1), var_id_map)
        return f"max(0, ceil(min(1, ({left} - {right}) + 1)))"
    
    if node_type == libsbml.AST_RELATIONAL_LT:
        # a < b
        left = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(0), var_id_map)
        right = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(1), var_id_map)
        return f"max(0, min(1, {right} - {left}))"
    
    if node_type == libsbml.AST_RELATIONAL_LEQ:
        # a <= b
        left = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(0), var_id_map)
        right = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(1), var_id_map)
        return f"max(0, ceil(min(1, ({right} - {left}) + 1)))"
    
    # Arithmetic operators
    if node_type == libsbml.AST_PLUS:
        operands = [_convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(i), var_id_map) 
                   for i in range(num_children)]
        return "(" + " + ".join(operands) + ")"
    
    if node_type == libsbml.AST_MINUS:
        if num_children == 1:
            operand = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(0), var_id_map)
            return f"(-{operand})"
        else:
            left = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(0), var_id_map)
            right = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(1), var_id_map)
            return f"({left} - {right})"
    
    if node_type == libsbml.AST_TIMES:
        operands = [_convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(i), var_id_map) 
                   for i in range(num_children)]
        return "(" + " * ".join(operands) + ")"
    
    if node_type == libsbml.AST_DIVIDE:
        left = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(0), var_id_map)
        right = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(1), var_id_map)
        return f"({left} / {right})"
    
    # Functions
    if node_type == libsbml.AST_FUNCTION_MIN:
        if num_children == 0:
            return "0"
        result = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(0), var_id_map)
        for i in range(1, num_children):
            operand = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(i), var_id_map)
            result = f"min({result}, {operand})"
        return result
    
    if node_type == libsbml.AST_FUNCTION_MAX:
        if num_children == 0:
            return "0"
        result = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(0), var_id_map)
        for i in range(1, num_children):
            operand = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(i), var_id_map)
            result = f"max({result}, {operand})"
        return result
    
    if node_type == libsbml.AST_FUNCTION_FLOOR:
        operand = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(0), var_id_map)
        return f"floor({operand})"
    
    if node_type == libsbml.AST_FUNCTION_CEILING:
        operand = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(0), var_id_map)
        return f"ceil({operand})"
    
    if node_type == libsbml.AST_FUNCTION_ABS:
        operand = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(0), var_id_map)
        return f"max({operand}, -{operand})"
    
    # Power
    if node_type == libsbml.AST_POWER:
        base = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(0), var_id_map)
        exponent = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(1), var_id_map)
        
        try:
            exp_val = int(exponent)
            if exp_val == 0:
                return "1"
            elif exp_val == 1:
                return base
            elif exp_val == 2:
                return f"({base} * {base})"
            elif exp_val == 3:
                return f"({base} * {base} * {base})"
            elif exp_val > 0 and exp_val <= 5:
                terms = [base] * exp_val
                return "(" + " * ".join(terms) + ")"
        except:
            pass
        
        return f"({base}^{exponent})"
    
    # Piecewise - convert to max of products
    if node_type == libsbml.AST_FUNCTION_PIECEWISE:
        terms = []
        i = 0
        while i < num_children - 1:
            value = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(i), var_id_map)
            condition = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(i + 1), var_id_map)
            terms.append(f"({condition} * {value})")
            i += 2
        
        # Otherwise value
        if num_children % 2 == 1:
            otherwise = _convert_mathml_ast_to_bma_arithmetic(math_ast.getChild(num_children - 1), var_id_map)
            terms.append(otherwise)
        
        if not terms:
            return "0"
        
        if len(terms) == 1:
            return terms[0]
        
        result = terms[0]
        for term in terms[1:]:
            result = f"max({result}, {term})"
        
        return result
    
    # Unknown
    return "0"
    
# ============================================================================
# Public API
# ============================================================================

def load_sbml_qual(sbml_path, use_libsbml='auto'):
    """
    Load SBML-qual file and convert to BMA model format.
    
    Args:
        sbml_path: Path to SBML-qual XML file
        use_libsbml: 'auto' (default), True, or False
                     'auto' uses libsbml if available, falls back to native
    
    Returns:
        dict: BMA model data structure
    
    Example:
        model_data = load_sbml_qual("model.sbml")
    """
    if use_libsbml == 'auto':
        use_libsbml = LIBSBML_AVAILABLE
    elif use_libsbml and not LIBSBML_AVAILABLE:
        raise ImportError(
            "libsbml requested but not installed. "
            "Install with: pip install python-libsbml"
        )
    
    if use_libsbml:
        return _load_with_libsbml(sbml_path)
    else:
        return _load_native(sbml_path)


def sbml_to_bma_model(sbml_path, use_libsbml='auto'):
    """
    Load SBML-qual file and create BMAModel instance.
    
    Args:
        sbml_path: Path to SBML-qual XML file
        use_libsbml: 'auto' (default), True, or False
    
    Returns:
        BMAModel instance
    
    Example:
        model = sbml_to_bma_model("model.sbml")
        result = check_stability(model.qn)
    """
    from .core import BMAModel
    import tempfile
    import json
    import os
    
    # Load SBML and convert to BMA format
    bma_data = load_sbml_qual(sbml_path, use_libsbml)
    
    # Write to temporary JSON file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(bma_data, f, indent=2)
        temp_path = f.name
    
    try:
        # Create BMAModel from the JSON
        model = BMAModel(temp_path)
        return model
    finally:
        # Clean up temp file
        os.unlink(temp_path)


def export_to_sbml_qual(bma_model, output_path):
    """
    Export BMA model to SBML-qual format.
    
    Args:
        bma_model: BMAModel instance or dict with BMA model data
        output_path: Path to save SBML-qual XML file
    
    Example:
        export_to_sbml_qual(model, "output.sbml")
    """
    from .core import BMAModel
    
    # Get model data
    if isinstance(bma_model, BMAModel):
        model_data = bma_model.data
        model_name = bma_model.name
    else:
        model_data = bma_model
        model_name = bma_model.get('Model', {}).get('Name', 'Exported Model')
    
    # Create SBML structure
    sbml = ET.Element('sbml', {
        'xmlns': 'http://www.sbml.org/sbml/level3/version1/core',
        'xmlns:qual': 'http://www.sbml.org/sbml/level3/version1/qual/version1',
        'level': '3',
        'version': '1',
        'qual:required': 'true'
    })
    
    model_elem = ET.SubElement(sbml, 'model', {
        'id': 'model',
        'name': model_name
    })
    
    # Add compartments (required)
    comp_list = ET.SubElement(model_elem, 'listOfCompartments')
    ET.SubElement(comp_list, 'compartment', {
        'id': 'default',
        'constant': 'true'
    })
    
    # Add qualitative species
    qual_species_list = ET.SubElement(model_elem, 'qual:listOfQualitativeSpecies')
    
    variables = model_data['Model']['Variables']
    for var in variables:
        species_attrs = {
            'qual:id': f"var_{var['Id']}",
            'qual:name': var.get('Name', f"Variable {var['Id']}"),
            'qual:compartment': 'default',
            'qual:constant': 'false',
            'qual:maxLevel': str(var.get('RangeTo', 1))
        }
        
        # Add initial level if available
        formula = var.get('Formula', '')
        if formula and formula.isdigit():
            species_attrs['qual:initialLevel'] = formula
        
        ET.SubElement(qual_species_list, 'qual:qualitativeSpecies', species_attrs)
    
    # Add transitions
    transitions_list = ET.SubElement(model_elem, 'qual:listOfTransitions')
    
    # Group relationships by target variable
    by_target = {}
    for rel in model_data['Model']['Relationships']:
        target = rel['ToVariable']
        if target not in by_target:
            by_target[target] = []
        by_target[target].append(rel)
    
    for target_id, rels in by_target.items():
        transition = ET.SubElement(transitions_list, 'qual:transition', {
            'qual:id': f"tr_{target_id}"
        })
        
        # Add inputs with signs if available
        inputs_list = ET.SubElement(transition, 'qual:listOfInputs')
        for rel in rels:
            input_attrs = {
                'qual:id': f"in_{rel['FromVariable']}_{target_id}",
                'qual:qualitativeSpecies': f"var_{rel['FromVariable']}",
                'qual:transitionEffect': 'none'
            }
            
            # Add sign if available
            if 'Type' in rel:
                if rel['Type'] == 1:  # Activator in BMA
                    input_attrs['qual:sign'] = 'positive'
                elif rel['Type'] == 2:  # Inhibitor in BMA
                    input_attrs['qual:sign'] = 'negative'
            
            ET.SubElement(inputs_list, 'qual:input', input_attrs)
        
        # Add outputs
        outputs_list = ET.SubElement(transition, 'qual:listOfOutputs')
        ET.SubElement(outputs_list, 'qual:output', {
            'qual:id': f"out_{target_id}",
            'qual:qualitativeSpecies': f"var_{target_id}",
            'qual:transitionEffect': 'assignmentLevel'
        })
        
        # Add function terms
        func_terms = ET.SubElement(transition, 'qual:listOfFunctionTerms')
        ET.SubElement(func_terms, 'qual:defaultTerm', {
            'qual:resultLevel': '0'
        })
    
    # Write to file
    tree = ET.ElementTree(sbml)
    ET.indent(tree, space="  ")
    tree.write(output_path, encoding='utf-8', xml_declaration=True)


def validate_sbml_qual(sbml_path):
    """
    Validate SBML-qual file (requires libsbml).
    
    Args:
        sbml_path: Path to SBML file
    
    Returns:
        dict: {'valid': bool, 'errors': list, 'warnings': list}
    """
    if not LIBSBML_AVAILABLE:
        return {
            'valid': False,
            'errors': ['libsbml not installed - cannot validate'],
            'warnings': []
        }
    
    document = libsbml.readSBMLFromFile(str(sbml_path))
    
    errors = []
    warnings = []
    
    for i in range(document.getNumErrors()):
        error = document.getError(i)
        message = f"Line {error.getLine()}: {error.getMessage()}"
        
        if error.isFatal() or error.isError():
            errors.append(message)
        elif error.isWarning():
            warnings.append(message)
    
    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings
    }


def get_sbml_info(sbml_path):
    """
    Get basic information about SBML file (requires libsbml).
    
    Args:
        sbml_path: Path to SBML file
    
    Returns:
        dict: Model information
    """
    if not LIBSBML_AVAILABLE:
        raise ImportError("libsbml required for this function. Install with: pip install python-libsbml")
    
    document = libsbml.readSBMLFromFile(str(sbml_path))
    model = document.getModel()
    
    if model is None:
        return {'error': 'No model in file'}
    
    qual_plugin = model.getPlugin("qual")
    
    info = {
        'model_name': model.getName() or model.getId(),
        'sbml_level': document.getLevel(),
        'sbml_version': document.getVersion(),
        'has_qual': qual_plugin is not None,
    }
    
    if qual_plugin:
        info['num_species'] = qual_plugin.getNumQualitativeSpecies()
        info['num_transitions'] = qual_plugin.getNumTransitions()
        
        # Get species names
        species_names = []
        for i in range(qual_plugin.getNumQualitativeSpecies()):
            species = qual_plugin.getQualitativeSpecies(i)
            species_names.append(species.getName() or species.getId())
        info['species'] = species_names
    
    return info


# ============================================================================
# Native XML parser implementation
# ============================================================================

def _load_native(sbml_path):
    """
    Load SBML-qual using native XML parsing (no libsbml required).
    Handles layout information and relationship signs.
    """
    tree = ET.parse(sbml_path)
    root = tree.getroot()
    
    # SBML namespaces
    ns = {
        'sbml': 'http://www.sbml.org/sbml/level3/version1/core',
        'qual': 'http://www.sbml.org/sbml/level3/version1/qual/version1',
        'layout': 'http://www.sbml.org/sbml/level3/version1/layout/version1'
    }
    
    # Extract model
    sbml_model = root.find('sbml:model', ns)
    model_name = sbml_model.get('name', 'Imported SBML Model') if sbml_model is not None else 'Imported SBML Model'
    if not model_name or model_name == 'Imported SBML Model':
        model_name = sbml_model.get('id', 'Imported SBML Model') if sbml_model is not None else 'Imported SBML Model'
    
    # Extract qualitative species (variables)
    variables = []
    qual_species_list = root.findall('.//qual:qualitativeSpecies', ns)
    
    var_id_map = {}  # Map SBML IDs to BMA IDs
    var_name_map = {}  # Map variable names to IDs for layout lookup
    
    for idx, species in enumerate(qual_species_list):
        # Try with and without namespace prefix
        sbml_id = (species.get('{http://www.sbml.org/sbml/level3/version1/qual/version1}id') or 
                   species.get('qual:id') or 
                   species.get('id'))
        
        name = (species.get('{http://www.sbml.org/sbml/level3/version1/qual/version1}name') or 
                species.get('qual:name') or 
                species.get('name') or 
                sbml_id)
        
        # Get max level
        max_level = (species.get('{http://www.sbml.org/sbml/level3/version1/qual/version1}maxLevel') or
                     species.get('qual:maxLevel'))
        range_to = int(max_level) if max_level else 1
        
        # Initial level
        initial_level = (species.get('{http://www.sbml.org/sbml/level3/version1/qual/version1}initialLevel') or
                        species.get('qual:initialLevel'))
        initial = int(initial_level) if initial_level else 0
        
        var = {
            'Id': idx,
            'Name': name,
            'RangeFrom': 0,
            'RangeTo': range_to,
            'Formula': str(initial)
        }
        
        variables.append(var)
        var_id_map[sbml_id] = idx
        var_name_map[name] = idx
        var_name_map[sbml_id] = idx  # Also map by ID
    
    # Extract layout information
    layout_variables = []
    
    # Try to find layout in different possible locations
    layouts = root.findall('.//layout:layout', ns)
    
    for layout in layouts:
        # Look for speciesGlyph elements
        species_glyphs = layout.findall('.//layout:speciesGlyph', ns)
        
        for glyph in species_glyphs:
            species_ref = (glyph.get('{http://www.sbml.org/sbml/level3/version1/layout/version1}species') or
                          glyph.get('layout:species') or
                          glyph.get('species'))
            
            if species_ref and species_ref in var_id_map:
                var_id = var_id_map[species_ref]
                
                # Get bounding box
                bbox = glyph.find('.//layout:boundingBox', ns)
                if bbox is not None:
                    pos = bbox.find('.//layout:position', ns)
                    
                    if pos is not None:
                        x = (pos.get('{http://www.sbml.org/sbml/level3/version1/layout/version1}x') or
                             pos.get('layout:x') or
                             pos.get('x'))
                        y = (pos.get('{http://www.sbml.org/sbml/level3/version1/layout/version1}y') or
                             pos.get('layout:y') or
                             pos.get('y'))
                        
                        if x and y:
                            layout_variables.append({
                                'Id': var_id,
                                'Name': variables[var_id]['Name'],
                                'Type': 'Default',
                                'X': float(x),
                                'Y': float(y),
                                'CellX': 0,
                                'CellY': 0,
                                'Angle': 0,
                                'Description': ''
                            })
        
        # Also look for generalGlyph elements (used in some tools)
        general_glyphs = layout.findall('.//layout:generalGlyph', ns)
        
        for glyph in general_glyphs:
            # Get reference attribute
            reference = (glyph.get('{http://www.sbml.org/sbml/level3/version1/layout/version1}reference') or
                        glyph.get('layout:reference') or
                        glyph.get('reference'))
            
            if reference:
                # Look up by name or ID
                var_id = var_name_map.get(reference)
                
                if var_id is not None:
                    # Get bounding box
                    bbox = glyph.find('.//layout:boundingBox', ns)
                    if bbox is not None:
                        pos = bbox.find('.//layout:position', ns)
                        
                        if pos is not None:
                            x = (pos.get('{http://www.sbml.org/sbml/level3/version1/layout/version1}x') or
                                 pos.get('layout:x') or
                                 pos.get('x'))
                            y = (pos.get('{http://www.sbml.org/sbml/level3/version1/layout/version1}y') or
                                 pos.get('layout:y') or
                                 pos.get('y'))
                            
                            if x and y:
                                layout_variables.append({
                                    'Id': var_id,
                                    'Name': variables[var_id]['Name'],
                                    'Type': 'Default',
                                    'X': float(x),
                                    'Y': float(y),
                                    'CellX': 0,
                                    'CellY': 0,
                                    'Angle': 0,
                                    'Description': ''
                                })
    
    # Extract transitions (relationships with signs)
    transitions = root.findall('.//qual:transition', ns)
    relationships = []
    
    for transition in transitions:
        # Get target variable
        outputs = transition.findall('.//qual:output', ns)
        if not outputs:
            continue
        
        target_id = (outputs[0].get('{http://www.sbml.org/sbml/level3/version1/qual/version1}qualitativeSpecies') or
                     outputs[0].get('qual:qualitativeSpecies'))
        
        if target_id not in var_id_map:
            continue
        
        target_var_id = var_id_map[target_id]
        
        # Get input variables with signs
        inputs = transition.findall('.//qual:input', ns)
        
        for input_elem in inputs:
            input_id = (input_elem.get('{http://www.sbml.org/sbml/level3/version1/qual/version1}qualitativeSpecies') or
                       input_elem.get('qual:qualitativeSpecies'))
            
            if input_id in var_id_map:
                input_var_id = var_id_map[input_id]
                
                # Get sign (positive/negative/dual/unknown)
                sign = (input_elem.get('{http://www.sbml.org/sbml/level3/version1/qual/version1}sign') or
                       input_elem.get('qual:sign'))
                
                # Map SBML sign to BMA Type
                # BMA: 1 = Activator, 2 = Inhibitor
                # Default to activator if ambiguous
                rel_type = "Activator"  # Default: Activator
                
                if sign == 'negative':
                    rel_type = "Inhibitor"  # Inhibitor
                elif sign == 'positive':
                    rel_type = "Activator"  # Activator
                # For 'dual', 'unknown', or missing: default to activator (1)
                
                relationship = {
                    'Id': len(relationships),
                    'FromVariable': input_var_id,
                    'ToVariable': target_var_id,
                    'Type': rel_type
                }
                relationships.append(relationship)
    
    # Create BMA model structure
    bma_model = {
        'Model': {
            'Name': model_name,
            'Variables': variables,
            'Relationships': relationships
        },
        'Layout': {
            'Variables': layout_variables,
            'Containers': [],
            'AnnotatedGridCells': [],
            'Description': f'Imported from SBML-qual: {Path(sbml_path).name}'
        },
        'ltl': {
            'states': [],
            'operations': []
        }
    }
    

# ============================================================================
# libsbml implementation (enhanced)
# ============================================================================

def _load_with_libsbml(sbml_path):
    """
    Load SBML-qual using libsbml library.
    Handles layout information and relationship signs.
    """
    document = libsbml.readSBMLFromFile(str(sbml_path))
    
    # Check for errors
    if document.getNumErrors() > 0:
        errors = []
        for i in range(document.getNumErrors()):
            error = document.getError(i)
            if error.isFatal() or error.isError():
                errors.append(f"Line {error.getLine()}: {error.getMessage()}")
        
        if errors:
            raise ValueError(f"SBML parsing errors:\n" + "\n".join(errors))
    
    # Get model
    model = document.getModel()
    if model is None:
        raise ValueError("No model found in SBML file")
    
    # Get qual plugin
    qual_plugin = model.getPlugin("qual")
    if qual_plugin is None:
        raise ValueError("File is not SBML-qual (qual extension not found)")
    
    model_name = model.getName() or model.getId() or "Imported SBML Model"
    
    # Extract qualitative species
    variables = []
    var_id_map = {}
    
    for i in range(qual_plugin.getNumQualitativeSpecies()):
        species = qual_plugin.getQualitativeSpecies(i)
        
        sbml_id = species.getId()
        name = species.getName() or sbml_id
        max_level = species.getMaxLevel()
        initial_level = species.getInitialLevel() if species.isSetInitialLevel() else 0
        
        var = {
            'Id': i,
            'Name': name,
            'RangeFrom': 0,
            'RangeTo': max_level,
            'Formula': str(initial_level)
        }
        
        variables.append(var)
        var_id_map[sbml_id] = i
    
    # Extract layout information
    layout_variables = []
    layout_plugin = model.getPlugin("layout")
    
    if layout_plugin is not None and layout_plugin.getNumLayouts() > 0:
        layout = layout_plugin.getLayout(0)
        
        for i in range(layout.getNumGeneralGlyphs()):
            glyph = layout.getGeneralGlyph(i)
            species_ref = glyph.getReferenceId()
            
            if species_ref in var_id_map:
                var_id = var_id_map[species_ref]
                bbox = glyph.getBoundingBox()
                
                if bbox is not None:
                    layout_variables.append({
                        'Id': var_id,
                        'Name': variables[var_id]['Name'],
                        'Type': 'Default',
                        'PositionX': bbox.getX(),
                        'PositionY': bbox.getY(),
                        'CellX': 0,
                        'CellY': 0,
                        'Angle': 0,
                        'Description': ''
                    })
    
    # Extract transitions with signs
    relationships = []
    
    for i in range(qual_plugin.getNumTransitions()):
        transition = qual_plugin.getTransition(i)
        
        # Get target
        if transition.getNumOutputs() == 0:
            continue
        
        output = transition.getOutput(0)
        target_id = output.getQualitativeSpecies()
        
        if target_id not in var_id_map:
            continue
        
        target_var_id = var_id_map[target_id]
        
        # Get inputs with signs
        for j in range(transition.getNumInputs()):
            input_elem = transition.getInput(j)
            input_id = input_elem.getQualitativeSpecies()
            
            if input_id in var_id_map:
                input_var_id = var_id_map[input_id]
                
                # Get sign
                sign = input_elem.getSign()
                
                # Map to BMA type (1=Activator, 2=Inhibitor)
                rel_type = "Activator"  # Default: Activator
                
                if sign == libsbml.INPUT_SIGN_NEGATIVE:
                    rel_type = "Inhibitor"  # Inhibitor
                elif sign == libsbml.INPUT_SIGN_POSITIVE:
                    rel_type = "Activator"  # Activator
                # For DUAL, UNKNOWN, or unset: default to activator
                
                relationship = {
                    'Id': len(relationships),
                    'FromVariable': input_var_id,
                    'ToVariable': target_var_id,
                    'Type': rel_type
                }
                relationships.append(relationship)
        
        # Extract formula (simplified)
        '''
        if transition.getNumFunctionTerms() > 0:
            function_term = transition.getFunctionTerm(0)
            result_level = function_term.getResultLevel()
            variables[target_var_id]['Formula'] = str(result_level)
        ''' 
        formula = _extract_formula_from_transition_libsbml(transition, var_id_map)
        if formula:
            variables[target_var_id]['Formula'] = formula
    
    # Create BMA model
    bma_model = {
        'Model': {
            'Name': model_name,
            'Variables': variables,
            'Relationships': relationships
        },
        'Layout': {
            'Variables': layout_variables,
            'Containers': [],
            'AnnotatedGridCells': [],
            'Description': f'Imported from SBML-qual'
        },
        'ltl': {
            'states': [],
            'operations': []
        }
    }
    
    return bma_model

def save_bma_to_sbml_qual_libsbml(model_data, output_path):
    """
    Save BMA model to SBML-qual format using libsbml.
    Evaluates BMA formulas to create truth tables, then generates function terms.
    
    Args:
        model_data: BMA model dict (from load_model or BMAModel.data)
        output_path: Path to save SBML-qual XML file
    
    Requires:
        libsbml must be installed
    
    Example:
        from pybma import load_model, save_bma_to_sbml_qual_libsbml
        model_data = load_model("model.json")
        save_bma_to_sbml_qual_libsbml(model_data, "output.sbml")
    """
    if not LIBSBML_AVAILABLE:
        raise ImportError(
            "libsbml is required for this function. "
            "Install with: pip install python-libsbml"
        )
    
    from .core import model_to_qn, _assembly
    import System
    
    # Get model info
    model_name = model_data['Model'].get('Name', 'BMA Model')
    variables = model_data['Model']['Variables']
    relationships = model_data['Model']['Relationships']
    layout_vars = model_data.get('Layout', {}).get('Variables', [])
    
    # Convert to QN for formula evaluation
    qn = model_to_qn(model_data)
    
    sbmlns = libsbml.SBMLNamespaces(3, 1)
    sbmlns.addPkgNamespace("qual", 1)
    sbmlns.addPkgNamespace("layout", 1)
    
    # Create SBML document
    document = libsbml.SBMLDocument(sbmlns)
    document.setPackageRequired('qual', True)
    document.setPackageRequired('layout', True)
    model = document.createModel()
    model.setId('model')
    model.setName(model_name)
    
    # Enable layout plugin if we have layout info
    has_layout = len(layout_vars) > 0
    
    # Enable qual plugin
    qual_plugin = model.getPlugin('qual')
    
    # Add compartment (required)
    compartment = model.createCompartment()
    compartment.setId('default')
    compartment.setConstant(True)
    
    # Add qualitative species
    var_id_to_species = {}
    
    for var in variables:
        var_id = var['Id']
        species = qual_plugin.createQualitativeSpecies()
        species.setId(f"var_{var_id}")
        species.setName(var.get('Name', f"Variable {var_id}"))
        species.setCompartment('default')
        species.setConstant(False)
        species.setMaxLevel(var.get('RangeTo', 1))
        
        # Set initial level if it's a simple number
        formula = var.get('Formula', '0')
        if formula.isdigit():
            species.setInitialLevel(int(formula))
        
        var_id_to_species[var_id] = species
    
    # Add layout information if available
    if has_layout:
        layout_plugin = model.getPlugin('layout')
        
        if layout_plugin is not None:
            # Create layout
            layout = layout_plugin.createLayout()
            layout.setId('__layout__')
            
            # Calculate bounding box for layout
            if layout_vars:
                max_x = max(lv.get('X', 0) + 50 for lv in layout_vars)  # Add some padding
                max_y = max(lv.get('Y', 0) + 50 for lv in layout_vars)
                
                dimensions = libsbml.Dimensions()
                dimensions.setWidth(max(max_x, 500))
                dimensions.setHeight(max(max_y, 500))
                layout.setDimensions(dimensions)

            else:
                dimensions = libsbml.Dimensions()
                dimensions.setWidth(500)
                dimensions.setHeight(500)
                layout.setDimensions(dimensions)
            
            # Create a map from variable ID to layout info
            layout_by_id = {lv['Id']: lv for lv in layout_vars}
            
            # Add glyphs for each variable
            for var in variables:
                var_id = var['Id']
                
                if var_id in layout_by_id:
                    layout_info = layout_by_id[var_id]
                    
                    # Create general glyph (since speciesGlyph is for SBML core species)
                    glyph = layout.createGeneralGlyph()
                    glyph.setId(f"_ly_var_{var_id}")
                    glyph.setReferenceId(f"var_{var_id}")
                    
                    # Set bounding box
                    bbox = libsbml.BoundingBox()
                    bbox.setId(f"_bb_var_{var_id}")
                    
                    position = libsbml.Point() # bbox.createPosition()
                    position.setX(float(layout_info.get('X', layout_info.get("PositionX",0))))
                    position.setY(float(layout_info.get('Y', layout_info.get("PositionY",0))))
                    bbox.setPosition(position)
                    
                    dimensions = libsbml.Dimensions()
                    dimensions.setWidth(45.0)  # Default width
                    dimensions.setHeight(25.0)  # Default height
                    bbox.setDimensions(dimensions)
                    
                    glyph.setBoundingBox(bbox)


    # Get function evaluator from BMA
    evaluator_type = _assembly.GetType('Evaluate')
    if evaluator_type is None:
        for t in _assembly.GetTypes():
            if 'eval' in t.Name.lower():
                evaluator_type = t
                break
    
    # Group relationships by target variable
    by_target = {}
    for rel in relationships:
        target = rel['ToVariable']
        if target not in by_target:
            by_target[target] = []
        by_target[target].append(rel)
    
    # Process each variable that has a formula
    for var in variables:
        var_id = var['Id']
        formula = var.get('Formula', '')
        
        if formula.isdigit():
            continue
        
        # Create transition
        transition = qual_plugin.createTransition()
        transition.setId(f"tr_{var_id}")
        
        # Add inputs (from relationships)
        input_vars = []
        
        if var_id in by_target:
            for rel in by_target[var_id]:
                input_var_id = rel['FromVariable']
                input_vars.append(input_var_id)
                
                input_elem = transition.createInput()
                input_elem.setId(f"in_{input_var_id}_{var_id}")
                input_elem.setQualitativeSpecies(f"var_{input_var_id}")
                input_elem.setTransitionEffect(libsbml.INPUT_TRANSITION_EFFECT_NONE)
                
                # Add sign if available
                if 'Type' in rel:
                    if rel['Type'] == "Activator":
                        input_elem.setSign(libsbml.INPUT_SIGN_POSITIVE)
                    elif rel['Type'] == "Inhibitor":
                        input_elem.setSign(libsbml.INPUT_SIGN_NEGATIVE)
        
        # Add output
        output_elem = transition.createOutput()
        output_elem.setId(f"out_{var_id}")
        output_elem.setQualitativeSpecies(f"var_{var_id}")
        output_elem.setTransitionEffect(libsbml.OUTPUT_TRANSITION_EFFECT_ASSIGNMENT_LEVEL)
        
        # Generate truth table
        truth_table = _generate_truth_table(qn, var_id, input_vars, variables, evaluator_type)
        
        # Convert truth table to function terms
        _add_function_terms_libsbml(transition, truth_table, input_vars, var_id)
    
    # Write to file
    libsbml.writeSBMLToFile(document, str(output_path))

def _generate_truth_table(qn, target_var_id, input_var_ids, variables, evaluator_type):
    """
    Generate truth table for a variable by evaluating its formula.
    
    Args:
        qn: QN object
        target_var_id: ID of target variable
        input_var_ids: List of input variable IDs
        variables: List of variable dicts
        evaluator_type: BMA Evaluate type
    
    Returns:
        dict: Maps input state tuples to output values
    """
    import itertools
    import System
    
    # Get variable ranges
    var_ranges = {}
    for var in variables:
        var_id = var['Id']
        range_to = var.get('RangeTo', 1)
        range_from = var.get('RangeFrom', 0)
        var_ranges[var_id] = list(range(range_from, range_to + 1))
    
    # If no inputs, just evaluate at state 0
    if not input_var_ids:
        input_var_ids = [target_var_id]
    
    # Generate all combinations of input values
    input_ranges = [var_ranges[vid] for vid in input_var_ids]
    
    truth_table = {}
    
    # Find evaluate method
    eval_method = None
    if evaluator_type:
        for method in evaluator_type.GetMethods():
            if method.IsPublic and method.IsStatic:
                # Look for evaluate or similar method
                if 'eval' in method.Name.lower():
                    eval_method = method
                    break
    
    # Generate truth table
    for input_values in itertools.product(*input_ranges):
        # Create state map
        state = {}
        for i, var_id in enumerate(input_var_ids):
            state[var_id] = input_values[i]
        
        # Add other variables at 0
        for var in variables:
            if var['Id'] not in state:
                state[var['Id']] = 0
        
        # Evaluate formula at this state
        
        #Expr.eval_expr v.var range v.f env_0
        #let rec eval_expr_int (node:var) (range:Map<var,int*int>) (e : expr) (env : Map<var, int>)
                
        #try:
        output_value = _evaluate_formula_at_state(qn, target_var_id, state)
        truth_table[input_values] = output_value

    return truth_table

def _wrap_bma_call(module_name,function_name,args):
    module = _assembly.GetType(module_name)
    function = module.GetMethod(function_name)
    '''
    print("######################################")
    print(module_name + ":" + function_name)
    params = function.GetParameters()

    for p in params:
        print(f"{p.Name}: {p.ParameterType.FullName}")

    for arg in args:
        print(f"{arg} - type: {type(arg)}")
    '''
    result = function.Invoke(None,args)
    return result

def python_dict_to_fsharp_map(python_dict, key_type=System.Int32, value_type=System.Int32):
    """
    Convert Python dict to F# Map.
    
    Args:
        python_dict: Python dictionary
        key_type: .NET type for keys (default: System.Int32)
        value_type: .NET type for values (default: System.Int32)
    
    Returns:
        F# Map<key_type, value_type>
    
    Examples:
        # Int to Int map
        fsharp_map = python_dict_to_fsharp_map({1: 10, 2: 20})
        
        # String to Int map
        fsharp_map = python_dict_to_fsharp_map(
            {"a": 1, "b": 2}, 
            System.String, 
            System.Int32
        )
    """
    from System.Collections.Generic import Dictionary, IEnumerable, KeyValuePair
    from Microsoft.FSharp.Collections import FSharpMap, MapModule
    
    if not python_dict:
        # Return empty map
        return MapModule.Empty[key_type, value_type]()
    
    # Create list of KeyValuePairs
    kvp_type = System.Tuple[key_type, value_type]
    from System.Collections.Generic import List as NetList
    
    kvp_list = NetList[kvp_type]()
    
    for k, v in python_dict.items():
        kvp = kvp_type(key_type(k), value_type(v))
        kvp_list.Add(kvp)
    
    # Convert to F# Map using MapModule.ofSeq
    #fsharp_map = MapModule.OfSeq(kvp_list)
    
    # Use MapModule.OfSeq via reflection
    map_module = System.Type.GetType("Microsoft.FSharp.Collections.MapModule, FSharp.Core")
    of_seq_method = map_module.GetMethod("OfSeq")
    
    # Make it generic for our key and value types
    generic_of_seq = of_seq_method.MakeGenericMethod(key_type, value_type)
    
    # Invoke with the list
    result = generic_of_seq.Invoke(None, [kvp_list])

    return result

    
def specialised_dict_to_fsharp_map(python_dict):
    from Microsoft.FSharp.Collections import MapModule
    from System import Int32, Tuple
    """
    Robust version that handles type conversion explicitly
    Works with both System types and Python native types
    """
    # Build map incrementally using MapModule.Add
    fsharp_map = MapModule.Empty[Int32, Tuple[Int32, Int32]]()
    
    for k, v in python_dict.items():
        # Convert key to System.Int32 if needed
        if isinstance(k, int) and not isinstance(k, Int32):
            sys_key = Int32(k)
        else:
            sys_key = k
        
        # Convert value to System.Tuple if needed
        if isinstance(v, tuple) and not isinstance(v, Tuple[Int32, Int32]):
            if len(v) == 2:
                sys_value = Tuple[Int32, Int32](Int32(v[0]), Int32(v[1]))
            else:
                raise ValueError(f"Value must be a 2-tuple, got {len(v)} items")
        else:
            sys_value = v
        
        # Add to map (returns new map, maps are immutable)
        fsharp_map = fsharp_map.Add(sys_key, sys_value)
    
    return fsharp_map

def _evaluate_formula_at_state(qn, target_var_id, state, ):
    #(node:var) (range:Map<var,int*int>) (e : expr) (env : Map<var, int>)
    
    stateInt32= {}
    for key in state.keys():
        stateInt32[System.Int32(key)] = System.Int32(state[key])
    
    env = python_dict_to_fsharp_map(stateInt32)
        
    e = qn[target_var_id].f
    
    variableRange = {}
    for node in qn:
        variableRange[node.var] = node.range
    variableRange = specialised_dict_to_fsharp_map(variableRange)
    
    args = [ System.Int32(target_var_id), variableRange, e, env ]
    result = int(_wrap_bma_call("Expr","eval_expr_int",args))
    return result

def _add_function_terms_libsbml(transition, truth_table, input_var_ids, target_var_id):
    """
    Add SBML function terms to transition using libsbml.
    
    Args:
        transition: libsbml Transition object
        truth_table: Dict mapping input tuples to output values
        input_var_ids: List of input variable IDs
        target_var_id: Target variable ID
    """
    # Group by output value
    by_output = {}
    for input_state, output_value in truth_table.items():
        if output_value not in by_output:
            by_output[output_value] = []
        by_output[output_value].append(input_state)
    
    # old- Find most common output (for default)
    # new- ginsim fails to import non-zero defaults correctly
    default_output = 0 # max(by_output.keys(), key=lambda k: len(by_output[k]))
    
    # Add default term
    default_term = transition.createDefaultTerm()
    default_term.setResultLevel(default_output)
    
    # Add function terms for other outputs
    for output_value, input_states in by_output.items():
        if output_value == default_output:
            continue
        
        # Create function term
        func_term = transition.createFunctionTerm()
        func_term.setResultLevel(output_value)
        
        # Build MathML condition
        math_ast = _create_condition_ast_libsbml(input_states, input_var_ids)
        if math_ast:
            func_term.setMath(math_ast)


def _create_condition_ast_libsbml(input_states, input_var_ids):
    """
    Create MathML AST for condition matching input states.
    
    Args:
        input_states: List of input state tuples
        input_var_ids: List of input variable IDs
    
    Returns:
        libsbml ASTNode
    """
    if len(input_states) == 0:
        return None
    
    if len(input_states) == 1:
        # Single state - create condition
        return _create_single_state_condition_libsbml(input_states[0], input_var_ids)
    
    # Multiple states - OR them together
    or_node = libsbml.ASTNode(libsbml.AST_LOGICAL_OR)
    
    for input_state in input_states:
        state_condition = _create_single_state_condition_libsbml(input_state, input_var_ids)
        or_node.addChild(state_condition)
    
    return or_node


def _create_single_state_condition_libsbml(input_state, input_var_ids):
    """
    Create MathML AST for a single input state condition.
    
    Args:
        input_state: Tuple of input values
        input_var_ids: List of input variable IDs
    
    Returns:
        libsbml ASTNode representing the condition
    """
    if len(input_var_ids) == 1:
        # Single variable: var = value
        eq_node = libsbml.ASTNode(libsbml.AST_RELATIONAL_EQ)
        
        var_node = libsbml.ASTNode(libsbml.AST_NAME)
        var_node.setName(f"var_{input_var_ids[0]}")
        
        val_node = libsbml.ASTNode(libsbml.AST_INTEGER)
        val_node.setValue(int(input_state[0]))
        
        eq_node.addChild(var_node)
        eq_node.addChild(val_node)
        
        return eq_node
    
    # Multiple variables: AND of (var1 = val1) AND (var2 = val2) ...
    and_node = libsbml.ASTNode(libsbml.AST_LOGICAL_AND)
    
    for i, var_id in enumerate(input_var_ids):
        eq_node = libsbml.ASTNode(libsbml.AST_RELATIONAL_EQ)
        
        var_node = libsbml.ASTNode(libsbml.AST_NAME)
        var_node.setName(f"var_{var_id}")
        
        val_node = libsbml.ASTNode(libsbml.AST_INTEGER)
        val_node.setValue(int(input_state[i]))
        
        eq_node.addChild(var_node)
        eq_node.addChild(val_node)
        
        and_node.addChild(eq_node)
    
    return and_node


def save_bma_to_sbml_qual(model_data, output_path, use_libsbml='auto'):
    """
    Save BMA model to SBML-qual format with function terms.
    
    Args:
        model_data: BMA model dict or BMAModel instance
        output_path: Path to save SBML-qual XML file
        use_libsbml: 'auto' (default), True, or False
                     'auto' uses libsbml if available
    
    Example:
        from pybma import load_model, save_bma_to_sbml_qual
        model_data = load_model("model.json")
        save_bma_to_sbml_qual(model_data, "output.sbml")
        
        # Force libsbml
        save_bma_to_sbml_qual(model_data, "output.sbml", use_libsbml=True)
        
        # Force native XML
        save_bma_to_sbml_qual(model_data, "output.sbml", use_libsbml=False)
    """
    from .core import BMAModel
    
    # Extract model data if BMAModel instance
    if isinstance(model_data, BMAModel):
        model_data = model_data.data
    
    # Decide which implementation to use
    if use_libsbml == 'auto':
        use_libsbml = LIBSBML_AVAILABLE
    elif use_libsbml and not LIBSBML_AVAILABLE:
        raise ImportError(
            "libsbml requested but not installed. "
            "Install with: pip install python-libsbml"
        )
    
    if use_libsbml:
        save_bma_to_sbml_qual_libsbml(model_data, output_path)
    else:
        save_bma_to_sbml_qual_native(model_data, output_path)


def save_bma_to_sbml_qual_native(model_data, output_path):
    """
    Save BMA model to SBML-qual using native XML (original implementation).
    This is the previous export_to_sbml_qual with truth table generation added.
    """
    from .core import model_to_qn, _assembly
    import System
    
    # Get model info
    model_name = model_data['Model'].get('Name', 'BMA Model')
    variables = model_data['Model']['Variables']
    relationships = model_data['Model']['Relationships']
    
    # Convert to QN for formula evaluation
    qn = model_to_qn(model_data)
    
    # Create SBML structure
    sbml = ET.Element('sbml', {
        'xmlns': 'http://www.sbml.org/sbml/level3/version1/core',
        'xmlns:qual': 'http://www.sbml.org/sbml/level3/version1/qual/version1',
        'level': '3',
        'version': '1',
        'qual:required': 'true'
    })
    
    model_elem = ET.SubElement(sbml, 'model', {
        'id': 'model',
        'name': model_name
    })
    
    # Add compartments (required)
    comp_list = ET.SubElement(model_elem, 'listOfCompartments')
    ET.SubElement(comp_list, 'compartment', {
        'id': 'default',
        'constant': 'true'
    })
    
    # Add qualitative species
    qual_species_list = ET.SubElement(model_elem, 'qual:listOfQualitativeSpecies')
    
    for var in variables:
        species_attrs = {
            'qual:id': f"var_{var['Id']}",
            'qual:name': var.get('Name', f"Variable {var['Id']}"),
            'qual:compartment': 'default',
            'qual:constant': 'false',
            'qual:maxLevel': str(var.get('RangeTo', 1))
        }
        
        # Add initial level if it's a simple number
        formula = var.get('Formula', '0')
        if formula.isdigit():
            species_attrs['qual:initialLevel'] = formula
        
        ET.SubElement(qual_species_list, 'qual:qualitativeSpecies', species_attrs)
    
    # Get function evaluator from BMA
    evaluator_type = _assembly.GetType('Evaluate')
    if evaluator_type is None:
        for t in _assembly.GetTypes():
            if 'eval' in t.Name.lower():
                evaluator_type = t
                break
    
    # Add transitions with function terms
    transitions_list = ET.SubElement(model_elem, 'qual:listOfTransitions')
    
    # Group relationships by target variable
    by_target = {}
    for rel in relationships:
        target = rel['ToVariable']
        if target not in by_target:
            by_target[target] = []
        by_target[target].append(rel)
    
    # Process each variable that has a formula
    for var in variables:
        var_id = var['Id']
        formula = var.get('Formula', '')
        
        if not formula or formula.isdigit():
            continue
        
        transition = ET.SubElement(transitions_list, 'qual:transition', {
            'qual:id': f"tr_{var_id}"
        })
        
        # Add inputs (from relationships)
        inputs_list = ET.SubElement(transition, 'qual:listOfInputs')
        input_vars = []
        
        if var_id in by_target:
            for rel in by_target[var_id]:
                input_var_id = rel['FromVariable']
                input_vars.append(input_var_id)
                
                input_attrs = {
                    'qual:id': f"in_{input_var_id}_{var_id}",
                    'qual:qualitativeSpecies': f"var_{input_var_id}",
                    'qual:transitionEffect': 'none'
                }
                
                # Add sign if available
                if 'Type' in rel:
                    if rel['Type'] == 1:
                        input_attrs['qual:sign'] = 'positive'
                    elif rel['Type'] == 2:
                        input_attrs['qual:sign'] = 'negative'
                
                ET.SubElement(inputs_list, 'qual:input', input_attrs)
        
        # Add output
        outputs_list = ET.SubElement(transition, 'qual:listOfOutputs')
        ET.SubElement(outputs_list, 'qual:output', {
            'qual:id': f"out_{var_id}",
            'qual:qualitativeSpecies': f"var_{var_id}",
            'qual:transitionEffect': 'assignmentLevel'
        })
        
        # Generate function terms from truth table
        func_terms_elem = ET.SubElement(transition, 'qual:listOfFunctionTerms')
        
        # Generate truth table
        truth_table = _generate_truth_table(qn, var_id, input_vars, variables, evaluator_type)
        
        # Convert truth table to function terms
        _add_function_terms(func_terms_elem, truth_table, input_vars, var_id)
    
    # Write to file
    tree = ET.ElementTree(sbml)
    ET.indent(tree, space="  ")
    tree.write(output_path, encoding='utf-8', xml_declaration=True)