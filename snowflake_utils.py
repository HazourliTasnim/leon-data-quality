"""
Snowflake connection and utility functions for the Semantic YAML Tool.
"""

import re
from typing import Optional, List, Dict, Any
import snowflake.connector
from snowflake.connector import SnowflakeConnection


def _convert_row_to_dict(row) -> dict:
    """
    Convert a Snowflake Row object to a dictionary.
    Handles both snowflake.connector.cursor.RowType and regular tuples.
    """
    if hasattr(row, 'as_dict'):
        # Snowflake Row object with as_dict method
        return row.as_dict()
    elif hasattr(row, '__getitem__') and hasattr(row, '_fields'):
        # namedtuple-like object
        return dict(zip(row._fields, row))
    elif isinstance(row, dict):
        # Already a dictionary
        return row
    else:
        # Try to convert to dict generically
        try:
            return dict(row)
        except (TypeError, ValueError):
            # If all else fails, return as is
            return {"_raw_data": str(row)}


def parse_account_from_url(url: str) -> str:
    """
    Extract account identifier from Snowflake URL.

    Examples:
        https://mycompany.eu-central-1.snowflakecomputing.com -> mycompany.eu-central-1
        https://abc123.us-east-1.snowflakecomputing.com -> abc123.us-east-1
        mycompany.eu-central-1.snowflakecomputing.com -> mycompany.eu-central-1
    """
    url = url.strip()
    # Remove protocol if present
    url = re.sub(r'^https?://', '', url)
    # Remove trailing slash
    url = url.rstrip('/')
    # Remove .snowflakecomputing.com suffix
    account = re.sub(r'\.snowflakecomputing\.com$', '', url, flags=re.IGNORECASE)
    return account


def get_connection_from_params(
    snowflake_url: str,
    user: str,
    warehouse: Optional[str] = None,
    role: Optional[str] = None,
    database: Optional[str] = None,
    schema: Optional[str] = None,
) -> SnowflakeConnection:
    """
    Create a Snowflake connection using externalbrowser SSO authentication.
    All parameters except URL and user are optional.
    """
    account = parse_account_from_url(snowflake_url)

    conn_params = {
        "account": account,
        "user": user,
        "authenticator": "externalbrowser",
    }

    if warehouse:
        conn_params["warehouse"] = warehouse
    if role:
        conn_params["role"] = role
    if database:
        conn_params["database"] = database
    if schema:
        conn_params["schema"] = schema

    return snowflake.connector.connect(**conn_params)


def list_warehouses(conn: SnowflakeConnection) -> List[str]:
    """List all accessible warehouses."""
    cursor = conn.cursor()
    try:
        cursor.execute("SHOW WAREHOUSES")
        return [row[0] for row in cursor.fetchall()]
    finally:
        cursor.close()


def list_roles(conn: SnowflakeConnection) -> List[str]:
    """List all accessible roles."""
    cursor = conn.cursor()
    try:
        cursor.execute("SHOW ROLES")
        return [row[1] for row in cursor.fetchall()]
    finally:
        cursor.close()


def use_warehouse(conn: SnowflakeConnection, warehouse: str) -> None:
    """Set the current warehouse."""
    cursor = conn.cursor()
    try:
        cursor.execute(f'USE WAREHOUSE "{warehouse}"')
    finally:
        cursor.close()


def use_role(conn: SnowflakeConnection, role: str) -> None:
    """Set the current role."""
    cursor = conn.cursor()
    try:
        cursor.execute(f'USE ROLE "{role}"')
    finally:
        cursor.close()


def use_database(conn: SnowflakeConnection, database: str) -> None:
    """Set the current database."""
    cursor = conn.cursor()
    try:
        cursor.execute(f'USE DATABASE "{database}"')
    finally:
        cursor.close()


def use_schema(conn: SnowflakeConnection, schema: str) -> None:
    """Set the current schema."""
    cursor = conn.cursor()
    try:
        cursor.execute(f'USE SCHEMA "{schema}"')
    finally:
        cursor.close()


def list_databases(conn: SnowflakeConnection) -> List[str]:
    """List all accessible databases."""
    cursor = conn.cursor()
    try:
        cursor.execute("SHOW DATABASES")
        return [row[1] for row in cursor.fetchall()]
    finally:
        cursor.close()


def list_schemas(conn: SnowflakeConnection, database: str) -> List[str]:
    """List all schemas in a database."""
    cursor = conn.cursor()
    try:
        cursor.execute(f"SHOW SCHEMAS IN DATABASE \"{database}\"")
        return [row[1] for row in cursor.fetchall()]
    finally:
        cursor.close()


def list_tables(conn: SnowflakeConnection, database: str, schema: str) -> List[str]:
    """List all tables in a schema."""
    cursor = conn.cursor()
    try:
        cursor.execute(f"SHOW TABLES IN \"{database}\".\"{schema}\"")
        return [row[1] for row in cursor.fetchall()]
    finally:
        cursor.close()


def get_columns(
    conn: SnowflakeConnection,
    database: str,
    schema: str,
    table: str
) -> List[Dict[str, Any]]:
    """
    Get column metadata for a table using INFORMATION_SCHEMA.

    Returns list of dicts with: column_name, data_type, is_nullable, ordinal_position
    """
    cursor = conn.cursor()
    try:
        query = f"""
        SELECT
            COLUMN_NAME,
            DATA_TYPE,
            IS_NULLABLE,
            ORDINAL_POSITION,
            CHARACTER_MAXIMUM_LENGTH,
            NUMERIC_PRECISION,
            NUMERIC_SCALE,
            COLUMN_DEFAULT,
            COMMENT
        FROM "{database}".INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = '{schema}'
          AND TABLE_NAME = '{table}'
        ORDER BY ORDINAL_POSITION
        """
        cursor.execute(query)
        columns = []
        for row in cursor.fetchall():
            columns.append({
                "column_name": row[0],
                "data_type": row[1],
                "is_nullable": row[2],
                "ordinal_position": row[3],
                "char_max_length": row[4],
                "numeric_precision": row[5],
                "numeric_scale": row[6],
                "column_default": row[7],
                "comment": row[8],
            })
        return columns
    finally:
        cursor.close()


def get_primary_keys(
    conn: SnowflakeConnection,
    database: str,
    schema: str,
    table: str
) -> List[str]:
    """Get primary key columns for a table."""
    cursor = conn.cursor()
    try:
        cursor.execute(f"SHOW PRIMARY KEYS IN \"{database}\".\"{schema}\".\"{table}\"")
        return [row[4] for row in cursor.fetchall()]  # column_name is at index 4
    except Exception:
        return []
    finally:
        cursor.close()


def generate_semantic_yaml_with_cortex(
    conn: SnowflakeConnection,
    database: str,
    schema: str,
    table: str,
    model: str = "mistral-large",
    dq_columns: List[str] = None,
    source_system: str = "GENERIC",
    business_domain: Optional[str] = None,
    entity_type: Optional[str] = None,
    view_name: Optional[str] = None,
    description: Optional[str] = None,
    sample_values: Optional[dict] = None,
    view_level_filters: Optional[List[str]] = None
) -> str:
    """
    Generate semantic YAML using Snowflake Cortex AI directly.
    For large tables (>20 columns), generates base YAML locally and uses Cortex only for DQ rules.

    Args:
        dq_columns: List of column names to generate DQ rules for.
        source_system: Source system identifier (e.g., SAP_SD, SFDC)
        business_domain: Business domain (e.g., Sales, Finance)
        entity_type: Entity type (e.g., SalesOrderHeader, Customer)
        view_name: Optional view name (defaults to schema_table)
        description: Optional view description
        sample_values: Optional dict mapping column names to lists of sample values
    """
    import yaml as yaml_module
    from doc_snippets import build_context_prompt

    # Suggest entity type if not provided
    if not entity_type:
        entity_type = suggest_entity_type(table)

    # Default view name if not provided
    if not view_name:
        view_name = f"{schema.lower()}_{table.lower()}"

    cursor = conn.cursor()
    try:
        # Step 1: Fetch column metadata
        col_query = f'''
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
            FROM "{database}".INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        '''
        cursor.execute(col_query, (schema, table))
        columns = cursor.fetchall()

        if not columns:
            raise ValueError(f"No columns found for {database}.{schema}.{table}")

        num_columns = len(columns)

        # For large tables: hybrid approach - local YAML + Cortex for DQ rules only
        if num_columns > 20:
            return _generate_large_table_yaml(
                cursor, database, schema, table, columns, dq_columns, model,
                source_system, business_domain, entity_type, view_name, description,
                sample_values, view_level_filters
            )

        # Build context from documentation
        context = build_context_prompt(source_system, entity_type, business_domain)

        # For small/medium tables: full Cortex generation
        # Build column descriptions with sample values if available
        col_desc_lines = []
        for row in columns:
            col_name = row[0]
            col_type = row[1]
            nullable = 'NOT NULL' if row[2] == 'NO' else 'NULL'

            # Add sample values if provided
            if sample_values and col_name in sample_values and sample_values[col_name]:
                samples_str = ", ".join([str(v) for v in sample_values[col_name][:5]])
                col_desc_lines.append(f"- {col_name}: {col_type}, {nullable} [Samples: {samples_str}]")
            else:
                col_desc_lines.append(f"- {col_name}: {col_type}, {nullable}")

        col_desc = "\n".join(col_desc_lines)

        if num_columns <= 10:
            # Small tables: full AI generation with DQ rules
            desc_instruction = f'  description: "{description}"' if description else '  description: "Write a detailed business description here"'
            
            biz_domain_line = f"- Business Domain: {business_domain}" if business_domain else ""
            entity_type_line = f"- Entity Type: {entity_type}" if entity_type else ""
            biz_domain_yaml = f"  business_domain: {business_domain}" if business_domain else ""
            entity_type_yaml = f"  entity_type: {entity_type}" if entity_type else ""
            context_text = context if context else "No specific documentation available for this source system/entity type."
            sample_note = "and actual sample values" if sample_values else ""
            sample_usage = "- USE the sample values [Samples: ...] to understand the data format and patterns" if sample_values else ""
            
            desc_or_generate = "Use the provided description" if description else "Generate a BUSINESS-FRIENDLY table description (2-3 sentences) that explains:"
            col_instructions = "" if description else "- What business process or entity this table represents\n   - What key information it contains\n   - How it's typically used\n   - DO NOT just repeat column names or say 'contains data'"

            prompt = f'''You are a data quality expert creating a semantic YAML definition for a Snowflake table.

**Table Information:**
- Table: {database}.{schema}.{table}
- Source System: {source_system}
{biz_domain_line}
{entity_type_line}

**Context & Documentation:**
{context_text}

**Columns:**
{col_desc}

**Instructions:**
1. {desc_or_generate}
   {col_instructions}

2. For each column, write a MEANINGFUL description that explains:
   - The business purpose of the column
   - What the values represent in business terms
   - Any important constraints or patterns
   - NOT just "Column name field" - explain what it actually means!
   {sample_usage}

3. Generate appropriate DQ rules based on the source system and business context {sample_note}.

Return ONLY valid YAML (no markdown, no code blocks):

semantic_view:
  name: {view_name}
  version: 1
  source_system: {source_system}
{biz_domain_yaml}
{entity_type_yaml}
  source:
    database: {database}
    schema: {schema}
    table: {table}
  target:
    database: SEMANTIC
    schema: {schema}
    view_name: {view_name}
{desc_instruction}
  grain: "row"
  primary_key: []
  columns:
    - name: COLUMN_NAME
      label: "Title Case label"
      data_type: "Snowflake type"
      role: "dimension or measure"
      logical_type: "identifier/date/number/text/category"
      description: "Write meaningful business description"
      dq_rules:
        - id: "column_name_ruletype"
          type: "NOT_NULL|UNIQUE|MIN_VALUE|MAX_VALUE|PATTERN|FOREIGN_KEY|LOOKUP"
          severity: "CRITICAL/WARNING/INFO"
          description: "Explain why this rule is important for data quality"
          lambda_hint: "SQL expression like COLUMN_NAME IS NOT NULL"
          params: null or key_value_pairs
  metrics: []

Return ONLY the YAML, no extra text.'''
        else:
            # Medium tables (11-20): generate with selected DQ columns
            dq_instruction = f"Generate DQ rules ONLY for: {', '.join(dq_columns)}. Other columns: dq_rules: []" if dq_columns else "Set dq_rules: [] for all columns."
            desc_instruction = f'  description: "{description}"' if description else '  description: "Write detailed business description"'
            
            biz_domain_line = f"- Business Domain: {business_domain}" if business_domain else ""
            entity_type_line = f"- Entity Type: {entity_type}" if entity_type else ""
            biz_domain_yaml = f"  business_domain: {business_domain}" if business_domain else ""
            entity_type_yaml = f"  entity_type: {entity_type}" if entity_type else ""
            context_text = context if context else "No specific documentation available."

            prompt = f'''You are a data quality expert creating a semantic YAML definition for a Snowflake table.

**Table Information:**
- Table: {database}.{schema}.{table}
- Source System: {source_system}
{biz_domain_line}
{entity_type_line}

**Context & Documentation:**
{context_text}

**Columns:**
{col_desc}

**Instructions:**
1. {"Use the provided description" if description else "Generate a BUSINESS-FRIENDLY table description (2-3 sentences) explaining what this table represents and its business purpose."}
2. For each column, write a MEANINGFUL description explaining its business purpose (not just "field name").
3. {dq_instruction}

Return ONLY valid YAML (no markdown, no code blocks):

semantic_view:
  name: {view_name}
  version: 1
  source_system: {source_system}
{biz_domain_yaml}
{entity_type_yaml}
  source:
    database: {database}
    schema: {schema}
    table: {table}
  target:
    database: SEMANTIC
    schema: {schema}
    view_name: {view_name}
{desc_instruction}
  grain: "row"
  primary_key: []
  columns:
    - name: COLUMN_NAME
      label: "Title Case"
      data_type: "type"
      role: "dimension or measure"
      logical_type: "identifier/date/number/text/category"
      description: "Write meaningful business description"
      dq_rules:
        - id: "column_name_ruletype"
          type: "NOT_NULL"
          severity: "CRITICAL"
          description: "Why this rule matters"
          lambda_hint: "COLUMN_NAME IS NOT NULL"
          params: null
  metrics: []

Include ALL {num_columns} columns. For DQ rules, ALWAYS include id, type, severity, description, lambda_hint, and params fields. Return ONLY YAML.'''

        # Call Cortex
        cortex_sql = "SELECT SNOWFLAKE.CORTEX.COMPLETE(%s, %s)"
        cursor.execute(cortex_sql, (model, prompt))
        result = cursor.fetchone()

        if not result or not result[0]:
            raise ValueError("Cortex returned empty response")

        yaml_text = result[0].strip()

        # Clean up markdown code blocks if present
        if yaml_text.startswith("```"):
            lines = yaml_text.split("\n")
            if lines[-1].strip() == "```":
                yaml_text = "\n".join(lines[1:-1])
            else:
                yaml_text = "\n".join(lines[1:])

        # Fix any missing fields (like lambda_hint in DQ rules)
        from semantic_yaml_spec import auto_fix_yaml
        yaml_text = auto_fix_yaml(yaml_text)

        # Add sample values to each column in the YAML
        # Check if we have any sample values or filters to add
        has_samples = sample_values and any(sample_values.values())
        has_filters = view_level_filters and len(view_level_filters) > 0

        if has_samples or has_filters:
            parsed = yaml_module.safe_load(yaml_text)
            if parsed and "semantic_view" in parsed:
                # Add sample values to columns
                if sample_values:
                    columns_list = parsed["semantic_view"].get("columns", [])
                    for col in columns_list:
                        col_name = col.get("name")
                        if col_name and col_name in sample_values and sample_values[col_name]:
                            col["sample_values"] = sample_values[col_name]

                # Add view-level filters
                if view_level_filters:
                    parsed["semantic_view"]["filters"] = view_level_filters

                # Convert back to YAML
                yaml_text = yaml_module.dump(parsed, default_flow_style=False, sort_keys=False, allow_unicode=True)

        return yaml_text

    finally:
        cursor.close()


def _generate_large_table_yaml(
    cursor,
    database: str,
    schema: str,
    table: str,
    columns: list,
    dq_columns: List[str],
    model: str,
    source_system: str = "GENERIC",
    business_domain: Optional[str] = None,
    entity_type: Optional[str] = None,
    view_name: Optional[str] = None,
    description: Optional[str] = None,
    sample_values: Optional[dict] = None,
    view_level_filters: Optional[List[str]] = None
) -> str:
    """
    Generate YAML for large tables (>20 columns) using hybrid approach:
    1. Generate base YAML locally (all columns)
    2. Use Cortex for table & column descriptions
    3. Apply rule packs and use Cortex for DQ rules on selected columns
    4. Merge results
    """
    import yaml as yaml_module
    from doc_snippets import build_context_prompt
    import json

    # Suggest entity type if not provided
    if not entity_type:
        entity_type = suggest_entity_type(table)

    # Default view name if not provided
    if not view_name:
        view_name = f"{schema.lower()}_{table.lower()}"

    # Build context
    context = build_context_prompt(source_system, entity_type, business_domain)

    # Use provided description or generate one via AI
    if description:
        table_description = description
    else:
        # Build column summary for first 20 columns (for AI context)
        col_summary = []
        for i, row in enumerate(columns[:20]):
            col_name, data_type, is_nullable = row[0], row[1], row[2]
            col_summary.append(f"{col_name} ({data_type})")

        col_summary_text = ", ".join(col_summary)
        if len(columns) > 20:
            col_summary_text += f" ... and {len(columns) - 20} more columns"

        # Use Cortex to generate table description
        desc_prompt = f'''Generate a business-friendly description for this table.

Table: {database}.{schema}.{table}
Source System: {source_system}
{f"Business Domain: {business_domain}" if business_domain else ""}
{f"Entity Type: {entity_type}" if entity_type else ""}

Context:
{context if context else "Generic table"}

Columns: {col_summary_text}

Write a 2-3 sentence business description explaining what this table represents, what it contains, and how it's used. Be specific and meaningful, not generic.

Return ONLY the description text, no extra formatting.'''

        try:
            cursor.execute("SELECT SNOWFLAKE.CORTEX.COMPLETE(%s, %s)", (model, desc_prompt))
            desc_result = cursor.fetchone()
            table_description = desc_result[0].strip() if desc_result and desc_result[0] else f"Semantic view for {table} table"
        except:
            table_description = f"Semantic view for {table} table containing {len(columns)} columns"

    # Build base YAML structure locally
    base_columns = []
    for row in columns:
        col_name, data_type, is_nullable = row[0], row[1], row[2]

        # Infer role and logical_type
        role = "measure" if data_type in ("NUMBER", "FLOAT", "DECIMAL", "DOUBLE", "INTEGER", "BIGINT") and not col_name.endswith("_ID") else "dimension"
        if "_ID" in col_name or col_name.endswith("ID"):
            logical_type = "identifier"
        elif "DATE" in data_type or "TIME" in data_type:
            logical_type = "date"
        elif data_type in ("NUMBER", "FLOAT", "DECIMAL", "DOUBLE", "INTEGER", "BIGINT"):
            logical_type = "number"
        elif "BOOL" in data_type:
            logical_type = "category"
        else:
            logical_type = "text"

        # Create label from column name
        label = col_name.replace("_", " ").title()

        # Generate better column description
        col_desc = f"{label} field"
        # Add context-aware hints
        if "_id" in col_name.lower() or col_name.lower().endswith("id"):
            col_desc = f"Unique identifier for {label.lower()}"
        elif "date" in col_name.lower() or "time" in col_name.lower():
            col_desc = f"Date/time when {label.lower()} occurred"
        elif "amount" in col_name.lower() or "value" in col_name.lower() or "price" in col_name.lower():
            col_desc = f"Monetary value representing {label.lower()}"
        elif "name" in col_name.lower():
            col_desc = f"Name or label for {label.lower()}"
        elif "status" in col_name.lower() or "state" in col_name.lower():
            col_desc = f"Current status or state of {label.lower()}"

        base_columns.append({
            "name": col_name,
            "label": label,
            "data_type": data_type,
            "role": role,
            "logical_type": logical_type,
            "description": col_desc,
            "dq_rules": []
        })

    base_yaml = {
        "semantic_view": {
            "name": view_name,
            "version": 1,
            "source_system": source_system,
            "source": {
                "database": database,
                "schema": schema,
                "table": table
            },
            "target": {
                "database": "SEMANTIC",
                "schema": schema,
                "view_name": view_name
            },
            "description": table_description,
            "grain": "row",
            "primary_key": [],
            "columns": base_columns,
            "metrics": []
        }
    }

    # Add optional metadata fields
    if business_domain:
        base_yaml["semantic_view"]["business_domain"] = business_domain
    if entity_type:
        base_yaml["semantic_view"]["entity_type"] = entity_type

    # Add view-level filters if provided
    if view_level_filters:
        base_yaml["semantic_view"]["filters"] = view_level_filters

    # If DQ columns specified, apply rule packs + use Cortex for refinement
    if dq_columns and len(dq_columns) > 0:
        # Filter base_columns to only include selected DQ columns
        selected_columns_for_rules = [col for col in base_columns if col.get("name") in dq_columns]
        
        # Apply rule packs only to selected columns
        rule_pack_rules = apply_rule_packs_to_columns(
            selected_columns_for_rules,
            source_system,
            entity_type,
            business_domain
        )

        # Use Cortex for additional/refined rules (pass base_columns for descriptions)
        dq_rules_map = _generate_dq_rules_only(cursor, dq_columns, columns, model, base_columns)

        # Merge DQ rules into base YAML
        for col in base_yaml["semantic_view"]["columns"]:
            col_name = col["name"]
            col_rules = []

            # Add rule pack rules
            if col_name in rule_pack_rules:
                col_rules.extend(rule_pack_rules[col_name])

            # Add Cortex rules (avoid duplicates)
            if col_name in dq_rules_map:
                existing_types = [r.get("type") for r in col_rules]
                for cortex_rule in dq_rules_map[col_name]:
                    if cortex_rule.get("type") not in existing_types:
                        col_rules.append(cortex_rule)

            col["dq_rules"] = col_rules

    # Add sample values to columns if provided
    if sample_values:
        for col in base_yaml["semantic_view"]["columns"]:
            col_name = col.get("name")
            if col_name and col_name in sample_values and sample_values[col_name]:
                col["sample_values"] = sample_values[col_name]

    yaml_output = yaml_module.dump(base_yaml, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # Fix any missing fields (like lambda_hint in DQ rules)
    from semantic_yaml_spec import auto_fix_yaml
    yaml_output = auto_fix_yaml(yaml_output)

    return yaml_output


def _generate_dq_rules_only(cursor, dq_columns: List[str], all_columns: list, model: str, base_columns: list = None) -> Dict[str, list]:
    """
    Use Cortex to generate DQ rules only for specified columns.
    Batches columns into groups of 10 to avoid token limits.
    Returns a dict mapping column_name -> list of dq_rules.
    """
    import json

    # Build column info for selected columns only, including descriptions if available
    selected_col_info = []
    for row in all_columns:
        if row[0] in dq_columns:
            col_info = {
                "name": row[0],
                "type": row[1],
                "nullable": row[2],
                "description": ""
            }
            # Try to get description from base_columns if available
            if base_columns:
                for base_col in base_columns:
                    if isinstance(base_col, dict) and base_col.get("name") == row[0]:
                        col_info["description"] = base_col.get("description", "")
                        break
            selected_col_info.append(col_info)

    if not selected_col_info:
        return {}

    # Batch columns into groups of 10 to avoid token limits
    batch_size = 10
    all_rules_map = {}

    for i in range(0, len(selected_col_info), batch_size):
        batch = selected_col_info[i:i+batch_size]
        col_desc = "\n".join([
            f"- {col['name']}: {col['type']}, {'NOT NULL' if col['nullable'] == 'NO' else 'NULL'}" +
            (f"\n  Description: {col['description']}" if col['description'] else "")
            for col in batch
        ])

        prompt = f'''Generate DQ rules for these columns. Return ONLY valid JSON (no markdown).

Columns:
{col_desc}

Return JSON array with this EXACT structure:
[
  {{"column": "COLUMN_NAME", "rules": [
    {{
      "type": "NOT_NULL",
      "severity": "CRITICAL",
      "description": "Why this rule is important",
      "lambda_hint": "COLUMN_NAME IS NOT NULL",
      "params": null
    }}
  ]}}
]

IMPORTANT:
- Each rule MUST have: type, severity, description, lambda_hint, params
- lambda_hint is the SQL expression to check the rule (e.g., "COL >= 0", "COL IS NOT NULL")
- Use column descriptions to create meaningful rules
- Types: NOT_NULL, UNIQUE, MIN_VALUE, MAX_VALUE, ALLOWED_VALUES, MAX_LENGTH, PATTERN
- Generate 1-2 rules per column based on the column's purpose

Return ONLY the JSON array, no extra text.'''

        cortex_sql = "SELECT SNOWFLAKE.CORTEX.COMPLETE(%s, %s)"
        try:
            cursor.execute(cortex_sql, (model, prompt))
            result = cursor.fetchone()

            if not result or not result[0]:
                continue

            response = result[0].strip()

            # Clean markdown
            if response.startswith("```"):
                lines = response.split("\n")
                if lines[-1].strip() == "```":
                    response = "\n".join(lines[1:-1])
                else:
                    response = "\n".join(lines[1:])

            rules_list = json.loads(response)
            for item in rules_list:
                col_name = item.get("column")
                rules = item.get("rules", [])
                # Ensure all required fields exist
                for rule in rules:
                    if "id" not in rule:
                        rule["id"] = f"{col_name}_{rule.get('type', 'rule')}".lower()
                    if "params" not in rule:
                        rule["params"] = None
                    # Generate lambda_hint if missing
                    if "lambda_hint" not in rule or not rule["lambda_hint"]:
                        rule_type = rule.get("type", "")
                        params = rule.get("params")
                        if rule_type == "NOT_NULL":
                            rule["lambda_hint"] = f"{col_name} IS NOT NULL"
                        elif rule_type == "UNIQUE":
                            rule["lambda_hint"] = f"COUNT(DISTINCT {col_name}) = COUNT({col_name})"
                        elif rule_type == "MIN_VALUE" and params:
                            min_val = params.get("min_value", 0) if isinstance(params, dict) else 0
                            rule["lambda_hint"] = f"{col_name} >= {min_val}"
                        elif rule_type == "MAX_VALUE" and params:
                            max_val = params.get("max_value", 0) if isinstance(params, dict) else 0
                            rule["lambda_hint"] = f"{col_name} <= {max_val}"
                        elif rule_type == "PATTERN" and params:
                            pattern = params.get("pattern", "") if isinstance(params, dict) else ""
                            rule["lambda_hint"] = f"REGEXP_LIKE({col_name}, '{pattern}')"
                        else:
                            rule["lambda_hint"] = f"-- {rule_type} rule for {col_name}"
                all_rules_map[col_name] = rules
        except (json.JSONDecodeError, KeyError, TypeError, Exception):
            # Skip this batch if it fails
            continue

    return all_rules_map


def call_generate_semantic_yaml(
    conn: SnowflakeConnection,
    database: str,
    schema: str,
    table: str
) -> str:
    """Alias for generate_semantic_yaml_with_cortex."""
    return generate_semantic_yaml_with_cortex(conn, database, schema, table)


def add_dq_rule_from_natural_language(
    yaml_text: str,
    column_name: str,
    nl_rule: str,
    llm_call_fn
) -> str:
    """
    Add or update a DQ rule for an existing column based on natural language.

    - Never creates new columns
    - Creates dq_rules list if missing
    - Updates existing rule if same type exists, otherwise appends
    """
    import yaml as yaml_module
    import json

    # Parse existing YAML
    parsed = yaml_module.safe_load(yaml_text)
    if not parsed or "semantic_view" not in parsed:
        raise ValueError("Invalid YAML: missing semantic_view")

    sv = parsed["semantic_view"]
    columns = sv.get("columns", [])

    # Find the target column (never create new)
    target_col = None
    target_idx = None
    for idx, col in enumerate(columns):
        if col.get("name") == column_name:
            target_col = col
            target_idx = idx
            break

    if target_col is None:
        raise ValueError(f"Column '{column_name}' not found. Cannot add rule to non-existent column.")

    # Get column metadata for context
    col_data_type = target_col.get("data_type", "unknown")
    col_logical_type = target_col.get("logical_type", "unknown")
    col_samples = target_col.get("sample_values", [])

    # Build sample values context
    samples_context = ""
    if col_samples:
        samples_str = ", ".join([str(v) for v in col_samples[:5]])
        samples_context = f"\nSample values: {samples_str}"

    # Build LLM prompt
    prompt = f'''Convert this rule to JSON. Column: {column_name} ({col_data_type}){samples_context}
Rule: "{nl_rule}"

Types: NOT_NULL, UNIQUE, MIN_VALUE, MAX_VALUE, ALLOWED_VALUES, MAX_LENGTH, PATTERN, MAX_AGE_DAYS, FOREIGN_KEY, LOOKUP

Use the sample values to better understand the data format and create more accurate validation rules.

Return ONLY JSON:
{{"id":"{column_name.lower()}_<type>","type":"<TYPE>","severity":"CRITICAL/WARNING/INFO","params":null,"description":"<what it checks>","lambda_hint":"<python expr>"}}'''

    # Call LLM
    response_text = llm_call_fn(prompt).strip()

    # Extract JSON from LLM response (handles markdown, extra text, etc.)
    def extract_json(text: str) -> str:
        """Extract the first valid JSON object from LLM response."""
        # Remove markdown code blocks
        if "```" in text:
            # Handle ```json or ``` followed by JSON
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                # Skip language identifiers
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{") and part.endswith("}"):
                    return part
                # Try to find JSON even if there's extra text after
                if part.startswith("{"):
                    # Find the matching closing brace
                    brace_count = 0
                    for i, char in enumerate(part):
                        if char == "{":
                            brace_count += 1
                        elif char == "}":
                            brace_count -= 1
                            if brace_count == 0:
                                return part[:i+1]

        # No markdown blocks - try to extract JSON directly
        text = text.strip()
        if text.startswith("{"):
            # Find the matching closing brace
            brace_count = 0
            for i, char in enumerate(text):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        return text[:i+1]

        return text

    response_text = extract_json(response_text)

    # Parse JSON
    try:
        new_rule = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}\nResponse was: {response_text[:200]}")

    # Validate required fields
    for field in ["id", "type", "severity", "description", "lambda_hint"]:
        if field not in new_rule:
            raise ValueError(f"Missing field: {field}")

    if "params" not in new_rule:
        new_rule["params"] = None

    # Ensure dq_rules list exists
    if "dq_rules" not in target_col or not isinstance(target_col["dq_rules"], list):
        target_col["dq_rules"] = []

    # Check if rule with same type exists - replace it; otherwise append
    rule_type = new_rule["type"]
    existing_idx = None
    for i, rule in enumerate(target_col["dq_rules"]):
        if isinstance(rule, dict) and rule.get("type") == rule_type:
            existing_idx = i
            break

    if existing_idx is not None:
        target_col["dq_rules"][existing_idx] = new_rule
    else:
        target_col["dq_rules"].append(new_rule)

    # Update column in list
    columns[target_idx] = target_col
    sv["columns"] = columns
    parsed["semantic_view"] = sv

    return yaml_module.dump(parsed, default_flow_style=False, sort_keys=False, allow_unicode=True)


def add_table_level_rule_from_natural_language(
    yaml_text: str,
    column_names: List[str],
    nl_rule: str,
    llm_call_fn
) -> str:
    """
    Add a table-level cross-column DQ rule based on natural language.

    Args:
        yaml_text: The current YAML definition
        column_names: List of columns involved in this rule (2+ columns)
        nl_rule: Natural language description of the rule
        llm_call_fn: Function to call LLM (e.g., call_cortex_for_rule)

    Returns:
        Updated YAML text with the new table-level rule
    """
    import yaml as yaml_module
    import json

    if not column_names or len(column_names) < 2:
        raise ValueError("Table-level rules require at least 2 columns")

    # Parse existing YAML
    parsed = yaml_module.safe_load(yaml_text)
    if not parsed or "semantic_view" not in parsed:
        raise ValueError("Invalid YAML: missing semantic_view")

    sv = parsed["semantic_view"]

    # Ensure table_rules list exists
    if "table_rules" not in sv:
        sv["table_rules"] = []

    # Validate that all columns exist and collect sample values
    existing_columns = [col.get("name") for col in sv.get("columns", [])]
    columns_info = {}
    for col in sv.get("columns", []):
        col_name = col.get("name")
        if col_name in column_names:
            columns_info[col_name] = {
                "data_type": col.get("data_type", "unknown"),
                "sample_values": col.get("sample_values", [])[:5]
            }

    for col_name in column_names:
        if col_name not in existing_columns:
            raise ValueError(f"Column '{col_name}' not found in semantic view")

    # Build sample values context
    samples_context = ""
    for col_name in column_names:
        if col_name in columns_info and columns_info[col_name]["sample_values"]:
            samples_str = ", ".join([str(v) for v in columns_info[col_name]["sample_values"]])
            samples_context += f"\n  {col_name} ({columns_info[col_name]['data_type']}): {samples_str}"

    # Build LLM prompt for cross-column rules
    columns_str = ", ".join(column_names)
    prompt = f'''Convert this cross-column rule to JSON. Columns: {columns_str}
Rule: "{nl_rule}"
{f"Sample values:{samples_context}" if samples_context else ""}

Use the sample values to better understand the data and create more accurate validation rules.

Rule Types:
- COMPOSITE_UNIQUE: Multiple columns together must be unique
- CROSS_COLUMN_COMPARISON: Compare values between columns (e.g., start < end)
- CONDITIONAL_REQUIRED: If column A has value, column B is required
- MUTUAL_EXCLUSIVITY: Only one of the columns can have a value
- CONDITIONAL_VALUE: If column A = value, then column B must meet condition

Return ONLY JSON:
{{"type":"<TYPE>","columns":{column_names},"severity":"CRITICAL/WARNING/INFO","description":"<what it checks>","lambda_hint":"<SQL expression using column names>"}}

Examples:
{{"type":"COMPOSITE_UNIQUE","columns":["customer_id","order_id"],"severity":"CRITICAL","description":"Customer ID and Order ID together must be unique","lambda_hint":"COUNT(*) OVER (PARTITION BY customer_id, order_id) = 1"}}
{{"type":"CROSS_COLUMN_COMPARISON","columns":["start_date","end_date"],"severity":"WARNING","description":"Start date must be before end date","lambda_hint":"start_date < end_date OR end_date IS NULL"}}
'''

    # Call LLM
    response_text = llm_call_fn(prompt).strip()

    # Extract JSON from LLM response (handles markdown, extra text, etc.)
    def extract_json(text: str) -> str:
        """Extract the first valid JSON object from LLM response."""
        # Remove markdown code blocks
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{") and part.endswith("}"):
                    return part
                if part.startswith("{"):
                    brace_count = 0
                    for i, char in enumerate(part):
                        if char == "{":
                            brace_count += 1
                        elif char == "}":
                            brace_count -= 1
                            if brace_count == 0:
                                return part[:i+1]

        # No markdown blocks - try to extract JSON directly
        text = text.strip()
        if text.startswith("{"):
            brace_count = 0
            for i, char in enumerate(text):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        return text[:i+1]

        return text

    response_text = extract_json(response_text)

    # Parse JSON
    try:
        new_rule = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}\nResponse was: {response_text[:200]}")

    # Validate required fields
    for field in ["type", "columns", "severity", "description", "lambda_hint"]:
        if field not in new_rule:
            raise ValueError(f"Missing field: {field}")

    # Ensure columns is a list
    if not isinstance(new_rule["columns"], list):
        new_rule["columns"] = column_names

    # Add ID for tracking
    rule_id = "_".join(column_names).lower() + "_" + new_rule["type"].lower()
    new_rule["id"] = rule_id

    # Check if similar rule exists (same type and columns) - replace it; otherwise append
    rule_type = new_rule["type"]
    rule_cols = set(new_rule["columns"])
    existing_idx = None

    for i, rule in enumerate(sv["table_rules"]):
        if isinstance(rule, dict) and rule.get("type") == rule_type:
            if set(rule.get("columns", [])) == rule_cols:
                existing_idx = i
                break

    if existing_idx is not None:
        sv["table_rules"][existing_idx] = new_rule
    else:
        sv["table_rules"].append(new_rule)

    parsed["semantic_view"] = sv

    return yaml_module.dump(parsed, default_flow_style=False, sort_keys=False, allow_unicode=True)


def generate_filter_with_ai(
    conn: SnowflakeConnection,
    nl_description: str,
    columns: list,
    model: str = "mistral-large",
    semantic_columns: list = None
) -> str:
    """
    Generate a SQL WHERE filter condition from natural language description.

    Args:
        conn: Snowflake connection
        nl_description: Natural language description of the filter (e.g., "only active customers")
        columns: List of column dicts with 'name' and 'type' keys (basic info)
        model: LLM model to use
        semantic_columns: Optional list of semantic view column dicts with descriptions, sample_values, etc.

    Returns:
        SQL WHERE condition string (without the WHERE keyword)
    """
    # Build enhanced column info if semantic view is available
    if semantic_columns:
        col_info_lines = []
        for col in semantic_columns:
            col_name = col.get('name', '')
            col_type = col.get('data_type', '')
            col_desc = col.get('description', '')
            sample_vals = col.get('sample_values', [])

            line = f"- {col_name} ({col_type})"
            if col_desc:
                line += f": {col_desc}"
            if sample_vals:
                samples_str = ", ".join([str(v) for v in sample_vals[:5]])
                line += f" [Examples: {samples_str}]"
            col_info_lines.append(line)
        col_info = "\n".join(col_info_lines)
        context_note = "\nNOTE: Use the example values to understand the exact format and casing of data."
    else:
        # Fallback to basic column info
        col_info = "\n".join([f"- {c['name']} ({c['type']})" for c in columns])
        context_note = ""

    prompt = f"""Given the following table columns:
{col_info}{context_note}

Generate a SQL WHERE condition for this filter requirement:
"{nl_description}"

Requirements:
- Return ONLY the SQL condition (without "WHERE")
- Use proper SQL syntax for the column types
- Use single quotes for string literals
- Match the EXACT casing and format shown in example values
- For date comparisons, use appropriate date functions
- Keep it simple and correct

Examples:
- "only active records" → status = 'ACTIVE'
- "created after 2024" → created_date > '2024-01-01'
- "high value customers" → total_value > 10000

Return ONLY the SQL condition, no explanation."""

    cursor = conn.cursor()
    try:
        cursor.execute("SELECT SNOWFLAKE.CORTEX.COMPLETE(%s, %s)", (model, prompt))
        result = cursor.fetchone()
        if not result or not result[0]:
            raise ValueError("Cortex returned empty response")

        # Clean up the response
        sql_condition = result[0].strip()

        # Remove common prefixes if AI added them
        if sql_condition.upper().startswith("WHERE "):
            sql_condition = sql_condition[6:].strip()

        return sql_condition
    finally:
        cursor.close()


def call_cortex_for_rule(conn: SnowflakeConnection, prompt: str, model: str = "mistral-large") -> str:
    """Call Snowflake Cortex to get LLM response for rule generation."""
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT SNOWFLAKE.CORTEX.COMPLETE(%s, %s)", (model, prompt))
        result = cursor.fetchone()
        if not result or not result[0]:
            raise ValueError("Cortex returned empty response")
        return result[0]
    finally:
        cursor.close()


def auto_identify_and_create_rule(
    conn: SnowflakeConnection,
    yaml_text: str,
    nl_description: str,
    model: str = "mistral-large"
) -> dict:
    """
    Automatically identify relevant field(s) from natural language and create appropriate rule.

    This function allows business users to describe what they want to validate without
    knowing the exact field names. AI will:
    1. Analyze the table schema
    2. Identify which field(s) are relevant
    3. Determine appropriate rule type
    4. Generate the complete rule

    Args:
        conn: Snowflake connection
        yaml_text: Current YAML definition
        nl_description: Natural language description of what to validate
        model: LLM model to use (default: mistral-large)

    Returns:
        dict with:
            - identified_fields: List of field names identified
            - rule_type: Type of rule (column-level or table-level)
            - updated_yaml: Updated YAML with the new rule
            - explanation: Human-readable explanation of what was done

    Examples:
        "Make sure customer emails are valid"
        -> Identifies: email field
        -> Creates: PATTERN rule with email regex

        "Check that order totals match line item sums"
        -> Identifies: order_total, order_lines table
        -> Creates: MULTI_TABLE_AGGREGATE rule

        "Customers should only be active if they bought something recently"
        -> Identifies: active field, sales table relationship
        -> Creates: MULTI_TABLE_CONDITION rule
    """
    import yaml as yaml_module
    import json

    # Parse existing YAML to get schema information
    parsed = yaml_module.safe_load(yaml_text)
    if not parsed or "semantic_view" not in parsed:
        raise ValueError("Invalid YAML: missing semantic_view")

    sv = parsed["semantic_view"]
    columns = sv.get("columns", [])

    # Build schema context for AI
    schema_info = []
    for col in columns:
        col_name = col.get("name", "")
        col_type = col.get("data_type", "")
        col_desc = col.get("description", "")
        col_logical = col.get("logical_type", "")
        col_samples = col.get("sample_values", [])

        col_info = {
            "name": col_name,
            "data_type": col_type,
            "logical_type": col_logical,
            "description": col_desc
        }

        # Include sample values if available
        if col_samples:
            col_info["sample_values"] = col_samples[:5]  # Limit to 5 samples

        schema_info.append(col_info)

    schema_json = json.dumps(schema_info, indent=2)

    # Build AI prompt for field identification
    prompt = f"""You are a data quality expert. A business user wants to create a validation rule but doesn't know the exact field names.

Table Schema (with sample values):
{schema_json}

User Request: "{nl_description}"

Your task:
1. Identify which field(s) from the schema are relevant to this validation
   - Use the sample_values to better understand the actual data in each field
2. Determine if this is a single-field rule or multi-field rule
3. Suggest the appropriate rule type
4. Provide reasoning

Respond ONLY with JSON in this exact format:
{{
  "identified_fields": ["field1", "field2"],
  "rule_category": "column-level" or "table-level",
  "suggested_rule_type": "<RULE_TYPE>",
  "reasoning": "Brief explanation of why these fields and this rule type",
  "nl_rule_description": "Refined natural language description for rule generation"
}}

Available column-level rule types: NOT_NULL, UNIQUE, FUZZY_DUPLICATE, MIN_VALUE, MAX_VALUE, ALLOWED_VALUES, MAX_LENGTH, PATTERN, MAX_AGE_DAYS, FOREIGN_KEY, LOOKUP

Available table-level rule types: COMPOSITE_UNIQUE, CROSS_COLUMN_COMPARISON, CONDITIONAL_REQUIRED, MUTUAL_EXCLUSIVITY, CONDITIONAL_VALUE, MULTI_TABLE_AGGREGATE, MULTI_TABLE_CONDITION

Examples:
User: "Make sure emails are valid"
Response: {{"identified_fields": ["email"], "rule_category": "column-level", "suggested_rule_type": "PATTERN", "reasoning": "Email field needs format validation", "nl_rule_description": "Must match email pattern"}}

User: "Start date must be before end date"
Response: {{"identified_fields": ["start_date", "end_date"], "rule_category": "table-level", "suggested_rule_type": "CROSS_COLUMN_COMPARISON", "reasoning": "Comparing two date columns", "nl_rule_description": "start_date < end_date"}}

Now identify fields for the user's request."""

    # Call AI to identify fields
    response_text = call_cortex_for_rule(conn, prompt, model).strip()

    # Extract JSON from response
    def extract_json(text: str) -> str:
        """Extract the first valid JSON object from LLM response."""
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{") and part.endswith("}"):
                    return part
                if part.startswith("{"):
                    brace_count = 0
                    for i, char in enumerate(part):
                        if char == "{":
                            brace_count += 1
                        elif char == "}":
                            brace_count -= 1
                            if brace_count == 0:
                                return part[:i+1]

        text = text.strip()
        if text.startswith("{"):
            brace_count = 0
            for i, char in enumerate(text):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        return text[:i+1]

        return text

    response_text = extract_json(response_text)

    try:
        identification = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"AI returned invalid JSON: {e}\nResponse: {response_text[:500]}")

    # Validate response structure
    required_fields = ["identified_fields", "rule_category", "suggested_rule_type", "reasoning", "nl_rule_description"]
    for field in required_fields:
        if field not in identification:
            raise ValueError(f"AI response missing field: {field}")

    identified_fields = identification["identified_fields"]
    rule_category = identification["rule_category"]
    nl_rule_description = identification["nl_rule_description"]

    if not identified_fields:
        raise ValueError("AI could not identify any relevant fields for this request")

    # Validate identified fields exist in schema
    existing_field_names = [col.get("name") for col in columns]
    for field in identified_fields:
        if field not in existing_field_names:
            raise ValueError(f"AI identified field '{field}' but it doesn't exist in schema. Available fields: {existing_field_names}")

    # Create the rule using appropriate function
    llm_call_fn = lambda p: call_cortex_for_rule(conn, p, model)

    if rule_category == "column-level":
        if len(identified_fields) != 1:
            raise ValueError(f"Column-level rule should identify exactly 1 field, but got {len(identified_fields)}: {identified_fields}")

        updated_yaml = add_dq_rule_from_natural_language(
            yaml_text=yaml_text,
            column_name=identified_fields[0],
            nl_rule=nl_rule_description,
            llm_call_fn=llm_call_fn
        )

    elif rule_category == "table-level":
        if len(identified_fields) < 2:
            raise ValueError(f"Table-level rule should identify 2+ fields, but got {len(identified_fields)}: {identified_fields}")

        updated_yaml = add_table_level_rule_from_natural_language(
            yaml_text=yaml_text,
            column_names=identified_fields,
            nl_rule=nl_rule_description,
            llm_call_fn=llm_call_fn
        )

    else:
        raise ValueError(f"Unknown rule category: {rule_category}")

    return {
        "identified_fields": identified_fields,
        "rule_type": identification["suggested_rule_type"],
        "rule_category": rule_category,
        "updated_yaml": updated_yaml,
        "explanation": identification["reasoning"],
        "nl_rule_description": nl_rule_description
    }


def save_semantic_yaml(
    conn: SnowflakeConnection,
    name: str,
    version: int,
    source_db: str,
    source_schema: str,
    source_table: str,
    target_db: str,
    target_schema: str,
    target_view: str,
    yaml_definition: str,
    status: str = "DRAFT"
) -> bool:
    """Save semantic YAML definition to the registry table."""
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO SEMANTIC_CONFIG.SEMANTIC_VIEW (
                NAME, VERSION, SOURCE_DB, SOURCE_SCHEMA, SOURCE_TABLE,
                TARGET_DB, TARGET_SCHEMA, TARGET_VIEW, YAML_DEFINITION, STATUS
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (name, version, source_db, source_schema, source_table,
              target_db, target_schema, target_view, yaml_definition, status))
        return True
    except Exception as e:
        raise e
    finally:
        cursor.close()


def execute_ddl(conn: SnowflakeConnection, ddl: str) -> bool:
    """Execute a DDL statement."""
    cursor = conn.cursor()
    try:
        cursor.execute(ddl)
        return True
    finally:
        cursor.close()


# ============================================================================
# Rule Packs and Enrichment Functions
# ============================================================================

def load_rule_packs(rule_packs_file: str = "rule_packs.yaml") -> Dict[str, Any]:
    """Load rule packs configuration from YAML file."""
    import os
    import yaml as yaml_module

    # Get the directory of this file
    current_dir = os.path.dirname(os.path.abspath(__file__))
    rule_packs_path = os.path.join(current_dir, rule_packs_file)

    try:
        with open(rule_packs_path, 'r') as f:
            return yaml_module.safe_load(f)
    except FileNotFoundError:
        return {"rule_packs": [], "entity_type_suggestions": []}


def match_column_to_pattern(column_name: str, pattern: str) -> bool:
    """
    Check if a column name matches a pattern.

    Patterns can be:
    - Exact match: "customer_id"
    - Wildcard: "*customer*", "*_id", "order_*"
    - Multiple patterns: "net_value|gross_value|amount"
    """
    import fnmatch

    column_lower = column_name.lower()

    # Handle multiple patterns separated by |
    if "|" in pattern:
        patterns = [p.strip() for p in pattern.split("|")]
        return any(match_column_to_pattern(column_name, p) for p in patterns)

    # Handle wildcard patterns
    pattern_lower = pattern.lower()
    return fnmatch.fnmatch(column_lower, pattern_lower)


def apply_rule_packs_to_columns(
    columns: list,
    source_system: str,
    entity_type: Optional[str] = None,
    business_domain: Optional[str] = None
) -> Dict[str, list]:
    """
    Apply rule packs to columns and return initial DQ rules.

    Returns:
        Dict mapping column_name -> list of rule dicts
    """
    rule_packs_data = load_rule_packs()
    rule_packs = rule_packs_data.get("rule_packs", [])

    # Find matching rule packs
    matching_packs = []

    # First, try exact match
    for pack in rule_packs:
        pack_system = pack.get("source_system")
        pack_entity = pack.get("entity_type")
        pack_domain = pack.get("business_domain")

        if pack_system == source_system:
            if entity_type and pack_entity == entity_type:
                matching_packs.append(pack)
            elif not entity_type and pack_entity == "GENERIC":
                matching_packs.append(pack)

    # If no match, fall back to GENERIC
    if not matching_packs:
        for pack in rule_packs:
            if pack.get("source_system") == "GENERIC":
                matching_packs.append(pack)

    # Apply rules from matching packs
    rules_by_column = {}

    for pack in matching_packs:
        pack_rules = pack.get("rules", [])

        for rule_template in pack_rules:
            applies_to = rule_template.get("applies_to", "")

            # Find matching columns
            for col in columns:
                col_name = col.get("name") if isinstance(col, dict) else col

                if match_column_to_pattern(col_name, applies_to):
                    if col_name not in rules_by_column:
                        rules_by_column[col_name] = []

                    # Create rule from template
                    rule_type = rule_template.get("type")
                    params = rule_template.get("params")

                    # Generate lambda_hint based on rule type
                    lambda_hint = ""
                    if rule_type == "NOT_NULL":
                        lambda_hint = f"{col_name} IS NOT NULL"
                    elif rule_type == "UNIQUE":
                        lambda_hint = f"COUNT(DISTINCT {col_name}) = COUNT({col_name})"
                    elif rule_type == "MIN_VALUE" and params:
                        min_val = params.get("min_value", 0)
                        lambda_hint = f"{col_name} >= {min_val}"
                    elif rule_type == "MAX_VALUE" and params:
                        max_val = params.get("max_value", 0)
                        lambda_hint = f"{col_name} <= {max_val}"
                    elif rule_type == "PATTERN" and params:
                        pattern = params.get("pattern", "")
                        lambda_hint = f"REGEXP_LIKE({col_name}, '{pattern}')"
                    elif rule_type == "ALLOWED_VALUES" and params:
                        values = params.get("values", [])
                        if values:
                            values_str = ", ".join([f"'{v}'" for v in values])
                            lambda_hint = f"{col_name} IN ({values_str})"
                    elif rule_type == "MAX_LENGTH" and params:
                        max_len = params.get("max_length", 0)
                        lambda_hint = f"LENGTH({col_name}) <= {max_len}"
                    elif rule_type == "MAX_AGE_DAYS" and params:
                        max_age = params.get("max_age_days", 0)
                        lambda_hint = f"DATEDIFF(day, {col_name}, CURRENT_DATE()) <= {max_age}"
                    elif rule_type == "FOREIGN_KEY" and params:
                        ref_table = params.get("reference_table", "")
                        ref_col = params.get("reference_column", "")
                        lambda_hint = f"{col_name} IN (SELECT {ref_col} FROM {ref_table})"
                    elif rule_type == "LOOKUP" and params:
                        ref_table = params.get("reference_table", "")
                        ref_col = params.get("reference_column", "")
                        lambda_hint = f"{col_name} IN (SELECT {ref_col} FROM {ref_table})"
                    else:
                        lambda_hint = f"-- {rule_type} rule for {col_name}"

                    rule = {
                        "id": f"{col_name}_{rule_type}".lower(),
                        "type": rule_type,
                        "severity": rule_template.get("severity"),
                        "description": rule_template.get("description", ""),
                        "params": params,
                        "lambda_hint": lambda_hint,
                        "source": "rule_pack"  # Mark as coming from rule pack
                    }

                    # Avoid duplicates (same type for same column)
                    existing_types = [r.get("type") for r in rules_by_column[col_name]]
                    if rule["type"] not in existing_types:
                        rules_by_column[col_name].append(rule)

    return rules_by_column


def suggest_entity_type(table_name: str) -> Optional[str]:
    """Suggest entity type based on table name patterns."""
    rule_packs_data = load_rule_packs()
    suggestions = rule_packs_data.get("entity_type_suggestions", [])

    table_lower = table_name.lower()

    for suggestion in suggestions:
        patterns = suggestion.get("patterns", [])
        for pattern in patterns:
            if match_column_to_pattern(table_name, pattern):
                return suggestion.get("entity_type")

    return None


def enrich_table_description(
    conn: SnowflakeConnection,
    yaml_content: str,
    model: str = "mistral-large"
) -> Dict[str, Any]:
    """
    Use Cortex AI to validate and enrich the table description.

    Returns:
        Dict with keys: enhanced_description, suggested_entity_type, suggested_business_domain
    """
    import yaml as yaml_module
    from doc_snippets import build_context_prompt

    # Parse YAML
    try:
        parsed = yaml_module.safe_load(yaml_content)
        sv = parsed.get("semantic_view", {})
    except:
        raise ValueError("Invalid YAML")

    # Extract metadata
    source = sv.get("source", {})
    table_name = source.get("table", "")
    source_system = sv.get("source_system", "GENERIC")
    business_domain = sv.get("business_domain")
    entity_type = sv.get("entity_type")
    current_description = sv.get("description", "")
    columns = sv.get("columns", [])

    # Build column summary
    col_summary = []
    for col in columns[:20]:  # Limit to first 20 columns
        col_name = col.get("name", "")
        data_type = col.get("data_type", "")
        col_desc = col.get("description", "")
        col_summary.append(f"- {col_name} ({data_type}): {col_desc if col_desc else 'N/A'}")

    col_summary_text = "\n".join(col_summary)
    if len(columns) > 20:
        col_summary_text += f"\n... and {len(columns) - 20} more columns"

    # Build context from documentation
    context = build_context_prompt(source_system, entity_type, business_domain)
    
    # Prepare context lines
    biz_domain_line = f"Business Domain: {business_domain}" if business_domain else ""
    entity_type_line = f"Entity Type: {entity_type}" if entity_type else ""
    context_block = f"Context:\n{context}" if context else ""

    # Build enrichment prompt
    prompt = f"""You are a data quality expert analyzing a table's semantic definition.

Table: {table_name}
Source System: {source_system}
{biz_domain_line}
{entity_type_line}

Current Description:
"{current_description}"

Columns:
{col_summary_text}

{context_block}

Tasks:
1. Improve the table description to be clear, concise, and business-friendly (2-3 sentences max).
2. If entity_type is not set or seems incorrect, suggest an appropriate entity type from this list:
   SalesOrderHeader, SalesOrderLine, Customer, Account, Opportunity, Product, Invoice, Payment, Person, Employee, Transaction, Shipment, Inventory, GENERIC
3. If business_domain is not set, suggest one from: Sales, Finance, HR, SupplyChain, Marketing, Customer Service, Operations, Product

Return your response in this exact JSON format:
{{
  "enhanced_description": "your improved description here",
  "suggested_entity_type": "EntityType or null",
  "suggested_business_domain": "Domain or null"
}}

Return ONLY the JSON, no markdown formatting."""

    # Call Cortex
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT SNOWFLAKE.CORTEX.COMPLETE(%s, %s)", (model, prompt))
        result = cursor.fetchone()

        if not result or not result[0]:
            raise ValueError("Cortex returned empty response")

        response = result[0].strip()

        # Clean markdown if present
        if response.startswith("```"):
            lines = response.split("\n")
            response = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

        # Parse JSON response
        import json
        result_data = json.loads(response)

        return {
            "enhanced_description": result_data.get("enhanced_description", current_description),
            "suggested_entity_type": result_data.get("suggested_entity_type"),
            "suggested_business_domain": result_data.get("suggested_business_domain")
        }

    except Exception as e:
        # Return original if enrichment fails
        return {
            "enhanced_description": current_description,
            "suggested_entity_type": None,
            "suggested_business_domain": None,
            "error": str(e)
        }
    finally:
        cursor.close()


# ============================================================================
# Data Quality Rule Execution Functions
# ============================================================================

def execute_column_rule(
    conn: SnowflakeConnection,
    database: str,
    schema: str,
    table: str,
    column_name: str,
    rule: dict,
    limit: int = 100
) -> dict:
    """
    Execute a single column-level data quality rule and return violations.

    Args:
        conn: Snowflake connection
        database: Database name
        schema: Schema name
        table: Table name
        column_name: Column to validate
        rule: Rule definition dict with type, params, etc.
        limit: Max violations to return (default 100)

    Returns:
        dict with:
            - rule_id: str
            - rule_type: str
            - severity: str
            - total_rows: int
            - violation_count: int
            - pass_rate: float (0-100)
            - violations: list of dicts (sample)
            - sql_query: str (the query used)
    """
    cursor = conn.cursor()
    try:
        full_table = f"{database}.{schema}.{table}"
        rule_type = rule.get("type", "")
        params = rule.get("params", {})

        # Get optional filter to apply rule to subset of data
        filter_condition = params.get("filter", "")  # e.g., "active = TRUE"

        # Build SQL query based on rule type
        violation_condition = ""

        if rule_type == "NOT_NULL":
            violation_condition = f"{column_name} IS NULL"

        elif rule_type == "UNIQUE":
            # Find duplicate values
            query = f"""
            WITH duplicates AS (
                SELECT {column_name}, COUNT(*) as cnt
                FROM {full_table}
                WHERE {column_name} IS NOT NULL
                GROUP BY {column_name}
                HAVING COUNT(*) > 1
            )
            SELECT t.*, d.cnt as duplicate_count
            FROM {full_table} t
            JOIN duplicates d ON t.{column_name} = d.{column_name}
            LIMIT {limit}
            """
            cursor.execute(query)
            violations = [_convert_row_to_dict(row) for row in cursor.fetchall()]

            cursor.execute(f"SELECT COUNT(*) FROM {full_table}")
            total_rows = cursor.fetchone()[0]

            cursor.execute(f"""
                SELECT COUNT(DISTINCT {column_name}) as unique_vals,
                       COUNT({column_name}) as non_null_vals
                FROM {full_table}
            """)
            result = cursor.fetchone()
            unique_vals, non_null_vals = result[0], result[1]
            violation_count = non_null_vals - unique_vals

            return {
                "rule_id": rule.get("id", f"{column_name}_{rule_type}".lower()),
                "rule_type": rule_type,
                "severity": rule.get("severity", "WARNING"),
                "column": column_name,
                "total_rows": total_rows,
                "violation_count": violation_count,
                "pass_rate": ((total_rows - violation_count) / total_rows * 100) if total_rows > 0 else 100.0,
                "violations": violations[:limit],
                "sql_query": query
            }

        elif rule_type == "FUZZY_DUPLICATE":
            # Find similar values using string similarity
            # Uses Levenshtein distance (edit distance) and normalization
            similarity_threshold = params.get("threshold", 0.8)  # 80% similar
            method = params.get("method", "editdistance")  # editdistance, soundex, normalized

            if method == "editdistance":
                # Use EDITDISTANCE function (Snowflake built-in)
                # Find pairs of records with similar values
                query = f"""
                WITH pairs AS (
                    SELECT
                        a.{column_name} as value_a,
                        b.{column_name} as value_b,
                        EDITDISTANCE(LOWER(a.{column_name}), LOWER(b.{column_name})) as distance,
                        GREATEST(LENGTH(a.{column_name}), LENGTH(b.{column_name})) as max_len,
                        1.0 - (EDITDISTANCE(LOWER(a.{column_name}), LOWER(b.{column_name})) /
                               GREATEST(LENGTH(a.{column_name}), LENGTH(b.{column_name}))) as similarity,
                        a.*
                    FROM {full_table} a
                    JOIN {full_table} b
                        ON a.{column_name} != b.{column_name}
                        AND a.{column_name} IS NOT NULL
                        AND b.{column_name} IS NOT NULL
                    WHERE EDITDISTANCE(LOWER(a.{column_name}), LOWER(b.{column_name})) <=
                          GREATEST(LENGTH(a.{column_name}), LENGTH(b.{column_name})) * {1 - similarity_threshold}
                )
                SELECT DISTINCT * FROM pairs
                WHERE similarity >= {similarity_threshold}
                LIMIT {limit}
                """
            elif method == "soundex":
                # Use SOUNDEX for phonetic matching (sounds similar)
                query = f"""
                WITH soundex_groups AS (
                    SELECT
                        SOUNDEX({column_name}) as soundex_code,
                        {column_name},
                        COUNT(*) OVER (PARTITION BY SOUNDEX({column_name})) as similar_count
                    FROM {full_table}
                    WHERE {column_name} IS NOT NULL
                )
                SELECT *
                FROM soundex_groups
                WHERE similar_count > 1
                LIMIT {limit}
                """
            else:  # normalized - remove spaces, lowercase, trim
                query = f"""
                WITH normalized AS (
                    SELECT
                        {column_name},
                        TRIM(LOWER(REGEXP_REPLACE({column_name}, '\\s+', ''))) as normalized_value,
                        COUNT(*) OVER (PARTITION BY TRIM(LOWER(REGEXP_REPLACE({column_name}, '\\s+', '')))) as dup_count
                    FROM {full_table}
                    WHERE {column_name} IS NOT NULL
                )
                SELECT *
                FROM normalized
                WHERE dup_count > 1
                LIMIT {limit}
                """

            cursor.execute(query)
            violations = [_convert_row_to_dict(row) for row in cursor.fetchall()]

            cursor.execute(f"SELECT COUNT(*) FROM {full_table}")
            total_rows = cursor.fetchone()[0]

            violation_count = len(violations)

            return {
                "rule_id": rule.get("id", f"{column_name}_{rule_type}".lower()),
                "rule_type": rule_type,
                "severity": rule.get("severity", "WARNING"),
                "column": column_name,
                "total_rows": total_rows,
                "violation_count": violation_count,
                "pass_rate": ((total_rows - violation_count) / total_rows * 100) if total_rows > 0 else 100.0,
                "violations": violations[:limit],
                "sql_query": query,
                "metadata": {
                    "method": method,
                    "threshold": similarity_threshold
                }
            }

        elif rule_type == "FOREIGN_KEY":
            # Cross-table validation: Check if values exist in reference table
            ref_database = params.get("ref_database", database)
            ref_schema = params.get("ref_schema", schema)
            ref_table = params.get("ref_table")
            ref_column = params.get("ref_column")

            if not ref_table or not ref_column:
                return {
                    "rule_id": rule.get("id", f"{column_name}_{rule_type}".lower()),
                    "rule_type": rule_type,
                    "severity": rule.get("severity", "CRITICAL"),
                    "column": column_name,
                    "error": "Missing ref_table or ref_column in params",
                    "total_rows": 0,
                    "violation_count": 0,
                    "pass_rate": 0.0,
                    "violations": [],
                    "sql_query": ""
                }

            ref_full_table = f"{ref_database}.{ref_schema}.{ref_table}"

            # Find values that don't exist in reference table
            query = f"""
            SELECT t.*
            FROM {full_table} t
            LEFT JOIN {ref_full_table} ref
                ON t.{column_name} = ref.{ref_column}
            WHERE t.{column_name} IS NOT NULL
                AND ref.{ref_column} IS NULL
            LIMIT {limit}
            """

            cursor.execute(query)
            violations = [_convert_row_to_dict(row) for row in cursor.fetchall()]

            # Get total count of violations
            count_query = f"""
            SELECT COUNT(*) as violation_count
            FROM {full_table} t
            LEFT JOIN {ref_full_table} ref
                ON t.{column_name} = ref.{ref_column}
            WHERE t.{column_name} IS NOT NULL
                AND ref.{ref_column} IS NULL
            """
            cursor.execute(count_query)
            violation_count = cursor.fetchone()[0]

            cursor.execute(f"SELECT COUNT(*) FROM {full_table}")
            total_rows = cursor.fetchone()[0]

            pass_rate = ((total_rows - violation_count) / total_rows * 100) if total_rows > 0 else 100.0

            return {
                "rule_id": rule.get("id", f"{column_name}_{rule_type}".lower()),
                "rule_type": rule_type,
                "severity": rule.get("severity", "CRITICAL"),
                "column": column_name,
                "total_rows": total_rows,
                "violation_count": violation_count,
                "pass_rate": pass_rate,
                "violations": violations[:limit],
                "sql_query": query,
                "metadata": {
                    "reference_table": ref_full_table,
                    "reference_column": ref_column
                }
            }

        elif rule_type == "MIN_VALUE":
            min_val = params.get("min")
            if min_val is not None:
                violation_condition = f"{column_name} < {min_val}"

        elif rule_type == "MAX_VALUE":
            max_val = params.get("max")
            if max_val is not None:
                violation_condition = f"{column_name} > {max_val}"

        elif rule_type == "ALLOWED_VALUES":
            allowed = params.get("allowed", [])
            if allowed:
                allowed_str = ", ".join([f"'{v}'" if isinstance(v, str) else str(v) for v in allowed])
                violation_condition = f"{column_name} NOT IN ({allowed_str}) AND {column_name} IS NOT NULL"

        elif rule_type == "MAX_LENGTH":
            max_len = params.get("max_length")
            if max_len is not None:
                violation_condition = f"LENGTH({column_name}) > {max_len}"

        elif rule_type == "PATTERN":
            pattern = params.get("pattern", "")
            if pattern:
                # Use RLIKE for regex matching
                violation_condition = f"{column_name} NOT RLIKE '{pattern}' AND {column_name} IS NOT NULL"

        elif rule_type == "MAX_AGE_DAYS":
            max_days = params.get("max_age_days")
            if max_days is not None:
                violation_condition = f"DATEDIFF(day, {column_name}, CURRENT_DATE()) > {max_days}"

        elif rule_type == "EXTERNAL_REFERENCE":
            # Validate against external reference data (INSEE SIRET, ISO codes, etc.)
            from reference_data_providers import (
                get_reference_registry,
                validate_with_cache,
                ensure_cache_tables
            )

            provider_id = params.get("provider_id")
            check_exists = params.get("check_exists", True)
            check_active = params.get("check_active", False)
            cache_enabled = params.get("cache_enabled", True)

            if not provider_id:
                return {
                    "rule_id": rule.get("id", f"{column_name}_{rule_type}".lower()),
                    "rule_type": rule_type,
                    "severity": rule.get("severity", "CRITICAL"),
                    "column": column_name,
                    "error": "Missing provider_id in params",
                    "total_rows": 0,
                    "violation_count": 0,
                    "pass_rate": 0.0,
                    "violations": [],
                    "sql_query": ""
                }

            # Get provider
            registry = get_reference_registry()
            provider = registry.get_provider(provider_id)

            if not provider:
                return {
                    "rule_id": rule.get("id", f"{column_name}_{rule_type}".lower()),
                    "rule_type": rule_type,
                    "severity": rule.get("severity", "CRITICAL"),
                    "column": column_name,
                    "error": f"Provider '{provider_id}' not found. Available: {[p['id'] for p in registry.list_providers()]}",
                    "total_rows": 0,
                    "violation_count": 0,
                    "pass_rate": 0.0,
                    "violations": [],
                    "sql_query": ""
                }

            # Ensure cache tables exist
            try:
                ensure_cache_tables(conn)
            except Exception as e:
                # Non-critical - continue without cache
                pass

            # Get distinct values to validate (optimization - don't validate duplicates)
            cursor.execute(f"""
                SELECT DISTINCT {column_name} as value
                FROM {full_table}
                WHERE {column_name} IS NOT NULL
            """)

            distinct_values = [row[0] for row in cursor.fetchall()]

            # Validate each distinct value
            validation_results = {}
            api_calls = 0

            for value in distinct_values:
                if cache_enabled:
                    result = validate_with_cache(conn, provider, value)
                else:
                    result = provider.validate_single(value)

                validation_results[value] = result

                # Track API calls
                if result and result.get("source") in ["API", "ERROR"]:
                    api_calls += 1

            # Find violations based on check criteria
            violation_values = []

            for value, result in validation_results.items():
                # Skip if result is None
                if result is None:
                    continue
                    
                is_violation = False

                if check_exists and not result.get("exists"):
                    is_violation = True

                if check_active and result.get("status") != "ACTIVE":
                    is_violation = True

                if is_violation:
                    violation_values.append(value)

            # Get sample violation rows
            if violation_values:
                placeholders = ",".join(["%s"] * min(len(violation_values), limit))
                sample_values = violation_values[:limit]

                query = f"""
                SELECT *
                FROM {full_table}
                WHERE {column_name} IN ({placeholders})
                LIMIT {limit}
                """
                cursor.execute(query, sample_values)
                violations = [_convert_row_to_dict(row) for row in cursor.fetchall()]
            else:
                violations = []
                query = f"-- No violations found for EXTERNAL_REFERENCE rule on {column_name}"

            # Calculate metrics
            cursor.execute(f"SELECT COUNT(*) FROM {full_table}")
            total_rows = cursor.fetchone()[0]

            # Count actual violation rows (not just distinct values)
            if violation_values:
                placeholders = ",".join(["%s"] * len(violation_values))
                cursor.execute(f"""
                    SELECT COUNT(*) FROM {full_table}
                    WHERE {column_name} IN ({placeholders})
                """, violation_values)
                violation_count = cursor.fetchone()[0]
            else:
                violation_count = 0

            pass_rate = ((total_rows - violation_count) / total_rows * 100) if total_rows > 0 else 100.0

            return {
                "rule_id": rule.get("id", f"{column_name}_{rule_type}".lower()),
                "rule_type": rule_type,
                "severity": rule.get("severity", "CRITICAL"),
                "column": column_name,
                "total_rows": total_rows,
                "violation_count": violation_count,
                "pass_rate": pass_rate,
                "violations": violations[:limit],
                "sql_query": query,
                "metadata": {
                    "provider": provider.provider_name,
                    "provider_id": provider_id,
                    "distinct_values_checked": len(distinct_values),
                    "distinct_violations": len(violation_values),
                    "api_calls_made": api_calls,
                    "cache_enabled": cache_enabled,
                    "check_exists": check_exists,
                    "check_active": check_active
                }
            }

        # If we have a lambda_hint, use it
        lambda_hint = rule.get("lambda_hint", "")
        if lambda_hint and not violation_condition:
            # Extract the condition from lambda hint like "lambda row: row['col'] > 0"
            # For SQL, we'll use the hint directly if it looks like SQL
            if "lambda" not in lambda_hint.lower():
                violation_condition = f"NOT ({lambda_hint})"

        # If still no condition, skip
        if not violation_condition:
            return {
                "rule_id": rule.get("id", f"{column_name}_{rule_type}".lower()),
                "rule_type": rule_type,
                "severity": rule.get("severity", "WARNING"),
                "column": column_name,
                "error": f"Unsupported rule type: {rule_type}",
                "total_rows": 0,
                "violation_count": 0,
                "pass_rate": 100.0,
                "violations": [],
                "sql_query": ""
            }

        # Execute standard violation query
        # Build WHERE clause with optional filter
        where_clause = violation_condition
        if filter_condition:
            where_clause = f"({violation_condition}) AND ({filter_condition})"

        query = f"""
        SELECT *
        FROM {full_table}
        WHERE {where_clause}
        LIMIT {limit}
        """

        cursor.execute(query)
        violations = [_convert_row_to_dict(row) for row in cursor.fetchall()]

        # Get total count of violations (with filter)
        count_query = f"""
        SELECT COUNT(*) as violation_count
        FROM {full_table}
        WHERE {where_clause}
        """
        try:
            cursor.execute(count_query)
            violation_count = cursor.fetchone()[0]
        except Exception as count_err:
            violation_count = 0

        # Get total rows (considering filter if provided)
        if filter_condition:
            total_rows_query = f"SELECT COUNT(*) FROM {full_table} WHERE {filter_condition}"
        else:
            total_rows_query = f"SELECT COUNT(*) FROM {full_table}"

        try:
            cursor.execute(total_rows_query)
            result = cursor.fetchone()
            total_rows = result[0] if result else 0
        except Exception as rows_err:
            total_rows = 0

        pass_rate = ((total_rows - violation_count) / total_rows * 100) if total_rows > 0 else 100.0

        return {
            "rule_id": rule.get("id", f"{column_name}_{rule_type}".lower()),
            "rule_type": rule_type,
            "severity": rule.get("severity", "WARNING"),
            "column": column_name,
            "total_rows": total_rows,
            "violation_count": violation_count,
            "pass_rate": pass_rate,
            "violations": violations[:limit],
            "sql_query": query
        }

    except Exception as e:
        # Safe handling when rule might be None or invalid
        rule_id = rule.get("id", f"{column_name}_unknown") if rule and isinstance(rule, dict) else f"{column_name}_unknown"
        rule_type = rule.get("type", "UNKNOWN") if rule and isinstance(rule, dict) else "UNKNOWN"
        severity = rule.get("severity", "WARNING") if rule and isinstance(rule, dict) else "WARNING"

        return {
            "rule_id": rule_id,
            "rule_type": rule_type,
            "severity": severity,
            "column": column_name if column_name else "unknown",
            "error": str(e),
            "total_rows": 0,
            "violation_count": 0,
            "pass_rate": 0.0,
            "violations": [],
            "sql_query": ""
        }
    finally:
        cursor.close()


def execute_table_rule(
    conn: SnowflakeConnection,
    database: str,
    schema: str,
    table: str,
    rule: dict,
    limit: int = 100
) -> dict:
    """
    Execute a single table-level (cross-column) data quality rule.

    Args:
        conn: Snowflake connection
        database: Database name
        schema: Schema name
        table: Table name
        rule: Rule definition dict with type, columns, params, etc.
        limit: Max violations to return

    Returns:
        dict with validation results
    """
    cursor = conn.cursor()
    try:
        full_table = f"{database}.{schema}.{table}"
        rule_type = rule.get("type", "")
        columns = rule.get("columns", [])
        params = rule.get("params", {})

        # Get optional filter to apply rule to subset of data
        filter_condition = params.get("filter", "")  # e.g., "main.status = 'ACTIVE'"

        violation_condition = ""

        if rule_type == "COMPOSITE_UNIQUE":
            # Check for duplicate combinations
            columns_str = ", ".join(columns)
            query = f"""
            WITH duplicates AS (
                SELECT {columns_str}, COUNT(*) as cnt
                FROM {full_table}
                GROUP BY {columns_str}
                HAVING COUNT(*) > 1
            )
            SELECT t.*, d.cnt as duplicate_count
            FROM {full_table} t
            JOIN duplicates d ON {" AND ".join([f"t.{c} = d.{c}" for c in columns])}
            LIMIT {limit}
            """
            cursor.execute(query)
            violations = [_convert_row_to_dict(row) for row in cursor.fetchall()]

            cursor.execute(f"SELECT COUNT(*) FROM {full_table}")
            total_rows = cursor.fetchone()[0]

            # Count violations
            count_query = f"""
            WITH duplicates AS (
                SELECT {columns_str}, COUNT(*) as cnt
                FROM {full_table}
                GROUP BY {columns_str}
                HAVING COUNT(*) > 1
            )
            SELECT SUM(cnt) FROM duplicates
            """
            cursor.execute(count_query)
            result = cursor.fetchone()
            violation_count = result[0] if result[0] is not None else 0

            return {
                "rule_id": rule.get("id", "_".join(columns).lower()),
                "rule_type": rule_type,
                "severity": rule.get("severity", "WARNING"),
                "columns": columns,
                "total_rows": total_rows,
                "violation_count": violation_count,
                "pass_rate": ((total_rows - violation_count) / total_rows * 100) if total_rows > 0 else 100.0,
                "violations": violations[:limit],
                "sql_query": query
            }

        elif rule_type == "CROSS_COLUMN_COMPARISON":
            # e.g., start_date < end_date
            if len(columns) >= 2:
                col1, col2 = columns[0], columns[1]
                operator = params.get("operator", "<")

                # Map operator
                if operator == "less_than" or operator == "<":
                    violation_condition = f"{col1} >= {col2}"
                elif operator == "greater_than" or operator == ">":
                    violation_condition = f"{col1} <= {col2}"
                elif operator == "equal" or operator == "=":
                    violation_condition = f"{col1} != {col2}"

        elif rule_type == "CONDITIONAL_REQUIRED":
            # If condition column has value, then required column must have value
            if len(columns) >= 2:
                condition_col = columns[0]
                required_col = columns[1]
                condition_value = params.get("condition_value")

                if condition_value:
                    violation_condition = f"{condition_col} = '{condition_value}' AND {required_col} IS NULL"

        elif rule_type == "MUTUAL_EXCLUSIVITY":
            # Only one of the columns should have a value
            if len(columns) >= 2:
                null_checks = [f"{c} IS NOT NULL" for c in columns]
                violation_condition = f"({' + '.join([f'CASE WHEN {c} IS NOT NULL THEN 1 ELSE 0 END' for c in columns])}) > 1"

        elif rule_type == "CONDITIONAL_VALUE":
            # If column1 = X, then column2 must = Y
            if len(columns) >= 2:
                col1, col2 = columns[0], columns[1]
                col1_value = params.get("if_value")
                col2_value = params.get("then_value")

                if col1_value and col2_value:
                    violation_condition = f"{col1} = '{col1_value}' AND {col2} != '{col2_value}'"

        elif rule_type == "MULTI_TABLE_AGGREGATE":
            # Validate that a column value matches an aggregation from other table(s)
            # Example: Order.total_amount = SUM(OrderLines.amount)

            target_column = params.get("target_column")  # Column to validate (e.g., total_amount)
            related_tables = params.get("related_tables", [])  # List of tables to join
            aggregate_expression = params.get("aggregate_expr")  # e.g., "SUM(ol.price * ol.quantity)"
            join_conditions = params.get("join_conditions", [])  # How to join tables
            tolerance = params.get("tolerance", 0.01)  # Allow small differences (e.g., rounding)

            if not target_column or not aggregate_expression:
                return {
                    "rule_id": rule.get("id", "multi_table_agg"),
                    "rule_type": rule_type,
                    "severity": rule.get("severity", "CRITICAL"),
                    "columns": columns,
                    "error": "Missing target_column or aggregate_expr in params",
                    "total_rows": 0,
                    "violation_count": 0,
                    "pass_rate": 0.0,
                    "violations": [],
                    "sql_query": ""
                }

            # Build JOIN clauses
            join_clauses = []
            for i, rel_table_def in enumerate(related_tables):
                rel_db = rel_table_def.get("database", database)
                rel_schema = rel_table_def.get("schema", schema)
                rel_table = rel_table_def.get("table")
                alias = rel_table_def.get("alias", f"t{i+1}")

                if rel_table:
                    full_rel_table = f"{rel_db}.{rel_schema}.{rel_table}"
                    join_type = rel_table_def.get("join_type", "LEFT JOIN")

                    if i < len(join_conditions):
                        join_clause = f"{join_type} {full_rel_table} {alias} ON {join_conditions[i]}"
                        join_clauses.append(join_clause)

            joins_str = "\n".join(join_clauses)

            # Build query to find violations
            # Compare actual value vs calculated aggregate
            query = f"""
            WITH aggregated AS (
                SELECT
                    main.*,
                    {aggregate_expression} as calculated_value
                FROM {full_table} main
                {joins_str}
                GROUP BY main.*
            )
            SELECT *
            FROM aggregated
            WHERE ABS(COALESCE({target_column}, 0) - COALESCE(calculated_value, 0)) > {tolerance}
            LIMIT {limit}
            """

            cursor.execute(query)
            violations = [_convert_row_to_dict(row) for row in cursor.fetchall()]

            # Get count
            count_query = f"""
            WITH aggregated AS (
                SELECT
                    main.*,
                    {aggregate_expression} as calculated_value
                FROM {full_table} main
                {joins_str}
                GROUP BY main.*
            )
            SELECT COUNT(*) as violation_count
            FROM aggregated
            WHERE ABS(COALESCE({target_column}, 0) - COALESCE(calculated_value, 0)) > {tolerance}
            """
            cursor.execute(count_query)
            violation_count = cursor.fetchone()[0]

            cursor.execute(f"SELECT COUNT(*) FROM {full_table}")
            total_rows = cursor.fetchone()[0]

            pass_rate = ((total_rows - violation_count) / total_rows * 100) if total_rows > 0 else 100.0

            return {
                "rule_id": rule.get("id", "multi_table_agg"),
                "rule_type": rule_type,
                "severity": rule.get("severity", "CRITICAL"),
                "columns": columns if columns else [target_column],
                "total_rows": total_rows,
                "violation_count": violation_count,
                "pass_rate": pass_rate,
                "violations": violations[:limit],
                "sql_query": query,
                "metadata": {
                    "target_column": target_column,
                    "aggregate_expression": aggregate_expression,
                    "related_tables": [t.get("table") for t in related_tables],
                    "tolerance": tolerance
                }
            }

        elif rule_type == "MULTI_TABLE_CONDITION":
            # Validate complex conditions across multiple tables
            # Example: Customer.status = 'VIP' only if SUM(Orders.amount) > 10000

            condition_sql = params.get("condition")  # SQL condition to check
            related_tables = params.get("related_tables", [])
            join_conditions = params.get("join_conditions", [])

            if not condition_sql:
                return {
                    "rule_id": rule.get("id", "multi_table_cond"),
                    "rule_type": rule_type,
                    "severity": rule.get("severity", "WARNING"),
                    "columns": columns,
                    "error": "Missing condition in params",
                    "total_rows": 0,
                    "violation_count": 0,
                    "pass_rate": 0.0,
                    "violations": [],
                    "sql_query": ""
                }

            # Build JOIN clauses
            join_clauses = []
            for i, rel_table_def in enumerate(related_tables):
                rel_db = rel_table_def.get("database", database)
                rel_schema = rel_table_def.get("schema", schema)
                rel_table = rel_table_def.get("table")
                alias = rel_table_def.get("alias", f"t{i+1}")

                if rel_table:
                    full_rel_table = f"{rel_db}.{rel_schema}.{rel_table}"
                    join_type = rel_table_def.get("join_type", "LEFT JOIN")

                    if i < len(join_conditions):
                        join_clause = f"{join_type} {full_rel_table} {alias} ON {join_conditions[i]}"
                        join_clauses.append(join_clause)

            joins_str = "\n".join(join_clauses)

            # Find records that violate the condition
            query = f"""
            SELECT main.*
            FROM {full_table} main
            {joins_str}
            WHERE NOT ({condition_sql})
            LIMIT {limit}
            """

            cursor.execute(query)
            violations = [_convert_row_to_dict(row) for row in cursor.fetchall()]

            # Get count
            count_query = f"""
            SELECT COUNT(*)
            FROM {full_table} main
            {joins_str}
            WHERE NOT ({condition_sql})
            """
            cursor.execute(count_query)
            violation_count = cursor.fetchone()[0]

            cursor.execute(f"SELECT COUNT(*) FROM {full_table}")
            total_rows = cursor.fetchone()[0]

            pass_rate = ((total_rows - violation_count) / total_rows * 100) if total_rows > 0 else 100.0

            return {
                "rule_id": rule.get("id", "multi_table_cond"),
                "rule_type": rule_type,
                "severity": rule.get("severity", "WARNING"),
                "columns": columns,
                "total_rows": total_rows,
                "violation_count": violation_count,
                "pass_rate": pass_rate,
                "violations": violations[:limit],
                "sql_query": query,
                "metadata": {
                    "condition": condition_sql,
                    "related_tables": [t.get("table") for t in related_tables]
                }
            }

        # Use lambda_hint if available and no condition built
        lambda_hint = rule.get("lambda_hint", "")
        if lambda_hint and not violation_condition:
            if "lambda" not in lambda_hint.lower():
                violation_condition = f"NOT ({lambda_hint})"

        if not violation_condition:
            return {
                "rule_id": rule.get("id", "_".join(columns).lower()),
                "rule_type": rule_type,
                "severity": rule.get("severity", "WARNING"),
                "columns": columns,
                "error": f"Unsupported rule type: {rule_type}",
                "total_rows": 0,
                "violation_count": 0,
                "pass_rate": 100.0,
                "violations": [],
                "sql_query": ""
            }

        # Execute violation query
        # Build WHERE clause with optional filter
        where_clause = violation_condition
        if filter_condition:
            where_clause = f"({violation_condition}) AND ({filter_condition})"

        query = f"""
        SELECT *
        FROM {full_table}
        WHERE {where_clause}
        LIMIT {limit}
        """

        cursor.execute(query)
        violations = [_convert_row_to_dict(row) for row in cursor.fetchall()]

        # Get counts (with filter)
        count_query = f"SELECT COUNT(*) FROM {full_table} WHERE {where_clause}"
        try:
            cursor.execute(count_query)
            violation_count = cursor.fetchone()[0]
        except Exception as count_err:
            violation_count = 0

        # Get total rows (considering filter if provided)
        if filter_condition:
            total_rows_query = f"SELECT COUNT(*) FROM {full_table} WHERE {filter_condition}"
        else:
            total_rows_query = f"SELECT COUNT(*) FROM {full_table}"

        try:
            cursor.execute(total_rows_query)
            result = cursor.fetchone()
            total_rows = result[0] if result else 0
        except Exception as rows_err:
            total_rows = 0

        pass_rate = ((total_rows - violation_count) / total_rows * 100) if total_rows > 0 else 100.0

        return {
            "rule_id": rule.get("id", "_".join(columns).lower()),
            "rule_type": rule_type,
            "severity": rule.get("severity", "WARNING"),
            "columns": columns,
            "total_rows": total_rows,
            "violation_count": violation_count,
            "pass_rate": pass_rate,
            "violations": violations[:limit],
            "sql_query": query
        }

    except Exception as e:
        # Safe handling when rule might be None or invalid
        rule_id = rule.get("id", "_".join(columns).lower() if columns else "unknown") if rule and isinstance(rule, dict) else ("_".join(columns).lower() if columns else "unknown")
        rule_type = rule.get("type", "UNKNOWN") if rule and isinstance(rule, dict) else "UNKNOWN"
        severity = rule.get("severity", "WARNING") if rule and isinstance(rule, dict) else "WARNING"

        return {
            "rule_id": rule_id,
            "rule_type": rule_type,
            "severity": severity,
            "columns": columns if columns else [],
            "error": str(e),
            "total_rows": 0,
            "violation_count": 0,
            "pass_rate": 0.0,
            "violations": [],
            "sql_query": ""
        }
    finally:
        cursor.close()


def execute_all_rules(
    conn: SnowflakeConnection,
    yaml_content: str,
    limit_per_rule: int = 100
) -> dict:
    """
    Execute all data quality rules defined in a semantic YAML.

    Args:
        conn: Snowflake connection
        yaml_content: YAML content as string
        limit_per_rule: Max violations to return per rule

    Returns:
        dict with:
            - summary: dict with overall stats
            - column_rules_results: list of results
            - table_rules_results: list of results
    """
    import yaml

    try:
        parsed = yaml.safe_load(yaml_content)
        sv = parsed.get("semantic_view", {})
        source = sv.get("source", {})

        database = source.get("database")
        schema = source.get("schema")
        table = source.get("table")

        if not all([database, schema, table]):
            return {
                "error": "Invalid YAML: missing source database/schema/table",
                "summary": {},
                "column_rules_results": [],
                "table_rules_results": []
            }

        # Execute column-level rules
        column_rules_results = []
        columns = sv.get("columns", [])

        for col in columns:
            col_name = col.get("name")
            dq_rules = col.get("dq_rules", [])

            for rule in dq_rules:
                if not isinstance(rule, dict):
                    continue

                result = execute_column_rule(
                    conn, database, schema, table,
                    col_name, rule, limit_per_rule
                )
                column_rules_results.append(result)

        # Execute table-level rules
        table_rules_results = []
        table_rules = sv.get("table_rules", [])

        for rule in table_rules:
            if not isinstance(rule, dict):
                continue

            result = execute_table_rule(
                conn, database, schema, table,
                rule, limit_per_rule
            )
            table_rules_results.append(result)

        # Calculate summary
        all_results = column_rules_results + table_rules_results
        total_rules = len(all_results)
        rules_with_violations = len([r for r in all_results if r.get("violation_count", 0) > 0])
        rules_passed = total_rules - rules_with_violations

        total_violations = sum([r.get("violation_count", 0) for r in all_results])

        critical_violations = sum([
            r.get("violation_count", 0)
            for r in all_results
            if r.get("severity") == "CRITICAL"
        ])

        warning_violations = sum([
            r.get("violation_count", 0)
            for r in all_results
            if r.get("severity") == "WARNING"
        ])

        info_violations = sum([
            r.get("violation_count", 0)
            for r in all_results
            if r.get("severity") == "INFO"
        ])

        # Get total rows from first result
        total_rows = all_results[0].get("total_rows", 0) if all_results else 0

        summary = {
            "total_rules": total_rules,
            "rules_passed": rules_passed,
            "rules_with_violations": rules_with_violations,
            "total_violations": total_violations,
            "critical_violations": critical_violations,
            "warning_violations": warning_violations,
            "info_violations": info_violations,
            "total_rows": total_rows,
            "overall_pass_rate": (rules_passed / total_rules * 100) if total_rules > 0 else 100.0
        }

        return {
            "summary": summary,
            "column_rules_results": column_rules_results,
            "table_rules_results": table_rules_results,
            "source": {"database": database, "schema": schema, "table": table}
        }

    except Exception as e:
        return {
            "error": str(e),
            "summary": {},
            "column_rules_results": [],
            "table_rules_results": []
        }
