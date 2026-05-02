"""
Apply minimal fixes to mission_control.py:
1. Change line 366: ("embedding", "articles", "embedded") -> ("embedding", "articles", "pending")
2. Change lines 579 and 792: done = step_data.get("embedded", 0) + ... -> done = step_data.get("embedded", 0)
"""

with open('review/mission_control.py', 'r') as f:
    content = f.read()

# Fix 1: In get_pipeline_health function, line with ("embedding", "articles", "embedded")
content = content.replace(
    '("embedding", "articles", "embedded")',
    '("embedding", "articles", "pending")'
)

# Fix 2: In HTML rendering functions, change the done calculation for embedding
# From: done = step_data.get("embedded", 0) + step_data.get("analyzed", 0) + step_data.get("failed", 0)
# To: done = step_data.get("embedded", 0)
# But only for the embedding elif block

# We need to be careful to only replace in the embedding context
# Let's do a more targeted replacement

# Pattern for embedding elif block in html_status function
old_embedding_html = ''' elif key == "embedding":
 total = step_data.get("total", 0)
 done = step_data.get("embedded", 0) + step_data.get("analyzed", 0) + step_data.get("failed", 0)
 waiting = health_data.get("waiting", 0)'''

new_embedding_html = ''' elif key == "embedding":
 total = step_data.get("total", 0)
 done = step_data.get("embedded", 0)
 waiting = health_data.get("waiting", 0)'''

content = content.replace(old_embedding_html, new_embedding_html)

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
    print(f"❌ Syntax error: {e}")
