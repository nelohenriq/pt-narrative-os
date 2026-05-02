"""Debug indentation"""

with open('review/mission_control.py', 'r') as f:
    lines = f.readlines()

# Find the get_pipeline_health function
for i, line in enumerate(lines):
    if 'async def get_pipeline_health()' in line:
        print(f"Found function at line {i+1}")
        for j in range(i, min(i+15, len(lines))):
            print(f"  Line {j+1}: {repr(lines[j][:50])}")
        break
