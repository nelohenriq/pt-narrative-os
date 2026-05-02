"""Fix indentation in mission_control.py"""

with open('review/mission_control.py', 'r') as f:
    lines = f.readlines()

# Find the get_pipeline_health function and fix its indentation
in_function = False
function_start = None
for i, line in enumerate(lines):
    if 'async def get_pipeline_health()' in line:
        in_function = True
        function_start = i
        continue
    if in_function:
        # Check if we've reached the next function definition at column 0
        if line.strip() and not line.startswith(' ') and not line.startswith('\t') and line.startswith('async def') or line.startswith('def'):
            in_function = False
            break
        # Check if we've reached a comment section at column 0
        if line.strip() and not line.startswith(' ') and not line.startswith('\t') and line.startswith('#'):
            in_function = False
            break

# Fix lines from function_start+1 to the end of the function
if function_start is not None:
    # Find the end of the function (next blank line followed by non-indented line)
    function_end = None
    for i in range(function_start + 1, len(lines)):
        if lines[i].strip() == '':
            continue
        if not lines[i].startswith(' ') and not lines[i].startswith('\t'):
            function_end = i
            break
    
    if function_end is None:
        function_end = len(lines)
    
    print(f"Fixing indentation from line {function_start+2} to {function_end}")
    
    # Add 4 spaces to each line in the function body
    for i in range(function_start + 1, function_end):
        if lines[i].strip():  # Don't modify blank lines
            if not lines[i].startswith(' ') and not lines[i].startswith('\t'):
                lines[i] = '    ' + lines[i]
    
    with open('review/mission_control.py', 'w') as f:
        f.writelines(lines)
    print("Fixed!")
else:
    print("Function not found")
