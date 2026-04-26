# pt-media-os V1 — Institutional Sources Reference

_Last updated: 2026-04-25_

---

## 1. Assembleia da República (AR) — Open Data

### Base URL
`https://app.parlamento.pt/` (data pages) and `http://www.parlamento.pt/Cidadania/paginas/dadosabertos.aspx` (index)

### Data formats
- **XML** and **JSON** (both available for all datasets)
- No API key required
- Reuse policy: free, must cite source ("Assembleia da República")

### Available datasets (relevant for V1)

| Dataset | URL path | Content | Value for V1 |
|---|---|---|---|
| **Diplomas Aprovados** | `/Cidadania/Paginas/DADiplomasAprovados.aspx` | Laws, decrees, resolutions passed by AR | Link events to approved legislation |
| **Atividades** | `/Cidadania/Paginas/DAatividades.aspx` | Parliamentary activities: hearings, debates, questions, votes, interpellations | Match events to parliamentary debates/questions |
| **DAR (Diário da AR)** | `/Cidadania/Paginas/DAdar.aspx` | Official journal: Série I (plenary), Série II-A/II-B (committees, questions) | Full parliamentary record text |
| **Atividade dos Deputados** | `/Cidadania/Paginas/DAatividadeDeputado.aspx` | Per-deputy activity: initiatives, questions, interventions | Cross-reference entities (politicians) with parliamentary action |
| **Agenda Parlamentar** | `/Cidadania/Paginas/DABoletimInformativo.aspx` | Upcoming AR activities | Future: event prediction |

### How to access
1. Visit the dataset page (e.g., Diplomas Aprovados)
2. Select the legislature (e.g., XVI — current)
3. Download XML/JSON files per legislative session
4. The AR site organizes data by legislature, not by date — need to map legislature to date ranges

### Data structure (Diplomas Aprovados — XML)
```xml
<Diploma>
  <id>...</id>
  <tipoDiploma>Lei</tipoDiploma>
  <numero>...</numero>
  <ano>2024</ano>
  <ementa>Summary text...</ementa>
  <urlDiarioDaAR>...</urlDiarioDaAR>
  <dataAprovacao>2024-03-15</dataAprovacao>
  <dataPublicacao>2024-03-20</dataPublicacao>
</Diploma>
```

### Data structure (Atividades — JSON)
```json
{
  "id": "...",
  "tipo": "Audição",
  "descricao": "...",
  "data": "2024-03-15T10:00:00",
  "local": "Sala 1",
  "orgaos": ["Comissão de Constituição"],
  "deputados": [{"nome": "...", "partido": "..."}]
}
```

### V1 ingestion strategy
1. **One-time bulk load**: Download all Diplomas Aprovados and Atividades for the current legislature (XVI).
2. **Incremental poll** (every 4 hours): Check for new entries since last `fetched_at`.
3. Store in `source_documents` with `source_type = 'parliamentary'`.
4. Use `ementa`/`descricao` for topic matching against events.

### Known issues
- The AR website uses SharePoint-style URLs with encoded paths — not a clean REST API.
- Data is organized by legislature, making time-range queries awkward.
- The centraldedados/parlamento GitHub repo (https://github.com/centraldedados/parlamento) has scraped versions of some data that may be easier to parse.
- No webhook/notification system — polling only.

---

## 2. ERC — Portal da Transparência

### Base URL
`https://portaltransparencia.erc.pt/`

### Data formats
- **HTML only** — no structured API, no CSV/XML/JSON download
- The portal renders data via JavaScript (AJAX calls to internal endpoints)

### Available data

| Category | URL path | Content | Value for V1 |
|---|---|---|---|
| **Órgãos de Comunicação Social** | `/ocs/?idOcs=...` | Registered media outlets by type (Imprensa, Online, Rádio, TV, Agência) | Validate/expand outlets table |
| **Entidades Proprietárias** | `/entidades-ocs/?idActividade=...` | Owning entities of media orgs (SA, quota companies, persons) | Populate owners + outlet_ownership |
| **Grupos de Media** | (via Navigator) | Media group structures and cross-ownership | Ownership enrichment |
| **Notícias** | `/notícias/` | ERC transparency news/updates | Low priority |
| **Relatórios** | `/relatórios/` | ERC reports on media ownership/concentration | Low priority |

### How to access
1. The portal is HTML-rendered with AJAX calls.
2. Inspect browser network requests to find internal API endpoints (likely returning JSON).
3. Alternatively, scrape the HTML pages directly.
4. The portal requires JavaScript — use a headless browser or find the hidden API.

### V1 ingestion strategy
1. **One-time manual load**: Use the portal to look up each of the 20 outlets and their ownership entities.
2. **Manual entry into `owners` and `outlet_ownership` tables** with confidence scores.
3. **Quarterly re-check**: Re-scrape the portal every 3 months to update ownership data.
4. This is NOT a real-time source — ownership changes are infrequent.

### Known issues
- No official API — all data is HTML/JS-rendered.
- Data quality depends on what media entities self-report to ERC (legally required but compliance varies).
- The `confidence` field in `outlet_ownership` is critical — always show it.
- Per CLAUDE.md: "Do NOT treat ERC ownership data as ground truth — always show confidence level."

### Internal API (reverse-engineered)
The portal likely has AJAX endpoints like:
- `https://portaltransparencia.erc.pt/api/ocs` (list of media outlets)
- `https://portaltransparencia.erc.pt/api/entidades` (list of owning entities)

These need to be verified by inspecting network requests in the browser. If they exist, they'll return JSON and be much easier to parse than the HTML.

---

## 3. Additional institutional sources (future / V1.1)

These are NOT required for V1 but should be noted for future phases:

| Source | URL | Content | Notes |
|---|---|---|---|
| **Diário da República Eletrónico** | `https://diariodarepublica.pt/` | Official government gazette — laws, decrees, regulations | Requires subscription for full access; free search |
| **Dados.gov.pt** | `https://dados.gov.pt/` | Central open data portal — 10,000+ datasets | Some AR datasets may be mirrored here |
| **PORDATA** | `https://www.pordata.pt/` | Statistical data about Portugal | Useful for context but not real-time |
| **Tribunal de Contas** | `https://www.tcontas.pt/` | Audit reports on public spending | Low priority |
| **ACM — Alta Autoridade para a Comunicação Social** (historical) | N/A | Pre-ERC regulatory decisions | Archive only |

---

## 4. Implementation notes for `services/ingestion/institutional.py`

### Phase 0 approach (recommended)
1. **Do NOT build an automated ERC scraper for V1.** The HTML/JS portal is fragile and changes often.
2. **Manually populate ownership data** from ERC portal research into `db/seed/outlets.sql`.
3. **Build AR open data ingestion first** — it has clean XML/JSON downloads and is the most valuable institutional source.
4. **Add ERC scraping as a Phase 2 task** once the core pipeline works.

### AR ingestion implementation steps
```python
# Pseudocode for institutional.py

async def fetch_parliamentary_documents(since: datetime):
    """Fetch new parliamentary documents from AR open data."""
    base_url = "https://app.parlamento.pt/..."
    
    # 1. Fetch Diplomas Aprovados (laws/decrees)
    diplomas = await fetch_xml(base_url + "/DADiplomasAprovados.aspx", 
                               legislature=CURRENT_LEGISLATURE)
    
    # 2. Fetch Atividades (debates, hearings, questions)
    activities = await fetch_json(base_url + "/DAatividades.aspx",
                                  legislature=CURRENT_LEGISLATURE)
    
    # 3. For each new document:
    for doc in parse_documents(diplomas, activities):
        if doc.published_at < since:
            continue  # already processed
        
        # Dedup by source_type + external_id
        existing = await db.fetch_one(
            "SELECT id FROM source_documents WHERE source_type='parliamentary' AND external_id=$1",
            doc.id
        )
        if existing:
            continue
        
        await db.execute("""
            INSERT INTO source_documents (source_type, title, external_id, 
                canonical_url, published_at, body_text, metadata)
            VALUES ('parliamentary', $1, $2, $3, $4, $5, $6)
        """, doc.title, doc.id, doc.url, doc.published_at, doc.text, doc.metadata)
```
