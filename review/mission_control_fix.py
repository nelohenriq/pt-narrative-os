"""Temporary script to fix the indentation in mission_control.py"""

with open('review/mission_control.py', 'r') as f:
    lines = f.readlines()

# Find and fix the return statement at line 159 (0-indexed: 158)
# The issue is that line 159 (index 158) has "return {" with no indentation
# It should have 4 spaces of indentation

for i, line in enumerate(lines):
    if i == 158 and line.strip() == 'return {':
        lines[i] = '    return {\n'
        print(f"Fixed line {i+1}: added 4-space indent to 'return {'")
        break

with open('review/mission_control.py', 'w') as f:
    f.writelines(lines)

print("Fix applied. Checking syntax...")

# Verify the fix
import py_compile
try:
    py_compile.compile('review/mission_control.py', doraise=True)
    print("✅ Syntax is now valid!")
except py_compile.PyCompileError as e:
    print(f"❌ Still has syntax error: {e}")
