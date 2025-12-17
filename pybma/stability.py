"""
Stability analysis functions
"""

import System
from pathlib import Path
from .core import _assembly
from .utilities import bmaTrace_to_dict

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

def _timepoint_to_python(timepoint):
    time = int(timepoint.Item1)
    range = timepoint.Item2
    #process range map
    rangeResult = {}
    for item in range:
        key = item.Key
        value = item.Value    
        try:
                key = int(key)
        except:
                key = str(key)
        value = (int(value.Item1),int(value.Item2))
        rangeResult[key] = value
    return(time,rangeResult)

def _convertProofStep(step):
    timepoint = int(step.Item1)
    ranges = _fsharp_map_to_python(step.Item2)
    return(timepoint,ranges)

def unpackProof(result):
    name = result.GetType().FullName.split("+")[-1]
    if name == "SRStabilizing":
        #stable result
        stable = True
    else:
        stable = False
    rawHistory = result.Item
    history = [_timepoint_to_python(timepoint) for timepoint in _fsharp_list_to_python(rawHistory)]
    output = {"stable":stable,"history":history}
    return output

def unpackCex(result):
    if result==None: return None
    cex = result.Value
    t = cex.GetType().FullName.split("+")[-1]
    if t == "CExCycle":
        sim = bmaTrace_to_dict(_fsharp_map_to_python(cex.Item))
    elif t == "CExFixpoint":
        sim = bmaTrace_to_dict(_fsharp_map_to_python(cex.Item))
    elif t == "CExEndComponent":
        sim = bmaTrace_to_dict(_fsharp_map_to_python(cex.Item))
    elif t == "CExBifurcation":
        sim = (bmaTrace_to_dict(_fsharp_map_to_python(cex.Item1)),bmaTrace_to_dict(_fsharp_map_to_python(cex.Item2)))
    else:
        sim = None
    return({"Result":t,"Example":sim})
        
def unpackResult(proofResult):
    progression = unpackProof(proofResult.Item1)
    cex = unpackCex(proofResult.Item2)
    return({"ProofProgression":progression,"CounterExample":cex})

def check_stability(qn, synchronous=True):
    """
    Check stability of a QN (Qualitative Network).
    
    Args:
        qn: QN object from model_to_qn()
        synchronous: Use synchronous concurrency (default True)
        
    Returns:
        Stability result object
    """
    # Get Stabilize type and method
    stabilize = _assembly.GetType('Stabilize')
    sp = stabilize.GetMethod("stabilization_prover")
    
    # Get concurrency mode
    Concurrency = _assembly.GetType("Counterexample+concurrency")
    if synchronous:
        concurrency = Concurrency.GetProperty("Synchronous").GetValue(None)
    else:
        concurrency = Concurrency.GetProperty("Asynchronous").GetValue(None)
    
    # Invoke stability prover
    args = System.Array[System.Object]([qn, False, concurrency])
    result = sp.Invoke(None, args)
    
    return unpackResult(result)
