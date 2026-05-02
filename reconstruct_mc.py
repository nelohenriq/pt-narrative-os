#!/usr/bin/env python3
"""
Reconstruct mission_control.py with proper indentation.
This script reads the corrupted file and fixes the indentation issues.
"""

with open('/teamspace/studios/this_studio/pt-narrative-os/review/mission_control.py', 'r') as f:
    lines = f.readlines()

# The file has these issues:
# 1. get_pipeline_health() function body (line 367+) has 0 indentation - needs 4 spaces
# 2. html_status() function body (line 543+) has proper indentation for first few lines,
#    but the for loop at line 562+ has 0 indentation inside the function
# 3. There might be other functions with similar issues

# Let's identify all function definitions and track expected indentation
fixed_lines = []
indent_stack = [0]  # Stack of current indentation levels

for i, line in enumerate(lines):
    stripped = line.lstrip()
    
    # Count leading spaces
    leading_spaces = len(line) - len(stripped)
    
    # Detect function/class definitions
    if stripped.startswith(('async def ', 'def ', 'class ')) and ':' in stripped:
        # This is a function/class definition
        # The next lines should be indented by 4 more spaces
        current_indent = indent_stack[-1]
        expected_indent = current_indent + 4
        indent_stack.append(expected_indent)
        # Keep the function definition as-is (it has correct indentation)
        fixed_lines.append(line)
        continue
    
    # Detect end of block (dedent)
    if stripped in ('', 'else:', 'elif ') or (stripped.startswith('else:') or stripped.startswith('elif ')):
        # Check if we need to dedent
        pass
    
    # For now, let's just fix the known broken sections manually
    
# Actually, let's take a simpler approach: we know the exact broken sections
# Let's rebuild the file by reading it and fixing the specific ranges

# Read the whole file
with open('/teamspace/studios/this_studio/pt-narrative-os/review/mission_control.py', 'r') as f:
    content = f.read()

# Fix 1: get_pipeline_health function body needs indentation
# Find the function and indent its body
lines = content.split('\n')
new_lines = []
in_get_pipeline_health = False
in_html_status = False

for i, line in enumerate(lines):
    stripped = line.lstrip()
    
    # Detect get_pipeline_health function start
    if 'async def get_pipeline_health()' in line and not in_get_pipeline_health:
        in_get_pipeline_health = True
        new_lines.append(line)
        continue
    
    # Detect html_status function start  
    if 'async def html_status(' in line and not in_html_status:
        in_html_status = True
        new_lines.append(line)
        continue
    
    # Detect end of get_pipeline_health (next function definition at same level)
    if in_get_pipeline_health and stripped.startswith(('async def ', 'def ', '@app.get', '@app.post')) and i > 367:
        in_get_pipeline_health = False
        new_lines.append(line)
        continue
    
    # Detect end of html_status
    if in_html_status and stripped.startswith(('async def ', 'def ', '@app.get', '@app.post')) and i > 543:
        in_html_status = False
        new_lines.append(line)
        continue
    
    # Fix indentation for get_pipeline_health body
    if in_get_pipeline_health and line.strip() and not line.strip().startswith('#'):
        # Add 4 spaces of indentation
        new_lines.append('    ' + line)
        continue
    
    # Fix indentation for html_status body
    if in_html_status:
        # The html_status function has a more complex structure
        # Lines 543-559 are fine (function docstring and initial vars)
        # The for loop at 562+ needs indentation
        if i >= 561:  # Line 562 is the for loop
            # Check if this line should be indented inside the function
            if line.strip() and not line.strip().startswith('#'):
                # Count existing indentation
                existing_indent = len(line) - len(line.lstrip())
                if existing_indent == 0:
                    # Add 4 spaces for function body
                    new_lines.append('    ' + line)
                    continue
        new_lines.append(line)
        continue
    
    new_lines.append(line)

# Write the fixed content
with open('/teamspace/studios/this_studio/pt-narrative-os/review/mission_control.py', 'w') as f:
    f.write('\n'.join(new_lines))

print("Applied fixes. Checking syntax...")
