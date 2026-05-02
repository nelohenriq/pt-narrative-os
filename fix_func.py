"""Fix the get_pipeline_health function with proper indentation"""

with open('review/mission_control.py', 'r') as f:
    content = f.read()

# Find the get_pipeline_health function
import re

# Find the function start and end
func_start = content.find('async def get_pipeline_health() -> dict[str, Any]:')
if func_start == -1:
    print("Function not found!")
    exit(1)

# Find the end of the function (next function definition or end of file)
# Look for the next 'async def' or 'def' at the start of a line
func_end_search = content[func_start+1:]
next_func_match = re.search(r'\n(async def |def )', func_end_search)
if next_func_match:
    func_end = func_start + 1 + next_func_match.start()
else:
    func_end = len(content)

func_content = content[func_start:func_end]

# Now fix the indentation
lines = func_content.split('\n')
fixed_lines = []
indent_level = 0
for line in lines:
    stripped = line.lstrip()
    if not stripped:
        fixed_lines.append('')
        continue
    
    # Count leading whitespace
    leading_ws = len(line) - len(stripped)
    
    # If line starts with async def or def, it's a function definition
    if stripped.startswith('async def ') or stripped.startswith('def '):
        fixed_lines.append(stripped)
        indent_level = 1
        continue
    
    # Apply proper indentation
    if indent_level > 0:
        fixed_lines.append('    ' * indent_level + stripped)
    else:
        fixed_lines.append(stripped)

# Actually, this is getting too complex. Let me just manually fix the function.
# The simplest approach: replace the entire function with a properly indented version.

replacement = '''async def get_pipeline_health() -> dict[str, Any]:
    """Calculate health metrics and ETA estimates for each pipeline step."""

    pipeline_steps = [
        ("ingestion", "raw_items", "pending"),
        ("normalization", "articles", "pending"),
        ("embedding", "articles", "pending"),
        ("analysis", "article_analysis", None),
        ("clustering", "events", "candidate"),
        ("scoring", "event_scores", None),
        ("generation", "event_summaries", None),
        ("digest", "daily_digests", None),
    ]

    health = {}

    for step_name, table, status_col in pipeline_steps:
        if status_col:
            # Count items in pending/working state
            count = await mc_fetch_one(
                f"""SELECT COUNT(*) as count FROM {table} WHERE status = '{status_col}'"""
            )
            waiting = count["count"] if count else 0
        else:
            # For tables without status, check if there are items needing processing
            if table == "article_analysis":
                # Articles that are embedded but not analyzed
                count = await mc_fetch_one(
                    """SELECT COUNT(*) as count FROM articles 
                    WHERE status = 'embedded' AND id NOT IN (SELECT article_id FROM article_analysis)"""
                )
                waiting = count["count"] if count else 0
            elif table == "event_scores":
                # Events without scores
                count = await mc_fetch_one(
                    """SELECT COUNT(*) as count FROM events 
                    WHERE status IN ('candidate', 'unreviewed') 
                    AND id NOT IN (SELECT event_id FROM event_scores)"""
                )
                waiting = count["count"] if count else 0
            elif table == "event_summaries":
                # Events with scores but without summaries
                count = await mc_fetch_one(
                    """SELECT COUNT(*) as count FROM event_scores es
                    WHERE es.event_id NOT IN (SELECT DISTINCT event_id FROM event_summaries)"""
                )
                waiting = count["count"] if count else 0
            elif table == "daily_digests":
                # Check if today's digest exists
                today = datetime.utcnow().date()
                count = await mc_fetch_one(
                    """SELECT COUNT(*) as count FROM daily_digests WHERE digest_date = $1""",
                    today,
                )
                waiting = 0 if (count and count["count"] > 0) else 1
            else:
                waiting = 0

        # Calculate ETA based on recent processing rates
        eta = None
        if waiting > 0:
            # Get recent completion times for this step
            if step_name == "ingestion":
                recent = await mc_fetch_all(
                    """SELECT created_at FROM raw_items 
                    WHERE status = 'parsed' 
                    ORDER BY created_at DESC 
                    LIMIT 5"""
                )
            elif step_name == "normalization":
                recent = await mc_fetch_all(
                    """SELECT created_at FROM articles 
                    WHERE status = 'embedded' 
                    ORDER BY created_at DESC 
                    LIMIT 5"""
                )
            elif step_name == "embedding":
                recent = await mc_fetch_all(
                    """SELECT updated_at FROM articles 
                    WHERE status = 'embedded' 
                    ORDER BY updated_at DESC 
                    LIMIT 5"""
                )
            elif step_name == "analysis":
                recent = await mc_fetch_all(
                    """SELECT created_at FROM article_analysis 
                    ORDER BY created_at DESC 
                    LIMIT 5"""
                )
            elif step_name == "clustering":
                recent = await mc_fetch_all(
                    """SELECT created_at FROM events 
                    WHERE status = 'candidate' 
                    ORDER BY created_at DESC 
                    LIMIT 5"""
                )
            elif step_name == "scoring":
                recent = await mc_fetch_all(
                    """SELECT created_at FROM event_scores 
                    ORDER BY created_at DESC 
                    LIMIT 5"""
                )
            elif step_name == "generation":
                recent = await mc_fetch_all(
                    """SELECT created_at FROM event_summaries 
                    ORDER BY created_at DESC 
                    LIMIT 5"""
                )
            elif step_name == "digest":
                recent = await mc_fetch_all(
                    """SELECT created_at FROM daily_digests 
                    ORDER BY created_at DESC 
                    LIMIT 5"""
                )

            if len(recent) >= 2:
                times = [r["created_at"] if "created_at" in r else r["updated_at"] for r in recent if (r.get("created_at") or r.get("updated_at"))]
                if len(times) >= 2:
                    time_diffs = []
                    for i in range(1, len(times)):
                        if times[i] and times[i-1]:
                            diff = (times[i-1] - times[i]).total_seconds()
                            if diff > 0:
                                time_diffs.append(diff)
                    if time_diffs:
                        avg_seconds = sum(time_diffs) / len(time_diffs)
                        if avg_seconds > 0:
                            eta_seconds = avg_seconds * waiting
                            eta = str(timedelta(seconds=eta_seconds))

        health[step_name] = {
            "waiting": waiting,
            "eta": eta,
            "status": "blocked" if waiting > 10 else "ok" if waiting == 0 else "working",
        }

    return health


# API Endpoints
# ──────────────────────────────────────────────────────────────────────────────
'''

new_content = content[:func_start] + replacement + content[func_end:]

with open('review/mission_control.py', 'w') as f:
    f.write(new_content)

print("Fixed get_pipeline_health function!")

# Verify
import py_compile
try:
    py_compile.compile('review/mission_control.py', doraise=True)
    print("✅ Syntax is valid!")
except py_compile.PyCompileError as e:
    print(f"❌ Still has syntax error: {e}")
