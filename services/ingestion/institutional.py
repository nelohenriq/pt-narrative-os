"""Institutional source ingestion for Portuguese parliamentary data.

Fetches open data from Assembleia da República (AR) open data portal:
    - Diplomas Aprovados (laws, decrees, resolutions)
    - Atividades (debates, hearings, questions)

Data is stored in the `source_documents` table with source_type='parliamentary'.

V1 strategy (per docs/institutional-sources.md):
    1.aleb bulk load of current legislature (XVI).
    2. Incremental poll every 4 hours for new entries.
    3. Dedup by source_type + external_id.
    4. ERC scraping is NOT automated in V1.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from xml.etree import ElementTree

import asyncpg
import httpx

logger = logging.getLogger(__name__)

USER_AGENT = (
    "pt-narrative-os/0.1 (https://github.com/pt-narrative-os; "
    "research crawler; contact@example.com)"
)

REQUEST_TIMEOUT = 60  # AR servers can be slow

# AR open data base URLs (as of 2025-2026)
AR_BASE = "https://app.parlamento.pt"

# Source: centraldedados/parlamento GitHub mirror (more reliable than AR site)
CD_BASE = "https://raw.githubusercontent.com/centraldedados/parlamento/master"

# Legislature XVI: 2024-03-26 onwards
XVI_START = datetime(2024, 3, 26, tzinfo=timezone.utc)

# ──────────────────────────────────────────────────────────────────────────────
# XML helpers
# ──────────────────────────────────────────────────────────────────────────────


def _safe_text(el: ElementTree.Element | None, tag: str) -> str | None:
    """Extract text from a sub-element, returning None if missing."""
    child = el.find(tag) if el is not None else None
    return (child.text or "").strip() if child is not None and child.text else None


def _try_parse_date(raw: str | None) -> datetime | None:
    """Parse a date string into UTC datetime, trying common formats."""
    if not raw:
        return None
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y",
        "%Y%m%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Diplomas Aprovados (laws, decrees, resolutions)
# ──────────────────────────────────────────────────────────────────────────────


async def _fetch_diplomas_xml(
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    """Fetch Diplomas Aprovados dataset.

    Returns a list of dicts parsed from the XML feed.
    Uses the centraldedados mirror as primary source (GitHub is more reliable
    than the AR SharePoint-based site).
    """
    # Primary: centraldedados GitHub mirror
    # Fallback: AR open data site
    urls = [
        f"{CD_BASE}/data/diplomas_aprovados.xml",
        f"{AR_BASE}/Cidadania/Paginas/DADiplomasAprovados.aspx",
    ]

    for url in urls:
        try:
            resp = await client.get(url, timeout=REQUEST_TIMEOUT, follow_redirects=True)
            resp.raise_for_status()
            break
        except httpx.HTTPError:
            continue
    else:
        logger.warning("Could not fetch diplomas from any source")
        return []

    try:
        root = ElementTree.fromstring(resp.text)
    except ElementTree.ParseError as exc:
        logger.error("XML parse error for diplomas: %s", exc)
        return []

    documents: list[dict[str, Any]] = []
    for diploma_el in root.findall(".//Diploma"):
        tipo = _safe_text(diploma_el, "tipoDiploma") or "Desconhecido"
        numero = _safe_text(diploma_el, "numero") or ""
        ano = _safe_text(diploma_el, "ano") or ""
        ementa = _safe_text(diploma_el, "ementa") or ""

        title = f"{tipo} n.º {numero}/{ano}: {ementa}" if ementa else f"{tipo} n.º {numero}/{ano}"
        external_id = _safe_text(diploma_el, "id") or f"diploma:{tipo}:{numero}:{ano}"
        published_at = _try_parse_date(
            _safe_text(diploma_el, "dataPublicacao")
            or _safe_text(diploma_el, "dataAprovacao")
        )

        canonical_url = _safe_text(diploma_el, "urlDiarioDaAR")

        documents.append(
            {
                "source_type": "parliamentary",
                "title": title,
                "external_id": external_id,
                "canonical_url": canonical_url,
                "published_at": published_at,
                "body_text": ementa,
                "metadata": {
                    "subtype": "diploma",
                    "tipo": tipo,
                    "numero": numero,
                    "ano": ano,
                    "data_aprovacao": _safe_text(diploma_el, "dataAprovacao"),
                    "data_publicacao": _safe_text(diploma_el, "dataPublicacao"),
                },
            }
        )

    return documents


# ──────────────────────────────────────────────────────────────────────────────
# Atividades (debates, hearings, questions)
# ──────────────────────────────────────────────────────────────────────────────


async def _fetch_atividades_json(
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    """Fetch Atividades dataset.

    Returns a list of dicts from JSON activity data.
    Uses GitHub mirror as primary, AR site as fallback.
    """
    urls = [
        f"{CD_BASE}/data/atividades.json",
        f"{AR_BASE}/Cidadania/Paginas/DAatividades.aspx",
    ]

    for url in urls:
        try:
            resp = await client.get(url, timeout=REQUEST_TIMEOUT, follow_redirects=True)
            resp.raise_for_status()
            break
        except httpx.HTTPError:
            continue
    else:
        logger.warning("Could not fetch activities from any source")
        return []

    import json as _json

    try:
        data = _json.loads(resp.text)
    except _json.JSONDecodeError as exc:
        logger.error("JSON parse error for activities: %s", exc)
        return []

    # Normalize — data may be a list or a dict with a key
    if isinstance(data, dict):
        # Try common keys
        activities = data.get("activities") or data.get("data") or data.get("items") or []
        if isinstance(activities, dict):
            activities = list(activities.values())
    elif isinstance(data, list):
        activities = data
    else:
        activities = []

    documents: list[dict[str, Any]] = []
    for act in activities:
        if not isinstance(act, dict):
            continue

        tipo = str(act.get("tipo") or act.get("type", "Desconhecido"))
        descricao = str(act.get("descricao") or act.get("description", ""))
        external_id = str(act.get("id") or act.get("_id", ""))
        published_at = _try_parse_date(str(act.get("data") or act.get("date", "")))

        title = f"{tipo}: {descricao}" if descricao else tipo

        documents.append(
            {
                "source_type": "parliamentary",
                "title": title,
                "external_id": external_id,
                "canonical_url": None,
                "published_at": published_at,
                "body_text": descricao,
                "metadata": {
                    "subtype": "atividade",
                    "tipo": tipo,
                    "local": act.get("local"),
                    "orgaos": act.get("orgaos", []),
                    "deputados": act.get("deputados", []),
                },
            }
        )

    return documents


# ──────────────────────────────────────────────────────────────────────────────
# Database operations
# ──────────────────────────────────────────────────────────────────────────────


async def _document_exists(
    conn: asyncpg.Connection, source_type: str, external_id: str
) -> bool:
    """Check if a source_document already exists."""
    row = await conn.fetchrow(
        "SELECT 1 FROM source_documents WHERE source_type = $1 AND external_id = $2 LIMIT 1",
        source_type,
        external_id,
    )
    return row is not None


async def _insert_source_document(
    conn: asyncpg.Connection, doc: dict[str, Any]
) -> str:
    """Insert a source_document row and return its UUID."""
    import json as _json

    row = await conn.fetchrow(
        """
        INSERT INTO source_documents (
            source_type, title, external_id, canonical_url,
            published_at, body_text, metadata
        ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
        RETURNING id::text
        """,
        doc["source_type"],
        doc["title"],
        doc["external_id"],
        doc["canonical_url"],
        doc["published_at"],
        doc["body_text"],
        _json.dumps(doc["metadata"]),
    )
    return row["id"]


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


async def ingest_institutional(
    db_url: str | None = None,
    *,
    since: datetime | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Ingest parliamentary documents from AR open data.

    Args:
        db_url: Postgres connection string. Reads from DATABASE_URL env if None.
        since: Only insert documents published after this date.
               Defaults to the start of legislature XVI (2024-03-26).
        http_client: Shared httpx client. Creates one if None.

    Returns a summary dict: {diplomas, atividades, total_inserted, total_skipped, errors}.
    """
    import os

    from dotenv import load_dotenv

    load_dotenv()

    if db_url is None:
        db_url = os.getenv("DATABASE_URL", "")

    if since is None:
        since = XVI_START

    own_client = http_client is None
    if own_client:
        http_client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )

    summary: dict[str, Any] = {
        "diplomas": {"fetched": 0, "inserted": 0, "skipped": 0},
        "atividades": {"fetched": 0, "inserted": 0, "skipped": 0},
        "errors": [],
    }

    try:
        # Fetch documents
        diplomas = await _fetch_diplomas_xml(http_client)
        summary["diplomas"]["fetched"] = len(diplomas)

        atividades = await _fetch_atividades_json(http_client)
        summary["atividades"]["fetched"] = len(atividades)

        all_docs = diplomas + atividades

        async with asyncpg.create_pool(db_url, min_size=1, max_size=3) as pool:
            async with pool.acquire() as conn:
                for doc in all_docs:
                    # Filter by time
                    if doc["published_at"] and doc["published_at"] < since:
                        continue

                    is_diploma = "diploma" in str(doc.get("metadata", {}).get("subtype", ""))

                    # Dedup
                    if await _document_exists(conn, doc["source_type"], doc["external_id"]):
                        if is_diploma:
                            summary["diplomas"]["skipped"] += 1
                        else:
                            summary["atividades"]["skipped"] += 1
                        continue

                    # Insert
                    try:
                        await _insert_source_document(conn, doc)
                    except Exception as exc:
                        summary["errors"].append({"doc": doc["external_id"], "error": str(exc)})
                        continue

                    if is_diploma:
                        summary["diplomas"]["inserted"] += 1
                    else:
                        summary["atividades"]["inserted"] += 1

    finally:
        if own_client and http_client:
            await http_client.aclose()

    total_inserted = summary["diplomas"]["inserted"] + summary["atividades"]["inserted"]
    logger.info(
        "Institutional ingestion: %d diplomas inserted, %d activities, %d errors",
        summary["diplomas"]["inserted"],
        summary["atividades"]["inserted"],
        len(summary["errors"]),
    )

    return summary