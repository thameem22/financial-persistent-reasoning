-- Financial Persistent Reasoning — Postgres init

CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS extraction;
CREATE SCHEMA IF NOT EXISTS reasoning;

CREATE TABLE IF NOT EXISTS staging.documents (
    doc_id              TEXT PRIMARY KEY,
    company_ticker      TEXT NOT NULL,
    company_cik         TEXT,
    doc_type            TEXT NOT NULL,
    filing_date         DATE NOT NULL,
    fiscal_period       TEXT NOT NULL,
    accession_number    TEXT,
    source_url          TEXT NOT NULL,
    raw_format          TEXT NOT NULL DEFAULT 'html',
    raw_path            TEXT,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS staging.chunks (
    chunk_id                TEXT PRIMARY KEY,
    doc_id                    TEXT NOT NULL REFERENCES staging.documents(doc_id),
    company_ticker            TEXT NOT NULL,
    section_path              TEXT NOT NULL,
    fiscal_period_covered     TEXT NOT NULL,
    filing_date               DATE NOT NULL,
    source_url                TEXT NOT NULL,
    text                      TEXT NOT NULL,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chunks_company_section
    ON staging.chunks (company_ticker, section_path, fiscal_period_covered);

CREATE TABLE IF NOT EXISTS extraction.claims (
    claim_id                TEXT PRIMARY KEY,
    chunk_id                TEXT NOT NULL REFERENCES staging.chunks(chunk_id),
    company_ticker          TEXT NOT NULL,
    object_class            TEXT NOT NULL,
    payload                 JSONB NOT NULL,
    confidence              NUMERIC(4,3),
    effective_from          DATE,
    effective_to            DATE,
    stated_from             DATE NOT NULL,
    stated_to               DATE,
    extraction_run_id       TEXT NOT NULL,
    reconciliation_status   TEXT NOT NULL DEFAULT 'pending',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_claims_pending
    ON extraction.claims (company_ticker, reconciliation_status);

CREATE TABLE IF NOT EXISTS reasoning.entity_aliases (
    alias_text          TEXT NOT NULL,
    canonical_id        TEXT NOT NULL,
    entity_type         TEXT NOT NULL,
    company_ticker      TEXT,
    PRIMARY KEY (alias_text, canonical_id)
);

CREATE TABLE IF NOT EXISTS reasoning.state_transitions (
    transition_id       TEXT PRIMARY KEY,
    company_ticker      TEXT NOT NULL,
    object_class        TEXT NOT NULL,
    canonical_object_id TEXT NOT NULL,
    transition_type     TEXT NOT NULL,
    old_value           JSONB,
    new_value           JSONB,
    claim_id            TEXT REFERENCES extraction.claims(claim_id),
    chunk_id            TEXT REFERENCES staging.chunks(chunk_id),
    stated_at           DATE NOT NULL,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    policy_applied      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transitions_trajectory
    ON reasoning.state_transitions (company_ticker, canonical_object_id, stated_at);
