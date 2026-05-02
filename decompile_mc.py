import marshal
import sys
import os

pyc_path = '/teamspace/studios/this_studio/pt-narrative-os/review/__pycache__/mission_control.cpython-312.pyc'

# Read the pyc file
with open(pyc_path, 'rb') as f:
    # Skip the header (16 bytes for Python 3.12+)
    header = f.read(16)
    print(f"Header: {header}")
    
    # The rest should be the code object
    code = marshal.load(f)
    print(f"Code object loaded: {code.co_name}")
    print(f"Number of lines: {code.co_firstlineno}")
    
    # Try to decompile to source
    # This is tricky without a proper decompiler, but let's try
    import dis
    print("\nDisassembly (first 50 instructions):")
    instructions = list(dis.get_instructions(code))
    for instr in instructions[:50]:
        print(f"  {instr}")
