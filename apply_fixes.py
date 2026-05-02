#!/usr/bin/env python3
"""
Apply minimal fixes to mission_control.py with proper indentation preservation.
Fixes:
1. Line ~373: ("embedding", "articles", "embedded") -> ("embedding", "articles", "pending")
2. Lines with elif key == "embedding" where done includes analyzed+failed -> just embedded
"""

with open('review/mission_control.py', 'r') as f:
    content = f.read()

# Fix 1: Replace the embedding health check tuple
# Original: ("embedding", "articles", "embedded")
# Fixed: ("embedding", "articles", "pending")
content = content.replace(
    '("embedding", "articles", "embedded")',
    '("embedding", "articles", "pending")'
)

# Fix 2: In html_status function, fix the embedding elif block
# We need to find the specific elif block and fix its done calculation
# The pattern is: elif key == "embedding": followed by done = step_data.get("embedded", 0) + step_data.get("analyzed", 0) + step_data.get("failed", 0)
# We want: done = step_data.get("embedded", 0)

# There are TWO places with this pattern (html_status and another function)
# Let's replace carefully

old_pattern_1 = """ elif key == "embedding":
 total = step_data.get("total", 0)
 done = step_data.get("embedded", 0) + step_data.get("analyzed", 0) + step_data.get("failed", 0)
 waiting = health_data.get("waiting", 0)"""

new_pattern_1 = """ elif key == "embedding":
 total = step_data.get("total", 0)
 done = step_data.get("embedded", 0)
 waiting = health_data.get("waiting", 0)"""

content = content.replace(old_pattern_1, new_pattern_1)

# Write the fixed content
with open('review/mission_control.py', 'w') as f:
    f.write(content)

print("Applied minimal fixes to mission_control.py")

# Verify syntax
import py_compile
try:
    py_compile.compile('review/mission_control.py', doraise=True)
    print("✅ Syntax is valid!")
except py_compile.PyCompileError as e:
    print(f"❌ Still has syntax error: {e}")
