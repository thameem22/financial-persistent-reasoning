# Visual Data Flow — Sample MSFT 10-K Walkthrough

End-to-end trace using **`data/samples/msft-10k-fy2024.html`** and the default pipeline:

```bash
python -m pipeline.orchestrator --ticker MSFT --mock
```

See also: [EDGAR.md](EDGAR.md) (live SEC path), [ReasoningEngineC4.png](ReasoningEngineC4.png) (architecture diagram).

---

## Master diagram (all services + stores)

```mermaid
flowchart TB
    subgraph sources [Sources]
        SAMPLE[data/samples/msft-10k-fy2024.html]
        SEC[SEC EDGAR API + Archives]
    end

    subgraph L1 [Layer 1 — Ingestion]
        EF[edgar_fetcher]
        DP[document_parser]
        SC[section_chunker]
    end

    subgraph PG1 [Postgres staging]
        DOCS[(staging.documents)]
        CHUNKS[(staging.chunks)]
    end

    subgraph L2 [Layer 2 — Extraction]
        LLM[llm_extractor]
        LC[shared/llm_client]
    end

    subgraph PG2 [Postgres extraction]
        CLAIMS[(extraction.claims)]
    end

    subgraph L3 [Layer 3 — Reasoning]
        ER[entity_resolver]
        RE[reconciliation_engine]
        API[query_api]
    end

    subgraph PG3 [Postgres reasoning]
        ALIAS[(entity_aliases)]
        TRANS[(state_transitions)]
    end

    subgraph NEO [Neo4j]
        GRAPH[(Company Risk Capability Doctrine nodes)]
    end

    SAMPLE --> EF
    SEC --> EF
    EF --> DOCS
    EF --> RAW[data/raw/MSFT/*.html]
    DOCS --> DP
    RAW --> DP
    DP -->|clean text in memory| SC
    SC --> CHUNKS
    CHUNKS -->|SQL SELECT| LLM
    LLM --> LC
    LC -->|Anthropic/OpenAI or mock| LLM
    LLM --> CLAIMS
    CLAIMS --> ER
    ER --> ALIAS
    CLAIMS --> RE
    ALIAS --> RE
    RE --> GRAPH
    RE --> TRANS
    GRAPH --> API
    TRANS --> API
    CHUNKS --> API
```

---

## Step 0 — Two ways HTML enters the system

| Path | Command | EDGAR called? | HTML source |
|------|---------|---------------|-------------|
| **Sample (default)** | `pipeline.orchestrator --ticker MSFT` | No | `data/samples/msft-10k-fy2024.html` copied to `data/raw/` |
| **Live EDGAR** | `pipeline.orchestrator --edgar --ticker MSFT` | Yes | SEC Archives `.htm` download |

Both paths produce the **same Postgres row shape** in `staging.documents`. Everything after Step 1 is identical.

---

## Step 1 — `edgar_fetcher`

### Sample path (what you run locally)

**Service input:**

```python
ingest_from_local(
    doc_id="doc-msft-10k-fy2024-sample",
    company_ticker="MSFT",
    fiscal_period="FY2024",
    filing_date=date(2024, 7, 30),
    local_html_path=Path("data/samples/msft-10k-fy2024.html"),
)
```

**What it does:**

1. Copies sample HTML → `data/raw/MSFT/doc-msft-10k-fy2024-sample.html`
2. Inserts one row into **`staging.documents`**

**No HTTP call** in sample mode.

### Live EDGAR path (for comparison)

**What we send to SEC:**

| Call | Endpoint | Purpose |
|------|----------|---------|
| 1 | `GET https://data.sec.gov/submissions/CIK0000789019.json` | List filings; find latest `10-K` |
| 2 | `GET https://www.sec.gov/Archives/edgar/data/789019/.../msft-20240630.htm` | Download raw HTML |

**What SEC returns:**

| Call | Response | We store |
|------|----------|----------|
| Submissions JSON | `{ "filings": { "recent": { "form", "accessionNumber", "filingDate", "primaryDocument" } } }` | Used to build URL only (not kept) |
| Archives GET | Raw HTML bytes | `data/raw/MSFT/*.html` + `staging.documents` |

### Raw HTML received (our sample file)

```html
<h1>ITEM 1. BUSINESS</h1>
<p>Microsoft is a technology company... Our strategy is to build best-in-class
platforms for an intelligent cloud and intelligent edge infused with AI.</p>
<p>Azure is a comprehensive set of cloud services...</p>

<h1>ITEM 1A. RISK FACTORS</h1>
<p>Competition in cloud computing...</p>
<p>AI regulation. Our AI offerings may subject us to increased regulatory scrutiny...</p>

<h1>ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS</h1>
<p>Fiscal year 2024 revenue was $245.1 billion... Intelligent Cloud revenue
increased 20% to $87.9 billion... increased capital expenditures for AI infrastructure.</p>
```

### Postgres after Step 1 — `staging.documents`

| column | value |
|--------|-------|
| doc_id | `doc-msft-10k-fy2024-sample` |
| company_ticker | `MSFT` |
| company_cik | `0000789019` |
| doc_type | `10-K` |
| filing_date | `2024-07-30` |
| fiscal_period | `FY2024` |
| source_url | `local://sample` (or SEC URL if `--edgar`) |
| raw_format | `html` |
| raw_path | `data/raw/MSFT/doc-msft-10k-fy2024-sample.html` |

```sql
SELECT doc_id, company_ticker, fiscal_period, raw_path
FROM staging.documents
WHERE doc_id = 'doc-msft-10k-fy2024-sample';
```

**Handoff to next service:** `document_parser` reads `raw_path`.

---

## Step 2 — `document_parser`

### Service input

```python
doc = get_document("doc-msft-10k-fy2024-sample")
# doc["raw_path"] → data/raw/MSFT/doc-msft-10k-fy2024-sample.html
```

### What it expects

| Expects | Detail |
|---------|--------|
| File exists at `raw_path` | HTML or PDF |
| Valid encoding | UTF-8 HTML for sample |

### What it does

1. Read HTML from disk
2. `BeautifulSoup` removes `<script>`, `<style>`
3. `get_text()` → plain text with newlines
4. Collapse excessive blank lines

### Service output (in memory — **not saved to DB**)

```
ITEM 1. BUSINESS
Microsoft is a technology company focused on empowering every person and organization.
Our strategy is to build best-in-class platforms for an intelligent cloud and
intelligent edge infused with artificial intelligence (AI).
Azure is a comprehensive set of cloud services. We offer Microsoft Copilot across our products.

ITEM 1A. RISK FACTORS
Competition in cloud computing. We face intense competition from other cloud providers.
AI regulation. Our AI offerings may subject us to increased regulatory scrutiny,
including requirements in the European Union.

ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS
Fiscal year 2024 revenue was $245.1 billion, an increase of 16%.
Intelligent Cloud revenue increased 20% to $87.9 billion.
We expect increased capital expenditures for AI infrastructure.
```

**Handoff:** clean text string passed directly to `section_chunker`.

---

## Step 3 — `section_chunker`

### Service input

- Clean text from `document_parser`
- Metadata from `staging.documents` (ticker, fiscal_period, filing_date, source_url)

### What it does

1. Regex-scan for SEC section headers: `ITEM 1. BUSINESS`, `ITEM 1A. RISK FACTORS`, `ITEM 7. MD&A`
2. Slice text between headers → one chunk per section
3. Assign canonical `section_path` label
4. `INSERT` into **`staging.chunks`**

### Postgres after Step 3 — `staging.chunks` (3 rows)

#### Chunk A — Item 1

| column | value |
|--------|-------|
| chunk_id | `chk-a1b2c3d4e5f6` *(uuid in real run)* |
| doc_id | `doc-msft-10k-fy2024-sample` |
| company_ticker | `MSFT` |
| section_path | `Item 1 — Business` |
| fiscal_period_covered | `FY2024` |
| filing_date | `2024-07-30` |
| text | *"Microsoft is a technology company... Azure... Copilot..."* |

#### Chunk B — Item 1A

| column | value |
|--------|-------|
| section_path | `Item 1A — Risk Factors` |
| text | *"Competition in cloud computing... AI regulation... regulatory scrutiny..."* |

#### Chunk C — Item 7

| column | value |
|--------|-------|
| section_path | `Item 7 — MD&A` |
| text | *"Fiscal year 2024 revenue was $245.1 billion... Intelligent Cloud revenue increased 20% to $87.9 billion... capital expenditures..."* |

```sql
SELECT chunk_id, section_path, LEFT(text, 80) AS text_preview
FROM staging.chunks
WHERE doc_id = 'doc-msft-10k-fy2024-sample'
ORDER BY section_path;
```

```mermaid
flowchart LR
    HTML[Raw HTML file] --> PARSE[document_parser]
    PARSE --> TEXT[One clean text string]
    TEXT --> CHUNK[section_chunker]
    CHUNK --> C1[chk-... Item 1]
    CHUNK --> C2[chk-... Item 1A]
    CHUNK --> C3[chk-... Item 7]
    C1 --> PG[(staging.chunks)]
    C2 --> PG
    C3 --> PG
```

**Handoff to Layer 2:** `llm_extractor` runs SQL against `staging.chunks`.

---

## Step 4 — `llm_extractor` + `shared/llm_client`

### What the LLM reads (Postgres only — not Neo4j)

For each chunk, the service runs:

```sql
SELECT chunk_id, section_path, text, company_ticker,
       fiscal_period_covered, filing_date, source_url
FROM staging.chunks
WHERE doc_id = 'doc-msft-10k-fy2024-sample';
```

Then, **per section**, it picks object classes to extract:

| section_path | object classes extracted |
|--------------|-------------------------|
| Item 1 — Business | Doctrine, Capability |
| Item 1A — Risk Factors | Risk |
| Item 7 — MD&A | ActiveState, ActiveObligation, Doctrine |

### Example: what gets sent to the LLM (Chunk B / Item 1A)

**User message built by `llm_client.py`:**

```
Company: MSFT
Section: Item 1A — Risk Factors
Filing date: 2024-07-30
Fiscal period: FY2024
Extract object class: Risk

--- BEGIN SECTION TEXT ---
Competition in cloud computing. We face intense competition from other cloud providers.
AI regulation. Our AI offerings may subject us to increased regulatory scrutiny,
including requirements in the European Union.
--- END SECTION TEXT ---
```

**LLM returns (structured JSON via Anthropic tool use or OpenAI JSON schema):**

```json
{
  "claims": [
    {
      "risk_category": "competitive",
      "description": "We face intense competition from other cloud providers",
      "severity": "high"
    },
    {
      "risk_category": "regulatory",
      "description": "Our AI offerings may subject us to increased regulatory scrutiny, including requirements in the European Union",
      "severity": "high"
    }
  ]
}
```

With `--mock`, the same shapes are produced by regex rules instead of an API call.

### Postgres after Step 4 — `extraction.claims` (~8–10 rows for sample)

| claim_id | chunk_id | object_class | payload (abbrev) | stated_from | reconciliation_status |
|----------|----------|--------------|------------------|-------------|----------------------|
| clm-001 | chk-... Item 1A | Risk | competitive / cloud providers | 2024-07-30 | pending → merged |
| clm-002 | chk-... Item 1A | Risk | AI regulatory scrutiny | 2024-07-30 | pending → merged |
| clm-003 | chk-... Item 1 | Doctrine | AI and cloud strategy | 2024-07-30 | pending → merged |
| clm-004 | chk-... Item 1 | Capability | Azure | 2024-07-30 | pending → merged |
| clm-005 | chk-... Item 1 | Capability | Copilot | 2024-07-30 | pending → merged |
| clm-006 | chk-... Item 7 | ActiveState | Total revenue $245.1B +16% | 2024-07-30 | pending → merged |
| clm-007 | chk-... Item 7 | ActiveState | Intelligent Cloud $87.9B +20% | 2024-07-30 | pending → merged |
| clm-008 | chk-... Item 7 | ActiveObligation | capex for AI infrastructure | 2024-07-30 | pending → merged |

Example full row:

```json
{
  "claim_id": "clm-002",
  "chunk_id": "chk-b1a...",
  "company_ticker": "MSFT",
  "object_class": "Risk",
  "payload": {
    "risk_category": "regulatory",
    "description": "Our AI offerings may subject us to increased regulatory scrutiny...",
    "severity": "high"
  },
  "confidence": 0.92,
  "effective_from": "2023-07-01",
  "stated_from": "2024-07-30",
  "extraction_run_id": "run-abc123",
  "reconciliation_status": "pending"
}
```

```mermaid
sequenceDiagram
    participant PG as Postgres chunks
    participant LE as llm_extractor
    participant API as Anthropic/OpenAI
    participant CL as extraction.claims

    LE->>PG: SELECT chunks WHERE doc_id=...
    loop each chunk × object_class
        LE->>API: section text + Pydantic schema
        API-->>LE: JSON claims array
        LE->>CL: INSERT claim row + chunk_id
    end
```

**Important:** The LLM never reads Neo4j or prior enterprise state. It only sees **one chunk's text** at a time.

---

## Step 5 — `entity_resolver`

### Service input

Strings from claim payloads, e.g.:

- `"Azure"` → `capability:MSFT:azure`
- `"Our AI offerings may subject us to increased regulatory scrutiny..."` → `risk:MSFT:ai-regulation`

### Postgres — `reasoning.entity_aliases`

| alias_text | canonical_id | entity_type |
|------------|--------------|-------------|
| Azure | capability:MSFT:azure | capability |
| AI regulation... | risk:MSFT:ai-regulation | risk |

---

## Step 6 — `reconciliation_engine`

### Service input

```sql
SELECT c.*
FROM extraction.claims c
JOIN staging.chunks ch ON ch.chunk_id = c.chunk_id
WHERE ch.doc_id = 'doc-msft-10k-fy2024-sample'
  AND c.reconciliation_status = 'pending';
```

For each claim: compare to existing Neo4j node → apply policy → write graph + audit.

| object_class | policy | example outcome |
|--------------|--------|-----------------|
| Risk | append-only | `net_new` if first time |
| Doctrine | newer-wins | `supersede` if wording changed |
| Capability | newer-wins | MERGE Azure node |
| ActiveState | newer-wins | MERGE revenue snapshot |

### Postgres — `reasoning.state_transitions` (audit / trajectory)

| transition_id | canonical_object_id | transition_type | claim_id | chunk_id |
|---------------|---------------------|-----------------|----------|----------|
| st-001 | risk:MSFT:ai-regulation | net_new | clm-002 | chk-b1a... |
| st-002 | capability:MSFT:azure | net_new | clm-004 | chk-item1... |
| st-003 | state:MSFT:intelligent-cloud-revenue-fy2024 | net_new | clm-007 | chk-mdna... |

### Neo4j after Step 6 (simplified)

```cypher
(:Company {id: "entity:MSFT", ticker: "MSFT"})
  -[:HAS_RISK]->(:Risk {
      id: "risk:MSFT:ai-regulation",
      payload: "{\"risk_category\":\"regulatory\",...}",
      status: "active"
    })
  -[:OFFERS]->(:Capability {id: "capability:MSFT:azure", ...})
  -[:OFFERS]->(:Capability {id: "capability:MSFT:copilot", ...})
  -[:HAS_STATE]->(:ActiveState {id: "state:MSFT:intelligent-cloud-revenue-fy2024", ...})
  -[:HOLDS_DOCTRINE]->(:Doctrine {id: "doctrine:MSFT:ai-cloud-strategy", ...})
```

```mermaid
flowchart TB
    CLAIMS[(extraction.claims)]
    CLAIMS --> ER[entity_resolver]
    ER --> ALIAS[(entity_aliases)]
    CLAIMS --> RE[reconciliation_engine]
    RE --> NEO[(Neo4j graph)]
    RE --> AUDIT[(state_transitions)]
```

---

## Step 7 — `query_api` (read path — no LLM)

### Current risks

**Neo4j Cypher:**

```cypher
MATCH (c:Company {ticker: "MSFT"})-[:HAS_RISK]->(r:Risk)
WHERE r.status = "active"
RETURN r.id, r.payload
```

### Trajectory (Enterprise Trajectory — derived)

**Postgres SQL:**

```sql
SELECT stated_at, transition_type, new_value, chunk_id
FROM reasoning.state_transitions
WHERE company_ticker = 'MSFT'
  AND canonical_object_id = 'risk:MSFT:ai-regulation'
ORDER BY stated_at;
```

### Provenance ("why do we believe this?")

```sql
SELECT ch.section_path, ch.source_url, ch.filing_date, ch.text
FROM reasoning.state_transitions t
JOIN staging.chunks ch ON ch.chunk_id = t.chunk_id
WHERE t.canonical_object_id = 'risk:MSFT:ai-regulation'
ORDER BY t.stated_at DESC
LIMIT 1;
```

Returns: **Item 1A — Risk Factors**, filing date, link back to source, original paragraph text.

```mermaid
flowchart LR
    API[query_api]
    API --> NEO[Neo4j current state]
    API --> PG1[state_transitions]
    API --> PG2[staging.chunks provenance]
```

---

## Full pipeline in one view (sample file)

```
msft-10k-fy2024.html
        │
        ▼ edgar_fetcher (ingest_from_local)
        ├── data/raw/MSFT/doc-msft-10k-fy2024-sample.html
        └── staging.documents (1 row)
                │
                ▼ document_parser (reads raw_path)
                └── clean text string (memory)
                        │
                        ▼ section_chunker
                        └── staging.chunks (3 rows: Item 1, 1A, 7)
                                │
                                ▼ llm_extractor (SQL read chunks)
                                └── extraction.claims (~8 rows)
                                        │
                                        ▼ entity_resolver + reconciliation_engine
                                        ├── reasoning.entity_aliases
                                        ├── reasoning.state_transitions
                                        └── Neo4j (Company, Risks, Capabilities, …)
                                                │
                                                ▼ query_api
                                                └── JSON + citations
```

---

## Store cheat sheet

| Store | Written by | Read by | Contains |
|-------|------------|---------|----------|
| `data/raw/` | edgar_fetcher | document_parser | Original HTML file |
| `staging.documents` | edgar_fetcher | document_parser, query_api | Filing metadata + `raw_path` |
| `staging.chunks` | section_chunker | llm_extractor, query_api | Section text + provenance |
| `extraction.claims` | llm_extractor | reconciliation_engine | Typed facts from LLM |
| `reasoning.entity_aliases` | entity_resolver | reconciliation_engine | Name → canonical ID |
| `reasoning.state_transitions` | reconciliation_engine | query_api | Change history / trajectory |
| Neo4j | reconciliation_engine | query_api | Current enterprise graph |

---

## Run it and inspect each layer

```bash
docker compose up -d
pip install -e .
python scripts/init_db.py
python -m pipeline.orchestrator --ticker MSFT --mock

# Inspect Postgres
psql postgresql://fpr:fpr@localhost:5432/fpr -c "SELECT * FROM staging.documents"
psql postgresql://fpr:fpr@localhost:5432/fpr -c "SELECT chunk_id, section_path FROM staging.chunks"
psql postgresql://fpr:fpr@localhost:5432/fpr -c "SELECT claim_id, object_class, payload FROM extraction.claims"

# Inspect Neo4j Browser http://localhost:7474
# MATCH (c:Company {ticker:'MSFT'})-[r]->(n) RETURN c,r,n
```
