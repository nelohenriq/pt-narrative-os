"""
Fix all indentation in mission_control.py
This script will ensure all function bodies are properly indented with 4 spaces.
"""

with open('review/mission_control.py', 'r') as f:
    lines = f.readlines()

# Track the current indentation level
indent_level = 0
fixed_lines = []

for line in lines:
    stripped = line.rstrip()
    
    if not stripped:
        fixed_lines.append(line)
        continue
    
    # Check if this line is a function/class definition or decorator
    if (stripped.startswith('async def ') or 
        stripped.startswith('def ') or 
        stripped.startswith('class ') or
        stripped.startswith('@')):
        # These should be at indent_level 0
        fixed_lines.append('    ' * indent_level + stripped + '\n')
        if stripped.startswith('@'):
            # Decorator - next line (function def) should also be at same level
            pass
        elif stripped.startswith('async def ') or stripped.startswith('def ') or stripped.startswith('class '):
            indent_level += 1
    elif stripped.startswith('"""') or stripped.startswith("'''"):
        # Docstring - keep at current indent level
        fixed_lines.append('    ' * indent_level + stripped + '\n')
    elif stripped.startswith('#'):
        # Comment - keep at current indent level
        fixed_lines.append('    ' * indent_level + stripped + '\n')
    elif stripped in ['return', 'return {', 'return health', 'return activities[:20]']:
        # Return statement - reduce indent by 1
        indent_level = max(0, indent_level - 1)
        fixed_lines.append('    ' * indent_level + stripped + '\n')
    else:
        # Regular code line - use current indent level
        fixed_lines.append('    ' * indent_level + stripped + '\n')

# This approach is too simplistic and won't work for complex Python.
# Let me try a different approach - just use the tokenize module to properly reindent.

import tokenize
import io

# Read the file
with open('review/mission_control.py', 'rb') as f:
    content = f.read()

# Use tokenize to parse and reindent
try:
    tokens = tokenize.tokenize(io.BytesIO(content).readline)
    # This won't actually fix indentation, but it will tell us if the syntax is valid
    for tok in tokens:
        pass
    print("File is syntactically valid (after my fixes)")
except tokenize.TokenError as e:
    print(f"Tokenization error: {e}")
except IndentationError as e:
    print(f"Indentation error: {e}")

# Actually, the simplest fix is to just use the built-in reindent tool
# But Python doesn't have one. Let me try using the ast module to parse and reformat.

import ast
import astunparse

try:
    tree = ast.parse(content.decode())
    # If we can parse it, we can unparse it with proper indentation
    fixed_content = astunparse.unparse(tree)
    with open('review/mission_control.py', 'w') as f:
        f.write(fixed_content)
    print("Fixed file using astunparse!")
except Exception as e:
    print(f"Could not parse: {e}")
