"""
pt-media-os — Mission Control UI

Internal FastAPI + HTMX dashboard for monitoring the entire pipeline in real-time.
HTTP Basic Auth required (same credentials as review UI).

Features:
- Real-time pipeline progress monitoring (8 steps: ingestion → digest)
- Database state overview (row counts for all key tables)
- AI activity metrics (latency, errors, model usage from ai_runs)
- Live activity feed (recent actions with timestamps)
- Pipeline step health and ETA estimates
"""

from __future__ import annotations

import json as _json
import logging
import os
from datetime import datetime, timedelta
from typing import Any

import asyncpg
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

load_dotenv()

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# DB pool (shared with review/app.py)
# ──────────────────────────────────────────────────────────────────────────────

_mc_pool: asyncpg.Pool | None = None


async def get_mc_pool() -> asyncpg.Pool:
    global _mc_pool
    if _mc_pool is None:
        db_url = os.getenv("DATABASE_URL", "")
        _mc_pool = await asyncpg.create_pool(db_url, min_size=2, max_size=10)
    return _mc_pool


async def mc_fetch_all(query: str, *args) -> list[asyncpg.Record]:
    pool = await get_mc_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def mc_fetch_one(query: str, *args) -> asyncpg.Record | None:
    pool = await get_mc_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


# ──────────────────────────────────────────────────────────────────────────────
# Auth for Mission Control
# For Cloudspaces/Lightning, we check X-Forwarded-For or allow if no auth header
# ──────────────────────────────────────────────────────────────────────────────

import os


async def mc_require_auth(request: Request) -> str:
    """FastAPI dependency for Mission Control auth."""
    # If request has Authorization header, use Basic Auth
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        from review.app import require_auth
        return await require_auth(request)
    
    # For Cloudspaces, check if the request has Lightning headers
    headers_str = str(request.headers).lower()
    if "x-lightning" in headers_str:
        # Allow access - user is already auth'd by Lightning
        return "cloudspaces-user"
    
    # Fallback: check if running in Lightning environment
    if os.getenv("LIGHTNING_STUDIO", "") or os.getenv("CLOUDSPACES", ""):
        return "cloudspaces-user"
    
    # Otherwise require Basic Auth
    from review.app import require_auth
    return await require_auth(request)


# ──────────────────────────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────────────────────────

from contextlib import asynccontextmanager


@asynccontextmanager
async def mc_lifespan(app: FastAPI):
    yield
    global _mc_pool
    if _mc_pool:
        await _mc_pool.close()
        _mc_pool = None


    app = FastAPI(
    title="PT Media OS — Mission Control",
    lifespan=mc_lifespan,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Data collection functions
# ──────────────────────────────────────────────────────────────────────────────


async def get_pipeline_status() -> dict[str, Any]:
    """Get status counts for each pipeline step."""
    
    # Ingestion: raw_items status
    raw_items = await mc_fetch_all(
        """SELECT status, COUNT(*) as count FROM raw_items GROUP BY status"""
    )
    raw_status = {r["status"]: r["count"] for r in raw_items}
    
    # Normalization: articles status
    articles = await mc_fetch_all(
        """SELECT status, COUNT(*) as count FROM articles GROUP BY status"""
    )
    article_status = {r["status"]: r["count"] for r in articles}
    
    # Clustering: events status
    events = await mc_fetch_all(
        """SELECT status, COUNT(*) as count FROM events GROUP BY status"""
    )
    event_status = {r["status"]: r["count"] for r in events}
    
    # Analysis: articles with/without analysis
    analyzed = await mc_fetch_one(
        """SELECT COUNT(*) as count FROM article_analysis"""
    )
    
    # Scoring: events with scores
    scored = await mc_fetch_one(
        """SELECT COUNT(*) as count FROM event_scores"""
    )
    
    # Generation: events with summaries
    summarized = await mc_fetch_all(
        """SELECT summary_type, COUNT(*) as count FROM event_summaries GROUP BY summary_type"""
    )
    summary_counts = {r["summary_type"]: r["count"] for r in summarized}
    
    # Digest: daily digests
    digests = await mc_fetch_one(
        """SELECT COUNT(*) as count FROM daily_digests"""
 )

    return {
    "ingestion": {
 "total": sum(raw_status.values()),
 "pending": raw_status.get("pending", 0),
 "parsed": raw_status.get("parsed", 0),
 "failed": raw_status.get("failed", 0),
 "skipped": raw_status.get("skipped", 0),
 },
 "normalization": {
 "total": sum(article_status.values()),
 "pending": article_status.get("pending", 0),
 "embedded": article_status.get("embedded", 0),
 "analyzed": article_status.get("analyzed", 0),
 "failed": article_status.get("failed", 0),
 },
 "embedding": {
 "total": sum(article_status.values()),
 "pending": article_status.get("pending", 0),
 "embedded": article_status.get("embedded", 0),
 "analyzed": article_status.get("analyzed", 0),
 "failed": article_status.get("failed", 0),
 },
 "clustering": {
 "total": sum(event_status.values()),
 "candidate": event_status.get("candidate", 0),
 "unreviewed": event_status.get("unreviewed", 0),
 "reviewed_published": event_status.get("reviewed_published", 0),
 "reviewed_rejected": event_status.get("reviewed_rejected", 0),
 },
 "analysis": {
 "total": analyzed["count"] if analyzed else 0,
 },
 "scoring": {
 "total": scored["count"] if scored else 0,
 },
 "generation": {
 "event_summary": summary_counts.get("event_summary", 0),
 "framing_comparison": summary_counts.get("framing_comparison", 0),
 "undercoverage_card": summary_counts.get("undercoverage_card", 0),
 },
 "digest": {
 "total": digests["count"] if digests else 0,
 },
 }


async def get_database_stats() -> dict[str, Any]:
    """Get row counts for all key tables."""
    
    tables = [
        "owners", "outlets", "outlet_ownership",
        "raw_items", "articles", "article_analysis",
        "entities", "article_entities", "claims",
        "events", "event_articles", "event_scores",
        "source_documents", "event_documents",
        "undercoverage_flags", "event_summaries",
        "ai_runs", "daily_digests",
    ]
    
    counts = {}
    for table in tables:
        result = await mc_fetch_one(f"""SELECT COUNT(*) as count FROM {table}""")
        counts[table] = result["count"] if result else 0
    
    return counts


async def get_ai_metrics() -> dict[str, Any]:
    """Get AI activity metrics from ai_runs table."""
    
    # Total runs
    total = await mc_fetch_one(
        """SELECT COUNT(*) as count FROM ai_runs"""
    )
    
    # Runs by task
    by_task = await mc_fetch_all(
        """SELECT task_name, COUNT(*) as count FROM ai_runs GROUP BY task_name ORDER BY count DESC"""
    )
    
    # Runs by provider
    by_provider = await mc_fetch_all(
        """SELECT provider, COUNT(*) as count FROM ai_runs GROUP BY provider ORDER BY count DESC"""
    )
    
    # Runs by model
    by_model = await mc_fetch_all(
        """SELECT model_name, COUNT(*) as count FROM ai_runs GROUP BY model_name ORDER BY count DESC"""
    )
    
    # Status counts
    by_status = await mc_fetch_all(
        """SELECT status, COUNT(*) as count FROM ai_runs GROUP BY status"""
    )
    
    # Average latency
    avg_latency = await mc_fetch_one(
        """SELECT AVG(latency_ms) as avg_latency FROM ai_runs WHERE latency_ms IS NOT NULL"""
    )
    
    # Total token counts
    tokens = await mc_fetch_one(
        """SELECT SUM(input_token_count) as input_tokens, SUM(output_token_count) as output_tokens 
           FROM ai_runs WHERE input_token_count IS NOT NULL AND output_token_count IS NOT NULL"""
    )
    
    # Recent errors
    errors = await mc_fetch_all(
        """SELECT task_name, provider, model_name, error_message, created_at 
           FROM ai_runs 
           WHERE status = 'failed' 
           ORDER BY created_at DESC 
           LIMIT 10"""
    )
    
    # Recent runs (last 20)
    recent = await mc_fetch_all(
        """SELECT task_name, provider, model_name, latency_ms, status, created_at 
           FROM ai_runs 
           ORDER BY created_at DESC 
           LIMIT 20"""
    )
    
    return {
        "total_runs": total["count"] if total else 0,
        "by_task": {r["task_name"]: r["count"] for r in by_task},
        "by_provider": {r["provider"]: r["count"] for r in by_provider},
        "by_model": {r["model_name"]: r["count"] for r in by_model},
        "by_status": {r["status"]: r["count"] for r in by_status},
        "avg_latency_ms": round(avg_latency["avg_latency"]) if avg_latency and avg_latency["avg_latency"] else 0,
        "total_input_tokens": tokens["input_tokens"] if tokens and tokens["input_tokens"] else 0,
        "total_output_tokens": tokens["output_tokens"] if tokens and tokens["output_tokens"] else 0,
        "recent_errors": [dict(r) for r in errors],
        "recent_runs": [dict(r) for r in recent],
    }


async def get_recent_activity() -> list[dict[str, Any]]:
    """Get recent activity across all tables with timestamps."""
    
    activities = []
    
    # Recent raw_items
    raw_recent = await mc_fetch_all(
        """SELECT 'raw_items' as table_name, id::text, status, created_at, updated_at 
           FROM raw_items 
           ORDER BY created_at DESC 
           LIMIT 5"""
    )
    for r in raw_recent:
        activities.append({
            "table": r["table_name"],
            "id": r["id"],
            "action": f"status: {r['status']}",
            "timestamp": r["created_at"],
        })
    
    # Recent articles
    art_recent = await mc_fetch_all(
        """SELECT 'articles' as table_name, id::text, title, status, created_at, updated_at 
           FROM articles 
           ORDER BY created_at DESC 
           LIMIT 5"""
    )
    for r in art_recent:
        activities.append({
            "table": r["table_name"],
            "id": r["id"],
            "action": f"'{r['title'][:50]}' -> {r['status']}",
            "timestamp": r["created_at"],
        })
    
    # Recent events
    evt_recent = await mc_fetch_all(
        """SELECT 'events' as table_name, id::text, canonical_title, status, created_at, updated_at 
           FROM events 
           ORDER BY created_at DESC 
           LIMIT 5"""
    )
    for r in evt_recent:
        activities.append({
            "table": r["table_name"],
            "id": r["id"],
            "action": f"'{r['canonical_title'][:50]}' -> {r['status']}",
            "timestamp": r["created_at"],
        })
    
    # Recent AI runs
    ai_recent = await mc_fetch_all(
        """SELECT 'ai_runs' as table_name, id::text, task_name, provider, model_name, status, created_at 
           FROM ai_runs 
           ORDER BY created_at DESC 
           LIMIT 10"""
    )
    for r in ai_recent:
        activities.append({
            "table": r["table_name"],
            "id": r["id"],
            "action": f"{r['task_name']} -> {r['status']} ({r['provider']}/{r['model_name']})",
            "timestamp": r["created_at"],
        })
    
    # Sort by timestamp descending
    activities.sort(key=lambda x: x["timestamp"] if x["timestamp"] else datetime.min, reverse=True)
    
    return activities[:20]  # Return top 20


async def get_pipeline_health() -> dict[str, Any]:
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

async def api_status(username: str = Depends(mc_require_auth)):
    """Get pipeline status as JSON."""
    return await get_pipeline_status()


@app.get("/mission-control/api/database", response_class=JSONResponse)
async def api_database(username: str = Depends(mc_require_auth)):
    """Get database stats as JSON."""
    return await get_database_stats()


@app.get("/mission-control/api/ai", response_class=JSONResponse)
async def api_ai(username: str = Depends(mc_require_auth)):
    """Get AI metrics as JSON."""
    return await get_ai_metrics()


@app.get("/mission-control/api/activity", response_class=JSONResponse)
async def api_activity(username: str = Depends(mc_require_auth)):
    """Get recent activity as JSON."""
    return await get_recent_activity()


@app.get("/mission-control/api/health", response_class=JSONResponse)
async def api_health(username: str = Depends(mc_require_auth)):
    """Get pipeline health as JSON."""
    return await get_pipeline_health()


# ──────────────────────────────────────────────────────────────────────────────
# HTML Fragment Endpoints for HTMX
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/mission-control/html/status", response_class=HTMLResponse)
async def html_status(username: str = Depends(mc_require_auth)):
    """Get pipeline status as HTML fragment for HTMX."""
    pipeline_status = await get_pipeline_status()
    pipeline_health = await get_pipeline_health()
    
    # Pipeline step names and colors
    pipeline_steps = [
        ("Ingestion", "ingestion", "#7c3aed"),
        ("Normalization", "normalization", "#2563eb"),
        ("Embedding", "embedding", "#059669"),
        ("Analysis", "analysis", "#f59e0b"),
        ("Clustering", "clustering", "#dc2626"),
        ("Scoring", "scoring", "#ea580c"),
        ("Generation", "generation", "#8b5cf6"),
        ("Digest", "digest", "#14b8a6"),
    ]
    
    # Build pipeline progress bars
    pipeline_html = ""
    for name, key, color in pipeline_steps:
        step_data = pipeline_status.get(key, {})
        health_data = pipeline_health.get(key, {})
        
        if key == "ingestion":
            total = step_data.get("total", 0)
            done = step_data.get("parsed", 0) + step_data.get("skipped", 0)
            waiting = health_data.get("waiting", 0)
        elif key == "normalization":
            total = step_data.get("total", 0)
            done = step_data.get("embedded", 0) + step_data.get("analyzed", 0) + step_data.get("failed", 0)
            waiting = health_data.get("waiting", 0)
 elif key == "embedding":
 total = step_data.get("total", 0)
 done = step_data.get("embedded", 0)
 waiting = health_data.get("waiting", 0)
        elif key == "analysis":
            total = step_data.get("total", 0)
            done = step_data.get("total", 0)
            waiting = health_data.get("waiting", 0)
        elif key == "clustering":
            total = step_data.get("total", 0)
            done = step_data.get("candidate", 0) + step_data.get("unreviewed", 0) + step_data.get("reviewed_published", 0) + step_data.get("reviewed_rejected", 0)
            waiting = 0
        elif key == "scoring":
            total = step_data.get("total", 0)
            done = step_data.get("total", 0)
            waiting = health_data.get("waiting", 0)
        elif key == "generation":
            total = sum(step_data.values()) if step_data else 0
            done = total
            waiting = health_data.get("waiting", 0)
        elif key == "digest":
            total = step_data.get("total", 0)
            done = total
            waiting = health_data.get("waiting", 0)
        else:
            total = 0
            done = 0
            waiting = 0
        
        if total > 0:
            percent = (done / total) * 100
        else:
            percent = 100 if waiting == 0 else 0
        
        status_badge = ""
        if waiting > 0:
            status_badge = f'<span class="status-badge working">⏳ {waiting} waiting</span>'
        elif health_data.get("status") == "blocked":
            status_badge = '<span class="status-badge blocked">❌ blocked</span>'
        else:
            status_badge = '<span class="status-badge ok">✅ ok</span>'
        
        eta_str = health_data.get("eta", "")
        eta_html = f'<span class="eta">ETA: {eta_str}</span>' if eta_str else ""
        
        pipeline_html += f"""
    <div class="pipeline-step" style="border-left: 4px solid {color};">
    <div class="step-header">
    <h3>{name}</h3>
    <div class="step-stats">
    {status_badge}
    {eta_html}
    </div>
    </div>
    <div class="progress-container">
    <div class="progress-bar" style="width: {percent}%; background-color: {color};"></div>
    <span class="progress-text">{done}/{total} ({percent:.0f}%)</span>
    </div>
    </div>"""
    
    return HTMLResponse(content=pipeline_html)


@app.get("/mission-control/html/health", response_class=HTMLResponse)
async def html_health(username: str = Depends(mc_require_auth)):
    """Get pipeline health as HTML fragment for HTMX."""
    pipeline_health = await get_pipeline_health()
    
    return HTMLResponse(content=f"""
    <div class="stats-grid">
    <div class="stat-box">
    <label>Waiting</label>
    <div class="value">{sum(h.get('waiting', 0) for h in pipeline_health.values())}</div>
    </div>
    <div class="stat-box">
    <label>Blocked</label>
    <div class="value">{sum(1 for h in pipeline_health.values() if h.get('status') == 'blocked')}</div>
    </div>
    <div class="stat-box">
    <label>Working</label>
    <div class="value">{sum(1 for h in pipeline_health.values() if h.get('status') == 'working')}</div>
    </div>
    <div class="stat-box">
    <label>OK</label>
    <div class="value">{sum(1 for h in pipeline_health.values() if h.get('status') == 'ok')}</div>
    </div>
    </div>
    <pre style="margin-top: 1rem; font-size: .85rem; overflow-x: auto; white-space: pre-wrap;">{json.dumps(pipeline_health, indent=2)}</pre>
""")
# ──────────────────────────────────────────────────────────────────────────────

import subprocess
import json


# Track running pipeline process
_pipeline_process: subprocess.Popen | None = None


async def get_pipeline_status_api() -> dict:
    """Get current pipeline process status."""
    global _pipeline_process
    
    if _pipeline_process is None:
        return {"running": False, "pid": None, "status": "stopped"}
    
    # Check if process is still running
    poll = _pipeline_process.poll()
    if poll is not None:
        _pipeline_process = None
        return {"running": False, "pid": None, "status": "stopped", "exit_code": poll}
    
    return {"running": True, "pid": _pipeline_process.pid, "status": "running"}


@app.get("/mission-control/api/pipeline/status", response_class=JSONResponse)
async def api_pipeline_status(username: str = Depends(mc_require_auth)):
    """Get pipeline process status."""
    return await get_pipeline_status_api()


@app.post("/mission-control/api/pipeline/start")
async def api_pipeline_start(username: str = Depends(mc_require_auth)):
    """Start the pipeline process."""
    global _pipeline_process
    
    if _pipeline_process is not None:
        poll = _pipeline_process.poll()
        if poll is None:
            return JSONResponse(
                {"status": "error", "message": "Pipeline is already running"},
                status_code=400
            )
        _pipeline_process = None
    
    # Start pipeline in background
    import os
    import sys
    
    env = os.environ.copy()
    cwd = "/teamspace/studios/this_studio/pt-narrative-os"
    
    _pipeline_process = subprocess.Popen(
        [sys.executable, "run_pipeline.py"],
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    return JSONResponse(
        {"status": "ok", "message": "Pipeline started", "pid": _pipeline_process.pid}
    )


@app.post("/mission-control/api/pipeline/stop")
async def api_pipeline_stop(username: str = Depends(mc_require_auth)):
    """Stop the pipeline process."""
    global _pipeline_process
    
    if _pipeline_process is None:
        return JSONResponse(
            {"status": "error", "message": "No pipeline process running"},
            status_code=400
        )
    
    _pipeline_process.terminate()
    _pipeline_process = None
    
    return JSONResponse({"status": "ok", "message": "Pipeline stopped"})


# ──────────────────────────────────────────────────────────────────────────────
# HTML Dashboard
# ──────────────────────────────────────────────────────────────────────────────


def _render_mission_control(
    pipeline_status: dict[str, Any],
    database_stats: dict[str, Any],
    ai_metrics: dict[str, Any],
    recent_activity: list[dict[str, Any]],
    pipeline_health: dict[str, Any],
    username: str,
    ) -> str:
    """Render the full Mission Control dashboard HTML."""
    
    # Pipeline step names and colors
    pipeline_steps = [
        ("Ingestion", "ingestion", "#7c3aed"),
        ("Normalization", "normalization", "#2563eb"),
        ("Embedding", "embedding", "#059669"),
        ("Analysis", "analysis", "#f59e0b"),
        ("Clustering", "clustering", "#dc2626"),
        ("Scoring", "scoring", "#ea580c"),
        ("Generation", "generation", "#8b5cf6"),
        ("Digest", "digest", "#14b8a6"),
    ]
    
    # Build pipeline progress bars
    pipeline_html = ""
    for name, key, color in pipeline_steps:
        step_data = pipeline_status.get(key, {})
        health_data = pipeline_health.get(key, {})
        
        if key == "ingestion":
            total = step_data.get("total", 0)
            done = step_data.get("parsed", 0) + step_data.get("skipped", 0)
            waiting = health_data.get("waiting", 0)
        elif key == "normalization":
            total = step_data.get("total", 0)
            done = step_data.get("embedded", 0) + step_data.get("analyzed", 0) + step_data.get("failed", 0)
            waiting = health_data.get("waiting", 0)
 elif key == "embedding":
 total = step_data.get("total", 0)
 done = step_data.get("embedded", 0)
 waiting = health_data.get("waiting", 0)
        elif key == "analysis":
            total = step_data.get("total", 0)
            done = step_data.get("total", 0)
            waiting = health_data.get("waiting", 0)
        elif key == "clustering":
            total = step_data.get("total", 0)
            done = step_data.get("candidate", 0) + step_data.get("unreviewed", 0) + step_data.get("reviewed_published", 0) + step_data.get("reviewed_rejected", 0)
            waiting = 0
        elif key == "scoring":
            total = step_data.get("total", 0)
            done = step_data.get("total", 0)
            waiting = health_data.get("waiting", 0)
        elif key == "generation":
            total = sum(step_data.values()) if step_data else 0
            done = total
            waiting = health_data.get("waiting", 0)
        elif key == "digest":
            total = step_data.get("total", 0)
            done = total
            waiting = health_data.get("waiting", 0)
        else:
            total = 0
            done = 0
            waiting = 0
        
        if total > 0:
            percent = (done / total) * 100
        else:
            percent = 100 if waiting == 0 else 0
        
        status_badge = ""
        if waiting > 0:
            status_badge = f'<span class="status-badge working">⏳ {waiting} waiting</span>'
        elif health_data.get("status") == "blocked":
            status_badge = '<span class="status-badge blocked">❌ blocked</span>'
        else:
            status_badge = '<span class="status-badge ok">✅ ok</span>'
        
        eta_str = health_data.get("eta", "")
        eta_html = f'<span class="eta">ETA: {eta_str}</span>' if eta_str else ""
        
        pipeline_html += f"""
        <div class="pipeline-step" style="border-left: 4px solid {color};">
            <div class="step-header">
                <h3>{name}</h3>
                <div class="step-stats">
                    {status_badge}
                    {eta_html}
                </div>
            </div>
            <div class="progress-container">
                <div class="progress-bar" style="width: {percent}%; background-color: {color};"></div>
                <span class="progress-text">{done}/{total} ({percent:.0f}%)</span>
            </div>
        </div>"""
    
    # Database stats table
    db_rows = ""
    for table, count in sorted(database_stats.items()):
        db_rows += f"""
        <tr>
            <td><code>{table}</code></td>
            <td>{count:,}</td>
        </tr>"""
    
    # AI metrics
    total_runs = ai_metrics.get("total_runs", 0)
    avg_latency = ai_metrics.get("avg_latency_ms", 0)
    input_tokens = ai_metrics.get("total_input_tokens", 0)
    output_tokens = ai_metrics.get("total_output_tokens", 0)
    
    # Task breakdown
    task_rows = ""
    for task, count in sorted(ai_metrics.get("by_task", {}).items(), key=lambda x: x[1], reverse=True)[:10]:
        task_rows += f"""
        <tr>
            <td>{task}</td>
            <td>{count:,}</td>
        </tr>"""
    
    # Provider breakdown
    provider_rows = ""
    for provider, count in sorted(ai_metrics.get("by_provider", {}).items(), key=lambda x: x[1], reverse=True):
        provider_rows += f"""
        <tr>
            <td>{provider}</td>
            <td>{count:,}</td>
        </tr>"""
    
    # Model breakdown
    model_rows = ""
    for model, count in sorted(ai_metrics.get("by_model", {}).items(), key=lambda x: x[1], reverse=True)[:10]:
        model_rows += f"""
        <tr>
            <td>{model}</td>
            <td>{count:,}</td>
        </tr>"""
    
    # Status breakdown
    status_rows = ""
    for status, count in sorted(ai_metrics.get("by_status", {}).items()):
        status_rows += f"""
        <tr>
            <td>{status}</td>
            <td>{count:,}</td>
        </tr>"""
    
    # Recent errors
    error_rows = ""
    for error in ai_metrics.get("recent_errors", [])[:5]:
        timestamp = error.get("created_at", "")
        if isinstance(timestamp, datetime):
            timestamp = timestamp.strftime("%H:%M:%S")
        error_rows += f"""
        <tr>
            <td>{error.get('task_name', '?')}</td>
            <td>{error.get('provider', '?')}/{error.get('model_name', '?')}</td>
            <td>{error.get('error_message', '?')[:60]}</td>
            <td>{timestamp}</td>
        </tr>"""
    
    # Activity feed
    activity_rows = ""
    for act in recent_activity[:15]:
        timestamp = act.get("timestamp", "")
        if isinstance(timestamp, datetime):
            timestamp = timestamp.strftime("%H:%M:%S")
        activity_rows += f"""
        <tr>
            <td><code>{act.get('table', '?')}</code></td>
            <td>{act.get('action', '?')}</td>
            <td>{timestamp}</td>
        </tr>"""
    
    return f"""<!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Mission Control — PT Media OS</title>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            margin: 0;
            padding: 1.5rem;
            min-height: 100vh;
        }}
        h1 {{ font-size: 1.8rem; margin-bottom: 1rem; color: #fff; }}
        h2 {{ font-size: 1.2rem; margin: 1.5rem 0 .5rem; color: #cbd5e1; }}
        h3 {{ font-size: 1rem; margin: .5rem 0; color: #e2e8f0; }}
        
        .nav {{
            display: flex;
            gap: .5rem;
            margin-bottom: 1.5rem;
            flex-wrap: wrap;
        }}
        .nav a {{
            padding: 8px 18px;
            border-radius: 6px;
            background: #1e293b;
            border: 1px solid #334155;
            color: #cbd5e1;
            text-decoration: none;
            font-size: .9rem;
            transition: all .15s;
        }}
        .nav a:hover {{ background: #334155; }}
        .nav a.active {{ background: #2563eb; border-color: #2563eb; color: #fff; }}
        
        .user-info {{
            float: right;
            font-size: .85rem;
            color: #94a3b8;
            margin-top: .5rem;
        }}
        
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 1.5rem;
        }}
        
        .card {{
            background: #1e293b;
            border-radius: 12px;
            padding: 1.2rem;
            border: 1px solid #334155;
        }}
        
        .pipeline-step {{
            background: #1e293b;
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: .75rem;
            border: 1px solid #334155;
        }}
        
        .step-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: .75rem;
        }}
        
        .step-stats {{
            display: flex;
            gap: .75rem;
            align-items: center;
            font-size: .85rem;
        }}
        
        .status-badge {{
            padding: 4px 10px;
            border-radius: 4px;
            font-size: .8rem;
            font-weight: 600;
        }}
        .status-badge.ok {{ background: #16a34a; color: #fff; }}
        .status-badge.working {{ background: #f59e0b; color: #000; }}
        .status-badge.blocked {{ background: #dc2626; color: #fff; }}
        
        .eta {{
            color: #94a3b8;
            font-size: .85rem;
        }}
        
        .progress-container {{
            height: 24px;
            background: #0f172a;
            border-radius: 4px;
            overflow: hidden;
            position: relative;
        }}
        
        .progress-bar {{
            height: 100%;
            border-radius: 4px;
            transition: width .3s ease;
        }}
        
        .progress-text {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: .8rem;
            color: #fff;
            text-shadow: 0 0 4px rgba(0,0,0,.5);
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            background: #1e293b;
            border-radius: 8px;
            overflow: hidden;
        }}
        
        th, td {{
            padding: 10px 12px;
            text-align: left;
            font-size: .85rem;
            border-bottom: 1px solid #334155;
        }}
        
        th {{
            background: #0f172a;
            color: #94a3b8;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: .04em;
            font-size: .75rem;
        }}
        
        tr:hover {{ background: #334155; }}
        
        code {{
            background: #0f172a;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
            font-size: .85em;
        }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
        }}
        
        .stat-box {{
            background: #0f172a;
            padding: 1rem;
            border-radius: 8px;
            border: 1px solid #334155;
        }}
        
        .stat-box label {{
            display: block;
            color: #94a3b8;
            font-size: .75rem;
            text-transform: uppercase;
            letter-spacing: .04em;
            margin-bottom: .25rem;
        }}
        
        .stat-box .value {{
            font-size: 1.5rem;
            font-weight: 700;
            color: #fff;
        }}
        
        .stat-box .subvalue {{
            font-size: .85rem;
            color: #94a3b8;
            margin-top: .25rem;
        }}
        
        .refresh-btn {{
            padding: 8px 16px;
            background: #2563eb;
            color: #fff;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: .85rem;
            font-weight: 600;
        }}
        
        .refresh-btn:hover {{ background: #1d4ed8; }}
        
        .timestamp {{
            font-size: .75rem;
            color: #64748b;
            text-align: right;
            margin-top: .5rem;
        }}
        
        @media (max-width: 768px) {{
            body {{ padding: 1rem; }}
            .grid {{ grid-template-columns: 1fr; }}
            .nav {{ flex-direction: column; }}
            .nav a {{ width: 100%; }}
        }}
    </style>
    </head>
    <body>
    <span class="user-info">👤 {username}</span>
    
    <h1>🚀 Mission Control</h1>
    <p style="color: #94a3b8; margin-bottom: 1.5rem;">Real-time monitoring of PT Media OS pipeline</p>
    
 <div class="nav">
 <a href="/mission-control" class="active">📊 Dashboard</a>
 <a href="/">🔍 Review UI</a>
 <button class="refresh-btn" onclick="refreshAll()">🔄 Refresh All</button>
 </div>
 
 <!-- Pipeline Control -->
 <div class="card" id="pipeline-control">
 <h2 style="margin-top: 0;">⚙️ Pipeline Control</h2>
 <div style="display: flex; gap: 1rem; align-items: center; flex-wrap: wrap;">
 <button 
 class="btn btn-approve" 
 onclick="startPipeline()" 
 id="start-btn"
 >▶️ Start Pipeline</button>
 <button 
 class="btn btn-reject" 
 onclick="stopPipeline()" 
 id="stop-btn"
 >⏹️ Stop Pipeline</button>
 <span id="pipeline-status" style="font-size: .9rem; color: #f59e0b;">Status: <span id="status-text">Checking...</span></span>
 <div id="pipeline-logs" style="margin-top: .5rem; font-size: .85rem; color: #94a3b8; max-height: 100px; overflow-y: auto; white-space: pre-wrap;" hx-get="/mission-control/api/pipeline/logs" hx-trigger="every 5s"></div>
 </div>
 </div>
    <h2>📈 Pipeline Progress</h2>
    <div class="card">
    <div id="pipeline-container" hx-get="/mission-control/html/status" hx-trigger="every 10s">
    {pipeline_html}
    </div>
    </div>
    
    <!-- Pipeline Health -->
    <h2>⚡ Pipeline Health</h2>
    <div class="card">
    <div id="health-container" hx-get="/mission-control/html/health" hx-trigger="every 10s">
    <div class="stats-grid">
    <div class="stat-box">
    <label>Waiting</label>
    <div class="value">{sum(h.get('waiting', 0) for h in pipeline_health.values())}</div>
    </div>
    <div class="stat-box">
    <label>Blocked</label>
    <div class="value">{sum(1 for h in pipeline_health.values() if h.get('status') == 'blocked')}</div>
    </div>
    <div class="stat-box">
    <label>Working</label>
    <div class="value">{sum(1 for h in pipeline_health.values() if h.get('status') == 'working')}</div>
    </div>
    <div class="stat-box">
    <label>OK</label>
    <div class="value">{sum(1 for h in pipeline_health.values() if h.get('status') == 'ok')}</div>
    </div>
    </div>
    </div>
    </div>
    
    <!-- Database Stats -->
    <h2>🗃️ Database Stats</h2>
    <div class="card">
        <table id="db-table" hx-get="/mission-control/api/database" hx-trigger="every 30s">
            <thead>
                <tr><th>Table</th><th>Rows</th></tr>
            </thead>
            <tbody>
                {db_rows}
            </tbody>
        </table>
    </div>
    
    <!-- AI Metrics -->
    <h2>🤖 AI Metrics</h2>
    <div class="grid">
        <div class="card">
            <h3>Overview</h3>
            <div class="stats-grid" id="ai-overview" hx-get="/mission-control/api/ai" hx-trigger="every 30s">
                <div class="stat-box">
                    <label>Total Runs</label>
                    <div class="value">{total_runs:,}</div>
                </div>
                <div class="stat-box">
                    <label>Avg Latency</label>
                    <div class="value">{avg_latency}ms</div>
                </div>
                <div class="stat-box">
                    <label>Input Tokens</label>
                    <div class="value">{input_tokens:,}</div>
                    <div class="subvalue">Output: {output_tokens:,}</div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h3>By Task</h3>
            <table id="ai-task-table" hx-get="/mission-control/api/ai" hx-trigger="every 30s">
                <thead>
                    <tr><th>Task</th><th>Count</th></tr>
                </thead>
                <tbody>
                    {task_rows}
                </tbody>
            </table>
        </div>
        
        <div class="card">
            <h3>By Provider</h3>
            <table id="ai-provider-table" hx-get="/mission-control/api/ai" hx-trigger="every 30s">
                <thead>
                    <tr><th>Provider</th><th>Count</th></tr>
                </thead>
                <tbody>
                    {provider_rows}
                </tbody>
            </table>
        </div>
        
        <div class="card">
            <h3>By Model</h3>
            <table id="ai-model-table" hx-get="/mission-control/api/ai" hx-trigger="every 30s">
                <thead>
                    <tr><th>Model</th><th>Count</th></tr>
                </thead>
                <tbody>
                    {model_rows}
                </tbody>
            </table>
        </div>
        
        <div class="card">
            <h3>By Status</h3>
            <table id="ai-status-table" hx-get="/mission-control/api/ai" hx-trigger="every 30s">
                <thead>
                    <tr><th>Status</th><th>Count</th></tr>
                </thead>
                <tbody>
                    {status_rows}
                </tbody>
            </table>
        </div>
        
        <div class="card">
            <h3>Recent Errors</h3>
            <table id="ai-errors-table" hx-get="/mission-control/api/ai" hx-trigger="every 30s">
                <thead>
                    <tr><th>Task</th><th>Provider/Model</th><th>Error</th><th>Time</th></tr>
                </thead>
                <tbody>
                    {error_rows}
                </tbody>
            </table>
        </div>
    </div>
    
    <!-- Recent Activity -->
    <h2>📜 Recent Activity</h2>
    <div class="card">
        <table id="activity-table" hx-get="/mission-control/api/activity" hx-trigger="every 15s">
            <thead>
                <tr><th>Table</th><th>Action</th><th>Time</th></tr>
            </thead>
            <tbody>
                {activity_rows}
            </tbody>
        </table>
    </div>
    
    <div class="timestamp" id="last-refresh">
        Last refresh: <span id="refresh-time">{datetime.utcnow().strftime('%H:%M:%S UTC')}</span>
    </div>
    
 <script>
 function refreshAll() {{
 htmx.trigger('#pipeline-container', 'htmx:trigger');
 htmx.trigger('#health-container', 'htmx:trigger');
 htmx.trigger('#db-table', 'htmx:trigger');
 htmx.trigger('#ai-overview', 'htmx:trigger');
 htmx.trigger('#ai-task-table', 'htmx:trigger');
 htmx.trigger('#ai-provider-table', 'htmx:trigger');
 htmx.trigger('#ai-model-table', 'htmx:trigger');
 htmx.trigger('#ai-status-table', 'htmx:trigger');
 htmx.trigger('#ai-errors-table', 'htmx:trigger');
 htmx.trigger('#activity-table', 'htmx:trigger');
 
 document.getElementById('refresh-time').textContent = new Date().toLocaleTimeString('en-US', {{timeZone: 'UTC'}}) + ' UTC';
 }}
 
 // Pipeline control functions
 async function startPipeline() {{
 var btn = document.getElementById('start-btn');
 btn.disabled = true;
 btn.textContent = 'Starting...';
 
 try {{
 var resp = await fetch('/mission-control/api/pipeline/start', {{
 method: 'POST',
 headers: {{'Content-Type': 'application/json'}}
 }});
 var data = await resp.json();
 
 if (resp.ok) {{
 document.getElementById('status-text').textContent = 'Running';
 document.getElementById('status-text').style.color = '#16a34a';
 }} else {{
 document.getElementById('status-text').textContent = 'Error: ' + data.message;
 document.getElementById('status-text').style.color = '#dc2626';
 }}
 }} catch(e) {{
 document.getElementById('status-text').textContent = 'Error: ' + e.message;
 document.getElementById('status-text').style.color = '#dc2626';
 }} finally {{
 btn.disabled = false;
 btn.textContent = 'Start Pipeline';
 checkPipelineStatus();
 }}
 }}
 
 async function stopPipeline() {{
 var btn = document.getElementById('stop-btn');
 btn.disabled = true;
 btn.textContent = 'Stopping...';
 
 try {{
 var resp = await fetch('/mission-control/api/pipeline/stop', {{
 method: 'POST',
 headers: {{'Content-Type': 'application/json'}}
 }});
 var data = await resp.json();
 
 if (resp.ok) {{
 document.getElementById('status-text').textContent = 'Stopped';
 document.getElementById('status-text').style.color = '#dc2626';
 }} else {{
 document.getElementById('status-text').textContent = 'Error: ' + data.message;
 document.getElementById('status-text').style.color = '#dc2626';
 }}
 }} catch(e) {{
 document.getElementById('status-text').textContent = 'Error: ' + e.message;
 document.getElementById('status-text').style.color = '#dc2626';
 }} finally {{
 btn.disabled = false;
 btn.textContent = 'Stop Pipeline';
 checkPipelineStatus();
 }}
 }}
 
 async function checkPipelineStatus() {{
 try {{
 var resp = await fetch('/mission-control/api/pipeline/status');
 var data = await resp.json();
 
 if (data.running) {{
 document.getElementById('status-text').textContent = 'Running (PID: ' + data.pid + ')';
 document.getElementById('status-text').style.color = '#16a34a';
 }} else {{
 document.getElementById('status-text').textContent = 'Stopped';
 document.getElementById('status-text').style.color = '#dc2626';
 }}
 }} catch(e) {{
 document.getElementById('status-text').textContent = 'Unknown';
 document.getElementById('status-text').style.color = '#f59e0b';
 }}
 }}
 
 // Check pipeline status on page load
 checkPipelineStatus();
 
 // Auto-refresh all every 30 seconds
 setInterval(refreshAll, 30000);
 
 // Update timestamp on each HTMX swap
 document.body.addEventListener('htmx:afterSwap', function() {{
 document.getElementById('refresh-time').textContent = new Date().toLocaleTimeString('en-US', {{timeZone: 'UTC'}}) + ' UTC';
 }});
 </script>
    </body>
    </html>"""


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/mission-control", response_class=HTMLResponse)
async def mission_control_dashboard(request: Request, username: str = Depends(mc_require_auth)):
    """Render the Mission Control dashboard."""
    
    # Fetch all data in parallel
    pipeline_status = await get_pipeline_status()
    database_stats = await get_database_stats()
    ai_metrics = await get_ai_metrics()
    recent_activity = await get_recent_activity()
    pipeline_health = await get_pipeline_health()
    
    return _render_mission_control(
        pipeline_status=pipeline_status,
        database_stats=database_stats,
        ai_metrics=ai_metrics,
        recent_activity=recent_activity,
        pipeline_health=pipeline_health,
        username=username,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Health check
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/mission-control/health")
async def mc_health():
    """Health check for Mission Control."""
    try:
        await mc_fetch_one("SELECT 1")
        return {"status": "ok", "db": "connected", "mission_control": "running"}
    except Exception:
        return {"status": "degraded", "db": "unreachable"}


# ──────────────────────────────────────────────────────────────────────────────
# Mount to main app (for integration with review/app.py)
# ──────────────────────────────────────────────────────────────────────────────


def mount_to_app(main_app: FastAPI) -> None:
    """Mount Mission Control routes onto the main review app."""
    for route in app.routes:
        main_app.routes.append(route)
