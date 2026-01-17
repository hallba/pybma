"""
Core BMA functionality - model loading and QN conversion
"""

import json

# Configure .NET runtime
def _setup_runtime():
    """Configure .NET Core runtime"""
    try:
        import clr_loader
        from pythonnet import set_runtime
        runtime = clr_loader.get_coreclr()
        set_runtime(runtime)
    except Exception as e:
        print(f"Warning: Could not configure .NET Core runtime: {e}")

_setup_runtime()

import clr
import System
from pathlib import Path
from System.Collections.Generic import List

# Load BMA assembly
ASSEMBLIES_DIR = Path(__file__).parent / "assemblies"
DLL_PATH = ASSEMBLIES_DIR / "BioCheckAnalyzerMulti.dll"

if not DLL_PATH.exists():
    raise FileNotFoundError(
        f"BMA DLL not found at {DLL_PATH}. "
        "Please ensure BioCheckAnalyzerMulti.dll is in the assemblies directory."
    )

clr.AddReference(str(DLL_PATH))
_assembly = System.Reflection.Assembly.LoadFrom(str(DLL_PATH))

# Import BMA types
from BioModelAnalyzer import Model

Variable = Model.Variable
Relationship = Model.Relationship

# Get Marshal type
_marshal_type = _assembly.GetType('Marshal')
_qn_of_model_method = _marshal_type.GetMethod("QN_of_Model")


def load_model(json_path):
    """
    Load a BMA model from a JSON file.
    
    Args:
        json_path: Path to BMA JSON file
        
    Returns:
        dict: Model data as Python dictionary
    """
    with open(json_path, "r") as f:
        data = json.load(f)
    return data

def save_model(model, json_path):
    with open(json_path, "w") as f:
        json.dump(model,f, ensure_ascii=False, indent=4)

def model_to_qn(model_data):
    """
    Convert a BMA model dictionary to a QN (Qualitative Network).
    
    Args:
        model_data: Dictionary containing BMA model data
        
    Returns:
        QN object (FSharpList of nodes)
    """
    # Create BMA Model object
    model = Model()
    model_dict = model_data['Model']
    model.Name = model_dict['Name']
    
    # Add Variables
    variables = []
    for var_data in model_dict['Variables']:
        var = Variable()
        var.Id = var_data.get('Id')
        var.Name = var_data.get('Name')
        var.RangeFrom = var_data.get('RangeFrom')
        var.RangeTo = var_data.get('RangeTo')
        var.Formula = var_data.get('Formula')
        variables.append(var)
    
    model.Variables = System.Array[Variable](variables)
    
    # Add Relationships
    relationships = []
    for rel_data in model_dict['Relationships']:
        rel = Relationship()
        rel.Id = rel_data.get('Id')
        rel.FromVariable = rel_data.get('FromVariable')
        rel.ToVariable = rel_data.get('ToVariable')
        relationships.append(rel)
    
    model.Relationships = System.Array[Relationship](relationships)
    
    # Convert to QN
    args = System.Array[System.Object]([model])
    qn = _qn_of_model_method.Invoke(None, args)
    
    return qn


class BMAModel:
    """
    Wrapper class for BMA models providing a Pythonic interface.
    """
    
    def __init__(self, json_path=None, model=None):
        """
        Initialize BMA model from JSON file.
        
        Args:
            json_path: Path to BMA JSON file
        """
        self.json_path = json_path
        if model != None:
            self.data = model
        elif json_path != None:
            self.data = load_model(json_path)
        else:
            print("No model or model path given")
            raise
        self._qn = None

    def __deepcopy__(self, memo):
        """Create a deep copy of the BMAModel, regenerating qn from model."""
        import copy

        # Assuming self.model is a plain Python dict/JSON
        new_model = copy.deepcopy(self.data)

        # Create new instance using the normal constructor
        return BMAModel(model=new_model)

    @property
    def qn(self):
        """Get or create QN representation of the model"""
        if self._qn is None:
            self._qn = model_to_qn(self.data)
        return self._qn
    
    def refresh_qn(self):
        """Force regeneration of QN from current model data"""
        self._qn = model_to_qn(self.data)
        return self._qn
    
    def knockout_variable(self, variable_index, formula="0"):
        """
        Knock out a variable by setting its formula.
        
        Args:
            variable_index: Index of variable to knock out
            formula: Formula to set (default "0")
        """
        #work out the internal index
        true_index = None
        for i,variable in enumerate(self.data['Model']['Variables']):
            if variable['Id'] == variable_index:
                true_index = i
        
        self.data['Model']['Variables'][true_index]['Formula'] = formula
        self._qn = None  # Invalidate cached QN
    
    def get_variable(self, index):
        """Get variable data by index"""
        return self.data['Model']['Variables'][index]
    
    def get_variables(self):
        """Get all variables"""
        return self.data['Model']['Variables']
    
    @property
    def name(self):
        """Get model name"""
        return self.data['Model']['Name']
