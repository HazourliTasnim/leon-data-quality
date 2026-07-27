-- Snowflake DDL for Semantic YAML Tool Registry
-- Run these statements in your Snowflake account to enable YAML persistence

-- ============================================================================
-- Schema Creation
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS SEMANTIC_CONFIG;

-- ============================================================================
-- Registry Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS SEMANTIC_CONFIG.SEMANTIC_VIEW (
    VIEW_ID INTEGER AUTOINCREMENT,
    NAME STRING NOT NULL,
    VERSION INTEGER DEFAULT 1,
    SOURCE_DB STRING NOT NULL,
    SOURCE_SCHEMA STRING NOT NULL,
    SOURCE_TABLE STRING NOT NULL,
    TARGET_DB STRING NOT NULL,
    TARGET_SCHEMA STRING NOT NULL,
    TARGET_VIEW STRING NOT NULL,
    YAML_DEFINITION STRING NOT NULL,
    STATUS STRING DEFAULT 'DRAFT',
    CREATED_BY STRING DEFAULT CURRENT_USER(),
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (VIEW_ID)
);

-- ============================================================================
-- Stored Procedure for AI-based YAML Generation (using Cortex)
-- ============================================================================
CREATE OR REPLACE PROCEDURE SEMANTIC_CONFIG.SP_GENERATE_SEMANTIC_YAML(
    P_DATABASE STRING,
    P_SCHEMA STRING,
    P_TABLE STRING
)
RETURNS STRING
LANGUAGE SQL
AS
$$
DECLARE
    v_columns STRING;
    v_prompt STRING;
    v_result STRING;
    v_yaml STRING;
BEGIN
    -- Get column metadata as a formatted list
    SELECT LISTAGG(
        COLUMN_NAME || ' (' || DATA_TYPE ||
        CASE WHEN COMMENT IS NOT NULL THEN ', comment: ' || COMMENT ELSE '' END || ')',
        '; '
    ) WITHIN GROUP (ORDER BY ORDINAL_POSITION)
    INTO v_columns
    FROM IDENTIFIER(P_DATABASE || '.INFORMATION_SCHEMA.COLUMNS')
    WHERE TABLE_SCHEMA = P_SCHEMA AND TABLE_NAME = P_TABLE;

    -- Build prompt for Cortex
    v_prompt := '
You are a data modeling expert. Generate a semantic YAML definition for the following Snowflake table.

Table: ' || P_DATABASE || '.' || P_SCHEMA || '.' || P_TABLE || '
Columns: ' || v_columns || '

Generate YAML in exactly this format (no extra text, just the YAML):

semantic_view:
  name: SV_' || P_TABLE || '
  version: 1
  source:
    database: ' || P_DATABASE || '
    schema: ' || P_SCHEMA || '
    table: ' || P_TABLE || '
  target:
    database: SEMANTIC
    schema: ' || P_SCHEMA || '
    view_name: SV_' || P_TABLE || '
  description: "<generate a meaningful description>"
  grain: "row"
  primary_key: [<infer from column names>]
  columns:
    <for each column, generate>:
    - name: <column_name>
      label: "<Title Case Label>"
      data_type: "<snowflake type>"
      role: "<dimension or measure>"
      logical_type: "<identifier/date/category/text/number>"
      description: "<meaningful description>"
  metrics: []

Rules:
- role should be "measure" for numeric columns representing quantities, amounts, counts
- role should be "dimension" for all other columns
- logical_type should match the semantic meaning (identifier for IDs, date for dates, etc.)
- Generate meaningful descriptions based on column names
';

    -- Call Cortex AI
    SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large', v_prompt) INTO v_result;

    -- Clean up result (remove markdown code blocks if present)
    v_yaml := REGEXP_REPLACE(v_result, '^```ya?ml?\\n?', '');
    v_yaml := REGEXP_REPLACE(v_yaml, '\\n?```$', '');

    RETURN v_yaml;
END;
$$;

-- ============================================================================
-- Helper View: List all semantic views
-- ============================================================================
CREATE OR REPLACE VIEW SEMANTIC_CONFIG.V_SEMANTIC_VIEWS AS
SELECT
    VIEW_ID,
    NAME,
    VERSION,
    SOURCE_DB || '.' || SOURCE_SCHEMA || '.' || SOURCE_TABLE AS SOURCE_TABLE_FULL,
    TARGET_DB || '.' || TARGET_SCHEMA || '.' || TARGET_VIEW AS TARGET_VIEW_FULL,
    STATUS,
    CREATED_BY,
    CREATED_AT,
    UPDATED_AT
FROM SEMANTIC_CONFIG.SEMANTIC_VIEW
ORDER BY UPDATED_AT DESC;

-- ============================================================================
-- Grant permissions (adjust role as needed)
-- ============================================================================
-- GRANT USAGE ON SCHEMA SEMANTIC_CONFIG TO ROLE ANALYST;
-- GRANT SELECT, INSERT, UPDATE ON TABLE SEMANTIC_CONFIG.SEMANTIC_VIEW TO ROLE ANALYST;
-- GRANT USAGE ON PROCEDURE SEMANTIC_CONFIG.SP_GENERATE_SEMANTIC_YAML(STRING, STRING, STRING) TO ROLE ANALYST;
-- GRANT SELECT ON VIEW SEMANTIC_CONFIG.V_SEMANTIC_VIEWS TO ROLE ANALYST;
