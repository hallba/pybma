import clr_loader
from pythonnet import set_runtime

# Set the runtime to .NET Core before importing clr
runtime = clr_loader.get_coreclr()
set_runtime(runtime)

# NOW import clr
import clr
import System

dll_path = "/home/benjamin/src/pybma/pybma/assemblies/BioCheckAnalyzerMulti.dll"
clr.AddReference(dll_path)

assembly = System.Reflection.Assembly.LoadFrom(dll_path)

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


