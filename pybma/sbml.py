"""
SBML-qual import functionality for PyBMA
"""

import xml.etree.ElementTree as ET
from pathlib import Path

# Try to import libsbml
try:
    import libsbml
    LIBSBML_AVAILABLE = True
except ImportError:
    LIBSBML_AVAILABLE = False


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
        
        # Add inputs
        inputs_list = ET.SubElement(transition, 'qual:listOfInputs')
        for rel in rels:
            ET.SubElement(inputs_list, 'qual:input', {
                'qual:id': f"in_{rel['FromVariable']}_{target_id}",
                'qual:qualitativeSpecies': f"var_{rel['FromVariable']}",
                'qual:transitionEffect': 'none'
            })
        
        # Add outputs
        outputs_list = ET.SubElement(transition, 'qual:listOfOutputs')
        ET.SubElement(outputs_list, 'qual:output', {
            'qual:id': f"out_{target_id}",
            'qual:qualitativeSpecies': f"var_{target_id}",
            'qual:transitionEffect': 'assignmentLevel'
        })
        
        # Add function terms (simplified)
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
    
    Example:
        result = validate_sbml_qual("model.sbml")
        if not result['valid']:
            print("Errors:", result['errors'])
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
    
    Example:
        info = get_sbml_info("model.sbml")
        print(f"Model: {info['model_name']}")
        print(f"Variables: {info['num_species']}")
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
    Basic implementation - handles simple SBML-qual files.
    """
    tree = ET.parse(sbml_path)
    root = tree.getroot()
    
    # SBML namespaces
    ns = {
        'sbml': 'http://www.sbml.org/sbml/level3/version1/core',
        'qual': 'http://www.sbml.org/sbml/level3/version1/qual/version1'
    }
    
    # Extract model
    sbml_model = root.find('sbml:model', ns)
    model_name = sbml_model.get('name', 'Imported SBML Model') if sbml_model is not None else 'Imported SBML Model'
    
    # Extract qualitative species (variables)
    variables = []
    qual_species_list = root.findall('.//qual:qualitativeSpecies', ns)
    
    var_id_map = {}  # Map SBML IDs to BMA IDs
    
    for idx, species in enumerate(qual_species_list):
        sbml_id = species.get('{http://www.sbml.org/sbml/level3/version1/qual/version1}id') or species.get('id')
        name = species.get('{http://www.sbml.org/sbml/level3/version1/qual/version1}name') or species.get('name') or sbml_id
        
        # Get max level
        max_level = species.get('{http://www.sbml.org/sbml/level3/version1/qual/version1}maxLevel')
        range_to = int(max_level) if max_level else 1
        
        # Initial level
        initial_level = species.get('{http://www.sbml.org/sbml/level3/version1/qual/version1}initialLevel')
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
    
    # Extract transitions (relationships)
    transitions = root.findall('.//qual:transition', ns)
    relationships = []
    
    for transition in transitions:
        # Get target variable
        outputs = transition.findall('.//qual:output', ns)
        if not outputs:
            continue
        
        target_id = outputs[0].get('{http://www.sbml.org/sbml/level3/version1/qual/version1}qualitativeSpecies')
        if target_id not in var_id_map:
            continue
        
        target_var_id = var_id_map[target_id]
        
        # Get input variables
        inputs = transition.findall('.//qual:input', ns)
        
        for input_elem in inputs:
            input_id = input_elem.get('{http://www.sbml.org/sbml/level3/version1/qual/version1}qualitativeSpecies')
            if input_id in var_id_map:
                input_var_id = var_id_map[input_id]
                
                relationship = {
                    'Id': len(relationships),
                    'FromVariable': input_var_id,
                    'ToVariable': target_var_id,
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
            'Variables': [],
            'Containers': [],
            'AnnotatedGridCells': [],
            'Description': f'Imported from SBML-qual: {Path(sbml_path).name}'
        },
        'ltl': {
            'states': [],
            'operations': []
        }
    }
    
    return bma_model


# ============================================================================
# libsbml implementation (enhanced)
# ============================================================================

def _load_with_libsbml(sbml_path):
    """
    Load SBML-qual using libsbml library (handles complex files).
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
    
    # Extract transitions
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
        
        # Get inputs
        for j in range(transition.getNumInputs()):
            input_elem = transition.getInput(j)
            input_id = input_elem.getQualitativeSpecies()
            
            if input_id in var_id_map:
                input_var_id = var_id_map[input_id]
                
                relationship = {
                    'Id': len(relationships),
                    'FromVariable': input_var_id,
                    'ToVariable': target_var_id,
                }
                relationships.append(relationship)
        
        # Extract formula (simplified - could be enhanced with MathML parsing)
        if transition.getNumFunctionTerms() > 0:
            function_term = transition.getFunctionTerm(0)
            result_level = function_term.getResultLevel()
            variables[target_var_id]['Formula'] = str(result_level)
    
    # Create BMA model
    bma_model = {
        'Model': {
            'Name': model_name,
            'Variables': variables,
            'Relationships': relationships
        },
        'Layout': {
            'Variables': [],
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