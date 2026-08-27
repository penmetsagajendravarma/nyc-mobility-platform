CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS intermediate;
CREATE SCHEMA IF NOT EXISTS marts;
CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta.ingestion_log (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT        NOT NULL,
    file_key        TEXT        NOT NULL,
    rows_read       BIGINT,
    rows_loaded     BIGINT,
    rows_rejected   BIGINT,
    status          TEXT        NOT NULL,
    error_message   TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    CONSTRAINT uq_source_file UNIQUE (source, file_key)
);
