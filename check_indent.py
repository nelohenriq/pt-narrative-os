with open('review/mission_control.py', 'r') as f:
    lines = f.readlines()
for i in range(366, 375):
    indent = len(lines[i]) - len(lines[i].lstrip())
    print(f'Line {i+1}: indent={indent} | {repr(lines[i][:40])}')
