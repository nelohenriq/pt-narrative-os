#!/usr/bin/env python3
"""
Precise fix for mission_control.py indentation issues.
We know the exact problems:
1. Lines 574-577 have 1 space indent, should be 8 (inside for loop, part of if/elif chain)
2. Need to check for other similar issues
"""

with open('review/mission_control.py', 'r') as f:
    lines = f.readlines()

# First, let's find ALL lines with 1 space of indentation
print("Lines with 1 space indent:")
for i, line in enumerate(lines):
    indent = len(line) - len(line.lstrip())
    if indent == 1:
        print(f"  Line {i+1}: {repr(line[:40])}")

print("\nLines with 5 spaces indent:")
for i, line in enumerate(lines):
    indent = len(line) - len(line.lstrip())
    if indent == 5:
        print(f"  Line {i+1}: {repr(line[:40])}")
