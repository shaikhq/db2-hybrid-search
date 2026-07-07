-- Load sample.chunks.csv into Db2 and build the text + vector indexes.
-- Run from repo root as the Db2 instance owner:  db2 -tvf scripts/4_ingest.sql
-- Prereqs: db2set DB2_VECTOR_INDEXING=YES -immediate (first run only), and the
-- local embedding server must be up: llama.cpp serving bge-small-en-v1.5 on
-- http://127.0.0.1:8085 (see scripts/serve_embeddings.sh). Drop the
-- model/embed/vector steps for lexical-only.

CONNECT TO SAMPLE;

-- Clean slate (index before table; errors are harmless on a fresh database).
CALL SYSPROC.SYSTS_DROP('MYSCHEMA', 'CHUNKS_TEXT_IDX', 'en_US', ?);
DROP TABLE MYSCHEMA.CHUNKS;

-- Table + rows (SKIPCOUNT skips the header; delprioritychar keeps quoted newlines).
CREATE TABLE MYSCHEMA.CHUNKS (chunk_id INTEGER NOT NULL PRIMARY KEY, chunk_text CLOB(1M));
IMPORT FROM sample.chunks.csv OF DEL MODIFIED BY delprioritychar SKIPCOUNT 1 INSERT INTO MYSCHEMA.CHUNKS;

-- Text-search index (create, then populate).
CALL SYSPROC.SYSTS_CREATE('MYSCHEMA', 'CHUNKS_TEXT_IDX', 'MYSCHEMA.CHUNKS(CHUNK_TEXT)', 'SERVERID 1', 'en_US', ?);
CALL SYSPROC.SYSTS_UPDATE('MYSCHEMA', 'CHUNKS_TEXT_IDX', '', 'en_US', ?);

-- Embedding model: local llama.cpp (bge-small-en-v1.5), OpenAI-compatible endpoint.
-- PROVIDER OPENAI takes no PROJECT_ID; KEY is a dummy (the local server has no auth).
DROP EXTERNAL MODEL MYSCHEMA.CHUNKS_EMBED;
CREATE EXTERNAL MODEL MYSCHEMA.CHUNKS_EMBED PROVIDER OPENAI
  ID 'bge-small-en-v1.5'
  URL 'http://127.0.0.1:8085/v1/embeddings'
  TYPE TEXT_EMBEDDING RETURNING VECTOR(384, FLOAT32)
  KEY 'sk-noauth';

-- Embed each chunk.
ALTER TABLE MYSCHEMA.CHUNKS ADD COLUMN embedding VECTOR(384, FLOAT32);
UPDATE MYSCHEMA.CHUNKS SET embedding = TO_EMBEDDING(chunk_text USING MYSCHEMA.CHUNKS_EMBED);

-- Vector index (last — it makes the table read-only).
CREATE VECTOR INDEX MYSCHEMA.CHUNKS_VEC_IDX ON MYSCHEMA.CHUNKS(embedding) WITH DISTANCE COSINE EXCLUDE NULL KEYS;
CALL SYSPROC.ADMIN_CMD('RUNSTATS ON TABLE MYSCHEMA.CHUNKS AND INDEXES ALL');

CONNECT RESET;
