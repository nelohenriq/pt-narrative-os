#!/usr/bin/env python3
"""
Fix the indentation in mission_control.py
Two functions have broken indentation:
1. get_pipeline_health (lines 368-503): body has 0 indent, needs 4
2. html_status (lines 560-634): part of body has 0 indent, needs 4
"""

with open('review/mission_control.py', 'r') as f:
    lines = f.readlines()

# Fix 1: get_pipeline_health function body (lines 368-503, 0-indexed: 367-502)
# The function starts at line 367 (0-indexed), body starts at 368
# We need to add 4 spaces to lines 368-502 (the body before the return statement)
# But we need to be careful: some lines are already indented (like inside for loops, if statements)
# Actually, looking at the file, the ENTIRE body from line 368 to 503 has 0 indentation
# This is wrong - it should all be indented by 4

# Let's check: does line 368 have any indentation?
print(f"Line 368 indent: {len(lines[367]) - len(lines[367].lstrip())}")
print(f"Line 368: {repr(lines[367][:20])}")

# Fix approach: for lines 368-502 (0-indexed: 367-502), add 4 spaces
# But skip lines that are already indented (this shouldn't happen but just in case)
for i in range(367, 503):  # 0-indexed: lines 368-503 in 1-indexed
    if lines[i].strip():  # Non-empty line
        if len(lines[i]) - len(lines[i].lstrip()) == 0:
            lines[i] = '    ' + lines[i]

# Fix 2: html_status function body
# Lines 560-634 (1-indexed) need 4 spaces of indentation
# In 0-indexed: 559-633
# But lines 544-558 already have correct indentation, so we start from 560
for i in range(559, 634):  # 0-indexed: lines 560-634 in 1-indexed
    if lines[i].strip():  # Non-empty line
        current_indent = len(lines[i]) - len(lines[i].lstrip())
        if current_indent == 0:
            lines[i] = '    ' + lines[i]

# Write the fixed file
with open('review/mission_control.py', 'w') as f:
    f.writelines(lines)

print("Applied indentation fixes.")

# Verify syntax
import py_compile
try:
    py_compile.compile('review/mission_control.py', doraise=True)
    print("✅ Syntax is valid!")
except py_compile.PyCompileError as e:
    print(f"❌ Still has syntax error: {e}")
