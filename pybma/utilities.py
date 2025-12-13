def bmaTrace_to_dict(trace):
    timepoints = 0
    variables = set()
    for key in trace.keys():
        time = int(key.split("^")[1])
        var = int(key.split("^")[0])
        timepoints = max(timepoints,time+1)
        variables.add(var)
    variables = list(variables)
    result = {}
    for var in variables:
        result[var] = [None for i in range(timepoints)]
    for key in trace.keys():
        time = int(key.split("^")[1])
        var = int(key.split("^")[0])
        result[var][time] = trace[key]
    return(result)

def model_to_variableIDdict(model):
    variables = model['Model']['Variables']
    vmap = {}
    for var in variables:
        vmap[var['Id']] = var['Name']
    return vmap
