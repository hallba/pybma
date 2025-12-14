"""
Stability analysis functions
"""

import System
from pathlib import Path
from .core import _assembly

# Load BMA assembly
ASSEMBLIES_DIR = Path(__file__).parent / "assemblies"
DLL_PATH = ASSEMBLIES_DIR / "FSharp.Core.dll"

_simulate = _assembly.GetType("Simulate")
_simulate_many = _simulate.GetMethod("simulate_many")

def _fsharp_list_to_python(fsharp_list):
    """Convert F# list to Python list"""
    if fsharp_list is None:
        return []

    python_list = []
    current = fsharp_list

    # F# lists have IsEmpty and Head/Tail properties
    try:
        while not current.IsEmpty:
            python_list.append(current.Head)
            current = current.Tail
    except:
        # If not an F# list, try to iterate normally
        try:
            python_list = list(fsharp_list)
        except:
            pass

    return python_list

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

def simulate(qn,steps=10,initial_values=None):
    #Need to use the function simulate_many which takes a qn, and initial state 
    #list of tuple of qn node, int, and steps
    nodes = _fsharp_list_to_python(qn)

    t0 = {}
    numberVariables = qn.Length
    variables = [ qn[varId].var for varId in range(numberVariables) ]
    if initial_values == None:
        for var in variables:
            t0[var] = System.Int32(int(0))
    
    t0 = python_dict_to_fsharp_map(t0)

    args = [qn,t0,System.Int32(steps)]
    ftrace = _simulate_many.Invoke(None, args)

    trace = [item for item in ftrace]
    result = {}
    for key in trace[0].keys():
        result[key] = []

    for var in variables:
        for point in trace:
            result[var].append(point[var])

    return result
