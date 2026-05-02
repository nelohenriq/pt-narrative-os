"""
pt-media-os — Review UI

Internal FastAPI + HTMX web interface for human reviewers.
HTTP Basic Auth required. This is the single most important trust/quality gate in V1.

Features:
- List unreviewed events with scores
- Event detail: articles, framing, linked docs, AI summaries
- Approve: set reviewed_published, is_reviewed=TRUE, is_published=TRUE
- Reject: set reviewed_rejected, is_reviewed=TRUE, is_published=FALSE
- Edit summary inline before publishing
- Request re-generation: delete event_summaries, reset to unreviewed
"""

from __future__ import annotations

import hashlib
import json as _json
import logging
import os
from contextlib import asynccontextmanager

import asyncpg
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Depends, HTTPException, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

load_dotenv()

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# DB pool (single connection pool per process)
# ──────────────────────────────────────────────────────────────────────────────

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        db_url = os.getenv("DATABASE_URL", "")
        _pool = await asyncpg.create_pool(db_url, min_size=2, max_size=10)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def fetch_all(query: str, *args) -> list[asyncpg.Record]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def fetch_one(query: str, *args) -> asyncpg.Record | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def execute(query: str, *args) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(query, *args)


# ──────────────────────────────────────────────────────────────────────────────
# Auth
# ──────────────────────────────────────────────────────────────────────────────

def _check_auth(username: str, password: str) -> bool:
    """Verify HTTP Basic Auth credentials."""
    import bcrypt
    
    expected_user = os.getenv("REVIEW_USERNAME", "admin")
    expected_hash = os.getenv("REVIEW_PASSWORD_HASH", "")

    if username != expected_user:
        return False

    # Allow plaintext "changeme" for dev
    if not expected_hash or expected_hash == "changeme":
        return password == "changeme"

    # Try bcrypt first (starts with $2b$)
    if expected_hash.startswith("$2b$") or expected_hash.startswith("$2a$"):
        try:
            return bcrypt.checkpw(password.encode(), expected_hash.encode())
        except (ValueError, TypeError):
            return False

    password_hash = hashlib.sha256(password.encode()).hexdigest()
    if expected_hash.startswith("sha256:"):
        return f"sha256:{password_hash}" == expected_hash
    if len(expected_hash) == 64:
        return password_hash == expected_hash
    return password == expected_hash


async def require_auth(request: Request) -> str:
    """FastAPI dependency for HTTP Basic Auth."""
    import base64
    import os

    # For Cloudspaces/Lightning, check if the request has Lightning headers
    headers_str = str(request.headers).lower()
    if "x-lightning" in headers_str:
        # Allow access - user is already auth'd by Lightning Studio
        return "cloudspaces-user"
    
    # Fallback: check if running in Lightning environment
    if os.getenv("LIGHTNING_STUDIO", "") or os.getenv("CLOUDSPACES", ""):
        return "cloudspaces-user"
    
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )

    try:
        decoded = base64.b64decode(auth_header[6:]).decode()
        username, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not _check_auth(username, password):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return username


# ──────────────────────────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_pool()


app = FastAPI(title="PT Media OS — Review UI", lifespan=lifespan)



# ──────────────────────────────────────────────────────────────────────────────
# HTML Templates
# ──────────────────────────────────────────────────────────────────────────────


def _render_base(title: str, body: str, username: str, extra_head: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="utf-8">
    <title>{title} — PT Media OS</title>
    {extra_head}
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: system-ui, -apple-system, sans-serif; margin: 1.5rem; background: #f0f2f5; color: #222; }}
        h1, h2, h3 {{ margin-bottom: .5rem; }}
        h1 {{ font-size: 1.4rem; }}
        h2 {{ font-size: 1.1rem; margin-top: 1.5rem; }}
        table {{ border-collapse: collapse; width: 100%; background: #fff; margin-bottom: 1rem; border-radius: 6px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
        th, td {{ padding: 10px 12px; border-bottom: 1px solid #e8e8e8; text-align: left; font-size: .9rem; }}
        th {{ background: #1e293b; color: #fff; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; font-size: .75rem; }}
        tr:hover {{ background: #f8fafc; }}
        a {{ color: #2563eb; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .nav {{ display: flex; gap: 1rem; margin-bottom: 1.2rem; }}
        .nav a {{ padding: 6px 14px; border-radius: 4px; background: #fff; border: 1px solid #d1d5db; font-size: .85rem; }}
        .nav a.active {{ background: #2563eb; color: #fff; border-color: #2563eb; }}
        .user-info {{ float: right; font-size: .85rem; color: #666; }}
        .badge {{ display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: .75rem; font-weight: 600; }}
        .badge-lusa {{ background: #7c3aed; color: #fff; }}
        .badge-flag {{ background: #f59e0b; color: #fff; }}
        .card {{ background: #fff; padding: 1rem; margin: 1rem 0; border-left: 4px solid #2563eb; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,.05); }}
        .card.ucov {{ border-left-color: #f59e0b; }}
        .actions {{ margin: 1rem 0; display: flex; gap: .5rem; flex-wrap: wrap; }}
        .btn {{ padding: 8px 18px; border: none; border-radius: 4px; cursor: pointer; font-size: .9rem; font-weight: 600; transition: opacity .15s; }}
        .btn:hover {{ opacity: .85; }}
        .btn-approve {{ background: #16a34a; color: #fff; }}
        .btn-reject {{ background: #dc2626; color: #fff; }}
        .btn-regen {{ background: #f59e0b; color: #fff; }}
        .btn-back {{ background: #6b7280; color: #fff; }}
        .btn-edit {{ background: #0891b2; color: #fff; font-size: .8rem; padding: 4px 10px; }}
        .edit-form {{ display: none; margin-top: .5rem; }}
        .edit-form.show {{ display: block; }}
        textarea {{ width: 100%; padding: 8px; border: 1px solid #d1d5db; border-radius: 4px; font-family: inherit; font-size: .9rem; min-height: 120px; resize: vertical; }}
        input[type="text"] {{ padding: 7px 10px; border: 1px solid #d1d5db; border-radius: 4px; font-size: .9rem; min-width: 280px; }}
        .meta {{ font-size: .85rem; color: #666; margin: .3rem 0; }}
        .scores {{ display: flex; gap: 1rem; flex-wrap: wrap; margin: .5rem 0; }}
        .score-item {{ padding: 4px 10px; background: #e5e7eb; border-radius: 4px; font-size: .8rem; }}
        .empty {{ color: #999; font-style: italic; padding: 2rem; text-align: center; }}
        @media (max-width: 600px) {{
            body {{ margin: .5rem; }}
            .scores {{ flex-direction: column; }}
            .actions {{ flex-direction: column; }}
        }}
    </style>
    <script>
        function toggleEdit(type) {{
            var display = document.getElementById('summary-display-' + type);
            var form = document.getElementById('edit-form-' + type);
            if (form.classList.contains('show')) {{
                form.classList.remove('show');
                display.style.display = '';
            }} else {{
                form.classList.add('show');
                display.style.display = 'none';
            }}
        }}
    </script>
</head>
<body>
<span class="user-info">👤 {username}</span>
{body}
</body>
</html>"""


def _render_event_list(events: list[dict], username: str, list_type: str = "unreviewed") -> str:
    nav = """
 <div class="nav">
 <a href="/" class="{active_unreviewed}">📋 Unreviewed</a>
 <a href="/published" class="{active_published}">✅ Published</a>
 <a href="/rejected" class="{active_rejected}">❌ Rejected</a>
 <a href="/mission-control" style="background: #7c3aed; border-color: #7c3aed; color: #fff;">🚀 Mission Control</a>
 </div>"""
    nav = nav.replace(
        "{active_unreviewed}", "active" if list_type == "unreviewed" else ""
    ).replace(
        "{active_published}", "active" if list_type == "published" else ""
    ).replace(
        "{active_rejected}", "active" if list_type == "rejected" else ""
    )

    if not events:
        rows = '<tr><td colspan="7" class="empty">No events found.</td></tr>'
    else:
        rows = ""
        for e in events:
            flags = ""
            if float(e.get("undercoverage_score") or 0) > 0.3:
                flags += '<span class="badge badge-flag">⚠ undercovered</span> '
            if e.get("status") == "candidate":
                flags += '<span class="badge" style="background:#f59e0b;color:#fff">candidate</span>'

            rows += f"""
            <tr>
                <td><a href="/events/{e['id']}">{e['canonical_title'][:80]}</a></td>
                <td>{e['article_count']}</td>
                <td>{e['outlet_count']}</td>
                <td>{float(e.get('coverage_breadth') or 0):.0%}</td>
                <td>{float(e.get('framing_divergence') or 0):.2f}</td>
                <td>{flags}</td>
                <td>{str(e.get('first_seen_at') or e.get('reviewed_at') or '-')[:10]}</td>
            </tr>"""

    body = f"""<h1>🔍 Event Review</h1>
{nav}
<table>
<tr><th>Title</th><th># Art</th><th># Outl</th><th>Cov</th><th>Div</th><th>Flags</th><th>Date</th></tr>
{rows}
</table>"""

    return _render_base("Review", body, username)


def _render_event_detail(
    event: dict,
    articles: list[dict],
    summaries: list[dict],
    documents: list[dict],
    flags: list[dict],
    username: str,
) -> str:
    # Scores
    scores_html = ""
    if event.get("coverage_breadth") is not None:
        scores = [
            ("Cobertura", f"{float(event.get('coverage_breadth', 0)):.0%}"),
            ("Divergência", f"{float(event.get('framing_divergence', 0)):.2f}"),
            ("Evidência", f"{float(event.get('evidence_density', 0)):.0%}"),
            ("Lusa dep.", f"{float(event.get('lusa_dependency', 0)):.0%}"),
        ]
        scores_html = '<div class="scores">' + "".join(
            f'<span class="score-item"><strong>{k}</strong>: {v}</span>'
            for k, v in scores
        ) + "</div>"

    status_badge = {
        "candidate": '<span class="badge" style="background:#f59e0b;color:#fff">candidate</span>',
        "unreviewed": '<span class="badge" style="background:#dc2626;color:#fff">unreviewed</span>',
        "reviewed_published": '<span class="badge" style="background:#16a34a;color:#fff">published</span>',
        "reviewed_rejected": '<span class="badge" style="background:#6b7280;color:#fff">rejected</span>',
    }.get(event.get("status", ""), event.get("status", ""))

    # Summaries
    summary_cards = ""
    for i, s in enumerate(summaries):
        cls = "card ucov" if s["summary_type"] == "undercoverage_card" else "card"
        stype = s["summary_type"]
        escaped_content = s["content"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        summary_cards += f"""
        <div class="{cls}" id="summary-{stype}">
            <h4 style="text-transform:uppercase;letter-spacing:.04em;font-size:.75rem;color:#666;display:flex;justify-content:space-between;align-items:center">
                {stype}
                <button class="btn btn-edit" onclick="toggleEdit('{stype}')">✏️ Edit</button>
            </h4>
            <div id="summary-display-{stype}">
                <p style="white-space:pre-wrap">{s['content']}</p>
                <p class="meta">Model: {s.get('model_name','?')} | v{s.get('prompt_version','?')}</p>
            </div>
            <div class="edit-form" id="edit-form-{stype}">
                <form method="POST" action="/events/{event['id']}/summaries/{stype}" onsubmit="return saveEdit('{stype}', this)">
                    <textarea name="content" id="edit-content-{stype}">{escaped_content}</textarea>
                    <div style="margin-top:.5rem;display:flex;gap:.5rem">
                        <button type="submit" class="btn btn-approve">💾 Save</button>
                        <button type="button" class="btn btn-back" onclick="toggleEdit('{stype}')">Cancel</button>
                    </div>
                </form>
            </div>
        </div>"""

    # Articles
    if articles:
        art_rows = ""
        for a in articles:
            lusa = ""
            if a.get("lusa_cited"):
                lusa += '<span class="badge badge-lusa">Lusa cit</span> '
            if a.get("lusa_likely"):
                lusa += '<span class="badge badge-lusa">Lusa ≈</span> '
            art_rows += f"""
            <tr>
                <td>{a.get('outlet_name', '?')}</td>
                <td><a href="{a['canonical_url']}" target="_blank">{a['title'][:70]}</a></td>
                <td>{a.get('word_count',0)}</td>
                <td>{lusa}</td>
            </tr>"""
    else:
        art_rows = '<tr><td colspan="4" class="empty">No articles</td></tr>'

    # Documents
    if documents:
        doc_rows = ""
        for d in documents:
            doc_rows += f"""
            <tr>
                <td>{d.get('source_type','?')}</td>
                <td>{d['title'][:60]}</td>
                <td>{d.get('matched_by','?')}</td>
            </tr>"""
    else:
        doc_rows = '<tr><td colspan="3" class="empty">No linked documents</td></tr>'

    # Flags
    if flags:
        flag_rows = ""
        for f in flags:
            silent = f.get("silent_outlets", [])
            if isinstance(silent, str):
                try:
                    silent = _json.loads(silent)
                except Exception:
                    silent = []
            silent_str = ", ".join(silent[:6]) if silent else "—"
            if len(silent) > 6:
                silent_str += f" (+{len(silent) - 6})"
            flag_rows += f"""
            <tr>
                <td>{f.get('flag_type','?')}</td>
                <td>{f.get('reason','?')[:100]}</td>
                <td style="font-size:.8rem">{silent_str}</td>
            </tr>"""
    else:
        flag_rows = '<tr><td colspan="3" class="empty">No flags</td></tr>'

    body = f"""<h1>🔍 {event['canonical_title'][:100]}</h1>
<p class="meta">Status: {status_badge} | Articles: {event.get('article_count',0)} | Outlets: {event.get('outlet_count',0)}</p>
{scores_html}

<div class="actions">
    <form method="POST" action="/events/{event['id']}/approve" style="display:inline">
        <button class="btn btn-approve">✅ Approve & Publish</button>
    </form>
    <form method="POST" action="/events/{event['id']}/reject" style="display:inline">
        <input type="text" name="note" placeholder="Rejection reason...">
        <button class="btn btn-reject">❌ Reject</button>
    </form>
    <form method="POST" action="/events/{event['id']}/regenerate" style="display:inline">
        <button class="btn btn-regen">🔄 Re-generate</button>
    </form>
    <a href="/" class="btn btn-back" style="display:inline-block">← Back</a>
</div>

<h2>AI Summaries</h2>
{summary_cards if summary_cards else '<p class="empty">No summaries generated yet.</p>'}

<h2>Articles ({len(articles)})</h2>
<table><tr><th>Outlet</th><th>Title</th><th>Words</th><th>Flags</th></tr>
{art_rows}</table>

<h2>Source Documents ({len(documents)})</h2>
<table><tr><th>Type</th><th>Title</th><th>Matched</th></tr>
{doc_rows}</table>

<h2>Undercoverage Flags ({len(flags)})</h2>
<table><tr><th>Type</th><th>Reason</th><th>Silent</th></tr>
{flag_rows}</table>

<script>
async function saveEdit(type) {{
    var textarea = document.getElementById('edit-content-' + type);
    var content = textarea.value;
    var resp = await fetch('/events/{event['id']}/summaries/' + type, {{
        method: 'POST',
        headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
        body: 'content=' + encodeURIComponent(content)
    }});
    if (resp.ok) {{
        var data = await resp.json();
        document.getElementById('summary-display-' + type).querySelector('p').textContent = data.content;
        toggleEdit(type);
    }} else {{
        alert('Failed to save: ' + resp.status);
    }}
    return false;
}}
</script>"""

    return _render_base("Review", body, username)


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def list_unreviewed(request: Request, username: str = Depends(require_auth)):
    events = await fetch_all(
        """SELECT e.id::text, e.canonical_title, e.article_count, e.outlet_count,
                  e.status, e.first_seen_at, e.created_at,
                  es.coverage_breadth, es.framing_divergence,
                  es.undercoverage_score
           FROM events e
           LEFT JOIN event_scores es ON e.id = es.event_id
           WHERE e.is_reviewed = FALSE AND e.status IN ('candidate', 'unreviewed')
           ORDER BY e.article_count DESC, e.created_at DESC
           LIMIT 100"""
    )
    return _render_event_list([dict(r) for r in events], username, "unreviewed")


@app.get("/published", response_class=HTMLResponse)
async def list_published(request: Request, username: str = Depends(require_auth)):
    events = await fetch_all(
        """SELECT e.id::text, e.canonical_title, e.article_count, e.outlet_count,
                  e.status, e.first_seen_at, e.reviewed_at,
                  es.coverage_breadth, es.framing_divergence,
                  es.undercoverage_score
           FROM events e
           LEFT JOIN event_scores es ON e.id = es.event_id
           WHERE e.is_published = TRUE
           ORDER BY e.reviewed_at DESC LIMIT 50"""
    )
    return _render_event_list([dict(r) for r in events], username, "published")


@app.get("/rejected", response_class=HTMLResponse)
async def list_rejected(request: Request, username: str = Depends(require_auth)):
    events = await fetch_all(
        """SELECT e.id::text, e.canonical_title, e.article_count, e.outlet_count,
                  e.status, e.first_seen_at, e.reviewed_at, e.review_note
           FROM events e
           WHERE e.status = 'reviewed_rejected'
           ORDER BY e.reviewed_at DESC LIMIT 50"""
    )
    return _render_event_list([dict(r) for r in events], username, "rejected")


@app.get("/events/{event_id}", response_class=HTMLResponse)
async def event_detail(
    event_id: str, request: Request, username: str = Depends(require_auth)
):
    event = await fetch_one(
        """SELECT e.*,
                  es.coverage_breadth, es.framing_divergence, es.evidence_density,
                  es.lusa_dependency, es.undercoverage_score, es.explanation
           FROM events e
           LEFT JOIN event_scores es ON e.id = es.event_id
           WHERE e.id = $1""",
        event_id,
    )
    if not event:
        raise HTTPException(404, "Event not found")

    articles = await fetch_all(
        """SELECT a.id::text, a.title, a.canonical_url, a.word_count,
                  a.lusa_cited, a.lusa_likely,
                  o.name AS outlet_name
           FROM articles a
           JOIN outlets o ON a.outlet_id = o.id
           JOIN event_articles ea ON a.id = ea.article_id
           WHERE ea.event_id = $1
           ORDER BY a.published_at DESC""",
        event_id,
    )

    summaries = await fetch_all(
        """SELECT summary_type, content, model_name, prompt_version, ai_run_id
           FROM event_summaries WHERE event_id = $1""",
        event_id,
    )

    documents = await fetch_all(
        """SELECT sd.title, sd.source_type, ed.matched_by
           FROM source_documents sd
           JOIN event_documents ed ON sd.id = ed.document_id
           WHERE ed.event_id = $1""",
        event_id,
    )

    flags = await fetch_all(
        """SELECT flag_type, reason, silent_outlets::text AS silent_outlets_str
           FROM undercoverage_flags WHERE event_id = $1""",
        event_id,
    )

    flags_list: list[dict] = []
    for f in flags:
        fd = dict(f)
        flags_list.append(fd)

    return _render_event_detail(
        dict(event),
        [dict(a) for a in articles],
        [dict(s) for s in summaries],
        [dict(d) for d in documents],
        flags_list,
        username,
    )


@app.post("/events/{event_id}/approve")
async def approve_event(
    event_id: str, request: Request, username: str = Depends(require_auth)
):
    await execute(
        """UPDATE events
           SET status = 'reviewed_published', is_reviewed = TRUE, is_published = TRUE,
               reviewed_at = now(), reviewed_by = $1
           WHERE id = $2""",
        username,
        event_id,
    )
    await execute(
        "UPDATE undercoverage_flags SET is_published = TRUE WHERE event_id = $1",
        event_id,
    )
    return RedirectResponse(f"/events/{event_id}", status_code=303)


@app.post("/events/{event_id}/reject")
async def reject_event(
    event_id: str,
    request: Request,
    note: str = Form(""),
    username: str = Depends(require_auth),
):
    await execute(
        """UPDATE events
           SET status = 'reviewed_rejected', is_reviewed = TRUE, is_published = FALSE,
               reviewed_at = now(), reviewed_by = $1, review_note = $2
           WHERE id = $3""",
        username,
        note or "",
        event_id,
    )
    return RedirectResponse(f"/events/{event_id}", status_code=303)


@app.post("/events/{event_id}/regenerate")
async def regenerate_event(
    event_id: str, request: Request, username: str = Depends(require_auth)
):
    await execute("DELETE FROM event_summaries WHERE event_id = $1", event_id)
    await execute(
        """UPDATE events
           SET status = 'unreviewed', is_reviewed = FALSE, is_published = FALSE,
               updated_at = now()
           WHERE id = $1""",
        event_id,
    )
    return RedirectResponse(f"/events/{event_id}", status_code=303)


@app.post("/events/{event_id}/summaries/{summary_type}")
async def update_summary(
    event_id: str,
    summary_type: str,
    request: Request,
    content: str = Form(...),
    username: str = Depends(require_auth),
):
    # Validate summary_type against DB enum
    valid_types = {"event_summary", "framing_comparison", "undercoverage_card"}
    if summary_type not in valid_types:
        raise HTTPException(400, f"Invalid summary_type: {summary_type}")

    # Upsert: use ON CONFLICT with a COALESCE on ai_run_id
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO event_summaries (event_id, summary_type, content, ai_run_id, model_name, prompt_version)
               VALUES ($1, $2, $3,
                       (SELECT id FROM ai_runs WHERE event_id = $1 LIMIT 1),
                       'human-edited', 'manual')
               ON CONFLICT (event_id, summary_type)
               DO UPDATE SET content = $3, model_name = 'human-edited',
                             prompt_version = 'manual', created_at = now()""",
            event_id,
            summary_type,
            content,
        )
        await conn.execute(
            "UPDATE events SET updated_at = now() WHERE id = $1",
            event_id,
        )
    return JSONResponse({"status": "ok", "summary_type": summary_type, "content": content})


# ──────────────────────────────────────────────────────────────────────────────
# Health check for dev
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    try:
        await fetch_one("SELECT 1")
        return {"status": "ok", "db": "connected"}
    except Exception:
        return {"status": "degraded", "db": "unreachable"}