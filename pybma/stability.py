"""
Stability analysis functions
"""

import System
from pathlib import Path
from .core import _assembly


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
    
    return result
