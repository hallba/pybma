"""
LTL analysis
"""

import System
from pathlib import Path
from .core import _assembly

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

def _string_to_LTL_formula(string_formula,qn):
    args = [string_formula, qn, False]
    result = _wrap_bma_call("LTL","string_to_LTL_formula",args)
    return result

def _nuRangel(qn):
    args = [ qn ]
    result = _wrap_bma_call("Rangelist","nuRangel",args)
    return result

def _output_paths(qn,nuRangel):
    args = [qn, nuRangel]
    result = _wrap_bma_call("Paths" , "output_paths", args)
    return result

def _change_list_to_length(paths, length_of_path):
    args = [paths, length_of_path]
    result = _wrap_bma_call("Paths", "change_list_to_length", args)
    return result

def _double_bounded_mc_with_sim(ltl_formula, qn, correct_length_paths, polarity):
    args = [ltl_formula, qn, correct_length_paths, polarity]
    result = _wrap_bma_call("BMC", "DoubleBoundedMCWithSim", args)
    return result

def testQuery(query, qn, length_of_path):
    ltl_formula = _string_to_LTL_formula(query,qn)
    
    if str(ltl_formula) == "Error":
        print("Malformed LTL query: " + query)
        print("Check paranetheses and capitalisation- for examples and keywords see:")
        print("https://github.com/hallba/BioModelAnalyzer/blob/master/BmaLinux/BioCheckAnalyzerMulti/LTL.fs")
        return {}
    
    nuRangel = _nuRangel( qn)
    paths = _output_paths( qn, nuRangel)
    correct_length_paths = _change_list_to_length(paths, System.Int32(length_of_path))
    # res1, model1, res2, model2
    checkTuple = _double_bounded_mc_with_sim(ltl_formula, qn, correct_length_paths, System.Boolean(False))
    res1 = checkTuple.Item1
    
    def maxRange(d):
        if len(d)>0:
            return range(max(d.keys()))
        else:
            return []
    
    model1 = checkTuple.Item2.Item2
    
    ptrace = {}
    
    for x in maxRange(model1):
        t = model1[x]
        for item in t:
            if int(item.Key) in ptrace:
                ptrace[int(item.Key)].append(item.Value)
            else:
                ptrace[int(item.Key)] = [item.Value]
    
    res2 = checkTuple.Item3
    model2 = checkTuple.Item4.Item2
    
    ntrace = {}
    
    for x in maxRange(model2):
        t = model2[x]
        for item in t:
            if int(item.Key) in ntrace:
                ntrace[int(item.Key)].append(item.Value)
            else:
                ntrace[int(item.Key)] = [item.Value]
    print(ltl_formula)
    result = {"LTL":query, "query":res1,"posTrace":ptrace,"negation":res2,"negTrace":ntrace}
    
    return result
    #_check_model model1 res1 qn
    """
    let nuRangel = Rangelist.nuRangel qn
    let paths = Paths.output_paths qn nuRangel
    let correct_length_paths = Paths.change_list_to_length paths length_of_path
    BMC.DoubleBoundedMCWithSim ltl_formula qn correct_length_paths false 
    
    
    BioCheckPlusZ3.check_model model1 res1 qn
    Marshal.ltl_result_full res1 model1
    """
