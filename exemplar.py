import json

import clr_loader
from pythonnet import set_runtime


'''

Exemplar illustrating how to work with BMA libraries.

Script 
-reads "toy model unstable" model
-performs stability analysis
-knocks out a gene
-repeats stability analysis

Current philosophy
-models are dicts
-internally these are converted to QNs (don't need to see BMA "model type" directly)

'''

MODEL = "./models/ToyModelUnstable.json"
DLL = "/home/benjamin/src/pybma/pybma/assemblies/BioCheckAnalyzerMulti.dll"

# Set the runtime to .NET Core before importing clr
runtime = clr_loader.get_coreclr()
set_runtime(runtime)

# NOW import clr
import clr
import System

from System.Collections.Generic import List

fsharp_core_path = "/home/benjamin/src/pybma/pybma/assemblies/FSharp.Core.dll"
clr.AddReference(fsharp_core_path)

clr.AddReference("FSharp.Core")
from Microsoft.FSharp.Reflection import FSharpType, FSharpValue

dll_path = DLL
clr.AddReference(dll_path)

assembly = System.Reflection.Assembly.LoadFrom(dll_path)

from BioModelAnalyzer import Model

Variable = Model.Variable
Relationship = Model.Relationship

_assembly = assembly


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


def _fsharp_map_to_python(fsharp_map):
    """Convert F# Map to Python dict"""
    if fsharp_map is None:
        return {}
    
    python_dict = {}
    
    try:
        # Iterate through F# map
        for item in fsharp_map:
            # F# Map entries are KeyValuePairs
            key = item.Key
            value = item.Value
            
            # Convert to Python int if possible
            try:
                key = int(key)
            except:
                key = str(key)
            
            try:
                value = int(value)
            except:
                value = str(value)
            
            python_dict[key] = value
    except Exception as e:
        print(f"Warning: Could not convert map: {e}")
    
    return python_dict


def _convert_interval(interval):
    """
    Convert QN.interval to Python representation.
    
    QN.interval is likely a record or tuple with low/high bounds
    """
    try:
        # Try to get properties
        if hasattr(interval, 'lo') and hasattr(interval, 'hi'):
            return {"low": int(interval.lo), "high": int(interval.hi)}
        elif hasattr(interval, 'Item1') and hasattr(interval, 'Item2'):
            # If it's a tuple
            return {"low": int(interval.Item1), "high": int(interval.Item2)}
        else:
            # Try to inspect the type
            interval_type = interval.GetType()
            props = [p for p in interval_type.GetProperties()]
            
            if len(props) == 2:
                val1 = props[0].GetValue(interval)
                val2 = props[1].GetValue(interval)
                return {"low": int(val1), "high": int(val2)}
            
            return str(interval)
    except Exception as e:
        return {"error": str(e), "raw": str(interval)}


def _convert_history(history):
    """
    Convert history (int * QN.interval) list to Python list.
    
    Args:
        history: F# list of tuples (int, QN.interval)
        
    Returns:
        list: Python list of dicts with format [{"variable": int, "interval": {...}}, ...]
    """
    python_history = []
    
    try:
        fsharp_list = _fsharp_list_to_python(history)
        
        for item in fsharp_list:
            # Each item is a tuple (int * QN.interval)
            if hasattr(item, 'Item1') and hasattr(item, 'Item2'):
                var_id = int(item.Item1)
                interval = _convert_interval(item.Item2)
                
                python_history.append({
                    "variable": var_id,
                    "interval": interval
                })
            else:
                # Fallback
                python_history.append(str(item))
    
    except Exception as e:
        print(f"Warning: Could not convert history: {e}")
    
    return python_history


def _get_union_case_name(obj):
    """Get the case name of an F# union type"""
    try:
        obj_type = obj.GetType()
        
        # Check if it's actually a union
        if not System.Reflection.FSharpType.IsUnion(obj_type):
            return None
        
        # Get the case info
        case_info, _ = System.Reflection.FSharpValue.GetUnionFields(obj, obj_type)
        return case_info.Name
    except:
        return None


def _get_union_case_fields(obj):
    """Get the fields of an F# union case"""
    try:
        obj_type = obj.GetType()
        
        if not System.Reflection.FSharpType.IsUnion(obj_type):
            return []
        
        _, fields = System.Reflection.FSharpValue.GetUnionFields(obj, obj_type)
        return list(fields)
    except:
        return []


def _convert_stability_result(stability_result):
    """
    Convert stability_result to Python dict.
    
    From Result.fs:
    type history = (int * QN.interval) list 
    type stability_result =
        | SRStabilizing of history
        | SRNotStabilizing of history
    """
    if stability_result is None:
        return {"result": "unknown"}
    
    try:
        case_name = _get_union_case_name(stability_result)
        
        if case_name is None:
            return {"result": "unknown", "raw": str(stability_result)}
        
        if case_name == "SRStabilizing":
            # Get the history field
            fields = _get_union_case_fields(stability_result)
            history = fields[0] if fields else None
            
            return {
                "result": "stabilizing",
                "description": "Model is stabilizing",
                "history": _convert_history(history)
            }
        
        elif case_name == "SRNotStabilizing":
            # Get the history field
            fields = _get_union_case_fields(stability_result)
            history = fields[0] if fields else None
            
            return {
                "result": "not_stabilizing",
                "description": "Model is not stabilizing",
                "history": _convert_history(history)
            }
    
    except Exception as e:
        print(f"Warning: Could not convert stability_result: {e}")
        import traceback
        traceback.print_exc()
        return {"result": "error", "message": str(e), "raw": str(stability_result)}
    
    return {"result": "unknown", "raw": str(stability_result)}

def loadModel(name):
    #from a filename, return a BMA model object
    with open(name, "r") as f:
        data = json.load(f)
    print("✓ JSON available!")
    return(data)

def processModel(data):
    #load data into model object
    model = Model()
    modelData = data['Model']
    model.Name = modelData['Name']

    #variables_list = List[Variable]()
    variables = []
    for var_data in modelData['Variables']:
        var = Variable()
        var.Id = var_data.get('Id')
        var.Name = var_data.get('Name')
        var.RangeFrom = var_data.get('RangeFrom')
        var.RangeTo = var_data.get('RangeTo')
        var.Formula = var_data.get('Formula')
        variables.append(var)
    
    variables_array = System.Array[Variable](variables)
    model.Variables = variables_array

    relationships = []
    for rel_data in modelData['Relationships']:
        rel = Relationship()
        rel.Id = rel_data.get('Id')
        #rel.Type = rel_data.get('Type')
        rel.FromVariable = rel_data.get('FromVariable')
        rel.ToVariable = rel_data.get('ToVariable')
        relationships.append(rel)
    relationships_array = System.Array[Relationship](relationships)
    model.Relationships = relationships_array

    #turn model into qn
    marshal = assembly.GetType('Marshal')
    qn_of_model = marshal.GetMethod("QN_of_Model")
    args = System.Array[System.Object]([model])
    result = qn_of_model.Invoke(None, args)

    print("✓ Model converted!")
    return(result)

def stability(qn):
    stabilize = assembly.GetType('Stabilize')
    sp = stabilize.GetMethod("stabilization_prover")

    Concurrency = assembly.GetType("Counterexample+concurrency")
    sync = Concurrency.GetProperty("Synchronous").GetValue(None)

    args = System.Array[System.Object]([qn, False, sync])
    result = sp.Invoke(None, args)
    print("✓ Proof performed!")
    return(result)

#load model from json into a qn
model= loadModel(MODEL)
qn = processModel(model)
#stability analysis
proof0 = stability(qn)
#show the result
print(proof0)
print("Repeat with a knockout")
#knock out a variable
model['Model']['Variables'][0]['Formula'] = "0"
qn = processModel(model)
proof = stability(qn)
print(proof)



'''
# Find the marshal type
marshal_type = None
name = "marshal"
for t in assembly.GetTypes():
    if name in t.Name.lower() or name in str(t.FullName).lower():
        marshal_type = t
        break

if marshal_type:
    print(f"Found marshal module: {marshal_type.FullName}\n")
    print("ALL methods in marshal module:\n")
    
    for method in marshal_type.GetMethods():
        if method.IsPublic and method.IsStatic:
            params = ", ".join([f"{p.ParameterType.Name} {p.Name}" 
                               for p in method.GetParameters()])
            print(f"  {method.Name}({params}) -> {method.ReturnType.Name}")
    
    print("\n\nSearching for anything with 'QN' or 'model':\n")
    for method in marshal_type.GetMethods():
        if method.IsPublic and method.IsStatic:
            name_lower = method.Name.lower()
            if 'qn' in name_lower or 'model' in name_lower:
                params = ", ".join([f"{p.ParameterType.FullName} {p.Name}" 
                                   for p in method.GetParameters()])
                print(f"  {method.Name}:")
                print(f"    Params: {params if params else '(none)'}")
                print(f"    Returns: {method.ReturnType.FullName}\n")
else:
    print("marshal module not found!")

qn_of_model_method = marshal_type.GetMethod("QN_of_Model")

result = qn_of_model_method.Invoke(None, [your_model])

'''
