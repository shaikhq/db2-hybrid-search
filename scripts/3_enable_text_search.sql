-- Enable Db2 Text Search and register OpenSearch as the keyword backend.
-- Run as the Db2 instance owner:  db2 -tvf scripts/3_enable_text_search.sql
-- Run once: SYSTS_CREATE_SERVER does not dedupe.

CONNECT TO SAMPLE;

-- Tablespace + enable (errors if already present/enabled — harmless).
CREATE TABLESPACE systoolspace;
CALL SYSPROC.SYSTS_ENABLE('en_US', ?);

-- Register OpenSearch (localhost:9200).
CALL SYSPROC.SYSTS_CREATE_SERVER('localhost', 9200, 'dummyuser:dummypassword', 'dummymasterkey2024', 'OPENSEARCH', 0, 2, 0, 'en_US', ?, ?);

SELECT SERVERID, CAST(HOST AS VARCHAR(40)) AS HOST, PORT
  FROM SYSIBMTS.TSSERVERS WHERE ENGINETYPE='OPENSEARCH';

CONNECT RESET;
