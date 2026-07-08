-- Hybrid search demo (for testing) — runs the three legs for one hardcoded query.
-- Run as the Db2 instance owner:  db2 -tvf scripts/2_search.sql
-- To search something else, replace the query text in all three statements: the
-- raw form (vector leg) and the 'word OR word ...' form (keyword leg).
-- Knobs are inlined: POOL 50, weights 0.5/0.5, vector gate 0.30, lexical gate 0.

CONNECT TO SAMPLE;

-- Lexical leg (BM25).
SELECT chunk_id, SCORE(chunk_text, 'what OR privilege OR do OR I OR need OR to OR call OR TO_EMBEDDING') AS bm25,
       CAST(SUBSTR(chunk_text, 1, 70) AS VARCHAR(70)) AS snippet
FROM MYSCHEMA.CHUNKS
WHERE CONTAINS(chunk_text, 'what OR privilege OR do OR I OR need OR to OR call OR TO_EMBEDDING') = 1
ORDER BY bm25 DESC FETCH FIRST 5 ROWS ONLY;

-- Vector leg (cosine similarity over the query embedding).
WITH q (qv) AS (VALUES TO_EMBEDDING('what privilege do I need to call TO_EMBEDDING' USING MYSCHEMA.CHUNKS_EMBED))
SELECT c.chunk_id, (1 - VECTOR_DISTANCE(c.embedding, q.qv, COSINE)) AS cosine_sim,
       CAST(SUBSTR(c.chunk_text, 1, 70) AS VARCHAR(70)) AS snippet
FROM MYSCHEMA.CHUNKS c, q
ORDER BY VECTOR_DISTANCE(c.embedding, q.qv, COSINE)
FETCH APPROX FIRST 5 ROWS ONLY;

-- Hybrid leg: gate + max-normalize each leg, then weighted sum (one query).
WITH
q (qv) AS (VALUES TO_EMBEDDING('what privilege do I need to call TO_EMBEDDING' USING MYSCHEMA.CHUNKS_EMBED)),
lex0 AS (
  SELECT chunk_id, SCORE(chunk_text, 'what OR privilege OR do OR I OR need OR to OR call OR TO_EMBEDDING') AS s
  FROM MYSCHEMA.CHUNKS
  WHERE CONTAINS(chunk_text, 'what OR privilege OR do OR I OR need OR to OR call OR TO_EMBEDDING') = 1
  ORDER BY s DESC FETCH FIRST 50 ROWS ONLY),
vec0 AS (
  SELECT c.chunk_id, (1 - VECTOR_DISTANCE(c.embedding, q.qv, COSINE)) AS s
  FROM MYSCHEMA.CHUNKS c, q
  ORDER BY VECTOR_DISTANCE(c.embedding, q.qv, COSINE) FETCH APPROX FIRST 50 ROWS ONLY),
lex AS (SELECT chunk_id, CASE WHEN MAX(s) OVER () < 0.0 THEN 0 ELSE s / MAX(s) OVER () END AS n FROM lex0),
vec AS (SELECT chunk_id, CASE WHEN MAX(s) OVER () < 0.30 THEN 0 ELSE s / MAX(s) OVER () END AS n FROM vec0),
fused AS (
  SELECT COALESCE(lex.chunk_id, vec.chunk_id) AS chunk_id,
         0.5 * COALESCE(lex.n, 0) + 0.5 * COALESCE(vec.n, 0) AS score
  FROM lex FULL OUTER JOIN vec ON lex.chunk_id = vec.chunk_id)
SELECT f.chunk_id, f.score,
       CAST(SUBSTR(c.chunk_text, 1, 70) AS VARCHAR(70)) AS snippet
FROM fused f JOIN MYSCHEMA.CHUNKS c ON c.chunk_id = f.chunk_id
ORDER BY f.score DESC, f.chunk_id ASC FETCH FIRST 5 ROWS ONLY;

CONNECT RESET;
