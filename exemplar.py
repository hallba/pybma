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


dll_path = DLL
clr.AddReference(dll_path)

assembly = System.Reflection.Assembly.LoadFrom(dll_path)

from BioModelAnalyzer import Model

Variable = Model.Variable
Relationship = Model.Relationship

def loadModel(name):
    #from a filename, return a BMA model object
    with open(name, "r") as f:
        data = json.load(f)
        print("✓ JSON available!")
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

    return(data,result)

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
