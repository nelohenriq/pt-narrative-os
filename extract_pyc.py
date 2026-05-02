#!/usr/bin/env python3
"""
Try to extract source from pyc file using bytecode analysis.
"""
import marshal
import dis
import sys

pyc_path = '/teamspace/studios/this_studio/pt-narrative-os/review/__pycache__/mission_control.cpython-312.pyc'

with open(pyc_path, 'rb') as f:
    # Skip 16-byte header
    header = f.read(16)
    
    # Load the module code object
    module_code = marshal.load(f)
    
    print(f"Module: {module_code.co_name}")
    print(f"First line: {module_code.co_firstlineno}")
    print(f"Constants: {len(module_code.co_consts)}")
    
    # Find the docstring (usually first constant)
    for i, const in enumerate(module_code.co_consts):
        if isinstance(const, str) and len(const) > 100:
            print(f"\nDocstring (const {i}):")
            print(const[:500])
            break
    
    # Try to find function code objects
    for i, const in enumerate(module_code.co_consts):
        if hasattr(const, 'co_name') and hasattr(const, 'co_code'):
            print(f"\nFunction: {const.co_name} at line {const.co_firstlineno}")
            # Get first few instructions
            instructions = list(dis.get_instructions(const))
            for instr in instructions[:5]:
                print(f"  {instr.opname} {instr.argrepr}")
