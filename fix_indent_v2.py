"""
Fix indentation for all function bodies in mission_control.py
Add 4 spaces to all lines that are inside a function but not indented
"""

with open('review/mission_control.py', 'r') as f:
    lines = f.readlines()

# Track when we're inside a function
in_function = False
function_start_line = None

for i, line in enumerate(lines):
    stripped = line.rstrip()
    
    # Check if this is a function definition
    if stripped.startswith('async def ') or stripped.startswith('def '):
        in_function = True
        function_start_line = i
        continue
    
    # Check if this is a decorator
    if stripped.startswith('@'):
        continue
    
    # Check if this is a class definition
    if stripped.startswith('class '):
        in_function = True
        function_start_line = i
        continue
    
    # Check if we've left the function (next function/class at column 0)
    if in_function and i > function_start_line + 1:
        if (stripped.startswith('async def ') or 
            stripped.startswith('def ') or 
            stripped.startswith('class ') or
            stripped.startswith('# ────')):
            in_function = False
    
    # If we're in a function and the line is not blank and has no indentation
    if in_function and stripped and not line.startswith(' ') and not line.startswith('\t'):
        # Check if this is a line that should be indented
        # (not a docstring, not a comment at column 0, not a decorator)
        if not (stripped.startswith('"""') or 
                stripped.startswith("'''") or
                stripped.startswith('#') or
                stripped.startswith('import ') or
                stripped.startswith('from ')):
            # Add 4 spaces of indentation
            lines[i] = '    ' + line

with open('review/mission_control.py', 'w') as f:
    f.writelines(lines)

print("Fixed indentation")

# Verify
import py_compile
try:
    py_compile.compile('review/mission_control.py', doraise=True)
    print("✅ Syntax is valid!")
except py_compile.PyCompileError as e:
    print(f"❌ Still has syntax error: {e}")
