"""Leon — Data Quality Platform."""

import html
import io
import json
import re
import requests
from datetime import datetime, timedelta, timezone

# Fuseau horaire France (UTC+1 hiver, UTC+2 été)
try:
    from zoneinfo import ZoneInfo
    TZ_FR = ZoneInfo("Europe/Paris")
except ImportError:
    TZ_FR = timezone(timedelta(hours=2))  # fallback été


def _now() -> datetime:
    return datetime.now(TZ_FR)

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import snowflake.connector as sf_connector
import streamlit as st
import streamlit.components.v1 as st_components

# ---------------------------------------------------------------------------
# Theme tokens
# ---------------------------------------------------------------------------

THEMES = {
    "light": {
        "sidebar_bg": "#1a2332",
        "content_bg": "#f8fafc",
        "card_bg": "#ffffff",
        "card_bg_elevated": "#ffffff",
        "border": "#e2e8f0",
        "border_subtle": "#f1f5f9",
        "text_primary": "#0f172a",
        "text_secondary": "#64748b",
        "accent": "#0d9488",
        "accent_soft": "rgba(13,148,136,0.08)",
        "accent_glow": "rgba(13,148,136,0.15)",
        "high": "#ef4444",
        "medium": "#f59e0b",
        "low": "#3b82f6",
        "success": "#10b981",
        "sidebar_text": "#e2e8f0",
        "nav_inactive": "#94a3b8",
        "nav_hover": "rgba(255,255,255,0.06)",
        "gradient_hero": "none",
        "gradient_card": "none",
    },
    "dark": {
        "sidebar_bg": "#0f172a",
        "content_bg": "#0c1322",
        "card_bg": "#1e293b",
        "card_bg_elevated": "#1e293b",
        "border": "#334155",
        "border_subtle": "#1e293b",
        "text_primary": "#f1f5f9",
        "text_secondary": "#94a3b8",
        "accent": "#2dd4bf",
        "accent_soft": "rgba(45,212,191,0.12)",
        "accent_glow": "rgba(45,212,191,0.20)",
        "high": "#f87171",
        "medium": "#fbbf24",
        "low": "#60a5fa",
        "success": "#34d399",
        "sidebar_text": "#e2e8f0",
        "nav_inactive": "#94a3b8",
        "nav_hover": "rgba(255,255,255,0.06)",
        "gradient_hero": "none",
        "gradient_card": "none",
    },
}

PAGES = [
    ("dashboard", "Tableau de bord", ":material/dashboard:"),
    ("customer_data", "Données clients", ":material/group:"),
    ("run_analysis", "Lancer l'analyse", ":material/play_circle:"),
    ("findings", "Anomalies", ":material/warning:"),
    ("tasks", "Tâches", ":material/checklist:"),
    ("exports", "Exports", ":material/download:"),
    ("france", "France", ":material/public:"),
    ("rule_catalog", "Catalogue de règles", ":material/menu_book:"),
]

TR_SEVERITY = {"All": "Tous", "HIGH": "Élevée", "MEDIUM": "Moyenne", "LOW": "Faible"}
TR_STATUS = {
    "All": "Tous", "Open": "Ouvert", "In Review": "En revue",
    "Resolved": "Résolu", "Dismissed": "Rejeté",
}
TR_SUBJECT = {
    "Compliance": "Conformité", "Duplicates": "Doublons",
    "Address": "Adresse", "Web": "Web",
}
TR_ACCOUNT_STATUS = {"Active": "Actif", "Inactive": "Inactif"}

SEVERITY_FILTER_OPTS = [("Tous", "All"), ("Élevée", "HIGH"), ("Moyenne", "MEDIUM"), ("Faible", "LOW")]
STATUS_FILTER_OPTS = [
    ("Tous", "All"), ("Ouvert", "Open"), ("En revue", "In Review"),
    ("Résolu", "Resolved"), ("Rejeté", "Dismissed"),
]


RULE_TEMPLATES = [
    {"id": "T-01", "name": "Contrôle conformité", "description": "Valide les identifiants légaux obligatoires (SIREN, TVA, forme juridique) selon la réglementation française.", "subject": "Compliance", "priority": "P1"},
    {"id": "T-02", "name": "Validation SIRET", "description": "Vérifie la clé SIRET et recoupe avec le registre INSEE SIRENE.", "subject": "Compliance", "priority": "P1"},
    {"id": "T-03", "name": "Détection de doublons", "description": "Identifie les doublons SIREN/SIRET dans la base clients.", "subject": "Duplicates", "priority": "P1"},
    {"id": "T-04", "name": "Fraîcheur code NAF", "description": "Contrôle les codes NAF/APE par rapport à la dernière nomenclature INSEE.", "subject": "Compliance", "priority": "P2"},
    {"id": "T-05", "name": "Validation adresse", "description": "Compare les adresses enregistrées avec le siège SIRENE.", "subject": "Address", "priority": "P2"},
    {"id": "T-06", "name": "Présence web", "description": "Vérifie la disponibilité du site corporate et la cohérence du domaine e-mail.", "subject": "Web", "priority": "P3"},
    {"id": "T-07", "name": "Format contact", "description": "Contrôle le format standard des téléphones et adresses e-mail.", "subject": "Compliance", "priority": "P3"},
]

ANALYSIS_SUBJECTS = [
    {"id": "compliance", "name": "Conformité", "description": "Identifiants légaux, TVA, champs réglementaires", "rules": 4, "priority": "P1"},
    {"id": "duplicates", "name": "Doublons", "description": "Détection de doublons SIREN/SIRET", "rules": 1, "priority": "P1"},
    {"id": "address", "name": "Adresse", "description": "Validation d'adresse vs INSEE", "rules": 1, "priority": "P2"},
    {"id": "web", "name": "Web", "description": "Vérification web : site, e-mail, croisement sources publiques", "rules": 2, "priority": "P3"},
]

# --- France : conformité SIREN / SIRET / TVA & e-facturation ----------------

FR_AUDIT_TABLES = [
    "QUALITY_TEST.COMMERCIAL_DATA.DIM_ACCOUNT",
    "QUALITY_TEST.COMMERCIAL_DATA.DIM_ESTABLISHMENT",
]

FR_DB_SCHEMAS = [
    "QUALITY_TEST.COMMERCIAL_DATA",
    "QUALITY_TEST.COMMERCIAL_DATA",
]

# Mapping fixe quand la source = table Snowflake connue (pas de détection nécessaire)
TABLE_COLUMN_MAPPING = {
    "QUALITY_TEST.COMMERCIAL_DATA.DIM_ACCOUNT": {
        "account_id": "account_id",
        "company_name": "company_name",
        "siren": "siren",
        "siret": "siret",
        "vat": "vat",
        "address": "address",
        "naf": "naf",
        "country": "country",
        "city": "city",
        "legal_form": "legal_form",
    },
    "QUALITY_TEST.COMMERCIAL_DATA.DIM_ESTABLISHMENT": {
        "account_id": "account_id",
        "company_name": "company_name",
        "siren": "siren",
        "siret": "siret",
        "vat": "vat",
        "address": "address",
        "naf": "naf",
        "country": "country",
        "city": "city",
        "legal_form": "legal_form",
    },
}

FR_SUBJECTS = [
    {
        "id": "compliance_einvoicing",
        "name": "Conformité & E-Facturation",
        "description": "Déclenche R01–R08 : SIREN, SIRET, cohérence SIREN+5, TVA intracom FR",
        "rules": ["R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08"],
    },
]

FR_BUSINESS_RULES = [
    {"id": "R01", "name": "Format SIREN", "check": "9 chiffres numériques"},
    {"id": "R02", "name": "Format SIRET", "check": "14 chiffres numériques"},
    {"id": "R03", "name": "Cohérence SIRET", "check": "SIRET = SIREN + 5 caractères"},
    {"id": "R04", "name": "TVA intracommunautaire", "check": "FR + 11 chiffres (clé Luhn)"},
    {"id": "R05", "name": "Pays FR", "check": "Code pays = FR pour comptes domestiques"},
    {"id": "R06", "name": "Code NAF/APE", "check": "Format XX.XXZ"},
    {"id": "R07", "name": "Forme juridique", "check": "Champ renseigné (SA, SAS, SARL…)"},
    {"id": "R08", "name": "Identifiant e-facturation", "check": "SIREN + SIRET valides pour PDP"},
]

STAGING_TABLE = "QUALITY_TEST.DATA_QUALITY.DQ_STAGING_IMPORT"

DEDUP_KEY_OPTIONS = {
    "siren": "SIREN",
    "siret": "SIRET",
    "account_id": "ID compte",
    "company_name": "Raison sociale",
    "vat": "N° TVA",
}

DEFAULT_DEDUP_KEYS = ["siren"]

DEDUP_STRATEGIES = {
    "keep_first": "Conserver la 1ère occurrence",
    "keep_last": "Conserver la dernière occurrence",
}

RULE_TYPES = {
    "regex": "Expression régulière",
    "not_empty": "Champ obligatoire",
    "in_list": "Valeur dans une liste",
    "length": "Longueur (min:max)",
}

# Alias colonnes pour import CSV / Excel (formats variés)
COLUMN_ALIASES = {
    "siren": ["siren", "num_siren", "no_siren", "idsiren", "siren_number", "code_siren"],
    "siret": ["siret", "num_siret", "no_siret", "idsiret", "siret_number", "code_siret", "commercial_registration", "commercial_registration_id", "registration_id"],
    "company_name": [
        "company_name", "raison_sociale", "raison sociale", "nom", "name", "company",
        "entreprise", "libelle", "libellé", "account_name", "account name", "account", "client",
        "afficher_nom", "afficher nom", "nom_societe", "nom société", "denomination",
        "societe", "société", "nom_entreprise", "nom entreprise", "billing account name",
        "subscription_name", "subscription name",
    ],
    "vat": ["vat", "tva", "vat_number", "num_tva", "tva_intra", "tva_intracom", "intracom_vat_id", "intracom vat id", "vat_id", "n_tva", "n_tva_intracom", "n° tva", "no tva", "n°_tva", "vat id", "tax_number", "tax number"],
    "address": ["address", "adresse", "adresse_siege", "adresse_siège", "street", "adresse_complete", "adresse_complète", "adresse complète", "adresse complete"],
    "city": ["city", "ville", "commune", "libelle_commune", "localite", "localité"],
    "naf": ["naf", "ape", "code_naf", "code_ape", "naf_code"],
    "country": ["country", "pays", "country_code", "code_pays", "bill_to_country", "bill to country"],
    "account_id": ["account_id", "id", "id_compte", "customer_id", "code_client", "ref", "record_id"],
    "legal_form": ["forme_juridique", "legal_form", "forme", "statut_juridique", "type_societe", "statut_legal"],
}

# Marketplace SIRENE database reference
_SIRENE_DB = "FRENCH_NATIONAL_IDENTIFICATION_SYSTEM_OF_DIRECTORY_OF_BUSINESSES_AND_THEIR_ESTABLISHMENTS"
_SIRENE_UL = f"{_SIRENE_DB}.SIRENE.V_UNITE_LEGALE"
_SIRENE_ETAB = f"{_SIRENE_DB}.SIRENE.V_ETABLISSEMENT"

IMPORT_FIELD_LABELS = {
    "siren": "SIREN",
    "siret": "SIRET",
    "company_name": "Raison sociale",
    "vat": "N° TVA intracom",
    "address": "Adresse",
    "city": "Ville",
    "naf": "Code NAF/APE",
    "country": "Pays",
    "account_id": "ID compte",
    "legal_form": "Forme juridique",
}

# ---------------------------------------------------------------------------
# Snowflake data access layer  (login page → password auth)
# ---------------------------------------------------------------------------


@st.cache_resource
def _build_conn(account: str, user: str, password: str, warehouse: str, passcode: str = "", authenticator: str = ""):
    """Create and cache a Snowflake connection via username/password (+MFA) or SSO."""
    params = dict(
        account=account,
        user=user,
        warehouse=warehouse,
        login_timeout=120,
    )
    if authenticator == "externalbrowser":
        params["authenticator"] = "externalbrowser"
    else:
        params["password"] = password
        if passcode:
            params["passcode"] = passcode
    return sf_connector.connect(**params)


def _get_conn():
    acc = st.session_state.get("sf_account", "")
    usr = st.session_state.get("sf_user", "")
    pwd = st.session_state.get("sf_password", "")
    wh = st.session_state.get("sf_warehouse", "COMPUTE_WH")
    mfa = st.session_state.get("sf_passcode", "")
    auth = st.session_state.get("sf_authenticator", "")
    if not acc or not usr:
        return None
    if not pwd and auth != "externalbrowser":
        return None
    try:
        return _build_conn(acc, usr, pwd, wh, mfa, auth)
    except Exception:
        return None


def _sf_query(sql: str) -> pd.DataFrame:
    """Execute SQL, return DataFrame with lowercase column names."""
    conn = _get_conn()
    if conn is None:
        return pd.DataFrame()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        if cur.description:
            cols = [d[0].lower() for d in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=cols)
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _sf_execute(sql: str, params: dict | None = None) -> None:
    """Execute a DML statement. Best-effort; session state is already updated."""
    conn = _get_conn()
    if conn is None:
        return
    try:
        conn.cursor().execute(sql, params or {})
    except Exception:
        pass


def _dim_account_fqn() -> str:
    db = st.session_state.get("sf_database", "")
    schema = st.session_state.get("sf_schema", "")
    table = st.session_state.get("sf_table", "DIM_ACCOUNT")
    return f"{db}.{schema}.{table}"


def _get_active_data() -> tuple:
    """Return (DataFrame, source_label) from uploaded file or Snowflake table."""
    if st.session_state.get("source_mode") == "file" and "uploaded_df" in st.session_state:
        df = st.session_state["uploaded_df"]
        label = st.session_state.get("uploaded_filename", "Fichier")
        return df, label
    fqn = _dim_account_fqn()
    raw = load_dim_account(fqn)
    df = pd.DataFrame(raw) if raw else pd.DataFrame()
    # Fallback: if Snowflake table is empty but we have an uploaded file, use it
    if df.empty and "uploaded_df" in st.session_state:
        df = st.session_state["uploaded_df"]
        label = st.session_state.get("uploaded_filename", "Fichier")
        return df, label
    return df, fqn


@st.cache_data(ttl=300)
def load_dim_account(fqn: str = "QUALITY_TEST.COMMERCIAL_DATA.DIM_ACCOUNT") -> list[dict]:
    df = _sf_query(f"SELECT * FROM {fqn}")
    return df.to_dict("records") if not df.empty else []


@st.cache_data(ttl=300, show_spinner=False)
def load_dq_findings() -> list[dict]:
    df = _sf_query(
        "SELECT id, account_id, company_name, severity, status, subject, rule_id, "
        "field, field_label, field_value, expected_value, finding_type, description, source_table "
        "FROM QUALITY_TEST.DATA_QUALITY.DQ_FINDINGS ORDER BY created_at DESC LIMIT 500"
    )
    return df.to_dict("records") if not df.empty else []


@st.cache_data(ttl=30)
def load_dq_audit_log() -> list[dict]:
    df = _sf_query(
        "SELECT * FROM QUALITY_TEST.DATA_QUALITY.DQ_AUDIT_LOG ORDER BY created_at DESC LIMIT 100"
    )
    if df.empty:
        return []
    if "created_at" in df.columns and "time" not in df.columns:
        df = df.rename(columns={"created_at": "time"})
    if "user_name" in df.columns and "user" not in df.columns:
        df = df.rename(columns={"user_name": "user"})
    return df.to_dict("records")


@st.cache_data(ttl=300)
def load_sirene_cache() -> dict:
    """Load SIRENE references for accounts in DIM_ACCOUNT from the real Marketplace SIRENE."""
    sirens_df = _sf_query("SELECT DISTINCT siren FROM QUALITY_TEST.COMMERCIAL_DATA.DIM_ACCOUNT WHERE siren IS NOT NULL AND siren <> ''")
    if sirens_df.empty:
        return {}
    siren_list = ",".join(f"'{s}'" for s in sirens_df['siren'].tolist() if s)
    df = _sf_query(f"""
        SELECT u.SIREN AS siren,
               u.DENOMINATION AS raison_sociale,
               u.SIREN || u.NIC_SIEGE AS siret,
               u.ACTIVITE_PRINCIPALE AS naf,
               u.ETAT_ADMINISTRATIF AS statut,
               u.CATEGORIE_JURIDIQUE AS categorie_juridique,
               e.LIBELLE_COMMUNE || ' ' || COALESCE(e.CODE_POSTAL, '') AS adresse
        FROM {_SIRENE_UL} u
        LEFT JOIN {_SIRENE_ETAB} e ON e.SIRET = u.SIREN || u.NIC_SIEGE
        WHERE u.SIREN IN ({siren_list})
    """)
    if df.empty:
        return {}
    return {str(row["siren"]): row for row in df.to_dict("records")}


@st.cache_data(ttl=60)
@st.cache_data(ttl=300)
def lookup_sirene(siren: str) -> dict | None:
    """Look up a single SIREN in the real Marketplace SIRENE (29M+ records)."""
    if not siren or len(siren) != 9:
        return None
    df = _sf_query(f"""
        SELECT u.SIREN AS siren,
               u.DENOMINATION AS raison_sociale,
               u.SIREN || u.NIC_SIEGE AS siret,
               u.ACTIVITE_PRINCIPALE AS naf,
               u.ETAT_ADMINISTRATIF AS statut,
               u.CATEGORIE_JURIDIQUE AS categorie_juridique,
               e.LIBELLE_COMMUNE || ' ' || COALESCE(e.CODE_POSTAL, '') AS adresse
        FROM {_SIRENE_UL} u
        LEFT JOIN {_SIRENE_ETAB} e ON e.SIRET = u.SIREN || u.NIC_SIEGE
        WHERE u.SIREN = '{siren}'
        LIMIT 1
    """)
    if df.empty:
        return None
    return df.to_dict("records")[0]


@st.cache_data(ttl=300)
def load_compliance_trend(days: int = 30) -> list[dict]:
    df = _sf_query(f"""
        SELECT DATE_TRUNC('DAY', created_at) AS date,
               ROUND(100.0 * SUM(CASE WHEN status = 'Resolved' THEN 1 ELSE 0 END)
                     / COUNT(*), 1) AS score
        FROM QUALITY_TEST.DATA_QUALITY.DQ_FINDINGS
        WHERE created_at >= DATEADD('day', -{days}, CURRENT_DATE())
        GROUP BY 1 ORDER BY 1
    """)
    return df.to_dict("records") if not df.empty else []


@st.cache_data(ttl=60)
def load_rule_hits() -> list[dict]:
    df = _sf_query(
        "SELECT rule_id AS rule, COUNT(*) AS hits "
        "FROM QUALITY_TEST.DATA_QUALITY.DQ_FINDINGS GROUP BY rule_id ORDER BY hits DESC"
    )
    return df.to_dict("records") if not df.empty else []


@st.cache_data(ttl=60)
def load_dq_dimensions() -> list[dict]:
    df = _sf_query(
        "SELECT subject AS dimension, "
        "ROUND(100.0 * SUM(CASE WHEN status='Resolved' THEN 1 ELSE 0 END) / COUNT(*), 0) AS score "
        "FROM QUALITY_TEST.DATA_QUALITY.DQ_FINDINGS GROUP BY subject"
    )
    return df.to_dict("records") if not df.empty else []


def write_dq_correction_db(c: dict) -> None:
    _sf_execute(
        "INSERT INTO QUALITY_TEST.DATA_QUALITY.DQ_CORRECTIONS "
        "(id, anomaly_id, account_id, company_name, field, field_value, expected_value, "
        "rule_id, action, rejection_reason, correction_status) "
        "VALUES (%(id)s, %(anomaly_id)s, %(account_id)s, %(company_name)s, %(field)s, "
        "%(field_value)s, %(expected_value)s, %(rule_id)s, %(action)s, "
        "%(rejection_reason)s, %(status)s)",
        c,
    )
    load_dq_findings.clear()


def update_finding_status_db(finding_id: str, status: str) -> None:
    _sf_execute(
        "UPDATE QUALITY_TEST.DATA_QUALITY.DQ_FINDINGS SET status = %(status)s WHERE id = %(id)s",
        {"status": status, "id": finding_id},
    )
    load_dq_findings.clear()


def write_audit_log_db(action: str, detail: str, user: str = "") -> None:
    if not user:
        user = st.session_state.get("sf_user", "unknown")
    _sf_execute(
        "INSERT INTO QUALITY_TEST.DATA_QUALITY.DQ_AUDIT_LOG (action, detail, user_name) "
        "VALUES (%(action)s, %(detail)s, %(user)s)",
        {"action": action, "detail": detail, "user": user},
    )
    load_dq_audit_log.clear()


def call_sp_business_rules(table: str) -> str:
    df = _sf_query(f"CALL QUALITY_TEST.DATA_QUALITY.SP_EXECUTE_BUSINESS_RULES('{table}')")
    if not df.empty:
        load_dq_findings.clear()
        return str(df.iloc[0, 0])
    return "Erreur: pas de résultat SP"


# ---------------------------------------------------------------------------
# Custom Rules CRUD (persisted to Snowflake)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def list_custom_rules(active_only: bool = True) -> list[dict]:
    where = "WHERE is_active = TRUE" if active_only else ""
    df = _sf_query(f"SELECT * FROM QUALITY_TEST.DATA_QUALITY.DQ_CUSTOM_RULES {where} ORDER BY created_at DESC")
    if df.empty:
        return []
    df.columns = [c.lower() for c in df.columns]
    return df.to_dict("records")


def create_custom_rule(name: str, target_field: str, rule_type: str, pattern: str, severity: str, description: str = "") -> str:
    existing = list_custom_rules(active_only=False)
    cid = f"C{len(existing) + 1:03d}"
    _sf_execute(
        "INSERT INTO QUALITY_TEST.DATA_QUALITY.DQ_CUSTOM_RULES "
        "(id, name, description, target_field, rule_type, pattern, severity) "
        "VALUES (%(id)s, %(name)s, %(desc)s, %(field)s, %(type)s, %(pattern)s, %(sev)s)",
        {"id": cid, "name": name, "desc": description, "field": target_field,
         "type": rule_type, "pattern": pattern, "sev": severity},
    )
    list_custom_rules.clear()
    add_audit_entry("Règle créée", f"{cid}: {name} ({target_field}, {rule_type})")
    return cid


def toggle_custom_rule(rule_id: str, active: bool):
    _sf_execute(
        "UPDATE QUALITY_TEST.DATA_QUALITY.DQ_CUSTOM_RULES SET is_active = %(active)s WHERE id = %(id)s",
        {"active": active, "id": rule_id},
    )
    list_custom_rules.clear()


def delete_custom_rule(rule_id: str):
    _sf_execute(
        "DELETE FROM QUALITY_TEST.DATA_QUALITY.DQ_CUSTOM_RULES WHERE id = %(id)s",
        {"id": rule_id},
    )
    list_custom_rules.clear()
    add_audit_entry("Règle supprimée", rule_id)


# ---------------------------------------------------------------------------
# Table columns + Cortex AI helpers (JOIN key + rule suggestions)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=120)
def load_table_columns(table_fqn: str) -> list[str]:
    """Return column names for any Snowflake table."""
    df = _sf_query(f"SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_CATALOG || '.' || TABLE_SCHEMA || '.' || TABLE_NAME = '{table_fqn.upper()}' ORDER BY ORDINAL_POSITION")
    if df.empty:
        parts = table_fqn.split(".")
        if len(parts) == 3:
            df = _sf_query(f"SHOW COLUMNS IN TABLE {table_fqn}")
            if not df.empty:
                col_name = "column_name" if "column_name" in df.columns else df.columns[2]
                return df[col_name].tolist()
        return []
    return df.iloc[:, 0].tolist()


def suggest_join_key_cortex(primary_cols: list[str], secondary_cols: list[str],
                            primary_table: str, secondary_table: str) -> dict:
    """Use Cortex AI to suggest the best JOIN key between two tables."""
    prompt = (
        f"Given two Snowflake tables:\n"
        f"Table A ({primary_table}): columns = {primary_cols}\n"
        f"Table B ({secondary_table}): columns = {secondary_cols}\n\n"
        f"Which columns should be used as the JOIN key? Pick the most likely pair based on naming conventions and semantics.\n"
        f'Return ONLY a JSON object: {{"primary_key": "COLUMN_FROM_A", "secondary_key": "COLUMN_FROM_B", "confidence": "high|medium|low"}}'
    )
    try:
        result = _sf_query(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', $${prompt}$$) AS r")
        raw = result.iloc[0]["r"] if not result.empty else "{}"
        # Extract JSON from response
        start = raw.index("{")
        end = raw.rindex("}") + 1
        return json.loads(raw[start:end])
    except Exception:
        return {"primary_key": primary_cols[0] if primary_cols else "", "secondary_key": secondary_cols[0] if secondary_cols else "", "confidence": "low"}


def suggest_rules_cortex(table_fqn: str, columns: list[str], sample_rows: list[dict]) -> list[dict]:
    """Use Cortex AI to suggest data quality rules for a table."""
    prompt = (
        f"Analyse cette table Snowflake pour détecter des problèmes de qualité de données.\n"
        f"Table: {table_fqn}\n"
        f"Colonnes: {columns}\n"
        f"Échantillon (3 lignes): {json.dumps(sample_rows[:3], default=str)}\n\n"
        f"Suggère 3 à 5 règles de qualité de données. Pour chaque règle retourne un objet JSON:\n"
        f'- "name": nom descriptif en français\n'
        f'- "target_field": nom exact de la colonne (de la liste ci-dessus)\n'
        f'- "rule_type": un parmi "regex", "not_empty", "in_list", "length"\n'
        f'- "pattern": le pattern de validation (regex, ou "min:max" pour length, ou liste séparée par des virgules pour in_list)\n'
        f'- "severity": "HIGH", "MEDIUM", ou "LOW"\n'
        f'- "description": description en une ligne en français\n\n'
        f"Retourne UNIQUEMENT un tableau JSON (pas de texte autour)."
    )
    try:
        result = _sf_query(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', $${prompt}$$) AS r")
        raw = result.iloc[0]["r"] if not result.empty else "[]"
        start = raw.index("[")
        end = raw.rindex("]") + 1
        rules = json.loads(raw[start:end])
        # Validate each rule has required keys
        valid = []
        for r in rules:
            if all(k in r for k in ("name", "target_field", "rule_type")):
                r.setdefault("pattern", "")
                r.setdefault("severity", "MEDIUM")
                r.setdefault("description", "")
                valid.append(r)
        return valid
    except Exception:
        return []

def persist_scoring(run_id: str, scores: list[dict]):
    if not scores:
        return
    for s in scores:
        _sf_execute(
            "INSERT INTO QUALITY_TEST.DATA_QUALITY.DQ_SCORING "
            "(run_id, account_id, row_num, score, rules_passed, rules_total, flags) "
            "VALUES (%(run_id)s, %(account_id)s, %(row_num)s, %(score)s, %(passed)s, %(total)s, %(flags)s)",
            {"run_id": run_id, "account_id": s.get("account_id", ""),
             "row_num": s.get("row_num", 0), "score": s.get("score", 0),
             "passed": s.get("rules_passed", 0), "total": s.get("rules_total", 0),
             "flags": json.dumps(s.get("flags", []))},
        )


def persist_dedup_result(run_id: str, source_table: str, original: int, clean: int, removed: int, keys: list, strategy: str, fuzzy_threshold: float = 0.0):
    _sf_execute(
        "INSERT INTO QUALITY_TEST.DATA_QUALITY.DQ_DEDUP_RESULTS "
        "(run_id, source_table, original_count, clean_count, removed_count, dedup_keys, strategy, fuzzy_threshold) "
        "VALUES (%(run_id)s, %(src)s, %(orig)s, %(clean)s, %(rem)s, %(keys)s, %(strat)s, %(fuzzy)s)",
        {"run_id": run_id, "src": source_table, "orig": original, "clean": clean,
         "rem": removed, "keys": ",".join(keys), "strat": strategy, "fuzzy": fuzzy_threshold},
    )


@st.cache_data(ttl=60)
def load_scoring(run_id: str = "") -> list[dict]:
    where = f"WHERE run_id = '{run_id}'" if run_id else ""
    df = _sf_query(f"SELECT * FROM QUALITY_TEST.DATA_QUALITY.DQ_SCORING {where} ORDER BY row_num")
    if df.empty:
        return []
    df.columns = [c.lower() for c in df.columns]
    return df.to_dict("records")


@st.cache_data(ttl=600)
def list_snowflake_databases() -> list[str]:
    df = _sf_query("SHOW DATABASES")
    if df.empty:
        return []
    col = "name" if "name" in df.columns else df.columns[0]
    return sorted(df[col].tolist())


@st.cache_data(ttl=300)
def list_snowflake_schemas(database: str) -> list[str]:
    df = _sf_query(f"SHOW SCHEMAS IN DATABASE {database}")
    if df.empty:
        return []
    col = "name" if "name" in df.columns else df.columns[0]
    return [s for s in sorted(df[col].tolist()) if s not in ("INFORMATION_SCHEMA", "PUBLIC")]


@st.cache_data(ttl=300)
def list_snowflake_tables(database: str, schema: str) -> list[str]:
    df = _sf_query(f"SHOW TABLES IN SCHEMA {database}.{schema}")
    if df.empty:
        return []
    col = "name" if "name" in df.columns else df.columns[0]
    return sorted(df[col].tolist())


def load_table_as_dataframe(table: str) -> pd.DataFrame:
    df = _sf_query(f"SELECT * FROM {table} LIMIT 5000")
    if df.empty:
        return pd.DataFrame(columns=["ACCOUNT_ID", "COMPANY_NAME", "SIREN", "SIRET", "ADDRESS", "NAF"])
    # Snowflake returns uppercase columns — keep them as-is
    df.columns = [c.upper() for c in df.columns]
    return df


def _mapping_for_table(table_fqn: str, df_columns: list[str] | None = None) -> dict[str, str | None]:
    """Return column mapping for a known Snowflake table or auto-detect from headers."""
    if table_fqn in TABLE_COLUMN_MAPPING:
        fixed = TABLE_COLUMN_MAPPING[table_fqn]
        mapping = {field: col for field, col in fixed.items() if col}
        # Normalize to lowercase (Snowflake returns lowercase from _sf_query)
        if df_columns:
            df_cols_lower = [c.lower() for c in df_columns]
            for field, col in list(mapping.items()):
                if col and col not in df_columns and col.lower() in df_cols_lower:
                    mapping[field] = col.lower()
            auto = detect_column_mapping(list(df_columns))
            for field, col in auto.items():
                if field not in mapping and col:
                    mapping[field] = col
        return mapping
    if df_columns:
        return detect_column_mapping(list(df_columns))
    return {field: None for field in IMPORT_FIELD_LABELS}


def _auto_correct_finding(f: dict) -> str:
    """Smart correction using Snowflake EDITDISTANCE + SOUNDEX fuzzy matching on INSEE SIRENE.
    Multi-strategy: TVA→SIREN, SIRET→SIREN, SIREN padding, fuzzy name+city+CP search.
    Returns 'corrected_value (confiance: XX% — sources)' or empty string."""
    company = f.get("company_name", "")
    field = f.get("field", "").upper()
    field_value = f.get("field_value", "")
    account_id = f.get("account_id", "")
    expected = f.get("expected_value", "")

    # --- Quick path: if expected_value already contains a concrete value, use it ---
    # (calculated during analysis from INSEE/derivation)
    _generic_expected = {
        "9 chiffres", "9 chiffres numériques", "14 chiffres", "14 chiffres numériques",
        "FR + 11 caractères", "TVA FR obligatoire", "Non vide", "XX.XXZ",
        "XX.XXZ (ex : 6202A)", "SA, SAS, SARL, SE…", "Active (A)",
        "Présent au registre SIRENE", "Format XXXXZ (4 chiffres + 1 lettre)",
    }
    if expected and expected not in _generic_expected and not expected.startswith("Valeur parmi"):
        # Check if expected looks like a real value (not just a format description)
        _is_concrete = (
            re.match(r'^FR\d{11}$', expected)  # TVA
            or re.match(r'^\d{9}$', expected)  # SIREN
            or re.match(r'^\d{14}$', expected)  # SIRET
            or re.match(r'^\d{4}[A-Z]$', expected)  # NAF
            or ("INSEE" in f.get("finding_type", "") and len(expected) > 3)
        )
        if _is_concrete:
            return f"{expected} (confiance: 90% — INSEE)"

    # Non-identity fields → Cortex AI directly
    if field not in ("SIREN", "SIRET", "VAT_NUMBER", "NAF"):
        prompt = (
            f"Corrige cette valeur:\nChamp: {f.get('field_label', '')}\n"
            f"Valeur: {field_value}\nAttendu: {expected}\n"
            f"Entreprise: {company}\nRetourne UNIQUEMENT la valeur corrigée."
        )
        try:
            r = _sf_query(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', $${prompt}$$) AS r")
            result = r.iloc[0]["r"].strip() if not r.empty else ""
            return f"{result} (confiance: 50%)" if result else ""
        except Exception:
            return ""

    # --- Identity fields: cross-validate using all available data ---
    city = ""
    postal_code = ""
    existing_siren = ""
    existing_siret = ""
    existing_vat = ""

    try:
        _accounts = load_dim_account(_dim_account_fqn())
        account_row = next((a for a in _accounts if str(a.get("account_id", "")).strip().upper() == str(account_id).strip().upper()), None)
        if not account_row:
            account_row = next((a for a in _accounts if company.upper() in str(a.get("company_name", "") or a.get("raison_sociale", "")).upper()), None)
        if account_row:
            city = str(account_row.get("city", "") or account_row.get("ville", "") or "").strip()
            postal_code = str(account_row.get("postal_code", "") or account_row.get("code_postal", "") or "").strip()
            if not postal_code and city:
                _cp_match = re.search(r'\b(\d{5})\b', city)
                if _cp_match:
                    postal_code = _cp_match.group(1)
            existing_siren = str(account_row.get("siren", "") or "").strip().replace(" ", "")
            existing_siret = str(account_row.get("siret", "") or "").strip().replace(" ", "")
            existing_vat = str(account_row.get("vat", "") or account_row.get("tva_intra", "") or account_row.get("tva", "") or "").strip().upper().replace(" ", "")
            if not company:
                company = str(account_row.get("company_name", "") or account_row.get("raison_sociale", "") or "").strip()
    except Exception:
        pass

    # --- Strategy: find valid SIREN from ANY available field ---
    found_siren = ""
    source = ""
    confidence = 0

    # 1. Extract SIREN from VAT (FR + 2 digits + 9 digits SIREN) — highest confidence
    if existing_vat and existing_vat.startswith("FR") and len(existing_vat) >= 13:
        potential_siren = existing_vat[-9:]
        if potential_siren.isdigit():
            ref = lookup_sirene(potential_siren)
            if ref:
                found_siren = potential_siren
                source = "TVA"
                confidence = 95

    # 2. Extract SIREN from SIRET (first 9 digits)
    if not found_siren and existing_siret and len(existing_siret) >= 9:
        potential_siren = re.sub(r'\D', '', existing_siret)[:9]
        if len(potential_siren) == 9:
            ref = lookup_sirene(potential_siren)
            if ref:
                found_siren = potential_siren
                source = "SIRET"
                confidence = 92

    # 3. Try existing SIREN (even if flagged invalid — maybe just needs padding)
    if not found_siren and existing_siren:
        digits = re.sub(r'\D', '', existing_siren)
        if len(digits) >= 8:
            padded = digits.zfill(9)[:9]
            ref = lookup_sirene(padded)
            if ref:
                found_siren = padded
                source = "SIREN corrigé"
                confidence = 88

    # 4. Fuzzy search by name + city + CP in INSEE (EDITDISTANCE + SOUNDEX)
    if not found_siren and company and len(company) >= 3:
        insee_match = _insee_search_by_name(company, city, postal_code)
        if insee_match and insee_match.get("siren"):
            found_siren = str(insee_match["siren"]).strip()
            # Compute confidence from scores
            total_score = float(insee_match.get("total_score", 0) or 0)
            confidence = min(int(total_score), 99)
            sources = ["nom"]
            if float(insee_match.get("city_score", 0) or 0) > 0:
                sources.append("ville")
            if float(insee_match.get("cp_score", 0) or 0) > 0:
                sources.append("CP")
            source = "+".join(sources)

    # 5. If nothing found → do NOT hallucinate identity numbers
    if not found_siren:
        # For identity fields, only return values confirmed by INSEE — never AI-generated
        return ""

    # --- We have a valid SIREN — cross-validate for extra confidence ---
    ref = lookup_sirene(found_siren)
    if ref and confidence < 90:
        # Boost confidence based on cross-validation
        ref_name = str(ref.get("raison_sociale", "") or ref.get("denomination", "")).upper()
        if company and ref_name:
            from difflib import SequenceMatcher
            sim = SequenceMatcher(None, company.upper()[:30], ref_name[:30]).ratio()
            if sim > 0.6:
                confidence = min(confidence + 10, 99)
                if "nom" not in source:
                    source += "+nom"
        ref_addr = str(ref.get("adresse", "")).upper()
        if city and city.upper() in ref_addr:
            confidence = min(confidence + 5, 99)
        if postal_code and postal_code in ref_addr:
            confidence = min(confidence + 5, 99)

    # Reject low-confidence corrections — don't propose unreliable replacements
    if confidence < 75:
        return ""

    # Don't replace an existing valid SIREN with a different one at low confidence
    if field == "SIREN" and existing_siren and len(existing_siren) == 9 and existing_siren.isdigit():
        if found_siren != existing_siren and confidence < 85:
            return ""

    # Build the corrected value
    corrected = ""
    if field == "SIREN":
        corrected = found_siren
    elif field == "SIRET":
        if ref and ref.get("siret"):
            corrected = str(ref["siret"])
        else:
            corrected = found_siren + "00000"
    elif field == "VAT_NUMBER":
        corrected = _vat_from_siren(found_siren)
    elif field == "NAF":
        if ref and ref.get("naf"):
            corrected = str(ref["naf"])
        elif ref and ref.get("activite_principale"):
            corrected = str(ref["activite_principale"])

    if corrected:
        return f"{corrected} (confiance: {confidence}% — {source})"
    return ""


# ---------------------------------------------------------------------------
# Web Verification Agent — AI-assisted web cross-check
# ---------------------------------------------------------------------------

def _web_verify_finding(finding: dict) -> dict:
    """Verify a finding by searching the web and using LLM to judge coherence."""
    company = finding.get("company_name", "")
    field_label = finding.get("field_label", "")
    field_value = str(finding.get("field_value", "") or "—")
    expected = str(finding.get("expected_value", "") or "")
    rule_id = finding.get("rule_id", "")
    account_id = finding.get("account_id", "")

    sources = []
    web_snippets = []

    # --- 1. Contextual web search based on field type ---
    try:
        # Pappers (free SIREN lookup)
        siren_val = ""
        if "siren" in field_label.lower() or rule_id in ("R01", "R03", "INSEE"):
            siren_val = expected if expected and expected.isdigit() and len(expected) == 9 else field_value
            if siren_val and siren_val.replace(" ", "").isdigit() and len(siren_val.replace(" ", "")) == 9:
                try:
                    r = requests.get(f"https://api.pappers.fr/v2/entreprise?siren={siren_val.strip()}", timeout=8)
                    if r.status_code == 200:
                        data = r.json()
                        web_snippets.append(
                            f"Pappers.fr: {data.get('denomination', '?')} — "
                            f"SIREN {data.get('siren', '?')}, "
                            f"forme juridique: {data.get('forme_juridique', '?')}, "
                            f"siège: {data.get('siege', {}).get('adresse_ligne_1', '?')} {data.get('siege', {}).get('code_postal', '')} {data.get('siege', {}).get('ville', '')}, "
                            f"statut: {'Active' if data.get('entreprise_cessee') == False else 'Cessée'}"
                        )
                        sources.append("pappers.fr")
                except Exception:
                    pass

        # Company website check
        if company:
            _search_name = company.replace(" ", "+").replace("&", "%26")
            try:
                r = requests.get(
                    f"https://www.google.com/search?q={_search_name}+entreprise+france+siren",
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=8,
                )
                if r.status_code == 200:
                    # Extract snippets from Google results (basic)
                    import re as _re
                    _snippets = _re.findall(r'<span[^>]*>(.*?)</span>', r.text)
                    _useful = [s for s in _snippets if len(s) > 40 and company.split()[0].lower() in s.lower()][:3]
                    if _useful:
                        web_snippets.append("Google: " + " | ".join(_useful[:2]))
                        sources.append("google.com")
            except Exception:
                pass

        # Societe.com check for SIREN
        if siren_val and siren_val.strip().isdigit():
            try:
                r = requests.get(f"https://www.societe.com/cgi-bin/search?champs={siren_val.strip()}", timeout=8, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200 and company.split()[0].lower() in r.text.lower():
                    sources.append("societe.com")
                    web_snippets.append(f"Societe.com: entreprise trouvée pour SIREN {siren_val}")
            except Exception:
                pass

    except Exception:
        pass

    # --- 2. Fallback: use Cortex LLM knowledge if no web results ---
    if not web_snippets:
        web_snippets.append("(Aucune source web accessible — utilisation des connaissances du modèle)")
        sources.append("connaissances LLM")

    web_summary = "\n".join(web_snippets)

    # --- 3. LLM Judgment ---
    prompt = f"""Tu es un agent de vérification de données B2B françaises.
Entreprise: {company}
Champ vérifié: {field_label}
Valeur en base: {field_value}
Valeur attendue/référence: {expected}
Règle déclenchée: {rule_id}

Informations web trouvées:
{web_summary}

Analyse cette anomalie et réponds UNIQUEMENT en JSON valide (pas de markdown):
{{"verdict": "coherent" ou "incoherent" ou "incertain", "confidence": nombre entre 0 et 100, "explanation": "explication en français (2-3 phrases max)", "suggested_value": "valeur corrigée ou null si pas de correction", "suggested_action": "action recommandée en français (1 phrase)"}}"""

    try:
        _safe_prompt = prompt.replace("$$", "\\$\\$")
        result = _sf_query(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', $${_safe_prompt}$$) AS r")
        if not result.empty:
            import json as _json
            raw = str(result.iloc[0]["r"]).strip()
            # Clean markdown code block if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            verdict_data = _json.loads(raw)
        else:
            verdict_data = {"verdict": "incertain", "confidence": 30, "explanation": "Impossible d'obtenir un jugement.", "suggested_value": None, "suggested_action": "Vérification manuelle recommandée"}
    except Exception as e:
        verdict_data = {"verdict": "incertain", "confidence": 20, "explanation": f"Erreur lors du jugement: {str(e)[:100]}", "suggested_value": None, "suggested_action": "Vérification manuelle recommandée"}

    return {
        "company": company,
        "field_label": field_label,
        "field_value": field_value,
        "expected_value": expected,
        "sources": sources,
        "web_summary": web_summary,
        **verdict_data,
    }

# ---------------------------------------------------------------------------
# 3-Phase Deduplication Pipeline
# ---------------------------------------------------------------------------

def _dedup_create_backup(df: pd.DataFrame, source_name: str) -> str:
    """Create backup of original data. Returns backup identifier. NEVER modifies original."""
    ts = _now().strftime("%Y%m%d%H%M%S")
    backup_key = f"DQ_BACKUP_{ts}"
    st.session_state["dedup_backup_df"] = df.copy()
    st.session_state["dedup_backup_name"] = backup_key
    st.session_state["dedup_original_source"] = source_name
    # Also persist to Snowflake for durability
    backup_fqn = f"QUALITY_TEST.DATA_QUALITY.{backup_key}"
    stage_dataframe_to_snowflake(df, backup_fqn)
    return backup_fqn


def _dedup_phase1_exact(df: pd.DataFrame, cols: list[str] | None = None) -> tuple[pd.DataFrame, list[dict]]:
    """Phase 1: Detect exact duplicate rows by business key.
    Finds rows sharing the same SIREN, or same normalized company name.
    Returns (working_df_unchanged, groups_of_exact_duplicates)."""
    work_cols = cols or list(df.columns)
    groups = []
    seen_indices = set()

    # Identify key columns
    _cols_lower = {c.lower(): c for c in work_cols}
    siren_col = next((c for c in work_cols if "siren" in c.lower() and "siret" not in c.lower()), None)
    name_col = next((c for c in work_cols if any(k in c.lower() for k in ("name", "nom", "company", "raison"))), None)

    # Strategy A: Same SIREN = exact duplicate
    if siren_col:
        siren_norm = df[siren_col].fillna("").astype(str).str.strip().str.replace(r'\D', '', regex=True)
        # Only consider valid SIRENs (9 digits, non-empty)
        valid_mask = siren_norm.str.len() == 9
        siren_groups = siren_norm[valid_mask].loc[siren_norm[valid_mask].duplicated(keep=False)]
        if not siren_groups.empty:
            for key, grp_idx in siren_groups.groupby(siren_norm[valid_mask]).groups.items():
                if len(grp_idx) >= 2 and grp_idx[0] not in seen_indices:
                    groups.append({
                        "type": "exact",
                        "indices": list(grp_idx),
                        "count": len(grp_idx),
                        "match_key": f"SIREN: {key}",
                        "sample": df.iloc[grp_idx[0]][work_cols[:4]].to_dict(),
                    })
                    seen_indices.update(grp_idx)

    # Strategy B: Same normalized company name (after removing legal forms, spaces, case)
    if name_col:
        _legal = re.compile(r'\b(SAS|SARL|SA|SCI|EURL|SNC|SASU|SE|GIE|EI|EARL)\b', re.IGNORECASE)
        name_norm = (df[name_col].fillna("").astype(str)
                     .str.strip().str.upper()
                     .str.replace(r'\s+', ' ', regex=True)
                     .apply(lambda x: _legal.sub('', x).strip()))
        valid_names = name_norm[name_norm.str.len() >= 3]
        name_dups = valid_names[valid_names.duplicated(keep=False)]
        if not name_dups.empty:
            for key, grp_idx in name_dups.groupby(valid_names).groups.items():
                # Skip if all indices already seen
                new_idx = [i for i in grp_idx if i not in seen_indices]
                if len(new_idx) >= 2:
                    groups.append({
                        "type": "exact",
                        "indices": list(grp_idx),
                        "count": len(grp_idx),
                        "match_key": f"Nom: {key[:40]}",
                        "sample": df.iloc[grp_idx[0]][work_cols[:4]].to_dict(),
                    })
                    seen_indices.update(grp_idx)

    return df, groups


def _dedup_phase2_errors(df: pd.DataFrame, mapping: dict[str, str | None]) -> tuple[pd.DataFrame, list[dict]]:
    """Phase 2: Detect formatting errors and propose corrections.
    Returns (cleaned_df, list_of_corrections_applied)."""
    corrections = []
    df_work = df.copy()

    # Normalize all string columns: strip whitespace, collapse multiple spaces
    for col in df_work.columns:
        if df_work[col].dtype == object:
            original = df_work[col].copy()
            df_work[col] = df_work[col].fillna("").astype(str).str.strip().str.replace(r'\s+', ' ', regex=True)
            changed = (original.fillna("").astype(str) != df_work[col]) & (original.fillna("") != "")
            if changed.any():
                corrections.append({"col": col, "type": "whitespace", "count": int(changed.sum()),
                                    "desc": f"Espaces normalisés dans '{col}'"})

    # SIREN: pad to 9 digits if 8 digits
    siren_col = mapping.get("siren")
    if siren_col and siren_col in df_work.columns:
        mask_8 = df_work[siren_col].astype(str).str.replace(r'\D', '', regex=True).str.len() == 8
        if mask_8.any():
            df_work.loc[mask_8, siren_col] = df_work.loc[mask_8, siren_col].astype(str).str.replace(r'\D', '', regex=True).str.zfill(9)
            corrections.append({"col": siren_col, "type": "siren_pad", "count": int(mask_8.sum()),
                                "desc": f"SIREN complété à 9 chiffres ({int(mask_8.sum())} lignes)"})

    # SIRET: pad to 14 digits if 13 digits
    siret_col = mapping.get("siret")
    if siret_col and siret_col in df_work.columns:
        mask_13 = df_work[siret_col].astype(str).str.replace(r'\D', '', regex=True).str.len() == 13
        if mask_13.any():
            df_work.loc[mask_13, siret_col] = df_work.loc[mask_13, siret_col].astype(str).str.replace(r'\D', '', regex=True).str.zfill(14)
            corrections.append({"col": siret_col, "type": "siret_pad", "count": int(mask_13.sum()),
                                "desc": f"SIRET complété à 14 chiffres ({int(mask_13.sum())} lignes)"})

    # Company name: capitalize properly
    name_col = mapping.get("company_name")
    if name_col and name_col in df_work.columns:
        # Detect all-uppercase names and convert to title case
        mask_upper = df_work[name_col].str.isupper() & (df_work[name_col].str.len() > 3)
        if mask_upper.any():
            _before_samples = df_work.loc[mask_upper, name_col].head(5).tolist()
            df_work.loc[mask_upper, name_col] = df_work.loc[mask_upper, name_col].str.title()
            _after_samples = df_work.loc[mask_upper, name_col].head(5).tolist()
            corrections.append({"col": name_col, "type": "case", "count": int(mask_upper.sum()),
                                "desc": f"Noms convertis en casse titre ({int(mask_upper.sum())} lignes)",
                                "samples_before": _before_samples, "samples_after": _after_samples})

    return df_work, corrections


def _dedup_phase3_similarity(df: pd.DataFrame, cols: list[str], threshold: float = 0.85, exclude_indices: set | None = None) -> list[dict]:
    """Phase 3: Detect near-duplicates using business logic.
    Real duplicates = same SIREN/SIRET, or very similar name (>threshold) + same city/SIREN prefix.
    NOT just sharing the same 3-character prefix."""
    from difflib import SequenceMatcher
    groups = []
    seen = set(exclude_indices) if exclude_indices else set()

    if not cols or df.empty:
        return groups

    # Identify key columns
    _cols_lower = {c.lower(): c for c in df.columns}
    name_col = None
    siren_col = None
    siret_col = None
    city_col = None
    for c in cols:
        cl = c.lower()
        if any(k in cl for k in ("name", "nom", "company", "raison", "account_name")):
            name_col = c
        elif "siren" in cl and "siret" not in cl:
            siren_col = c
        elif "siret" in cl:
            siret_col = c
        elif any(k in cl for k in ("city", "ville", "commune")):
            city_col = c
    if not name_col:
        name_col = cols[0]

    # Strategy 1: Group by SIREN (9 digits) — same SIREN = definite duplicate
    if siren_col and siren_col in df.columns:
        siren_vals = df[siren_col].fillna("").astype(str).str.replace(r'\D', '', regex=True)
        siren_groups = {}
        for i, s in enumerate(siren_vals):
            if i in seen or not s or len(s) != 9:
                continue
            siren_groups.setdefault(s, []).append(i)
        for siren_val, indices in siren_groups.items():
            if len(indices) >= 2:
                groups.append({
                    "type": "similar",
                    "indices": indices,
                    "count": len(indices),
                    "similarity": 99,
                    "sample": {col: str(df.iloc[indices[0]].get(col, "")) for col in cols[:3]},
                })
                seen.update(indices)

    # Strategy 2: Very similar names (>threshold) with blocking on first 5 chars + normalized
    names = df[name_col].fillna("").astype(str).str.strip().str.upper().tolist()
    # Normalize: remove legal forms and common suffixes for better comparison
    _legal = re.compile(r'\b(SAS|SARL|SA|SCI|EURL|SNC|SASU|SE|GIE|EI|EARL)\b')
    names_norm = [_legal.sub('', n).strip() for n in names]

    # Get SIREN values to cross-check (different SIREN = NOT a duplicate)
    # Derive from SIREN column or from first 9 digits of SIRET
    _siren_values = [""] * len(df)
    if siren_col and siren_col in df.columns:
        _sv = df[siren_col].fillna("").astype(str).str.replace(r'\D', '', regex=True).tolist()
        _siren_values = [s if len(s) == 9 else "" for s in _sv]
    if siret_col and siret_col in df.columns:
        # Fill missing SIRENs from SIRET (first 9 digits)
        _siret_v = df[siret_col].fillna("").astype(str).str.replace(r'\D', '', regex=True).tolist()
        for i, sv in enumerate(_siret_v):
            if not _siren_values[i] and len(sv) >= 9:
                _siren_values[i] = sv[:9]

    # Block by first 5 normalized chars (much more selective than 3)
    blocks = {}
    for i, n in enumerate(names_norm):
        # STRICT: Skip empty names, "NAN", very short names — no comparison without a real name
        if i in seen or len(n) < 5 or n in ("NAN", "NONE", "NULL", "NA", "N/A", "NOM", ""):
            continue
        # Also skip if the original name looks like NaN or is blank
        orig = names[i]
        if not orig or orig in ("NAN", "NONE", "NULL", "NA", "N/A", ""):
            continue
        block_key = n[:5]
        blocks.setdefault(block_key, []).append(i)

    _MAX_GROUPS = 20
    for block_indices in blocks.values():
        if len(block_indices) < 2 or len(block_indices) > 30:
            continue
        if len(groups) >= _MAX_GROUPS:
            break
        for i in range(len(block_indices)):
            idx_i = block_indices[i]
            if idx_i in seen:
                continue
            group_members = [idx_i]
            for j in range(i + 1, len(block_indices)):
                idx_j = block_indices[j]
                if idx_j in seen:
                    continue
                # If both have SIREN and they differ → NOT duplicates
                s_i = _siren_values[idx_i]
                s_j = _siren_values[idx_j]
                if s_i and s_j and s_i != s_j:
                    continue  # Different SIREN = different company
                # Compare normalized names
                sim = SequenceMatcher(None, names_norm[idx_i], names_norm[idx_j]).ratio()
                if sim >= threshold:
                    group_members.append(idx_j)
                    seen.add(idx_j)
            if len(group_members) >= 2:
                seen.add(idx_i)
                # Compute actual average similarity for display
                _sims = []
                for m in group_members[1:]:
                    _sims.append(SequenceMatcher(None, names_norm[idx_i], names_norm[m]).ratio())
                avg_sim = round((sum(_sims) / len(_sims)) * 100) if _sims else round(threshold * 100)
                groups.append({
                    "type": "similar",
                    "indices": group_members,
                    "count": len(group_members),
                    "similarity": avg_sim,
                    "sample": {col: str(df.iloc[group_members[0]].get(col, "")) for col in cols[:3]},
                })
    return groups


def _dedup_apply_decisions(df: pd.DataFrame, accepted_groups: list[dict], strategy: str = "keep_first") -> tuple[pd.DataFrame, int]:
    """Apply user-validated dedup decisions. Keep first/last of each accepted group.
    Returns (cleaned_df, removed_count). NEVER touches original."""
    indices_to_remove = set()
    for grp in accepted_groups:
        idxs = grp["indices"]
        if strategy == "keep_last":
            indices_to_remove.update(idxs[:-1])
        else:
            indices_to_remove.update(idxs[1:])
    # Only remove indices that exist in the current DataFrame
    valid_indices = indices_to_remove & set(df.index)
    df_clean = df.drop(index=list(valid_indices)).reset_index(drop=True)
    return df_clean, len(valid_indices)


def deduplicate_dataframe(
    df: pd.DataFrame,
    mapping: dict[str, str | None],
    keys: list[str],
    strategy: str = "keep_first",
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Auto-deduplicate rows before analysis. Returns (clean_df, removed_df, stats)."""
    if not keys or df.empty:
        return df.copy(), pd.DataFrame(), {"original": len(df), "clean": len(df), "removed": 0, "dup_groups": 0}

    def row_key(row):
        parts = []
        for k in keys:
            col = mapping.get(k)
            if col and col in row.index:
                v = _cell_str(row[col])
                if k in ("siren", "siret"):
                    v = _digits_only(v)
                parts.append(v.upper() if v else "")
            else:
                parts.append("")
        return tuple(parts)

    df_work = df.copy()
    df_work["_dedup_key"] = df_work.apply(row_key, axis=1)
    has_key = df_work["_dedup_key"].apply(lambda k: any(p for p in k))
    dup_groups = df_work[has_key & df_work["_dedup_key"].duplicated(keep=False)]["_dedup_key"].nunique()

    if strategy == "keep_last":
        keep = ~df_work["_dedup_key"].duplicated(keep="last") | ~has_key
    else:
        keep = ~df_work["_dedup_key"].duplicated(keep="first") | ~has_key

    clean = df_work[keep].drop(columns=["_dedup_key"])
    removed = df_work[~keep].drop(columns=["_dedup_key"])
    return clean, removed, {
        "original": len(df),
        "clean": len(clean),
        "removed": len(removed),
        "dup_groups": int(dup_groups),
        "keys": keys,
        "strategy": strategy,
    }


def deduplicate_snowflake_table(
    table_fqn: str, mapping: dict[str, str | None], keys: list[str], strategy: str = "keep_first",
) -> tuple[pd.DataFrame, dict]:
    """Run deduplication in Snowflake SQL, return cleaned dataframe + stats."""
    if not keys or not _get_conn():
        df = load_table_as_dataframe(table_fqn)
        return df, {"original": len(df), "clean": len(df), "removed": 0, "dup_groups": 0, "engine": "local"}

    partition_cols = []
    for k in keys:
        col = mapping.get(k)
        if col:
            if k in ("siren", "siret"):
                partition_cols.append(f"REGEXP_REPLACE(COALESCE({col}, ''), '[^0-9]', '')")
            else:
                partition_cols.append(f"UPPER(TRIM(COALESCE({col}, '')))")

    if not partition_cols:
        df = load_table_as_dataframe(table_fqn)
        return df, {"original": len(df), "clean": len(df), "removed": 0, "dup_groups": 0, "engine": "local"}

    order_col = mapping.get("account_id") or mapping.get("siren") or next(c for c in mapping.values() if c)
    order_dir = "DESC" if strategy == "keep_last" else "ASC"
    partition_expr = ", ".join(partition_cols)
    staging_clean = f"{STAGING_TABLE}_CLEAN"
    where_parts = [f"COALESCE({mapping[k]}, '') <> ''" for k in keys if mapping.get(k)]
    where_clause = " OR ".join(where_parts) if where_parts else "1=1"

    sql = f"""
        CREATE OR REPLACE TRANSIENT TABLE {staging_clean} AS
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY {partition_expr}
                ORDER BY {order_col} {order_dir}
            ) AS _rn
            FROM {table_fqn}
            WHERE {where_clause}
        ) WHERE _rn = 1
    """
    _sf_execute(sql)
    df_orig = load_table_as_dataframe(table_fqn)
    df_clean = load_table_as_dataframe(staging_clean)
    removed = max(0, len(df_orig) - len(df_clean))
    return df_clean, {
        "original": len(df_orig),
        "clean": len(df_clean),
        "removed": removed,
        "dup_groups": removed,
        "keys": keys,
        "strategy": strategy,
        "engine": "snowflake",
        "staging_table": staging_clean,
    }


def stage_dataframe_to_snowflake(df: pd.DataFrame, table_fqn: str = STAGING_TABLE) -> bool:
    """Upload a dataframe to a Snowflake table (fast: write_pandas or parameterized INSERT)."""
    conn = _get_conn()
    if conn is None or df.empty:
        return False
    parts = table_fqn.split(".")
    if len(parts) != 3:
        return False
    database, schema, table = parts
    # Clean column names for Snowflake compatibility
    df = df.copy()
    df.columns = [c.upper().replace(" ", "_").replace("-", "_") for c in df.columns]
    # Replace NaN with None for proper NULL handling
    df = df.where(df.notna(), None)
    try:
        from snowflake.connector.pandas_tools import write_pandas
        conn.cursor().execute(f"USE DATABASE {database}")
        conn.cursor().execute(f"USE SCHEMA {schema}")
        success, _, nrows, _ = write_pandas(
            conn, df, table.upper(),
            database=database, schema=schema,
            auto_create_table=True, overwrite=True,
            quote_identifiers=False,
        )
        if success and nrows and nrows[0] >= len(df) * 0.95:
            return True
        # If write_pandas lost too many rows, fall through to parameterized INSERT
    except Exception:
        pass

    # Fallback: CREATE TABLE + parameterized INSERT (handles all special characters)
    try:
        cols_ddl = ", ".join(f'"{c}" VARCHAR' for c in df.columns)
        conn.cursor().execute(f"CREATE OR REPLACE TABLE {table_fqn} ({cols_ddl})")
        col_list = ", ".join(f'"{c}"' for c in df.columns)
        placeholders = ", ".join(["%s"] * len(df.columns))
        cur = conn.cursor()
        batch_size = 100
        for start in range(0, len(df), batch_size):
            chunk = df.iloc[start:start + batch_size]
            rows_data = []
            for _, row in chunk.iterrows():
                rows_data.append(tuple(str(v) if v is not None else None for v in row))
            try:
                cur.executemany(
                    f"INSERT INTO {table_fqn} ({col_list}) VALUES ({placeholders})",
                    rows_data
                )
            except Exception:
                # Row-by-row fallback for truly problematic rows
                for row_tuple in rows_data:
                    try:
                        cur.execute(
                            f"INSERT INTO {table_fqn} ({col_list}) VALUES ({placeholders})",
                            row_tuple
                        )
                    except Exception:
                        pass
        return True
    except Exception:
        return False


def _quick_score(df: pd.DataFrame, mapping: dict[str, str | None]) -> int:
    """Fast conformity score estimate (% rows without obvious format issues)."""
    if df.empty:
        return 0
    ok = 0
    for _, row in df.iterrows():
        issues = 0
        siren_col = mapping.get("siren")
        siret_col = mapping.get("siret")
        if siren_col and siren_col in row.index:
            s = _digits_only(_cell_str(row[siren_col]))
            if s and not _valid_siren(s):
                issues += 1
        if siret_col and siret_col in row.index:
            t = _digits_only(_cell_str(row[siret_col]))
            if t and not _valid_siret(t):
                issues += 1
        if issues == 0:
            ok += 1
    return round(ok / len(df) * 100)


def run_snowflake_dq_analysis(
    table_fqn: str,
    mapping: dict[str, str | None],
    enabled_rules: list[str] | None = None,
    dedup_keys: list[str] | None = None,
    auto_dedup: bool = True,
    dedup_strategy: str = "keep_first",
    custom_rules: list[dict] | None = None,
    join_config: dict | None = None,
    df_override: pd.DataFrame | None = None,
) -> tuple[list[dict], dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Run DQ analysis on Snowflake: load/stage table, dedup in SQL, apply rules.
    Supports optional JOIN with a secondary table via join_config.
    If df_override is provided, uses it instead of loading from Snowflake.
    Returns (anomalies, stats, df_original, df_clean, df_removed).
    """
    if df_override is not None:
        df_orig = df_override.copy()
        if df_orig.empty:
            return [], {"total_rows": 0, "anomaly_count": 0, "score": 0}, df_orig, df_orig, pd.DataFrame()
    elif join_config:
        sec = join_config["table"]
        jtype = join_config["join_type"]
        ka = join_config["key_primary"]
        kb = join_config["key_secondary"]
        query = f"SELECT a.*, b.* EXCLUDE ({kb}) FROM {table_fqn} a {jtype} {sec} b ON a.{ka} = b.{kb}"
        df_orig = pd.DataFrame(_sf_query(query))
        if df_orig.empty:
            return [], {"total_rows": 0, "anomaly_count": 0, "score": 0}, df_orig, df_orig, pd.DataFrame()
        df_orig.columns = [c.lower() for c in df_orig.columns]
    else:
        df_orig = load_table_as_dataframe(table_fqn)
        if df_orig.empty:
            return [], {"total_rows": 0, "anomaly_count": 0, "score": 0}, df_orig, df_orig, pd.DataFrame()

    if not mapping or not any(mapping.values()):
        mapping = _mapping_for_table(table_fqn, list(df_orig.columns))

    dedup_keys = dedup_keys or DEFAULT_DEDUP_KEYS
    df_removed = pd.DataFrame()
    dedup_stats: dict = {}

    # Skip dedup + staging if df_override is already cleaned (from wizard Step 3)
    if df_override is not None:
        df_clean = df_orig
    elif auto_dedup and dedup_keys:
        df_clean, dedup_stats = deduplicate_snowflake_table(table_fqn, mapping, dedup_keys, dedup_strategy)
        if dedup_stats.get("engine") == "local":
            df_clean, df_removed, dedup_stats = deduplicate_dataframe(df_orig, mapping, dedup_keys, dedup_strategy)
    else:
        df_clean = df_orig.copy()

    # Only stage to Snowflake if not using override (avoid slow upload)
    if df_override is None:
        stage_dataframe_to_snowflake(df_clean, STAGING_TABLE)
    score_before = _quick_score(df_orig.head(200), mapping)  # Sample for speed

    rule_ids = enabled_rules or [r["id"] for r in FR_BUSINESS_RULES] + ["INSEE"]
    anomalies, stats = analyze_uploaded_dataframe(
        df_clean, mapping, source="snowflake",
        enabled_rules=rule_ids, skip_duplicate_check=auto_dedup,
        custom_rules=custom_rules or [],
    )
    stats["dedup"] = dedup_stats
    stats["score_before"] = score_before
    stats["active_rules"] = sorted(set(rule_ids))
    stats["engine"] = "snowflake"
    stats["source_table"] = table_fqn
    st.session_state["fr_clean_df"] = df_clean
    st.session_state["fr_removed_df"] = df_removed
    return anomalies, stats, df_orig, df_clean, df_removed


def _render_rules_and_dedup_config(key_prefix: str = "fr"):
    """Compact rule config — interactive checkboxes in a styled grid."""
    t = get_theme()

    # All rules including INSEE
    all_rules = FR_BUSINESS_RULES + [
        {"id": "INSEE", "name": "Registre SIRENE", "check": "29M+ entreprises"}
    ]

    # Render interactive checkboxes in 3-column grid
    cols = st.columns(3)
    for i, rule in enumerate(all_rules):
        with cols[i % 3]:
            st.checkbox(
                f"**{rule['id']}** — {rule['name']}",
                value=st.session_state.get(f"{key_prefix}_rule_{rule['id']}", True),
                key=f"{key_prefix}_rule_{rule['id']}",
            )

    enabled = [rule["id"] for rule in all_rules if st.session_state.get(f"{key_prefix}_rule_{rule['id']}", True)]

    st.session_state[f"{key_prefix}_enabled_rules"] = enabled
    return enabled


def _render_cleaning_preview(stats: dict, df_clean: pd.DataFrame, df_removed: pd.DataFrame):
    """Show before/after dedup scores and cleaned data preview."""
    dedup = stats.get("dedup", {})
    if not dedup.get("removed"):
        return

    section_header("Aperçu nettoyage", "Résultat du dédoublonnage automatique avant analyse.", icon="✦")
    score_before = stats.get("score_before", stats.get("score", 0))
    score_after = stats.get("score", 0)
    keys_label = ", ".join(DEDUP_KEY_OPTIONS.get(k, k) for k in dedup.get("keys", []))
    st.markdown(
        '<div class="qx-kpi-grid qx-kpi-grid-auto">'
        + kpi_card("Lignes originales", str(dedup.get("original", 0)), keys_label, "neutral")
        + kpi_card("Doublons supprimés", str(dedup.get("removed", 0)), f"{dedup.get('dup_groups', 0)} groupe(s)", "down")
        + kpi_card("Lignes nettoyées", str(dedup.get("clean", 0)), DEDUP_STRATEGIES.get(dedup.get("strategy", ""), ""), "neutral")
        + kpi_card("Score avant", f"{score_before}%", "Estimation format", "neutral")
        + kpi_card("Score après", f"{score_after}%", "Post-nettoyage", "up" if score_after >= score_before else "down")
        + '</div>',
        unsafe_allow_html=True,
    )
    tab_clean, tab_removed = st.tabs(["Données nettoyées (aperçu)", "Lignes supprimées (doublons)"])
    with tab_clean:
        st.dataframe(df_clean.head(20), use_container_width=True, hide_index=True)
    with tab_removed:
        if df_removed.empty:
            st.caption("Détail des lignes supprimées non disponible (dédoublonnage Snowflake SQL).")
        else:
            st.dataframe(df_removed.head(20), use_container_width=True, hide_index=True)


def _render_bulk_action_table(items: list[dict], on_accept, on_reject, key_prefix: str = "bulk"):
    """Premium bulk action table with toolbar."""
    if not items:
        return

    sel_key = f"{key_prefix}_selected"
    if sel_key not in st.session_state:
        st.session_state[sel_key] = set()

    sel: set = st.session_state[sel_key]
    st.markdown(
        f'<div class="qx-bulk-header">'
        f'<div class="qx-bulk-title">Actions groupées</div>'
        f'<div class="qx-bulk-meta">{len(items)} élément(s) · {len(sel)} sélectionné(s)</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    bc1, bc2, bc3, bc4 = st.columns([1, 1, 1, 1])
    with bc1:
        if st.button("☑ Tout sélectionner", key=f"{key_prefix}_all", use_container_width=True):
            st.session_state[sel_key] = {a["id"] for a in items}
            st.rerun()
    with bc2:
        if st.button("☐ Tout désélectionner", key=f"{key_prefix}_none", use_container_width=True):
            st.session_state[sel_key] = set()
            st.rerun()
    with bc3:
        if st.button(f"✓ Accepter ({len(sel)})", key=f"{key_prefix}_bulk_acc", type="primary", disabled=not sel, use_container_width=True):
            count = len(sel)
            for aid in list(sel):
                on_accept(aid)
            st.session_state[sel_key] = set()
            st.toast(f"✓ {count} anomalie(s) acceptée(s)")
            st.rerun()
    with bc4:
        if st.button(f"✗ Rejeter ({len(sel)})", key=f"{key_prefix}_bulk_rej", disabled=not sel, use_container_width=True):
            st.session_state[f"{key_prefix}_bulk_rej_open"] = True

    if st.session_state.get(f"{key_prefix}_bulk_rej_open") and sel:
        st.markdown('<div class="qx-reject-bar">', unsafe_allow_html=True)
        reason = st.text_input("Motif de rejet groupé", key=f"{key_prefix}_rej_reason", placeholder="Non applicable")
        if st.button("Confirmer le rejet groupé", key=f"{key_prefix}_confirm_rej", type="primary"):
            count = len(sel)
            for aid in list(sel):
                on_reject(aid, reason or "Rejet groupé")
            st.session_state[sel_key] = set()
            st.session_state.pop(f"{key_prefix}_bulk_rej_open", None)
            st.toast(f"✗ {count} anomalie(s) rejetée(s)")
            st.rerun()

    st.markdown('<div class="qx-data-shell">', unsafe_allow_html=True)
    rows = []
    for a in items:
        rows.append({
            "Sélectionner": a["id"] in sel,
            "ID": a.get("id", ""),
            "Compte": a.get("company_name", "")[:40],
            "Règle": a.get("rule_id", ""),
            "Sévérité": TR_SEVERITY.get(a.get("severity", ""), a.get("severity", "")),
            "Champ": a.get("field_label", a.get("field", "")),
            "Valeur actuelle": str(a.get("field_value", ""))[:50],
            "Valeur attendue": str(a.get("expected_value", ""))[:50],
        })

    edited = st.data_editor(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        key=f"{key_prefix}_editor",
        column_config={"Sélectionner": st.column_config.CheckboxColumn(default=False, required=True)},
        disabled=["ID", "Compte", "Règle", "Sévérité", "Champ", "Valeur actuelle", "Valeur attendue"],
    )

    new_sel = {items[i]["id"] for i, row in edited.iterrows() if row["Sélectionner"]}
    if new_sel != sel:
        st.session_state[sel_key] = new_sel
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# CSS / helpers
# ---------------------------------------------------------------------------


def get_theme():
    return THEMES[st.session_state.get("theme", "light")]


def inject_css():
    t = get_theme()
    is_light = st.session_state.get("theme", "dark") == "light"
    shadow = "none" if not is_light else "0 1px 3px rgba(0,0,0,0.08)"
    color_scheme = "light" if is_light else "dark"

    widget_shell = f"""
        /* Sélection texte — Leon accent */
        ::selection {{
            background: {t['accent_soft']} !important;
            color: {t['text_primary']} !important;
        }}

        /* Labels widgets — pas de fond bleu */
        [data-testid="stWidgetLabel"] p,
        [data-testid="stWidgetLabel"] label,
        [data-testid="stRadio"] label,
        [data-testid="stCheckbox"] label,
        [data-testid="stSelectbox"] label,
        [data-testid="stFileUploader"] label,
        [data-testid="stTextInput"] label {{
            color: {t['text_primary']} !important;
            background: transparent !important;
        }}

        /* Radio & checkbox */
        [data-testid="stRadio"] [data-baseweb="radio"],
        [data-testid="stRadio"] label[data-baseweb="radio"],
        [data-testid="stCheckbox"] label[data-baseweb="checkbox"] {{
            background: transparent !important;
        }}
        [data-testid="stRadio"] label[data-baseweb="radio"] > div:last-child,
        [data-testid="stCheckbox"] label[data-baseweb="checkbox"] > div:last-child {{
            color: {t['text_primary']} !important;
            background: transparent !important;
        }}
        [data-testid="stRadio"] label[data-baseweb="radio"]:focus,
        [data-testid="stRadio"] label[data-baseweb="radio"]:focus-within,
        [data-testid="stCheckbox"] label[data-baseweb="checkbox"]:focus,
        [data-testid="stCheckbox"] label[data-baseweb="checkbox"]:focus-within {{
            background: transparent !important;
            outline: none !important;
        }}

        /* Onglets */
        [data-testid="stTabs"] [data-baseweb="tab-list"] button {{
            color: {t['text_secondary']} !important;
            background: transparent !important;
        }}
        [data-testid="stTabs"] [data-baseweb="tab-list"] button[aria-selected="true"] {{
            color: {t['accent']} !important;
            border-bottom-color: {t['accent']} !important;
        }}
        [data-testid="stTabs"] [data-baseweb="tab-highlight"] {{
            background-color: {t['accent']} !important;
        }}

        /* Toggle sidebar */
        [data-testid="stSidebar"] [data-testid="stToggle"] label span {{
            color: {t['text_primary']} !important;
        }}

        /* Expander */
        [data-testid="stExpander"] summary,
        [data-testid="stExpander"] summary span {{
            color: {t['text_primary']} !important;
            background: transparent !important;
        }}

        /* Info / success / warning boxes */
        [data-testid="stAlert"] {{
            background-color: {"#f8fafc" if is_light else "#1e2028"} !important;
            color: {t['text_primary']} !important;
            border: 1px solid {t['border']} !important;
        }}
    """

    light_widgets = ""
    if is_light:
        light_widgets = f"""
        /* Mode clair — champs & boutons */
        [data-testid="stTextInput"] [data-baseweb="base-input"],
        [data-testid="stTextInput"] [data-baseweb="input"],
        [data-testid="stTextArea"] [data-baseweb="base-input"],
        [data-testid="stTextArea"] textarea,
        [data-testid="stNumberInput"] [data-baseweb="base-input"],
        [data-testid="stDateInput"] [data-baseweb="base-input"],
        [data-testid="stSelectbox"] [data-baseweb="select"] > div,
        [data-testid="stMultiSelect"] [data-baseweb="select"] > div,
        [data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"],
        [data-testid="stFileUploader"] section {{
            background-color: #ffffff !important;
            border-color: {t['border']} !important;
        }}
        [data-testid="stTextInput"] input,
        [data-testid="stTextArea"] textarea,
        [data-testid="stNumberInput"] input,
        [data-testid="stSelectbox"] [data-baseweb="select"] span,
        [data-testid="stMultiSelect"] [data-baseweb="select"] span {{
            color: {t['text_primary']} !important;
            -webkit-text-fill-color: {t['text_primary']} !important;
        }}
        [data-testid="stTextInput"] input::placeholder {{
            color: {t['text_secondary']} !important;
            opacity: 1;
        }}

        .main [data-testid="stButton"] > button,
        .main .stButton > button {{
            background-color: #ffffff !important;
            color: {t['text_primary']} !important;
            border: 1px solid {t['border']} !important;
            box-shadow: none !important;
        }}
        .main [data-testid="stButton"] > button:hover,
        .main .stButton > button:hover {{
            background-color: #f8fafc !important;
            border-color: {t['accent']} !important;
            color: {t['accent']} !important;
        }}
        .main [data-testid="stButton"] > button[kind="primary"],
        .main .stButton > button[kind="primary"] {{
            background-color: {t['accent']} !important;
            color: #ffffff !important;
            border: none !important;
        }}
        .main [data-testid="stButton"] > button[kind="primary"]:hover,
        .main .stButton > button[kind="primary"]:hover {{
            background-color: #0f766e !important;
            color: #ffffff !important;
        }}
        """
    else:
        light_widgets = f"""
        /* Mode sombre — widgets (config.toml = light, on re-sombre les contrôles) */
        [data-testid="stTextInput"] [data-baseweb="base-input"],
        [data-testid="stTextInput"] [data-baseweb="input"],
        [data-testid="stTextArea"] [data-baseweb="base-input"],
        [data-testid="stTextArea"] textarea,
        [data-testid="stNumberInput"] [data-baseweb="base-input"],
        [data-testid="stDateInput"] [data-baseweb="base-input"],
        [data-testid="stSelectbox"] [data-baseweb="select"] > div,
        [data-testid="stMultiSelect"] [data-baseweb="select"] > div,
        [data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"],
        [data-testid="stFileUploader"] section {{
            background-color: {t['card_bg']} !important;
            border-color: {t['border']} !important;
        }}
        [data-testid="stTextInput"] input,
        [data-testid="stTextArea"] textarea,
        [data-testid="stNumberInput"] input,
        [data-testid="stSelectbox"] [data-baseweb="select"] span,
        [data-testid="stMultiSelect"] [data-baseweb="select"] span {{
            color: {t['text_primary']} !important;
            -webkit-text-fill-color: {t['text_primary']} !important;
        }}

        .main [data-testid="stButton"] > button,
        .main .stButton > button {{
            background-color: {t['card_bg']} !important;
            color: {t['text_primary']} !important;
            border: 1px solid {t['border']} !important;
            box-shadow: none !important;
        }}
        .main [data-testid="stButton"] > button:hover,
        .main .stButton > button:hover {{
            border-color: {t['accent']} !important;
            color: {t['accent']} !important;
        }}
        .main [data-testid="stButton"] > button[kind="primary"],
        .main .stButton > button[kind="primary"] {{
            background-color: {t['accent']} !important;
            color: #1a1d23 !important;
            border: none !important;
        }}
        """

    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

        :root {{
            --sidebar-bg: {t['sidebar_bg']};
            --content-bg: {t['content_bg']};
            --card-bg: {t['card_bg']};
            --card-bg-elevated: {t.get('card_bg_elevated', t['card_bg'])};
            --border: {t['border']};
            --border-subtle: {t.get('border_subtle', t['border'])};
            --text-primary: {t['text_primary']};
            --text-secondary: {t['text_secondary']};
            --accent: {t['accent']};
            --accent-soft: {t['accent_soft']};
            --high: {t['high']};
            --medium: {t['medium']};
            --low: {t['low']};
            --success: {t['success']};
            --radius-sm: 8px;
            --radius-md: 16px;
            --radius-lg: 16px;
            --shadow-card: {"0 1px 3px rgba(0,0,0,0.08)" if is_light else "0 4px 24px rgba(0,0,0,0.35)"};
            --shadow-glow: 0 0 40px {t['accent_glow']};
        }}

        html, body, [class*="css"] {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
        }}

        /* App shell */
        .stApp {{
            background: var(--content-bg) !important;
            background-image: {t.get('gradient_hero', 'none')} !important;
            background-size: 100% 420px !important;
            background-repeat: no-repeat !important;
            color: var(--text-primary) !important;
            color-scheme: {color_scheme};
        }}
        {light_widgets}
        {widget_shell}

        .main .block-container {{ padding-top: 1rem; max-width: 1440px; color: var(--text-primary) !important; }}
        .main [data-testid="stVerticalBlock"] > div {{
            gap: 0.25rem !important;
        }}

        /* Texte markdown — pas les divs internes des widgets */
        .main [data-testid="stMarkdownContainer"] p,
        .main [data-testid="stMarkdownContainer"] span,
        .main [data-testid="stMarkdownContainer"] li,
        .main [data-testid="stMarkdownContainer"] strong {{
            color: var(--text-primary) !important;
        }}
        .main [data-testid="stCaptionContainer"],
        .main [data-testid="stCaptionContainer"] p {{
            color: var(--text-secondary) !important;
        }}
        h1, h2, h3, h4, h5, h6,
        .main h1, .main h2, .main h3 {{
            color: var(--text-primary) !important;
        }}
        [data-testid="stMetricLabel"] {{
            color: var(--text-secondary) !important;
        }}
        [data-testid="stMetricValue"] {{
            color: var(--text-primary) !important;
        }}
        [data-testid="stMetricDelta"] svg {{
            fill: var(--text-secondary) !important;
        }}
        [data-testid="stMetricDelta"] {{
            color: var(--text-secondary) !important;
        }}

        /* ===== SIDEBAR — always dark navy ===== */
        [data-testid="stSidebar"],
        section[data-testid="stSidebar"],
        section[data-testid="stSidebar"] > div {{
            background-color: {t['sidebar_bg']} !important;
            background: {t['sidebar_bg']} !important;
        }}
        section[data-testid="stSidebar"] > div {{
            padding-top: 0 !important;
            padding-left: 0.75rem !important;
            padding-right: 0.75rem !important;
        }}
        [data-testid="stSidebar"] [data-testid="stSidebarHeader"] {{
            padding: 0 !important;
            min-height: 0 !important;
            height: 0 !important;
            display: none !important;
        }}
        [data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] {{
            top: 4px !important;
        }}
        [data-testid="stSidebar"] {{
            border-right: 1px solid rgba(255,255,255,0.06) !important;
        }}
        /* All sidebar text = light */
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] div,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] span,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] strong,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h1,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {{
            color: {t['sidebar_text']} !important;
        }}
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] label span,
        [data-testid="stSidebar"] label p {{
            color: {t['sidebar_text']} !important;
        }}
        [data-testid="stSidebar"] hr {{
            border-color: rgba(255,255,255,0.08) !important;
            margin: 8px 0 !important;
        }}
        /* COMPACT sidebar — minimal gaps, not zero */
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{
            gap: 2px !important;
        }}
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div {{
            gap: 2px !important;
            margin: 0 !important;
            padding: 0 !important;
        }}
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div > div {{
            margin: 0 !important;
            padding: 0 !important;
        }}
        [data-testid="stSidebar"] .element-container {{
            margin: 0 !important;
            padding: 0 !important;
        }}
        [data-testid="stSidebar"] .stButton {{
            margin: 0 !important;
            padding: 0 !important;
        }}
        [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {{
            padding: 0 !important;
            margin: 0 !important;
        }}
        /* Sidebar nav buttons */
        [data-testid="stSidebar"] .stButton > button {{
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            text-align: left;
            padding: 8px 14px !important;
            margin: 1px 0 !important;
            border-radius: 6px !important;
            color: {t['nav_inactive']} !important;
            font-size: 0.85rem;
            font-weight: 400;
            justify-content: flex-start;
            width: 100%;
            min-height: 0 !important;
            height: auto !important;
            line-height: 1.4;
        }}
        [data-testid="stSidebar"] .stButton > button:hover {{
            background: {t['nav_hover']} !important;
            color: {t['sidebar_text']} !important;
        }}
        [data-testid="stSidebar"] .stButton > button[kind="primary"] {{
            background: rgba(255,255,255,0.05) !important;
            color: {t['accent']} !important;
            font-weight: 600;
            border-left: 3px solid {t['accent']} !important;
            border-radius: 0 6px 6px 0 !important;
        }}
        [data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {{
            color: {t['accent']} !important;
            background: rgba(255,255,255,0.08) !important;
        }}
        /* Sidebar icons & toggle */
        [data-testid="stSidebar"] .stButton > button span[data-testid="stIconMaterial"] {{
            color: {t['nav_inactive']} !important;
        }}
        [data-testid="stSidebar"] .stButton > button[kind="primary"] span[data-testid="stIconMaterial"] {{
            color: {t['accent']} !important;
        }}
        [data-testid="stSidebar"] .stColumn {{
            padding: 0 !important;
        }}
        /* Sidebar toggle label */
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {{
            color: {t['sidebar_text']} !important;
        }}

        /* Cards & metrics */
        div[data-testid="metric-container"] {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
            box-shadow: {shadow};
        }}
        .qx-card {{
            background: var(--card-bg);
            background-image: {t.get('gradient_card', 'none')};
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 14px 18px;
            margin-bottom: 10px;
            box-shadow: var(--shadow-card);
            color: var(--text-primary);
            transition: border-color 0.2s ease, box-shadow 0.2s ease;
        }}
        .qx-card:hover {{
            border-color: {"#cbd5e1" if is_light else "#353849"};
        }}
        .qx-card strong {{ color: var(--text-primary) !important; }}
        .qx-card span {{ color: inherit; }}

        /* Page header */
        .qx-page-header {{
            position: relative;
            margin: -0.5rem 0 0.75rem 0;
            padding: 1rem 0 0.75rem 0;
            border-bottom: 1px solid var(--border);
        }}
        .qx-page-header-glow {{
            display: none;
        }}
        .qx-page-title {{
            font-size: 1.6rem; font-weight: 800; letter-spacing: -0.02em;
            color: var(--text-primary) !important; margin: 0; line-height: 1.2;
        }}
        .qx-page-sub {{
            font-size: 0.88rem; color: var(--text-secondary) !important;
            margin: 4px 0 0 0; max-width: 640px; line-height: 1.4;
        }}
        .qx-page-badges {{ margin-top: 8px; }}
        .qx-page-badge {{
            display: inline-block; padding: 4px 12px; margin-right: 8px;
            border-radius: 999px; font-size: 0.72rem; font-weight: 600;
            background: var(--accent-soft); color: var(--accent);
            border: 1px solid {t['accent_soft']}; letter-spacing: 0.04em;
            text-transform: uppercase;
        }}

        /* Section header */
        .qx-section-head {{
            display: flex; align-items: flex-start; gap: 12px;
            margin: 0.75rem 0 0.5rem 0; padding-bottom: 8px;
            border-bottom: 1px solid var(--border-subtle);
        }}
        .qx-section-icon {{
            display: flex; align-items: center; justify-content: center;
            width: 36px; height: 36px; border-radius: 10px;
            background: var(--accent-soft); color: var(--accent);
            font-size: 1rem; flex-shrink: 0;
        }}
        .qx-section-title {{
            font-size: 1.05rem; font-weight: 700; color: var(--text-primary);
            letter-spacing: -0.01em;
        }}
        .qx-section-sub {{
            font-size: 0.82rem; color: var(--text-secondary); margin-top: 3px;
        }}

        /* Bulk action toolbar */
        .qx-bulk-header {{
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 12px;
        }}
        .qx-bulk-title {{ font-size: 0.95rem; font-weight: 700; color: var(--text-primary); }}
        .qx-bulk-meta {{ font-size: 0.8rem; color: var(--text-secondary); }}
        .qx-data-shell {{
            background: var(--card-bg); border: 1px solid var(--border);
            border-radius: var(--radius-md); padding: 4px; margin-top: 8px;
            box-shadow: var(--shadow-card);
        }}
        .qx-reject-bar {{
            background: rgba(239,68,68,0.06); border: 1px solid rgba(239,68,68,0.2);
            border-radius: var(--radius-sm); padding: 12px 16px; margin: 8px 0;
        }}

        /* Info chips & empty states */
        .qx-info-chip {{
            background: var(--accent-soft); border: 1px solid {t['accent_soft']};
            border-radius: var(--radius-sm); padding: 14px 16px; margin-bottom: 12px;
        }}
        .qx-info-chip-title {{ display: block; font-weight: 700; font-size: 0.88rem; color: var(--text-primary); }}
        .qx-info-chip-desc {{ display: block; font-size: 0.78rem; color: var(--text-secondary); margin-top: 4px; line-height: 1.4; }}
        .qx-empty-state {{
            text-align: center; padding: 28px 20px; color: var(--text-secondary);
            font-size: 0.88rem; border: 1px dashed var(--border);
            border-radius: var(--radius-sm); margin: 12px 0;
        }}
        .qx-custom-rule-row {{
            padding: 10px 14px; margin: 6px 0; background: var(--border-subtle);
            border-radius: var(--radius-sm); border: 1px solid var(--border);
            font-size: 0.88rem;
        }}

        /* Badges */
        .qx-badge {{
            display: inline-block;
            padding: 2px 10px;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.02em;
        }}
        .qx-badge-high {{ background: rgba(239,68,68,0.15); color: {t['high']}; }}
        .qx-badge-medium {{ background: rgba(217,119,6,0.12); color: {t['medium']}; }}
        .qx-badge-low {{ background: rgba(59,130,246,0.15); color: {t['low']}; }}
        .qx-badge-open {{ background: rgba(239,68,68,0.12); color: {t['high']}; }}
        .qx-badge-review {{ background: {t['accent_soft']}; color: {t['medium']}; }}
        .qx-badge-resolved {{ background: rgba(34,197,94,0.12); color: {t['success']}; }}
        .qx-badge-dismissed {{ background: rgba(139,141,151,0.15); color: {t['text_secondary']}; }}
        .qx-badge-p1 {{ background: rgba(239,68,68,0.15); color: {t['high']}; }}
        .qx-badge-p2 {{ background: rgba(217,119,6,0.12); color: {t['medium']}; }}
        .qx-badge-p3 {{ background: rgba(59,130,246,0.15); color: {t['low']}; }}
        .qx-badge-match {{ background: rgba(34,197,94,0.15); color: {t['success']}; }}
        .qx-badge-warn {{ background: rgba(217,119,6,0.12); color: {t['medium']}; }}
        .qx-badge-error {{ background: rgba(239,68,68,0.15); color: {t['high']}; }}

        /* Sidebar branding & footer */
        .qx-logo {{
            font-size: 1.5rem; font-weight: 800; letter-spacing: -0.02em;
            color: {t['sidebar_text']} !important;
            display: flex; align-items: center; gap: 10px;
        }}
        .qx-logo-mark {{
            display: inline-flex; align-items: center; justify-content: center;
            width: 38px; height: 38px; border-radius: 50%;
            background: {t['accent']};
            color: #ffffff; font-weight: 800; font-size: 0.9rem;
            box-shadow: 0 2px 8px {t.get('accent_glow', 'rgba(13,148,136,0.15)')};
            overflow: visible;
        }}
        .qx-logo-sub {{ font-size: 0.62rem; letter-spacing: 0.18em; color: {t['nav_inactive']} !important; margin-top: 4px; }}
        .qx-usage {{
            font-size: 0.75rem; color: {t['text_secondary']} !important; line-height: 1.7;
            background: var(--card-bg); border: 1px solid var(--border);
            border-radius: var(--radius-sm); padding: 12px 14px;
        }}
        .qx-usage strong {{ color: {t['text_primary']} !important; }}
        .qx-tier {{
            background: linear-gradient(135deg, var(--accent-soft) 0%, transparent 100%);
            border: 1px solid {t['accent_soft']};
            border-radius: var(--radius-md); padding: 12px 16px; margin-top: 12px;
        }}
        .qx-nav-label {{
            font-size: 0.63rem; font-weight: 700; letter-spacing: 0.12em;
            text-transform: uppercase; color: {t['accent']} !important;
            padding: 12px 14px 4px 14px; margin-top: 0; margin-bottom: 0;
        }}

        /* Wizard steps */
        .qx-wizard-track {{
            display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
            margin-bottom: 1.5rem; padding: 16px 20px;
            background: var(--card-bg); border: 1px solid var(--border);
            border-radius: var(--radius-md); box-shadow: var(--shadow-card);
        }}
        .qx-step {{
            display: inline-flex; align-items: center; gap: 8px;
            padding: 8px 16px; border-radius: 999px; font-size: 0.82rem;
            border: 1px solid transparent; font-weight: 500;
        }}
        .qx-step-active {{
            background: var(--accent-soft); color: {t['accent']}; font-weight: 700;
            border-color: {t['accent']}; box-shadow: 0 0 12px {t['accent_glow']};
        }}
        .qx-step-done {{ background: rgba(34,197,94,0.1); color: {t['success']}; border-color: rgba(34,197,94,0.25); }}
        .qx-step-pending {{ color: {t['text_secondary']}; border-color: var(--border); background: var(--border-subtle); }}

        /* Misc */
        .qx-filter-pill {{
            display: inline-block; padding: 4px 14px; margin: 2px 4px 2px 0;
            border-radius: 999px; border: 1px solid var(--border);
            font-size: 0.8rem; cursor: pointer;
        }}
        .qx-filter-pill.active {{ border-color: {t['accent']}; color: {t['accent']}; background: {t['accent_soft']}; }}

        /* Subject cards (Run Analysis wizard) */
        .qx-subject-card {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 16px 18px;
            margin-bottom: 10px;
            box-shadow: var(--shadow-card);
            transition: border-color 0.2s ease, box-shadow 0.2s ease;
        }}
        .qx-subject-card.selected {{
            border-color: {t['accent']};
            box-shadow: 0 0 0 1px {t['accent']}, var(--shadow-glow);
            background: linear-gradient(135deg, var(--accent-soft) 0%, var(--card-bg) 60%);
        }}

        /* Dashboard */
        .qx-dash-header {{
            display: flex; justify-content: space-between; align-items: flex-end;
            margin-bottom: 1.5rem; padding-bottom: 1rem;
            border-bottom: 1px solid var(--border);
        }}
        .qx-dash-title {{ font-size: 1.75rem; font-weight: 700; color: var(--text-primary); margin: 0; }}
        .qx-dash-sub {{ font-size: 0.9rem; color: var(--text-secondary); margin-top: 4px; }}
        .qx-dash-meta {{ text-align: right; font-size: 0.8rem; color: var(--text-secondary); }}
        .qx-kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 1.5rem; }}
        .qx-kpi-grid-auto {{ grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }}
        @media (max-width: 900px) {{ .qx-kpi-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
        .qx-kpi-card {{
            background: var(--card-bg); border: 1px solid var(--border);
            border-radius: var(--radius-md); padding: 20px 22px;
            box-shadow: var(--shadow-card); position: relative; overflow: hidden;
            transition: transform 0.2s ease, border-color 0.2s ease;
        }}
        .qx-kpi-card::before {{
            content: ''; position: absolute; top: 0; left: 0; width: 3px; height: 100%;
            background: var(--kpi-accent, var(--accent)); opacity: 0.85;
        }}
        .qx-kpi-card:hover {{ transform: translateY(-2px); border-color: {"#cbd5e1" if is_light else "#353849"}; }}
        .qx-kpi-label {{ font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-secondary); font-weight: 600; }}
        .qx-kpi-value {{ font-size: 2rem; font-weight: 800; letter-spacing: -0.03em; color: var(--text-primary); margin: 8px 0 4px; line-height: 1; }}
        .qx-kpi-delta {{ font-size: 0.78rem; font-weight: 500; }}
        .qx-kpi-delta.up {{ color: {t['success']}; }}
        .qx-kpi-delta.down {{ color: {t['high']}; }}
        .qx-kpi-delta.neutral {{ color: var(--text-secondary); }}
        .qx-panel-title {{
            font-size: 0.95rem; font-weight: 600; color: var(--text-primary);
            margin: 0 0 12px 0; padding-bottom: 8px; border-bottom: 1px solid var(--border);
        }}
        .qx-finding-row {{
            display: flex; justify-content: space-between; align-items: center;
            padding: 10px 0; border-bottom: 1px solid var(--border); font-size: 0.875rem;
        }}
        .qx-finding-row:last-child {{ border-bottom: none; }}
        .qx-score-ring {{
            text-align: center; padding: 8px 0;
        }}
        .qx-score-ring-value {{
            font-size: 2.4rem; font-weight: 700; color: {t['accent']}; line-height: 1;
        }}
        .qx-score-ring-label {{
            font-size: 0.75rem; color: var(--text-secondary); margin-top: 6px;
            text-transform: uppercase; letter-spacing: 0.05em;
        }}
        .qx-audit-item {{
            border-left: 2px solid {t['accent']};
            padding: 8px 0 8px 14px; margin-bottom: 12px;
        }}
        .qx-mismatch {{ background: rgba(239,68,68,0.08); padding: 2px 6px; border-radius: 4px; color: {t['high']} !important; }}
        .qx-match {{ color: {t['success']} !important; }}
        .qx-warn {{ color: {t['medium']} !important; }}
        .qx-error {{ color: {t['high']} !important; }}
        .stPlotlyChart {{ background: var(--card-bg); border-radius: 8px; padding: 8px; }}

        /* Inputs & widgets in main area */
        .main .stTextInput label,
        .main .stTextInput input,
        .main .stButton > button,
        .main [data-testid="stButton"] > button {{
            color: var(--text-primary) !important;
        }}
        .main .stButton > button[kind="secondary"],
        .main [data-testid="stButton"] > button[kind="secondary"] {{
            background: var(--card-bg) !important;
            border: 1px solid var(--border) !important;
            color: var(--text-primary) !important;
        }}
        .main .stButton > button[kind="primary"],
        .main [data-testid="stButton"] > button[kind="primary"] {{
            background: {t['accent']} !important;
            color: #ffffff !important;
            border: none !important;
            font-weight: 600 !important;
            box-shadow: 0 2px 12px {t['accent_glow']} !important;
        }}
        .main .stButton > button[kind="primary"]:hover,
        .main [data-testid="stButton"] > button[kind="primary"]:hover {{
            filter: brightness(1.08);
        }}

        /* Filter pill buttons (Anomalies) — après les styles généraux */
        .main div[data-testid="column"] .stButton > button,
        .main div[data-testid="column"] [data-testid="stButton"] > button {{
            border-radius: 999px !important;
            font-size: 0.8rem !important;
            padding: 6px 14px !important;
            min-height: 2rem !important;
        }}
        .main div[data-testid="column"] .stButton > button[kind="primary"],
        .main div[data-testid="column"] [data-testid="stButton"] > button[kind="primary"] {{
            background: {t['accent_soft']} !important;
            color: {t['accent']} !important;
            border: 1px solid {t['accent']} !important;
            font-weight: 600 !important;
            box-shadow: none !important;
        }}
        .main div[data-testid="column"] .stButton > button[kind="primary"]:hover,
        .main div[data-testid="column"] [data-testid="stButton"] > button[kind="primary"]:hover {{
            background: {t['accent_glow']} !important;
            color: {t['accent']} !important;
        }}
        .main div[data-testid="column"] .stButton > button[kind="secondary"],
        .main div[data-testid="column"] [data-testid="stButton"] > button[kind="secondary"] {{
            background: {"#ffffff" if is_light else "transparent"} !important;
            border: 1px solid var(--border) !important;
            color: var(--text-secondary) !important;
        }}
        .main div[data-testid="column"] .stButton > button[kind="secondary"]:hover,
        .main div[data-testid="column"] [data-testid="stButton"] > button[kind="secondary"]:hover {{
            border-color: {t['accent']} !important;
            color: {t['accent']} !important;
            background: {"#f8fafc" if is_light else "transparent"} !important;
        }}

        /* Login page */
        .qx-login-wrap {{ max-width: 440px; margin: 0 auto; }}
        .qx-login-card {{
            background: var(--card-bg); border: 1px solid var(--border);
            border-radius: var(--radius-lg); padding: 2rem 2.25rem;
            box-shadow: var(--shadow-card), var(--shadow-glow);
            position: relative; overflow: hidden;
        }}
        .qx-login-card::before {{
            content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
            background: linear-gradient(90deg, var(--accent), #14b8a6, var(--accent));
        }}
        .qx-login-hero {{ text-align: center; padding: 2.5rem 0 1.5rem 0; }}
        .qx-login-features {{ display: grid; gap: 10px; margin-top: 1.5rem; text-align: left; font-size: 0.82rem; }}
        .qx-login-feature {{
            display: flex; align-items: center; gap: 10px; padding: 8px 12px;
            background: var(--border-subtle); border-radius: var(--radius-sm); border: 1px solid var(--border);
            color: var(--text-secondary);
        }}
        .qx-login-feature-icon {{ color: var(--accent); font-weight: 700; }}

        /* Data editor premium */
        [data-testid="stDataEditor"] {{ border: none !important; }}
        [data-testid="stDataFrame"] {{ border: none; border-radius: var(--radius-sm); }}

        /* Tabs premium */
        [data-testid="stTabs"] [data-baseweb="tab-list"] {{
            gap: 4px; border-bottom: 1px solid var(--border) !important;
        }}
        [data-testid="stTabs"] [data-baseweb="tab-list"] button {{
            font-weight: 600 !important; font-size: 0.85rem !important;
            padding: 10px 18px !important; border-radius: 8px 8px 0 0 !important;
        }}
        [data-testid="stTabs"] [data-baseweb="tab-list"] button[aria-selected="true"] {{
            background: var(--accent-soft) !important;
        }}

        /* Rule toggle cards */
        .qx-rule-card {{
            background: var(--card-bg);
            border: 1.5px solid var(--border);
            border-radius: var(--radius-md);
            padding: 14px 16px;
            margin-bottom: 10px;
            transition: all 0.2s ease;
            cursor: pointer;
            position: relative;
            overflow: hidden;
        }}
        .qx-rule-card.active {{
            border-color: var(--accent);
            background: linear-gradient(135deg, {t['accent_soft']} 0%, var(--card-bg) 100%);
            box-shadow: 0 0 0 1px {t['accent_glow']}, 0 2px 8px {t['accent_soft']};
        }}
        .qx-rule-card.active::before {{
            content: ''; position: absolute; top: 0; left: 0; width: 3px; height: 100%;
            background: var(--accent);
        }}
        .qx-rule-card:hover {{
            border-color: {t['accent']};
            transform: translateY(-1px);
        }}
        .qx-rule-card-id {{
            font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em;
            text-transform: uppercase; color: var(--accent);
            margin-bottom: 4px;
        }}
        .qx-rule-card-name {{
            font-size: 0.88rem; font-weight: 600; color: var(--text-primary);
            line-height: 1.3;
        }}
        .qx-rule-card-check {{
            font-size: 0.75rem; color: var(--text-secondary); margin-top: 4px;
            line-height: 1.4;
        }}
        .qx-rule-card-badge {{
            position: absolute; top: 10px; right: 12px;
            width: 20px; height: 20px; border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            font-size: 0.65rem; font-weight: 700;
        }}
        .qx-rule-card-badge.on {{
            background: var(--accent); color: #1a1d23;
        }}
        .qx-rule-card-badge.off {{
            background: var(--border); color: var(--text-secondary);
        }}

        /* Form groups */
        .qx-form-group {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 20px 24px;
            margin-bottom: 16px;
        }}
        .qx-form-group-title {{
            font-size: 0.78rem; font-weight: 700; text-transform: uppercase;
            letter-spacing: 0.08em; color: var(--text-secondary);
            margin-bottom: 14px; padding-bottom: 10px;
            border-bottom: 1px solid var(--border);
        }}

        /* Dedup panel */
        .qx-dedup-panel {{
            background: linear-gradient(135deg, rgba(59,130,246,0.04) 0%, var(--card-bg) 100%);
            border: 1px solid rgba(59,130,246,0.2);
            border-radius: var(--radius-md);
            padding: 20px 24px;
            margin-bottom: 16px;
        }}
        .qx-dedup-panel-title {{
            font-size: 0.88rem; font-weight: 700; color: var(--text-primary);
            margin-bottom: 4px;
        }}
        .qx-dedup-panel-sub {{
            font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 14px;
        }}

        /* Score ring premium */
        .qx-score-big {{
            text-align: center; padding: 20px;
            background: var(--card-bg); border: 1px solid var(--border);
            border-radius: var(--radius-lg); position: relative;
        }}
        .qx-score-big-value {{
            font-size: 3.5rem; font-weight: 800; letter-spacing: -0.04em;
            color: var(--accent); line-height: 1;
        }}
        .qx-score-big-label {{
            font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.1em;
            color: var(--text-secondary); margin-top: 8px; font-weight: 600;
        }}

        /* Status indicator dots */
        .qx-status-dot {{
            display: inline-block; width: 8px; height: 8px; border-radius: 50%;
            margin-right: 6px;
        }}
        .qx-status-dot.green {{ background: {t['success']}; box-shadow: 0 0 6px rgba(34,197,94,0.4); }}
        .qx-status-dot.orange {{ background: {t['medium']}; box-shadow: 0 0 6px rgba(217,119,6,0.4); }}
        .qx-status-dot.red {{ background: {t['high']}; box-shadow: 0 0 6px rgba(239,68,68,0.4); }}

        /* Metric card enhanced */
        div[data-testid="metric-container"] {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 18px 20px;
            box-shadow: var(--shadow-card);
            transition: transform 0.2s ease, border-color 0.2s ease;
        }}
        div[data-testid="metric-container"]:hover {{
            transform: translateY(-2px);
            border-color: {t['accent_glow']};
        }}

        /* Selectbox & multiselect refinement */
        [data-testid="stSelectbox"] [data-baseweb="select"] > div,
        [data-testid="stMultiSelect"] [data-baseweb="select"] > div {{
            border-radius: 8px !important;
            min-height: 42px !important;
        }}

        /* Form submit buttons */
        [data-testid="stForm"] [data-testid="stFormSubmitButton"] button {{
            background: var(--accent) !important;
            color: #ffffff !important;
            border: none !important;
            font-weight: 600 !important;
            border-radius: 8px !important;
            box-shadow: 0 2px 12px {t['accent_glow']} !important;
            padding: 10px 24px !important;
        }}
        [data-testid="stForm"] [data-testid="stFormSubmitButton"] button:hover {{
            filter: brightness(1.1) !important;
            transform: translateY(-1px);
        }}

        /* Checkbox premium */
        [data-testid="stCheckbox"] {{
            padding: 4px 0 !important;
        }}
        [data-testid="stCheckbox"] label {{
            gap: 10px !important;
        }}

        /* Streamlit container with border — card styling */
        [data-testid="stVerticalBlockBorderWrapper"] {{
            border-radius: 16px !important;
            border-color: var(--border) !important;
            background: var(--card-bg) !important;
        }}
        [data-testid="stVerticalBlockBorderWrapper"] > div {{
            padding: 20px 24px !important;
        }}

        ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
        ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 999px; }}
        #MainMenu {{ visibility: hidden; }}
        footer {{ visibility: hidden; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def severity_badge(severity: str) -> str:
    cls = {"HIGH": "qx-badge-high", "MEDIUM": "qx-badge-medium", "LOW": "qx-badge-low"}.get(severity, "")
    label = TR_SEVERITY.get(severity, severity)
    return f'<span class="qx-badge {cls}">{html.escape(label)}</span>'


def status_badge(status: str) -> str:
    cls = {
        "Open": "qx-badge-open",
        "In Review": "qx-badge-review",
        "Resolved": "qx-badge-resolved",
        "Dismissed": "qx-badge-dismissed",
    }.get(status, "qx-badge-dismissed")
    label = TR_STATUS.get(status, status)
    return f'<span class="qx-badge {cls}">{html.escape(label)}</span>'


def subject_label(subject: str) -> str:
    return TR_SUBJECT.get(subject, subject)


def priority_badge(priority: str) -> str:
    cls = {"P1": "qx-badge-p1", "P2": "qx-badge-p2", "P3": "qx-badge-p3"}.get(priority, "")
    return f'<span class="qx-badge {cls}">{html.escape(priority)}</span>'


def card(html_content: str) -> None:
    st.markdown(f'<div class="qx-card">{html_content}</div>', unsafe_allow_html=True)


def kpi_card(label: str, value: str, delta: str, direction: str = "neutral", accent: str = "", highlight: bool = False) -> str:
    t = get_theme()
    if highlight:
        bg = t['accent']
        text_color = "#ffffff"
        delta_color = "rgba(255,255,255,0.8)"
        arrow_bg = "rgba(255,255,255,0.2)"
    else:
        bg = t['card_bg']
        text_color = t['text_primary']
        delta_color = t['success'] if direction == "up" else (t['high'] if direction == "down" else t['text_secondary'])
        arrow_bg = t['accent_soft']
    arrow_icon = "↗" if direction == "up" else ("↘" if direction == "down" else "→")
    return (
        f'<div style="background:{bg};border:1px solid {t["border"]};border-radius:16px;'
        f'padding:20px 22px;position:relative;min-width:0;">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
        f'<div style="font-size:0.78rem;font-weight:600;color:{delta_color if highlight else t["text_secondary"]};">{html.escape(label)}</div>'
        f'<span style="display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;'
        f'border-radius:8px;background:{arrow_bg};font-size:0.8rem;">{arrow_icon}</span>'
        f'</div>'
        f'<div style="font-size:2.2rem;font-weight:800;color:{text_color};margin:10px 0 6px;line-height:1;">{html.escape(value)}</div>'
        f'<div style="font-size:0.78rem;color:{delta_color};">'
        f'{"▲" if direction == "up" else ("▼" if direction == "down" else "●")} {html.escape(delta)}</div>'
        f'</div>'
    )


def kpi_grid(*cards: str, auto: bool = False) -> None:
    cls = "qx-kpi-grid qx-kpi-grid-auto" if auto else "qx-kpi-grid"
    st.markdown(f'<div class="{cls}">{"".join(cards)}</div>', unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "", badges: list[str] | None = None):
    """Premium page title block."""
    t = get_theme()
    badge_html = ""
    for b in badges or []:
        badge_html += f'<span class="qx-page-badge">{html.escape(b)}</span> '
    sub_part = f'<p class="qx-page-sub">{html.escape(subtitle)}</p>' if subtitle else ""
    badge_part = f'<div class="qx-page-badges">{badge_html}</div>' if badge_html else ""
    st.markdown(
        f'<div class="qx-page-header">'
        f'<div class="qx-page-header-glow"></div>'
        f'<div class="qx-page-header-inner">'
        f'<h1 class="qx-page-title">{html.escape(title)}</h1>'
        f'{sub_part}'
        f'{badge_part}'
        f'</div></div>',
        unsafe_allow_html=True,
    )


def section_header(title: str, subtitle: str = "", icon: str = ""):
    """Section divider with icon."""
    icon_html = f'<span class="qx-section-icon">{html.escape(icon)}</span>' if icon else ""
    sub_html = f'<div class="qx-section-sub">{html.escape(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f'<div class="qx-section-head">'
        f'{icon_html}'
        f'<div><div class="qx-section-title">{html.escape(title)}</div>'
        f'{sub_html}'
        f'</div></div>',
        unsafe_allow_html=True,
    )


def plotly_layout(fig, t, height=None):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=t["text_primary"], family="Inter, sans-serif"),
        margin=dict(l=10, r=10, t=36, b=10),
        legend=dict(font=dict(color=t["text_secondary"], size=11)),
    )
    fig.update_xaxes(gridcolor=t["border"], zerolinecolor=t["border"], showgrid=True, gridwidth=1)
    fig.update_yaxes(gridcolor=t["border"], zerolinecolor=t["border"], showgrid=False)
    if height:
        fig.update_layout(height=height)
    return fig


def init_session_data():
    if "findings" not in st.session_state:
        st.session_state["findings"] = []
    else:
        # Ensure findings have source_table (schema may have been updated)
        _f = st.session_state["findings"]
        if _f and len(_f) > 0 and "source_table" not in _f[0]:
            st.session_state["findings"] = load_dq_findings()
    if "audit_log" not in st.session_state:
        st.session_state["audit_log"] = []
    if "fr_anomalies" not in st.session_state:
        st.session_state["fr_anomalies"] = []
    if "fr_corrections" not in st.session_state:
        st.session_state["fr_corrections"] = []
    if "fr_scan_done" not in st.session_state:
        st.session_state["fr_scan_done"] = False
    if "fr_upload_anomalies" not in st.session_state:
        st.session_state["fr_upload_anomalies"] = []
    if "wizard_stats" not in st.session_state:
        st.session_state["wizard_stats"] = {}
    if "usage_lines" not in st.session_state:
        st.session_state["usage_lines"] = 0
    if "usage_rules" not in st.session_state:
        st.session_state["usage_rules"] = 0
    if "fr_removed_df" not in st.session_state:
        st.session_state["fr_removed_df"] = pd.DataFrame()
    if "usage_refs" not in st.session_state:
        st.session_state["usage_refs"] = 0
    if "fr_clean_df" not in st.session_state:
        st.session_state["fr_clean_df"] = pd.DataFrame()


def get_fr_anomalies():
    return st.session_state.get("fr_anomalies", [])


def get_fr_corrections():
    return st.session_state.get("fr_corrections", [])


def fr_resolve_anomaly(anomaly_id: str, action: str, rejection_reason: str = "", corrected_value: str = ""):
    anomaly = None
    for store_key in ("fr_anomalies", "fr_upload_anomalies"):
        for a in st.session_state.get(store_key, []):
            if a["id"] == anomaly_id:
                anomaly = a
                break
        if anomaly:
            break
    # Also check DQ_FINDINGS from database
    if not anomaly:
        db_findings = load_dq_findings()
        for f in db_findings:
            if f.get("id") == anomaly_id:
                anomaly = {
                    "id": f["id"],
                    "account_id": str(f.get("account_id", "")),
                    "company_name": str(f.get("company_name", "")),
                    "rule_id": str(f.get("rule_id", "")),
                    "field": str(f.get("field", "")),
                    "field_label": str(f.get("field_label", "")),
                    "field_value": str(f.get("field_value", "")),
                    "expected_value": str(f.get("expected_value", "")),
                    "severity": str(f.get("severity", "MEDIUM")),
                    "status": str(f.get("status", "Open")),
                }
                break
    if not anomaly:
        return
    new_status = "Resolved" if action == "Accepted" else "Dismissed"
    correction = {
        "id": f"COR-{len(st.session_state['fr_corrections']) + 1:03d}",
        "anomaly_id": anomaly_id,
        "account_id": anomaly["account_id"],
        "company_name": anomaly["company_name"],
        "field": anomaly["field"],
        "field_value": anomaly["field_value"],
        "expected_value": anomaly["expected_value"],
        "rule_id": anomaly["rule_id"],
        "action": action,
        "rejection_reason": rejection_reason if action == "Rejected" else "",
        "timestamp": _now().strftime("%Y-%m-%d %H:%M"),
        "status": "Accepted" if action == "Accepted" else "Rejected",
    }
    st.session_state["fr_corrections"].insert(0, correction)
    write_dq_correction_db(correction)
    anomaly["status"] = new_status
    # Update status in DQ_FINDINGS table
    update_finding_status_db(anomaly_id, new_status)
    # If accepted with a corrected value, update the source table (DIM_ACCOUNT)
    if action == "Accepted" and corrected_value and anomaly.get("account_id") and anomaly.get("field"):
        field_col = anomaly["field"]
        account_id = anomaly["account_id"]
        try:
            _sf_execute(
                f"UPDATE QUALITY_TEST.COMMERCIAL_DATA.DIM_ACCOUNT "
                f"SET {field_col} = %(val)s WHERE account_id = %(acct)s",
                {"val": corrected_value, "acct": account_id},
            )
            load_dim_account.clear()
        except Exception:
            pass  # Column may not exist in DIM_ACCOUNT — skip silently
    add_audit_entry(
        "Correction FR acceptée" if action == "Accepted" else "Correction FR rejetée",
        f'{anomaly_id} · {anomaly["field"]} · {anomaly["company_name"]}'
        + (f' → {corrected_value}' if corrected_value else ''),
    )


def get_findings():
    """Get findings, ensuring source_table column is present (reload if stale cache)."""
    _f = st.session_state.get("findings")
    if _f and len(_f) > 0 and "source_table" not in _f[0]:
        # Stale cache without source_table — force reload
        load_dq_findings.clear()
        _f = load_dq_findings()
        st.session_state["findings"] = _f
        return _f
    if _f is not None:
        return _f
    return load_dq_findings()


def get_audit_log():
    return st.session_state.get("audit_log", load_dq_audit_log())


def update_finding_status(finding_id: str, new_status: str):
    # Update in session findings list
    for f in st.session_state.get("findings", []):
        if f["id"] == finding_id:
            f["status"] = new_status
            break
    # Also update in fr_upload_anomalies if present
    for f in st.session_state.get("fr_upload_anomalies", []):
        if f.get("id") == finding_id:
            f["status"] = new_status
            break
    update_finding_status_db(finding_id, new_status)


def add_audit_entry(action: str, detail: str):
    entry = {
        "time": _now().strftime("%Y-%m-%d %H:%M"),
        "user": st.session_state.get("sf_user", "unknown"),
        "action": action,
        "detail": detail,
    }
    st.session_state["audit_log"].insert(0, entry)
    write_audit_log_db(action, detail)


def render_filter_pills(
    label: str,
    options: list[tuple[str, str]],
    state_key: str,
    key_prefix: str,
    reset_page_key: str | None = None,
):
    st.markdown(f"**{label}**")
    cols = st.columns(len(options))
    current = st.session_state.get(state_key, "All")
    for i, (display, value) in enumerate(options):
        with cols[i]:
            if st.button(
                display,
                key=f"{key_prefix}_{value}",
                use_container_width=True,
                type="primary" if current == value else "secondary",
            ):
                st.session_state[state_key] = value
                if reset_page_key:
                    st.session_state[reset_page_key] = 0
                st.rerun()


# ---------------------------------------------------------------------------
# Import fichier · détection colonnes · croisement INSEE
# ---------------------------------------------------------------------------


def _norm_col(name: str) -> str:
    n = re.sub(r"[^a-z0-9]", "_", str(name).lower().strip())
    return re.sub(r"_+", "_", n).strip("_")


def _cell_str(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    s = str(val).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def _digits_only(val: str) -> str:
    return re.sub(r"\D", "", _cell_str(val))


def detect_column_mapping(columns: list[str]) -> dict[str, str | None]:
    normalized = {_norm_col(c): c for c in columns}
    mapping = {}
    used_columns = set()
    # Pass 1: exact alias match (highest confidence)
    for field, aliases in COLUMN_ALIASES.items():
        mapping[field] = None
        for alias in aliases:
            key = _norm_col(alias)
            if key in normalized and normalized[key] not in used_columns:
                mapping[field] = normalized[key]
                used_columns.add(normalized[key])
                break
    # Pass 2: for unmatched fields, check if any column CONTAINS an alias
    for field, aliases in COLUMN_ALIASES.items():
        if mapping[field] is not None:
            continue
        best_match = None
        best_len = 999
        for col_norm, col_orig in normalized.items():
            if col_orig in used_columns:
                continue
            for alias in aliases:
                alias_norm = _norm_col(alias)
                if alias_norm in col_norm and len(col_norm) < best_len:
                    best_match = col_orig
                    best_len = len(col_norm)
        if best_match:
            mapping[field] = best_match
            used_columns.add(best_match)
    return mapping


def detect_column_mapping_ai(columns: tuple) -> dict[str, str | None]:
    """Use Cortex AI to intelligently map CSV column headers to expected fields."""
    target_fields = {
        "siren": "SIREN — 9-digit French company registration number",
        "siret": "SIRET — 14-digit French establishment number (SIREN + NIC)",
        "company_name": "Company name / Raison sociale",
        "vat": "VAT number / N° TVA intracommunautaire (starts with FR)",
        "address": "Street address / Adresse postale",
        "city": "City / Ville / Commune",
        "naf": "NAF/APE code — French industry classification (format: 4 digits + 1 letter)",
        "country": "Country code or name",
        "account_id": "Unique account/customer identifier",
        "legal_form": "Legal form / Forme juridique (SA, SAS, SARL, EURL…)",
    }
    cols_str = json.dumps(list(columns), ensure_ascii=False)
    fields_str = json.dumps(target_fields, ensure_ascii=False)
    prompt = (
        f"You are a data mapping assistant. Match these CSV/Excel column headers to the target fields.\n\n"
        f"CSV columns: {cols_str}\n\n"
        f"Target fields (key: description): {fields_str}\n\n"
        f"IMPORTANT RULES:\n"
        f"- When multiple columns could match a field, prefer the SHORTEST and SIMPLEST column name.\n"
        f"  Example: prefer 'Siret' over 'Billing Account: Siret Number'.\n"
        f"- Column matching is case-insensitive. 'VAT' matches 'vat'.\n"
        f"- A column named exactly like the field (e.g. 'Siret' for siret) is always the best match.\n"
        f"- Do NOT map a field if there is no reasonable match — use null.\n"
        f"- Each column can only be mapped to ONE field.\n\n"
        f"Return ONLY a valid JSON object where keys are target field names and values are "
        f"the best matching CSV column name (exact string from the CSV columns list), or null if no match.\n"
        f"Do not add explanations. Only output the JSON object."
    )
    try:
        df = _sf_query(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', $${prompt}$$) AS result")
        if df.empty:
            return {k: None for k in target_fields}
        raw = str(df.iloc[0]['result']).strip()
        # Extract JSON from potential markdown code block
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        mapping = json.loads(raw)
        # Normalize keys to lowercase and validate mapped values exist in columns
        col_set = set(columns)
        # Build case-insensitive lookup for column matching
        col_lower_map = {c.strip().lower(): c for c in columns}
        result = {}
        for k, v in mapping.items():
            key = k.strip().lower()
            if key not in target_fields:
                continue
            if v is None:
                result[key] = None
            elif v in col_set:
                result[key] = v
            elif isinstance(v, str) and v.strip().lower() in col_lower_map:
                result[key] = col_lower_map[v.strip().lower()]
            else:
                result[key] = None
        # Fill missing fields with None
        for k in target_fields:
            if k not in result:
                result[k] = None
        return result
    except Exception:
        return {k: None for k in target_fields}


def _clean_trailing_junk(df: pd.DataFrame) -> pd.DataFrame:
    """Remove trailing rows that are empty or contain footer text (not real data)."""
    if df.empty:
        return df
    # Drop rows where ALL columns are NaN/empty
    df = df.dropna(how="all").reset_index(drop=True)
    # Drop rows where the first non-null cell looks like a footer
    footer_patterns = re.compile(
        r"^(confidential|copyright|©|all rights reserved|generated by|report generated|"
        r"do not distribute|proprietary|disclaimer|page \d|total[:\s])",
        re.IGNORECASE,
    )
    rows_to_drop = []
    # Check from the end — stop at first real data row
    for i in range(len(df) - 1, -1, -1):
        row_vals = [str(v).strip() for v in df.iloc[i] if pd.notna(v) and str(v).strip()]
        if not row_vals:
            rows_to_drop.append(i)
            continue
        first_val = row_vals[0]
        if footer_patterns.search(first_val):
            rows_to_drop.append(i)
            continue
        # Row has real data — stop trimming
        break
    if rows_to_drop:
        df = df.drop(index=rows_to_drop).reset_index(drop=True)
    return df


def load_uploaded_file(uploaded) -> pd.DataFrame:
    name = uploaded.name.lower()
    raw = uploaded.getvalue()

    if name.endswith((".xlsx", ".xlsm", ".xls")):
        try:
            df = pd.read_excel(io.BytesIO(raw), dtype=str)
            first_col = str(df.columns[0]).strip()
            if first_col.replace(" ", "").isdigit() or len(df.columns[0]) > 80:
                df = pd.read_excel(io.BytesIO(raw), dtype=str, header=1)
            return _clean_trailing_junk(df)
        except Exception as exc:
            raise ValueError(
                f"Impossible de lire le fichier Excel ({exc}). "
                "Formats supportés : .xlsx · pour .xls ancien, exportez en CSV."
            ) from exc

    last_err = None
    for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        for sep in (";", ",", "\t", "|"):
            try:
                df = pd.read_csv(io.BytesIO(raw), sep=sep, encoding=encoding, dtype=str, on_bad_lines="skip")
                if df.shape[1] >= 2:
                    return _clean_trailing_junk(df)
            except Exception as exc:
                last_err = exc
    raise ValueError(f"Impossible de lire le fichier CSV ({last_err})")


def _valid_siren(siren: str) -> bool:
    return bool(re.fullmatch(r"\d{9}", siren))


def _valid_siret(siret: str) -> bool:
    return bool(re.fullmatch(r"\d{14}", siret))


def _valid_vat_fr(vat: str) -> bool:
    v = _cell_str(vat).upper().replace(" ", "")
    return bool(re.fullmatch(r"FR[A-HJ-NP-Z0-9]{2}\d{9}", v)) or bool(re.fullmatch(r"FR\d{11}", v))


def _valid_naf(naf: str) -> bool:
    n = naf.strip().replace(".", "").replace(" ", "")
    return bool(re.fullmatch(r"\d{4}[A-Za-z]", n))


_LEGAL_FORM_PATTERN = re.compile(
    r"\b(SAS|SARL|SA|SE|SCA|SNC|EURL|SCI|GIE|SCM|SASU|EARL|GAEC|SEM|EP)\b",
    re.IGNORECASE,
)


def _extract_legal_form(company_name: str) -> str:
    m = _LEGAL_FORM_PATTERN.search(company_name)
    return m.group(0).upper() if m else ""


def _siret_matches_siren(siren: str, siret: str) -> bool:
    return len(siren) == 9 and len(siret) == 14 and siret.startswith(siren)


def _vat_from_siren(siren: str) -> str:
    if not _valid_siren(siren):
        return ""
    # Public entities (communes, départements, établissements publics) use alphanumeric
    # TVA keys that cannot be computed from the SIREN alone.
    # SIREN starting with 1 or 2 = collectivités territoriales / organismes publics
    if siren[0] in ("1", "2"):
        return ""
    key = (12 + 3 * (int(siren) % 97)) % 97
    return f"FR{key:02d}{siren}"


def _is_french_city(city: str) -> bool:
    """Heuristic: detect if a city looks French (no DB query needed)."""
    if not city or len(city.strip()) < 2:
        return False
    city_upper = city.upper().strip()
    # Contains CEDEX → definitely French
    if "CEDEX" in city_upper:
        return True
    # Ends with FR
    if city_upper.endswith(" FR"):
        return True
    # Contains a French postal code pattern (5 digits)
    import re
    if re.search(r'\b\d{5}\b', city_upper):
        return True
    return False


@st.cache_data(ttl=300)
def _insee_search_by_name(company: str, city: str = "", postal_code: str = "") -> dict | None:
    """Fuzzy search SIRENE using EDITDISTANCE + SOUNDEX + scoring. Returns best match or None."""
    if not company or len(company.strip()) < 3:
        return None
    name_clean = company.upper().replace("'", "''").strip()[:60]
    # Remove common suffixes that differ between data and official names
    for suffix in ("SAS", "SARL", "SA", "SCI", "EURL", "EI", "SNC", "SASU"):
        name_clean = re.sub(rf'\b{suffix}\b', '', name_clean).strip()
    name_clean = re.sub(r'\s+', ' ', name_clean).strip()
    if len(name_clean) < 3:
        return None

    city_clean = ""
    if city:
        city_clean = city.upper().replace("'", "''").strip()
        for suffix in ("FR", "FRANCE", "CEDEX"):
            city_clean = city_clean.replace(suffix, "").strip()
        city_clean = re.sub(r'\d{5}', '', city_clean).strip()

    cp_clean = postal_code.strip()[:5] if postal_code else ""

    # Blocking: limit candidates using first 3 chars OR SOUNDEX OR partial match
    blocking_conditions = []
    if len(name_clean) >= 3:
        prefix3 = name_clean[:3].replace("'", "''")
        # Use multiple blocking strategies for better recall
        blocking_conditions.append(
            f"(LEFT(UPPER(u.DENOMINATION), 3) = '{prefix3}' "
            f"OR SOUNDEX(u.DENOMINATION) = SOUNDEX('{name_clean}') "
            f"OR UPPER(u.DENOMINATION) LIKE '%{name_clean[:6]}%')"
        )

    # Scoring query with EDITDISTANCE
    score_expr = f"(1.0 - (EDITDISTANCE(UPPER(u.DENOMINATION), '{name_clean}') / GREATEST(LENGTH(u.DENOMINATION), LENGTH('{name_clean}'), 1))) * 60"

    # City bonus
    city_score = "0"
    if city_clean and len(city_clean) >= 3:
        city_score = f"CASE WHEN UPPER(e.LIBELLE_COMMUNE) LIKE '%{city_clean}%' THEN 25 ELSE 0 END"

    # CP bonus
    cp_score = "0"
    if cp_clean and len(cp_clean) == 5:
        cp_score = f"CASE WHEN e.CODE_POSTAL = '{cp_clean}' THEN 20 WHEN LEFT(e.CODE_POSTAL, 2) = '{cp_clean[:2]}' THEN 10 ELSE 0 END"

    where_parts = ["u.ETAT_ADMINISTRATIF = 'A'", "u.DENOMINATION IS NOT NULL", "LENGTH(u.DENOMINATION) > 2"]
    if blocking_conditions:
        where_parts.extend(blocking_conditions)

    query = f"""
        SELECT u.SIREN AS siren, u.DENOMINATION AS raison_sociale,
               e.LIBELLE_COMMUNE AS ville, e.CODE_POSTAL AS code_postal,
               u.SIREN || u.NIC_SIEGE AS siret,
               u.ACTIVITE_PRINCIPALE AS naf,
               ({score_expr}) AS name_score,
               ({city_score}) AS city_score,
               ({cp_score}) AS cp_score,
               ({score_expr}) + ({city_score}) + ({cp_score}) AS total_score
        FROM {_SIRENE_UL} u
        LEFT JOIN {_SIRENE_ETAB} e ON e.SIRET = u.SIREN || u.NIC_SIEGE
        WHERE {' AND '.join(where_parts)}
        ORDER BY total_score DESC
        LIMIT 5
    """
    try:
        df = _sf_query(query)
        if not df.empty:
            best = df.iloc[0]
            total = float(best.get("total_score", 0) or 0)
            if total >= 35:  # Minimum threshold for accepting a match
                return df.to_dict("records")[0]
    except Exception:
        pass
    return None


def _insee_crossref_row(siren: str, siret: str, company: str, address: str, naf: str) -> list[dict]:
    """Croisement SIRENE réel (Marketplace 29M+) + écarts nom/adresse/NAF."""
    issues = []
    if not siren:
        return issues
    # Try cache first (pre-loaded for DIM_ACCOUNT), then individual lookup
    ref = load_sirene_cache().get(siren) or lookup_sirene(siren)
    if not ref:
        issues.append({
            "rule_id": "INSEE", "field": "SIREN", "field_label": "SIREN",
            "field_value": siren, "expected_value": "Présent au registre INSEE SIRENE",
            "severity": "MEDIUM", "finding_type": "SIREN absent du registre INSEE",
            "description": "SIREN introuvable dans le registre national SIRENE (29M+ entreprises)",
        })
        return issues
    if siret and ref.get("siret") and siret != ref["siret"]:
        issues.append({
            "rule_id": "INSEE", "field": "SIRET", "field_label": "SIRET",
            "field_value": siret, "expected_value": ref["siret"],
            "severity": "HIGH", "finding_type": "SIRET différent du siège INSEE",
            "description": "Le SIRET fichier ne correspond pas au siège SIRENE",
        })
    if company and ref.get("raison_sociale"):
        c_norm = company.upper()
        r_norm = str(ref["raison_sociale"]).upper()
        if c_norm not in r_norm and r_norm not in c_norm:
            issues.append({
                "rule_id": "INSEE", "field": "company_name", "field_label": "Raison sociale",
                "field_value": company, "expected_value": ref["raison_sociale"],
                "severity": "MEDIUM", "finding_type": "Raison sociale vs INSEE",
                "description": "Écart entre le nom fichier et la raison sociale SIRENE",
            })
    if address and ref.get("adresse"):
        a_norm = address.upper()[:20]
        r_addr = ref["adresse"].upper()[:20]
        if a_norm not in ref["adresse"].upper() and r_addr not in address.upper():
            issues.append({
                "rule_id": "INSEE", "field": "address", "field_label": "Adresse",
                "field_value": address, "expected_value": ref["adresse"],
                "severity": "MEDIUM", "finding_type": "Adresse vs INSEE",
                "description": "Adresse fichier différente du siège SIRENE",
            })
    if naf and ref.get("naf") and naf.replace(".", "").upper() != ref["naf"].replace(".", "").upper():
        issues.append({
            "rule_id": "INSEE", "field": "naf", "field_label": "NAF/APE",
            "field_value": naf, "expected_value": ref["naf"],
            "severity": "LOW", "finding_type": "Code NAF vs INSEE",
            "description": "Code NAF/APE différent du registre INSEE",
        })
    return issues


def analyze_uploaded_dataframe(
    df: pd.DataFrame,
    mapping: dict[str, str | None],
    source: str = "import",
    enabled_rules: list[str] | None = None,
    skip_duplicate_check: bool = False,
    custom_rules: list[dict] | None = None,
) -> tuple[list[dict], dict]:
    anomalies = []
    seen_siren = {}
    total = len(df)
    clean_rows = 0
    row_prefix = "DB" if source == "snowflake" else "IMP"
    active_rules = set(enabled_rules or [r["id"] for r in FR_BUSINESS_RULES] + ["INSEE"])
    custom_rules = custom_rules or []
    # Auto-load custom rules from Snowflake if none provided (skip if empty to save time)
    if not custom_rules:
        try:
            db_rules = list_custom_rules(active_only=True)
            custom_rules = [
                {"id": r["id"], "name": r["name"], "field": r["target_field"],
                 "pattern": r.get("pattern", ""), "severity": r.get("severity", "MEDIUM"),
                 "rule_type": r.get("rule_type", "regex")}
                for r in db_rules
            ]
        except Exception:
            custom_rules = []

    # Pre-load SIRENE cache for all SIRENs in this dataset (1 batch query instead of N)
    _sirene_batch_cache: dict = {}
    if "INSEE" in active_rules and mapping.get("siren"):
        siren_col = mapping["siren"]
        if siren_col in df.columns:
            all_sirens = df[siren_col].dropna().astype(str).str.strip().str.replace(r'\D', '', regex=True)
            valid_sirens = [s for s in all_sirens.unique() if len(s) == 9][:1000]  # Cap at 1000 for speed
            if valid_sirens:
                batch_size = 500
                for i in range(0, len(valid_sirens), batch_size):
                    batch = valid_sirens[i:i+batch_size]
                    siren_list = ",".join(f"'{s}'" for s in batch)
                    batch_df = _sf_query(f"""
                        SELECT u.SIREN AS siren, u.DENOMINATION AS raison_sociale,
                               u.SIREN || u.NIC_SIEGE AS siret, u.ACTIVITE_PRINCIPALE AS naf,
                               u.ETAT_ADMINISTRATIF AS statut, u.CATEGORIE_JURIDIQUE AS categorie_juridique,
                               e.LIBELLE_COMMUNE || ' ' || COALESCE(e.CODE_POSTAL, '') AS adresse
                        FROM {_SIRENE_UL} u
                        LEFT JOIN {_SIRENE_ETAB} e ON e.SIRET = u.SIREN || u.NIC_SIEGE
                        WHERE u.SIREN IN ({siren_list})
                    """)
                    if not batch_df.empty:
                        for rec in batch_df.to_dict("records"):
                            _sirene_batch_cache[str(rec.get("siren", ""))] = rec

    # Also pre-load SIRENs derived from VAT numbers in the file
    if "INSEE" in active_rules and mapping.get("vat"):
        vat_col = mapping["vat"]
        if vat_col in df.columns:
            vat_series = df[vat_col].dropna().astype(str).str.upper().str.replace(" ", "", regex=False)
            fr_vats = vat_series[vat_series.str.startswith("FR") & (vat_series.str.len() >= 13)]
            derived_sirens = fr_vats.str[-9:]
            new_sirens = [s for s in derived_sirens.unique() if s.isdigit() and len(s) == 9 and s not in _sirene_batch_cache]
            if new_sirens:
                batch_size = 500
                for i in range(0, len(new_sirens), batch_size):
                    batch = new_sirens[i:i+batch_size]
                    siren_list = ",".join(f"'{s}'" for s in batch)
                    batch_df = _sf_query(f"""
                        SELECT u.SIREN AS siren, u.DENOMINATION AS raison_sociale,
                               u.SIREN || u.NIC_SIEGE AS siret, u.ACTIVITE_PRINCIPALE AS naf,
                               u.ETAT_ADMINISTRATIF AS statut, u.CATEGORIE_JURIDIQUE AS categorie_juridique,
                               e.LIBELLE_COMMUNE || ' ' || COALESCE(e.CODE_POSTAL, '') AS adresse
                        FROM {_SIRENE_UL} u
                        LEFT JOIN {_SIRENE_ETAB} e ON e.SIRET = u.SIREN || u.NIC_SIEGE
                        WHERE u.SIREN IN ({siren_list})
                    """)
                    if not batch_df.empty:
                        for rec in batch_df.to_dict("records"):
                            _sirene_batch_cache[str(rec.get("siren", ""))] = rec

    # Pre-resolve companies that have no SIREN/SIRET/VAT by name+city (batch Cortex SQL)
    _name_resolved: dict = {}  # company_upper -> siren
    if "INSEE" in active_rules and mapping.get("company_name"):
        _name_col = mapping["company_name"]
        _city_col = mapping.get("city")
        # Find rows with no identity
        _siren_col = mapping.get("siren")
        _siret_col = mapping.get("siret")
        _vat_col = mapping.get("vat")
        _needs_lookup = []
        for _i, _r in df.iterrows():
            _has_id = False
            if _siren_col and _siren_col in _r.index and str(_r[_siren_col] or "").strip():
                _has_id = True
            if _siret_col and _siret_col in _r.index and str(_r[_siret_col] or "").strip():
                _has_id = True
            if _vat_col and _vat_col in _r.index:
                _v = str(_r[_vat_col] or "").upper().replace(" ", "")
                if _v.startswith("FR") and len(_v) >= 13:
                    _has_id = True
            if not _has_id and _name_col in _r.index:
                _cname = str(_r[_name_col] or "").strip()
                _ccity = str(_r[_city_col] or "").strip() if _city_col and _city_col in _r.index else ""
                if _cname and len(_cname) >= 3:
                    _needs_lookup.append((_cname, _ccity))

        # Batch: do max 5 lookups (avoid slowdown on large SIRENE table)
        for _cname, _ccity in _needs_lookup[:5]:
            _key = _cname.upper()
            if _key in _name_resolved:
                continue
            _match = _insee_search_by_name(_cname, _ccity)
            if _match and _match.get("siren"):
                _found = str(_match["siren"]).strip()
                _name_resolved[_key] = _found
                if _found not in _sirene_batch_cache and len(_found) == 9:
                    _ref = lookup_sirene(_found)
                    if _ref:
                        _sirene_batch_cache[_found] = _ref

    # Pre-validate mapping: if a mapped column is empty in >90% of rows, un-map it
    # This prevents false positives when a column doesn't really contain the expected data
    _sample_size = min(200, len(df))
    _sample_df = df.head(_sample_size)
    for _field in ["siren", "siret", "naf", "legal_form", "vat"]:
        _col = mapping.get(_field)
        if _col and _col in _sample_df.columns:
            _non_empty = _sample_df[_col].dropna().astype(str).str.strip().replace("", pd.NA).dropna()
            if len(_non_empty) < _sample_size * 0.1:
                mapping[_field] = None  # Un-map: column is mostly empty

    # If vat column was un-mapped or mostly empty, try alternative vat columns (intracom)
    if not mapping.get("vat"):
        _vat_aliases_norm = [_norm_col(a) for a in COLUMN_ALIASES["vat"]]
        for col in df.columns:
            if col == mapping.get("vat"):
                continue
            col_norm = _norm_col(col)
            if any(alias in col_norm for alias in _vat_aliases_norm if alias):
                _non_empty = _sample_df[col].dropna().astype(str).str.strip().replace("", pd.NA).dropna()
                if len(_non_empty) >= _sample_size * 0.1:
                    mapping["vat"] = col
                    break

    for idx, row in df.iterrows():
        row_num = int(idx) + 2  # header = ligne 1
        row_id = f"{row_prefix}-{row_num:04d}"

        def val(field: str) -> str:
            col = mapping.get(field)
            return _cell_str(row[col]) if col and col in row.index else ""

        account_id = val("account_id") or row_id
        company = val("company_name") or f"Ligne {row_num}"
        siren = _digits_only(val("siren"))
        siret = _digits_only(val("siret"))
        vat = _cell_str(val("vat")).upper().replace(" ", "")
        address = val("address")
        city = val("city").strip()
        naf = val("naf")
        country_raw = val("country").upper().strip()
        # Normalize country: handle "FRANCE", "FRA", CEDEX patterns, and city+country mixed
        _country_fr_variants = ("FR", "FRA", "FRANCE", "FRENCH")
        # Detect if city field contains country hint (e.g. "Cergy FR")
        _city_upper = city.upper()
        if not country_raw and _city_upper:
            # Check if city ends with a country code
            parts = _city_upper.split()
            if parts and parts[-1] in _country_fr_variants:
                country_raw = "FR"
            elif "CEDEX" in _city_upper or any(p.isdigit() and len(p) == 5 for p in parts):
                country_raw = "FR"  # CEDEX = French postal convention
        # Determine if row is French
        _is_fr = False
        _fr_names = ("FR", "FRA", "FRANCE", "FRENCH")
        if not country_raw:
            _is_fr = True  # No country specified → assume FR
        elif country_raw in _fr_names:
            _is_fr = True
        else:
            # Normalize full-text country names
            _country_norm = country_raw.replace("É", "E").replace("È", "E").replace("Ê", "E")
            if _country_norm in _fr_names:
                _is_fr = True

        if not _is_fr:
            clean_rows += 1
            continue  # Skip non-French rows — only validate FR entities

        country = "FR"
        legal_form = val("legal_form")

        row_issues = []

        # Try to resolve SIREN from name if available (for providing real expected values)
        _resolved_siren = ""
        _resolved_ref = None
        if company and company.upper() in _name_resolved:
            _resolved_siren = _name_resolved[company.upper()]
            _resolved_ref = _sirene_batch_cache.get(_resolved_siren)

        # Only check SIREN/SIRET if those columns are actually mapped
        _has_siren_mapped = mapping.get("siren") is not None
        _has_siret_mapped = mapping.get("siret") is not None

        if _has_siren_mapped or _has_siret_mapped:
            if not siren and not siret:
                if "R01" in active_rules:
                    _exp_siren = _resolved_siren if _resolved_siren else "9 chiffres numériques"
                    _exp_desc = f"SIREN trouvé via INSEE : {_resolved_siren}" if _resolved_siren else "Le champ SIREN est vide (aucun SIREN ni SIRET exploitable)"
                    row_issues.append({
                        "rule_id": "R01", "field": "SIREN", "field_label": "SIREN",
                        "field_value": val("siren"), "expected_value": _exp_siren,
                        "severity": "HIGH", "finding_type": "SIREN vide",
                        "description": _exp_desc,
                    })
            else:
                if _has_siren_mapped and "R01" in active_rules:
                    if siren and not _valid_siren(siren):
                        row_issues.append({
                            "rule_id": "R01", "field": "SIREN", "field_label": "SIREN",
                            "field_value": val("siren"), "expected_value": "9 chiffres numériques",
                            "severity": "HIGH", "finding_type": "Format SIREN invalide",
                            "description": f"Le SIREN doit contenir exactement 9 chiffres (trouvé: {len(siren)} chiffres)",
                        })
                    elif not siren:
                        row_issues.append({
                            "rule_id": "R01", "field": "SIREN", "field_label": "SIREN",
                            "field_value": val("siren"), "expected_value": "9 chiffres",
                            "severity": "HIGH", "finding_type": "SIREN vide",
                            "description": "Le champ SIREN est vide",
                        })
                    elif not skip_duplicate_check and siren in seen_siren:
                        row_issues.append({
                            "rule_id": "DUP", "field": "SIREN", "field_label": "SIREN",
                            "field_value": siren, "expected_value": f"Unique (doublon ligne {seen_siren[siren]})",
                            "severity": "HIGH", "finding_type": "Doublon SIREN dans le fichier",
                            "description": f"SIREN déjà présent ligne {seen_siren[siren]}",
                        })
                    else:
                        seen_siren[siren] = row_num

                if _has_siret_mapped and "R02" in active_rules:
                    if siret and not _valid_siret(siret):
                        row_issues.append({
                            "rule_id": "R02", "field": "SIRET", "field_label": "SIRET",
                            "field_value": val("siret"), "expected_value": "14 chiffres numériques",
                            "severity": "HIGH", "finding_type": "Format SIRET invalide",
                            "description": f"Le SIRET doit contenir exactement 14 chiffres (trouvé: {len(siret)} chiffres)",
                        })
                    elif not siret:
                        row_issues.append({
                            "rule_id": "R02", "field": "SIRET", "field_label": "SIRET",
                            "field_value": val("siret"), "expected_value": "14 chiffres",
                            "severity": "MEDIUM", "finding_type": "SIRET vide",
                            "description": "Le champ SIRET est vide",
                        })

                if "R03" in active_rules and siren and siret and _valid_siren(siren) and _valid_siret(siret) and not _siret_matches_siren(siren, siret):
                    row_issues.append({
                        "rule_id": "R03", "field": "SIRET", "field_label": "SIRET",
                        "field_value": siret, "expected_value": f"{siren} + 5 caractères établissement",
                        "severity": "HIGH", "finding_type": "Incohérence SIRET / SIREN",
                        "description": "Les 9 premiers chiffres du SIRET doivent égaler le SIREN",
                    })

        # --- Resolve SIREN for INSEE cross-check (no derivation/calculation) ---
        _derived_siren = ""
        _derived_ref = None
        if siren and _valid_siren(siren):
            _derived_siren = siren
            _derived_ref = _sirene_batch_cache.get(siren)
        elif siret and len(re.sub(r'\D', '', siret)) >= 9:
            # Extract SIREN from SIRET (first 9 digits) — this is not a calculation,
            # SIRET literally contains the SIREN as its first 9 digits
            _pot = re.sub(r'\D', '', siret)[:9]
            if len(_pot) == 9:
                _derived_siren = _pot
                _derived_ref = _sirene_batch_cache.get(_pot)

        # R04-R07 always execute
        if "R04" in active_rules and (mapping.get("vat") or mapping.get("country") or mapping.get("city")):
            if country in ("", "FR", "FRA", "FRANCE"):
                # Get expected TVA from INSEE reference if available (try derived first, then resolved)
                _ref_for_vat = _derived_ref or _resolved_ref
                _expected_vat = str(_ref_for_vat.get("tva", "")) if _ref_for_vat and _ref_for_vat.get("tva") else ""
                # If no TVA in ref but we have a SIREN, compute it
                if not _expected_vat and (_derived_siren or _resolved_siren):
                    _s = _derived_siren or _resolved_siren
                    _expected_vat = _vat_from_siren(_s) if len(_s) == 9 else ""
                if mapping.get("vat") and not vat:
                    row_issues.append({
                        "rule_id": "R04", "field": "VAT_NUMBER", "field_label": "N° TVA intracom",
                        "field_value": "", "expected_value": _expected_vat or "FR + 11 chiffres",
                        "severity": "HIGH", "finding_type": "TVA intracom vide",
                        "description": f"TVA trouvée via INSEE : {_expected_vat}" if _expected_vat else "Le champ N° TVA est vide",
                    })
                elif vat and not _valid_vat_fr(vat):
                    row_issues.append({
                        "rule_id": "R04", "field": "VAT_NUMBER", "field_label": "N° TVA intracom",
                        "field_value": vat, "expected_value": _expected_vat or "FR + 11 chiffres",
                        "severity": "HIGH", "finding_type": "Format TVA intracom invalide",
                        "description": f"TVA non-FR détectée" if vat[:2] != "FR" else "Format attendu : FRxxxxxxxxxxx",
                    })
                elif vat and _valid_vat_fr(vat) and _expected_vat and vat != _expected_vat:
                    # TVA format OK but doesn't match INSEE reference
                    row_issues.append({
                        "rule_id": "R04", "field": "VAT_NUMBER", "field_label": "N° TVA intracom",
                        "field_value": vat, "expected_value": _expected_vat,
                        "severity": "MEDIUM", "finding_type": "TVA divergente INSEE",
                        "description": f"TVA différente de la référence INSEE pour le SIREN {_derived_siren}",
                    })

        _is_account_french = country in ("", "FR", "FRA", "FRANCE") or _is_french_city(city)

        # R06 — format NAF/APE (only for French accounts)
        if "R06" in active_rules and mapping.get("naf") and _is_account_french:
            if naf:
                if not _valid_naf(naf):
                    row_issues.append({
                        "rule_id": "R06", "field": "NAF", "field_label": "Code NAF/APE",
                        "field_value": naf, "expected_value": "XX.XXZ (ex : 6202A)",
                        "severity": "MEDIUM", "finding_type": "Format NAF/APE invalide",
                        "description": "Le code NAF/APE doit respecter le format XXXXZ (4 chiffres + 1 lettre)",
                    })
            elif not naf:
                row_issues.append({
                    "rule_id": "R06", "field": "NAF", "field_label": "Code NAF/APE",
                    "field_value": "", "expected_value": "XX.XXZ",
                    "severity": "LOW", "finding_type": "Code NAF/APE absent",
                    "description": "Le code NAF/APE est requis pour les comptes FR",
                })

        # R07 — forme juridique (only for French accounts)
        if "R07" in active_rules and mapping.get("legal_form") and _is_account_french:
            if not legal_form:
                extracted = _extract_legal_form(company)
                if not extracted:
                    row_issues.append({
                        "rule_id": "R07", "field": "LEGAL_FORM", "field_label": "Forme juridique",
                        "field_value": "", "expected_value": "SA, SAS, SARL, SE…",
                        "severity": "MEDIUM", "finding_type": "Forme juridique manquante",
                        "description": "Champ forme juridique vide et non déductible du nom commercial",
                    })

        # Custom rules (supports regex, not_empty, in_list, length)
        for cr in custom_rules:
            field = cr.get("field", "")
            col = mapping.get(field)
            if not col or col not in row.index:
                continue
            raw_val = _cell_str(row[col])
            rule_type = cr.get("rule_type", "regex")
            pattern = cr.get("pattern", "")
            if rule_type == "not_empty":
                failed = not raw_val.strip()
                expected = "Non vide"
            elif rule_type == "in_list":
                allowed = [v.strip().upper() for v in pattern.split(",") if v.strip()]
                failed = raw_val.strip().upper() not in allowed
                expected = f"Valeur parmi : {pattern}"
            elif rule_type == "length":
                parts = pattern.split(":")
                mn = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0
                mx = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 9999
                failed = not (mn <= len(raw_val) <= mx)
                expected = f"Longueur entre {mn} et {mx}"
            else:  # regex
                failed = (not raw_val.strip()) if not pattern else not re.search(pattern, raw_val)
                expected = pattern or "Non vide"
            if failed:
                row_issues.append({
                    "rule_id": cr["id"], "field": field,
                    "field_label": IMPORT_FIELD_LABELS.get(field, field),
                    "field_value": raw_val, "expected_value": expected,
                    "severity": cr.get("severity", "MEDIUM"),
                    "finding_type": cr.get("name", "Règle personnalisée"),
                    "description": f"Règle personnalisée {cr['id']} non respectée",
                })

        # --- Generic INSEE cross-validation: compare ALL available fields against reference ---
        if "INSEE" in active_rules and _is_account_french and _derived_ref:
            _ref = _derived_ref
            # Compare SIREN
            if _has_siren_mapped and siren and _derived_siren and siren != _derived_siren:
                row_issues.append({
                    "rule_id": "INSEE", "field": "SIREN", "field_label": "SIREN",
                    "field_value": siren, "expected_value": _derived_siren,
                    "severity": "HIGH", "finding_type": "SIREN divergent INSEE",
                    "description": f"SIREN attendu : {_derived_siren}",
                })
            # Compare SIRET
            if _has_siret_mapped and siret and _ref.get("siret") and siret != str(_ref["siret"]):
                row_issues.append({
                    "rule_id": "INSEE", "field": "SIRET", "field_label": "SIRET",
                    "field_value": siret, "expected_value": str(_ref["siret"]),
                    "severity": "MEDIUM", "finding_type": "SIRET divergent INSEE",
                    "description": f"SIRET siège attendu : {_ref['siret']}",
                })
            # Compare NAF
            if mapping.get("naf") and naf and _ref.get("naf"):
                if naf.replace(".", "").upper() != str(_ref["naf"]).replace(".", "").upper():
                    row_issues.append({
                        "rule_id": "INSEE", "field": "NAF", "field_label": "Code NAF",
                        "field_value": naf, "expected_value": str(_ref["naf"]),
                        "severity": "LOW", "finding_type": "NAF divergent INSEE",
                        "description": f"Code NAF officiel : {_ref['naf']}",
                    })
            # Check if enterprise is still active
            if _ref.get("statut") and str(_ref["statut"]).upper() != "A":
                row_issues.append({
                    "rule_id": "INSEE", "field": "SIREN", "field_label": "Statut",
                    "field_value": _derived_siren, "expected_value": "Active (A)",
                    "severity": "HIGH", "finding_type": "Entreprise fermée / radiée",
                    "description": "Entreprise inactive selon le registre SIRENE",
                })
            # Compare company name (if very different, flag it)
            if company and _ref.get("raison_sociale"):
                from difflib import SequenceMatcher
                _sim = SequenceMatcher(None, company.upper()[:30], str(_ref["raison_sociale"]).upper()[:30]).ratio()
                if _sim < 0.4:
                    row_issues.append({
                        "rule_id": "INSEE", "field": "COMPANY_NAME", "field_label": "Raison sociale",
                        "field_value": company, "expected_value": str(_ref["raison_sociale"]),
                        "severity": "LOW", "finding_type": "Nom divergent INSEE",
                        "description": f"Nom officiel INSEE : {_ref['raison_sociale']}",
                    })
        elif "INSEE" in active_rules and _is_account_french and _derived_siren and not _derived_ref:
            # SIREN found but not in SIRENE registry
            row_issues.append({
                "rule_id": "INSEE", "field": "SIREN", "field_label": "SIREN",
                "field_value": _derived_siren, "expected_value": "Présent au registre SIRENE",
                "severity": "MEDIUM", "finding_type": "SIREN absent du registre",
                "description": "SIREN introuvable dans le registre national",
            })

        if not row_issues:
            clean_rows += 1

        for j, issue in enumerate(row_issues):
            anomalies.append({
                "id": f"{row_id}-{issue['rule_id']}-{j}",
                "account_id": account_id,
                "company_name": company,
                "row_num": row_num,
                "source": source,
                "status": "Open",
                **issue,
            })

    stats = {
        "total_rows": total,
        "anomaly_count": len(anomalies),
        "affected_rows": total - clean_rows,
        "clean_rows": clean_rows,
        "einvoicing_ready": sum(
            1 for _, row in df.iterrows()
            if _valid_siren(_digits_only(_cell_str(row[mapping["siren"]]) if mapping.get("siren") and mapping["siren"] in row.index else ""))
            and _valid_siret(_digits_only(_cell_str(row[mapping["siret"]]) if mapping.get("siret") and mapping["siret"] in row.index else ""))
            and _siret_matches_siren(
                _digits_only(_cell_str(row[mapping["siren"]])),
                _digits_only(_cell_str(row[mapping["siret"]])),
            )
        ) if mapping.get("siren") and mapping.get("siret") else 0,
        "score": round(clean_rows / total * 100) if total else 0,
        "active_rules": sorted(active_rules),
    }
    return anomalies, stats


def get_all_fr_anomalies():
    """Anomalies backend (DQ_FINDINGS) + anomalies analyse session (fichier ou table)."""
    # Load from DQ_FINDINGS database
    db_findings = load_dq_findings()
    # Filter by current source table
    _current_fqn = _dim_account_fqn().upper()
    _current_table = st.session_state.get("sf_table", "").upper()
    db_anomalies = []
    for f in db_findings:
        _src = str(f.get("source_table") or "").upper()
        if _src and _src != _current_fqn and not _src.endswith(f".{_current_table}"):
            continue  # Skip findings from other tables
        db_anomalies.append({
            "id": f.get("id", ""),
            "account_id": str(f.get("account_id", "")),
            "company_name": str(f.get("company_name", "")),
            "rule_id": str(f.get("rule_id", "")),
            "field": str(f.get("field", "")),
            "field_label": str(f.get("field_label", "")),
            "field_value": str(f.get("field_value", "")),
            "expected_value": str(f.get("expected_value", "")),
            "severity": str(f.get("severity", "MEDIUM")),
            "finding_type": str(f.get("finding_type", "")),
            "description": str(f.get("description", "")),
            "status": str(f.get("status", "Open")),
            "source": "snowflake",
        })
    # Also include session-uploaded anomalies
    uploaded = st.session_state.get("fr_upload_anomalies", [])
    # Deduplicate by ID
    seen_ids = {a["id"] for a in db_anomalies}
    for a in uploaded:
        if a["id"] not in seen_ids:
            db_anomalies.append(a)
    return db_anomalies



def compute_fr_sla(anomalies: list, total: int) -> list:
    """Recalcule les SLA R01-R08 à partir des anomalies de la dernière analyse."""
    if not anomalies or not total:
        return [{**rule, "ok": total or 0, "total": total or 0, "sla_pct": 100 if total else 0} for rule in FR_BUSINESS_RULES]
    fail_accounts: dict[str, set] = {}
    for a in anomalies:
        rid = a.get("rule_id", "")
        key = str(a.get("account_id") or a.get("row_num", ""))
        fail_accounts.setdefault(rid, set()).add(key)
    fr_stats = st.session_state.get("fr_upload_stats", {})
    einvoicing_ready = fr_stats.get("einvoicing_ready", 0)
    if not einvoicing_ready and total:
        # Compute from findings: e-facturation ready = accounts without R01, R02, R03 failures
        r01_r02_r03_fails = fail_accounts.get("R01", set()) | fail_accounts.get("R02", set()) | fail_accounts.get("R03", set())
        einvoicing_ready = max(0, total - len(r01_r02_r03_fails))
    result = []
    for rule in FR_BUSINESS_RULES:
        rid = rule["id"]
        if rid == "R08":
            ok = einvoicing_ready
        else:
            fails = len(fail_accounts.get(rid, set()))
            ok = max(0, total - fails)
        sla = round(ok / total * 100) if total else 0
        result.append({**rule, "ok": ok, "total": total, "sla_pct": sla})
    return result


def _run_wizard_analysis(selected_subjects: list) -> dict:
    """Compute wizard summary stats from DQ_FINDINGS filtered by selected subjects."""
    subject_rule_map: dict[str, set] = {
        "compliance": {"R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08", "INSEE"},
        "duplicates": {"DUP"},
        "address": {"ADDR"},
        "web": {"WEB"},
    }
    active_rules: set = set()
    for subj in selected_subjects:
        active_rules |= subject_rule_map.get(subj, set())
    findings = get_findings()
    relevant = [f for f in findings if f.get("rule_id") in active_rules]
    records = len(load_dim_account(_dim_account_fqn())) or 1
    affected_ids = {f["account_id"] for f in relevant if f["status"] in ("Open", "In Review")}
    clean = records - len(affected_ids)
    score = round(clean / records * 100) if records else 0
    high = sum(1 for f in relevant if f["severity"] == "HIGH")
    med = sum(1 for f in relevant if f["severity"] == "MEDIUM")
    low = sum(1 for f in relevant if f["severity"] == "LOW")
    return {
        "total_rows": records,
        "anomaly_count": len(relevant),
        "affected_rows": len(affected_ids),
        "clean_rows": clean,
        "score": score,
        "high": high,
        "med": med,
        "low": low,
        "active_rules": sorted(active_rules),
        "duration_s": 0,  # Will be measured during actual execution
    }


def _store_analysis_results(anomalies: list, stats: dict, label: str, source: str):
    st.session_state["fr_upload_anomalies"] = anomalies
    st.session_state["fr_upload_stats"] = stats
    st.session_state["fr_upload_filename"] = label
    st.session_state["fr_data_source"] = source
    st.session_state["fr_scan_done"] = True
    st.session_state["usage_lines"] = st.session_state.get("usage_lines", 0) + stats.get("total_rows", 0)
    st.session_state["usage_rules"] = st.session_state.get("usage_rules", 0) + len(stats.get("active_rules", []))
    st.session_state["usage_refs"] = st.session_state.get("usage_refs", 0) + stats.get("total_rows", 0)

    # Persist new anomalies to DQ_FINDINGS table (so dashboard shows them)
    if anomalies:
        for a in anomalies:
            _sf_execute(
                "INSERT INTO QUALITY_TEST.DATA_QUALITY.DQ_FINDINGS "
                "(id, account_id, company_name, severity, status, subject, rule_id, "
                "field, field_label, field_value, expected_value, finding_type, description, source_table) "
                "SELECT %(id)s, %(aid)s, %(name)s, %(sev)s, 'Open', 'Compliance', %(rid)s, "
                "%(field)s, %(fl)s, %(fv)s, %(ev)s, %(ft)s, %(desc)s, %(src)s "
                "WHERE NOT EXISTS (SELECT 1 FROM QUALITY_TEST.DATA_QUALITY.DQ_FINDINGS WHERE id = %(id)s)",
                {"id": a["id"], "aid": a.get("account_id", ""), "name": a.get("company_name", ""),
                 "sev": a.get("severity", "MEDIUM"), "rid": a.get("rule_id", ""),
                 "field": a.get("field", ""), "fl": a.get("field_label", ""),
                 "fv": str(a.get("field_value", ""))[:500], "ev": str(a.get("expected_value", ""))[:500],
                 "ft": a.get("finding_type", ""), "desc": a.get("description", "")[:1000],
                 "src": _dim_account_fqn()},
            )
        load_dq_findings.clear()


def _render_detection_pipeline_help():
    with st.expander("Comment fonctionne la détection et l'analyse ?", expanded=False):
        st.markdown("""
**Les deux sources passent par le même moteur d'analyse** — seule l'étape de chargement change.

| Étape | Table Snowflake | Fichier CSV / Excel |
|-------|-----------------|---------------------|
| **1. Chargement** | Table choisie (`DIM_ACCOUNT` par défaut) · mapping colonnes **fixe** | Upload · parsing auto (CSV `;` `,` tab · Excel) |
| **2. Mapping** | Colonnes prédéfinies (`siren`, `siret`, `company_name`, `forme_juridique`…) | **Détection auto** des en-têtes + ajustement manuel |
| **3. Règles R01–R08** | Format SIREN, SIRET, cohérence, TVA, pays, NAF, forme juridique, e-fact. | Idem |
| **4. Croisement INSEE** | Registre SIRENE réel (29M+ entreprises, Marketplace) | Idem |
| **5. Dédoublonnage** | SQL `ROW_NUMBER()` sur clés configurables (SIREN, SIRET…) | Idem (staging Snowflake) |
| **6. Résultats** | Score avant/après · aperçu données nettoyées · centre de résolution | Idem |

**Détection auto des colonnes (fichiers)** — on normalise chaque en-tête (`Raison Sociale` → `raison_sociale`) et on le compare à une liste d'alias :
`siren`, `num_siren`, `siret`, `raison_sociale`, `tva_intra`, `adresse`, `naf`, `code_ape`, `forme_juridique`…

**Règles appliquées ligne par ligne :**
- **R01** SIREN = 9 chiffres · **R02** SIRET = 14 chiffres · **R03** SIRET commence par SIREN
- **R04** TVA `FR` + 11 caractères · **R05** Code pays = FR (comptes domestiques)
- **R06** Format NAF/APE `XXXXZ` · **R07** Forme juridique renseignée (SA, SAS, SARL…)
- **R08** Prêt e-facturation (SIREN + SIRET valides + cohérents pour PDP) — dérivé de R01–R03
- **Doublons** : dédoublonnage **automatique** (configurable) · plus de flood d'anomalies DUP
- **Règles personnalisées** : regex ou champ obligatoire sur colonnes mappées
- **INSEE** comparaison nom / adresse / NAF vs registre SIRENE national

> Connexion Snowflake réelle et API INSEE live : configuré.
        """)


def _render_mapping_table(mapping: dict[str, str | None], detected: dict[str, str | None] | None = None):
    rows = ""
    for field, label in IMPORT_FIELD_LABELS.items():
        col = mapping.get(field)
        if detected is not None:
            auto = detected.get(field)
            status = (
                '<span class="qx-badge qx-badge-match">Auto</span>'
                if auto and auto == col
                else ('<span class="qx-badge qx-badge-warn">Ajusté</span>' if col else '<span class="qx-badge qx-badge-error">—</span>')
            )
        else:
            status = '<span class="qx-badge qx-badge-match">Fixe</span>' if col else '<span class="qx-badge qx-badge-error">—</span>'
        rows += (
            f"<tr><td>{html.escape(label)}</td>"
            f"<td><code>{html.escape(col) if col else '—'}</code></td>"
            f"<td>{status}</td></tr>"
        )
    st.markdown(
        f'<div class="qx-card" style="overflow-x:auto;font-size:0.85rem;">'
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<thead><tr style="border-bottom:1px solid var(--border);">'
        f'<th style="text-align:left;padding:6px;">Champ métier</th>'
        f'<th style="text-align:left;padding:6px;">Colonne source</th>'
        f'<th style="text-align:left;padding:6px;">Statut</th>'
        f'</tr></thead><tbody>{rows}</tbody></table></div>',
        unsafe_allow_html=True,
    )


def _fr_tab_source_analyse():
    t = get_theme()
    accent = t['accent']

    # Premium section header with accent bar
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:18px;">'
        f'<div style="width:3px;height:18px;border-radius:2px;background:{accent};"></div>'
        f'<div>'
        f'<div style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};">Source & analyse</div>'
        f'<div style="font-size:0.75rem;color:{t["text_secondary"]};">Table Snowflake ou CSV — moteur exécuté sur Snowflake (staging + SQL + INSEE).</div>'
        f'</div>'
        f'<span style="font-size:0.62rem;padding:3px 10px;background:{t["accent_soft"]};color:{accent};border-radius:999px;font-weight:600;margin-left:auto;">Snowflake connecté</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    _render_detection_pipeline_help()

    enabled_rules = _render_rules_and_dedup_config("fr")
    auto_dedup = st.session_state.get("fr_auto_dedup", True)
    dedup_keys = st.session_state.get("fr_dedup_keys", DEFAULT_DEDUP_KEYS)
    dedup_strategy = st.session_state.get("fr_dedup_strategy", "keep_first")
    custom_rules = [
        {"id": r["id"], "name": r["name"], "field": r["target_field"],
         "pattern": r.get("pattern", ""), "severity": r.get("severity", "MEDIUM"),
         "rule_type": r.get("rule_type", "regex")}
        for r in list_custom_rules(active_only=True)
    ]

    st.markdown("---")
    # Table Snowflake section with icon card
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">'
        f'<div style="width:28px;height:28px;border-radius:8px;background:{t["accent_soft"]};display:flex;align-items:center;justify-content:center;">'
        f'<svg width="14" height="14" fill="none" viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="{accent}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        f'</div>'
        f'<span style="font-size:0.88rem;font-weight:700;color:{t["text_primary"]};">Table Snowflake</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    primary_table = _dim_account_fqn()
    st.caption(f"Table principale (sidebar) : `{primary_table}`")

    extra_tables = [t for t in FR_AUDIT_TABLES if t != primary_table]
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        analyze_primary = st.button("Analyser la table principale", type="primary", key="fr_run_sf_primary")
    with col_t2:
        extra_table = st.selectbox(
            "Autre table (règles différentes)",
            ["— Aucune —"] + extra_tables + [
                t for t in [
                    f"{st.session_state.get('sf_database', 'EDW_DB_SANDBOX')}."
                    f"{st.session_state.get('sf_schema', 'HAZOURLI')}."
                    f"{st.session_state.get('sf_table', 'DIM_ACCOUNT')}"
                ] if t not in FR_AUDIT_TABLES
            ],
            key="fr_extra_table",
        )
        analyze_extra = st.button("Analyser cette table", key="fr_run_sf_extra", disabled=(extra_table == "— Aucune —"))

    # --- Uploaded file analysis ---
    _has_upload = st.session_state.get("source_mode") == "file" and "uploaded_df" in st.session_state
    analyze_upload = False
    if _has_upload:
        _up_name = st.session_state.get("uploaded_filename", "fichier")
        _up_len = len(st.session_state["uploaded_df"])
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;margin:12px 0;">'
            f'<span style="font-size:0.82rem;font-weight:600;color:{t["text_primary"]};">📂 Fichier uploadé : </span>'
            f'<code>{_up_name}</code> · <span style="color:{t["text_secondary"]};">{_up_len} lignes</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        analyze_upload = st.button("Analyser le fichier uploadé", type="primary", key="fr_run_upload", use_container_width=True)

    if analyze_upload:
        _upload_df = st.session_state["uploaded_df"].copy()
        _upload_df.columns = [c.lower().strip() for c in _upload_df.columns]
        mapping = _mapping_for_table("uploaded_file", list(_upload_df.columns))
        with st.spinner(f"Analyse fichier · {st.session_state.get('uploaded_filename', '')}…"):
            anomalies, stats, df_orig, df_clean, df_removed = run_snowflake_dq_analysis(
                st.session_state.get("uploaded_filename", "fichier"),
                mapping, enabled_rules, dedup_keys, auto_dedup, dedup_strategy, custom_rules,
                df_override=_upload_df,
            )
        _store_analysis_results(anomalies, stats, st.session_state.get("uploaded_filename", "fichier"), "import")
        st.session_state["fr_clean_df"] = df_clean
        st.session_state["fr_removed_df"] = df_removed
        add_audit_entry("Analyse fichier uploadé", f"{st.session_state.get('uploaded_filename', '')} · {stats.get('anomaly_count', 0)} anomalies")
        st.toast(f"{stats.get('anomaly_count', 0)} anomalie(s) · score {stats.get('score', 0)}%")
        st.rerun()
    elif analyze_primary or analyze_extra:
        target = primary_table if analyze_primary else extra_table
        # Load actual columns for proper mapping detection
        _target_df = _sf_query(f"SELECT * FROM {target} LIMIT 1")
        _target_cols = list(_target_df.columns) if not _target_df.empty else None
        mapping = _mapping_for_table(target, _target_cols)
        with st.spinner(f"Analyse Snowflake · {target}…"):
            anomalies, stats, df_orig, df_clean, df_removed = run_snowflake_dq_analysis(
                target, mapping, enabled_rules, dedup_keys, auto_dedup, dedup_strategy, custom_rules,
            )
        _store_analysis_results(anomalies, stats, target.split(".")[-1], "snowflake")
        st.session_state["fr_clean_df"] = df_clean
        st.session_state["fr_removed_df"] = df_removed
        add_audit_entry("Analyse table Snowflake", f"{target} · {stats.get('anomaly_count', 0)} anomalies · engine=snowflake")
        st.toast(f"{stats.get('anomaly_count', 0)} anomalie(s) · score {stats.get('score', 0)}%")
        st.rerun()

    # Preview table Snowflake
    with st.expander(f"Aperçu · {primary_table}", expanded=False):
        preview_df = load_table_as_dataframe(primary_table)
        if preview_df.empty:
            st.info("Table vide ou inaccessible.")
        else:
            st.dataframe(preview_df.head(10), use_container_width=True, hide_index=True)
            mapping_preview = _mapping_for_table(primary_table, list(preview_df.columns))
            _render_mapping_table(mapping_preview)

    st.markdown("---")
    # Import file section with icon
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">'
        f'<div style="width:28px;height:28px;border-radius:8px;background:{t["accent_soft"]};display:flex;align-items:center;justify-content:center;">'
        f'<svg width="14" height="14" fill="none" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" stroke="{accent}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        f'</div>'
        f'<span style="font-size:0.88rem;font-weight:700;color:{t["text_primary"]};">Import fichier CSV / Excel</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    uploaded = st.file_uploader(
        "Fichier clients (CSV, TSV, Excel)",
        type=["csv", "txt", "tsv", "xlsx", "xls", "xlsm"],
        key="fr_file_upload",
    )

    col_dl, _ = st.columns([1, 2])
    with col_dl:
        st.download_button(
            "Télécharger modèle CSV",
            "account_id;raison_sociale;siren;siret;tva_intra;adresse;naf;pays\n"
            "ACC-001;Bouygues SA;552032534;55203253400028;FR27552032534;32 Avenue Hoche Paris;4120A;FR\n"
            "ACC-002;TotalEnergies SE;542051180;54205118000127;;2 Place Jean Millier;0610Z;FR\n"
            "ACC-003;Test Invalid;123;55203253400099;FRBAD;1 rue test;0000Z;FR\n",
            file_name="modele_import_fr.csv",
            mime="text/csv",
            key="fr_template_csv",
        )

    if not uploaded:
        st.markdown(
            '<div class="qx-card" style="text-align:center;color:var(--text-secondary);">'
            "Déposez un CSV ou Excel — les colonnes seront détectées automatiquement</div>",
            unsafe_allow_html=True,
        )
    else:
        try:
            df_raw = load_uploaded_file(uploaded)
        except ValueError as exc:
            st.error(str(exc))
            df_raw = None

        if df_raw is not None:
            st.success(f"**{uploaded.name}** · {len(df_raw)} lignes · {len(df_raw.columns)} colonnes")

            # Option to persist as Snowflake table
            with st.expander("Créer une table Snowflake à partir du fichier", expanded=False):
                _db = st.session_state.get("sf_database", "")
                _sch = st.session_state.get("sf_schema", "")
                default_name = uploaded.name.rsplit(".", 1)[0].upper().replace(" ", "_").replace("-", "_")
                tbl_name = st.text_input("Nom de la table", value=default_name, key="csv_table_name")
                target_fqn = f"{_db}.{_sch}.{tbl_name}"
                st.caption(f"La table sera créée dans `{target_fqn}`")
                if st.button("Créer la table sur Snowflake", type="primary", key="csv_to_sf"):
                    with st.spinner(f"Écriture de {len(df_raw)} lignes dans {target_fqn}..."):
                        ok = stage_dataframe_to_snowflake(df_raw, target_fqn)
                    if ok:
                        st.success(f"Table `{target_fqn}` créée avec {len(df_raw)} lignes.")
                        list_snowflake_tables.clear()
                        # Clear old analysis results
                        for _k in ["fr_anomalies", "fr_last_stats", "fr_clean_df", "fr_removed_df",
                                   "fr_upload_anomalies", "fr_upload_stats", "fr_upload_filename",
                                   "fr_data_source", "fr_scan_done"]:
                            st.session_state.pop(_k, None)
                        add_audit_entry("Table créée depuis CSV", f"{uploaded.name} → {target_fqn}")
                        st.rerun()
                    else:
                        st.error("Erreur lors de la création de la table.")

            with st.expander("Colonnes détectées dans le fichier", expanded=False):
                st.code(", ".join(df_raw.columns.tolist()))
            st.dataframe(df_raw.head(8), use_container_width=True, hide_index=True)

            # 1. AI-based mapping (handles any file/column names)
            with st.spinner("Détection intelligente des colonnes (Cortex AI)…"):
                ai_map = detect_column_mapping_ai(tuple(df_raw.columns))
            # 2. Alias-based mapping (reliable for known patterns)
            alias_map = detect_column_mapping(list(df_raw.columns))
            # 3. Merge: alias overrides AI when it finds a match (more precise)
            auto_map = {field: None for field in IMPORT_FIELD_LABELS}
            for field in auto_map:
                if alias_map.get(field):
                    auto_map[field] = alias_map[field]
                elif ai_map.get(field):
                    auto_map[field] = ai_map[field]

            # 4. Content-based validation: check digit length to fix SIREN vs SIRET confusion
            def _detect_digit_length(col_name: str, df: pd.DataFrame, sample_size: int = 50) -> int:
                """Return the most common digit-only length in a column (0 if not numeric)."""
                if col_name not in df.columns:
                    return 0
                sample = df[col_name].dropna().head(sample_size)
                lengths = sample.astype(str).str.replace(r'\D', '', regex=True).str.len()
                lengths = lengths[lengths > 0]
                if lengths.empty:
                    return 0
                return int(lengths.mode().iloc[0]) if not lengths.mode().empty else 0

            # If SIREN column actually has 14 digits → it's SIRET
            siren_col = auto_map.get("siren")
            siret_col = auto_map.get("siret")
            if siren_col and not siret_col:
                digit_len = _detect_digit_length(siren_col, df_raw)
                if digit_len >= 14:
                    auto_map["siret"] = siren_col
                    auto_map["siren"] = None
            # If SIRET column actually has 9 digits → it's SIREN
            elif siret_col and not siren_col:
                digit_len = _detect_digit_length(siret_col, df_raw)
                if digit_len == 9:
                    auto_map["siren"] = siret_col
                    auto_map["siret"] = None
            st.markdown("##### Mapping colonnes (détection Cortex AI)")
            st.caption("Les colonnes sont mappées par intelligence artificielle (Cortex). Ajustez ci-dessous si besoin.")

            cols = list(df_raw.columns)
            mapping = {}
            map_cols = st.columns(4)
            fields_order = list(IMPORT_FIELD_LABELS.keys())
            for i, field in enumerate(fields_order):
                with map_cols[i % 4]:
                    options = ["— Non mappé —"] + cols
                    default_col = auto_map.get(field)
                    default_idx = options.index(default_col) if default_col in options else 0
                    chosen = st.selectbox(
                        IMPORT_FIELD_LABELS[field],
                        options,
                        index=default_idx,
                        key=f"fr_map_{field}",
                    )
                    mapping[field] = None if chosen == "— Non mappé —" else chosen

            _render_mapping_table(mapping, detected=auto_map)

            # Show which rules will apply based on mapped columns
            _applicable_rules = []
            _missing_critical = []
            if mapping.get("siren"):
                _applicable_rules.append("R01 SIREN")
            else:
                _missing_critical.append("SIREN")
            if mapping.get("siret"):
                _applicable_rules.append("R02 SIRET")
            else:
                _missing_critical.append("SIRET")
            if mapping.get("siren") and mapping.get("siret"):
                _applicable_rules.append("R03 Cohérence")
            if mapping.get("vat"):
                _applicable_rules.append("R04 TVA")
            else:
                _missing_critical.append("TVA")
            if mapping.get("country") or mapping.get("city"):
                _applicable_rules.append("Filtre pays FR")
            if mapping.get("naf"):
                _applicable_rules.append("R06 NAF")
            if mapping.get("legal_form"):
                _applicable_rules.append("R07 Forme juridique")
            if mapping.get("siren"):
                _applicable_rules.append("INSEE Registre national")

            if _missing_critical:
                st.warning(
                    f"⚠️ **Colonnes critiques non mappées** : {', '.join(_missing_critical)}. "
                    f"Mappez-les ci-dessus pour activer plus de règles. "
                    f"Seules **{len(_applicable_rules)}** règle(s) sont applicables avec le mapping actuel."
                )

            if not _applicable_rules:
                st.error("Aucune colonne mappée ne correspond à une règle de contrôle. Ajustez le mapping ci-dessus.")
            else:
                st.info(f"**Règles applicables** : {' · '.join(_applicable_rules)}")
            if _applicable_rules and st.button("Analyser le fichier (via Snowflake)", type="primary", key="fr_run_import"):
                progress_bar = st.progress(0, text="Préparation de l'analyse…")
                progress_bar.progress(5, text="Calcul du score initial…")
                score_before = _quick_score(df_raw, mapping)
                progress_bar.progress(10, text="Dédoublonnage…")
                df_clean, df_removed, dedup_stats = (
                    deduplicate_dataframe(df_raw, mapping, dedup_keys, dedup_strategy)
                    if auto_dedup and dedup_keys
                    else (df_raw.copy(), pd.DataFrame(), {})
                )
                progress_bar.progress(20, text=f"Analyse de {len(df_clean)} lignes (règles DQ + INSEE)…")
                anomalies, stats = analyze_uploaded_dataframe(
                    df_clean, mapping, source="import",
                    enabled_rules=enabled_rules, skip_duplicate_check=auto_dedup,
                    custom_rules=custom_rules,
                )
                progress_bar.progress(80, text="Sauvegarde sur Snowflake…")
                stats["dedup"] = dedup_stats
                stats["score_before"] = score_before
                stats["engine"] = "snowflake"
                stats["active_rules"] = enabled_rules
                stage_dataframe_to_snowflake(df_clean, STAGING_TABLE)
                progress_bar.progress(100, text="Terminé !")
                st.session_state["fr_clean_df"] = df_clean
                st.session_state["fr_removed_df"] = df_removed
                _store_analysis_results(anomalies, stats, uploaded.name, "import")
                add_audit_entry("Import fichier analysé", f"{uploaded.name} · {stats['anomaly_count']} anomalies · snowflake")
                st.toast(f"{stats['anomaly_count']} anomalie(s) détectée(s)")
                st.rerun()

    if st.session_state.get("fr_upload_stats"):
        _render_import_results()


def _render_import_results():
    stats = st.session_state.get("fr_upload_stats", {})
    anomalies = st.session_state.get("fr_upload_anomalies", [])
    fname = st.session_state.get("fr_upload_filename", "fichier")
    df_clean = st.session_state.get("fr_clean_df", pd.DataFrame())
    df_removed = st.session_state.get("fr_removed_df", pd.DataFrame())

    st.markdown("---")
    st.markdown(f"##### Résultats · `{html.escape(fname)}`")
    engine_label = stats.get("engine", "snowflake")
    source_label = "Table Snowflake" if st.session_state.get("fr_data_source") == "snowflake" else "Fichier importé"
    st.markdown(
        '<div class="qx-kpi-grid">'
        + kpi_card("Lignes analysées", str(stats.get("total_rows", 0)), f"{source_label} · {engine_label}", "neutral")
        + kpi_card("Anomalies", str(stats.get("anomaly_count", 0)), f"{stats.get('affected_rows', 0)} lignes impactées", "down")
        + kpi_card("Score conformité", f"{stats.get('score', 0)}%", f"Avant: {stats.get('score_before', '—')}%", "neutral")
        + kpi_card("E-facturation prête", str(stats.get("einvoicing_ready", 0)), "SIREN+SIRET valides", "neutral")
        + '</div>',
        unsafe_allow_html=True,
    )

    _render_cleaning_preview(stats, df_clean, df_removed)

    if not anomalies:
        st.success("Aucune anomalie détectée sur ce fichier.")
        return

    rule_filter = st.multiselect(
        "Filtrer par règle",
        sorted({a["rule_id"] for a in anomalies}),
        default=sorted({a["rule_id"] for a in anomalies}),
        key="fr_import_rule_filter",
    )
    sev_filter = st.multiselect(
        "Filtrer par sévérité",
        ["HIGH", "MEDIUM", "LOW"],
        default=["HIGH", "MEDIUM", "LOW"],
        key="fr_import_sev_filter",
    )
    filtered = [
        a for a in anomalies
        if a["rule_id"] in rule_filter and a["severity"] in sev_filter
    ]
    st.markdown(f"**{len(filtered)}** anomalie(s) affichée(s)")

    # --- Table style like page Anomalies ---
    t = get_theme()
    accent = t['accent']
    # Rules legend
    _rule_descriptions = {
        "R01": ("Format SIREN", "9 chiffres valides", "#ef4444"),
        "R02": ("Format SIRET", "14 chiffres valides", "#ef4444"),
        "R03": ("Cohérence SIRET", "SIRET = SIREN + NIC", "#f59e0b"),
        "R04": ("TVA intracommunautaire", "FR + 11 chiffres (Luhn)", "#f59e0b"),
        "R05": ("Pays FR", "Code pays = FR", "#3b82f6"),
        "R06": ("Code NAF/APE", "Format XX.XXZ", "#3b82f6"),
        "INSEE": ("Validation INSEE", "Registre SIRENE 29M+", "#f59e0b"),
        "DUP": ("Doublon", "SIREN en double", "#ef4444"),
    }
    _active_import_rules = sorted({a["rule_id"] for a in filtered})
    _legend = ""
    for _rid in _active_import_rules:
        _info = _rule_descriptions.get(_rid)
        if _info:
            _rname, _rdesc, _rc = _info
            _legend += (
                f'<div style="display:inline-flex;align-items:center;gap:6px;margin-right:14px;margin-bottom:4px;cursor:help;" title="{_rid} — {_rdesc}">'
                f'<span style="font-size:0.65rem;padding:2px 7px;border-radius:4px;background:{_rc};color:#fff;font-weight:700;">{_rid}</span>'
                f'<span style="font-size:0.75rem;color:{t["text_secondary"]};">{_rname}</span>'
                f'</div>'
            )
    if _legend:
        st.markdown(
            f'<div style="background:{t["card_bg"]};border:1px solid {t["border"]};border-radius:8px;padding:10px 14px;margin-bottom:10px;">'
            f'<div style="font-size:0.65rem;text-transform:uppercase;letter-spacing:0.08em;color:{t["text_secondary"]};font-weight:600;margin-bottom:4px;">Règles · Survoler pour détails</div>'
            f'<div style="display:flex;flex-wrap:wrap;align-items:center;">{_legend}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    select_all_import = st.checkbox("Tout sélectionner", value=False, key="fr_import_select_all")

    table_data = []
    for a in filtered[:50]:
        table_data.append({
            "Sélectionner": select_all_import,
            "Entreprise": a.get("company_name", ""),
            "Anomalie": a.get("finding_type", ""),
            "Champ": a.get("field_label", ""),
            "Valeur": str(a.get("field_value", "") or "—"),
            "Attendu": str(a.get("expected_value", "") or "—"),
            "Sévérité": a.get("severity", ""),
            "Règle": a.get("rule_id", ""),
        })

    if table_data:
        df_table = pd.DataFrame(table_data)
        edited_df = st.data_editor(
            df_table,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Sélectionner": st.column_config.CheckboxColumn("✓", width="small"),
                "Entreprise": st.column_config.TextColumn("Entreprise", width="medium"),
                "Anomalie": st.column_config.TextColumn("Anomalie", width="medium"),
                "Champ": st.column_config.TextColumn("Champ", width="small"),
                "Valeur": st.column_config.TextColumn("Valeur fichier", width="medium"),
                "Attendu": st.column_config.TextColumn("Attendu", width="medium"),
                "Sévérité": st.column_config.SelectboxColumn("Sévérité", options=["HIGH", "MEDIUM", "LOW"], width="small"),
                "Règle": st.column_config.TextColumn("Règle", width="small"),
            },
            key="fr_import_editor",
            num_rows="fixed",
        )

    # Export CSV
    export_df = pd.DataFrame([{
        "Ligne": a.get("row_num", ""),
        "ID": a.get("id", ""),
        "Compte": a.get("account_id", ""),
        "Raison sociale": a.get("company_name", ""),
        "Règle": a["rule_id"],
        "Sévérité": TR_SEVERITY.get(a["severity"], a["severity"]),
        "Champ": a.get("field_label", ""),
        "Valeur fichier": a.get("field_value", ""),
        "Valeur attendue": a.get("expected_value", ""),
        "Type": a.get("finding_type", ""),
    } for a in filtered])
    st.download_button(
        "Exporter les anomalies (CSV)",
        export_df.to_csv(index=False, sep=";"),
        file_name="anomalies_import.csv",
        mime="text/csv",
        key="fr_dl_import_anomalies",
    )

    with st.expander("Détail des anomalies"):
        for a in filtered[:50]:
            card(
                f'{severity_badge(a["severity"])} '
                f'<span class="qx-badge" style="background:var(--accent-soft);color:var(--accent);">{html.escape(a["rule_id"])}</span> '
                f'<strong>Ligne {a["row_num"]}</strong> · {html.escape(a["company_name"])}<br>'
                f'<span style="color:var(--text-secondary);">{html.escape(a["finding_type"])}</span><br>'
                f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px;font-size:0.85rem;">'
                f'<div><span style="color:var(--text-secondary);">Fichier · </span>{html.escape(a["field_value"]) or "—"}</div>'
                f'<div><span style="color:var(--text-secondary);">Attendu · </span>{html.escape(a["expected_value"])}</div>'
                f'</div>'
            )

    if st.button("Envoyer vers le centre de résolution", key="fr_push_resolution"):
        merged = {a["id"]: a for a in get_fr_anomalies()}
        for a in anomalies:
            merged[a["id"]] = {
                "id": a["id"],
                "account_id": a["account_id"],
                "company_name": a["company_name"],
                "field": a["field"],
                "field_label": a["field_label"],
                "field_value": a["field_value"],
                "expected_value": a["expected_value"],
                "rule_id": a["rule_id"],
                "status": "Open",
                "source": "import",
            }
        st.session_state["fr_anomalies"] = list(merged.values())
        st.toast(f"{len(anomalies)} anomalie(s) ajoutée(s) au centre de résolution")
        st.rerun()

    st.success(
        "Validation INSEE SIRENE **active** · Registre national 29M+ entreprises (Marketplace Snowflake)."
    )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------


def render_sidebar():
    t = get_theme()
    findings = get_findings()
    open_findings = sum(1 for f in findings if f["status"] == "Open")
    open_tasks = sum(1 for f in findings if f["status"] in ("Open", "In Review"))
    open_fr = sum(1 for a in get_all_fr_anomalies() if a["status"] in ("Open", "In Review"))

    with st.sidebar:
        st.markdown(
            f"""
            <div style="padding: 12px 8px 10px 8px;">
                <div class="qx-logo"><span class="qx-logo-mark"><svg viewBox="0 0 64 64" width="24" height="24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="32" cy="38" r="18" stroke="#fff" stroke-width="2.5" fill="none"/><path d="M22 56c0-6 4.5-10 10-10s10 4 10 10" stroke="#fff" stroke-width="2.5" stroke-linecap="round" fill="none"/><ellipse cx="32" cy="24" rx="14" ry="4" stroke="#fff" stroke-width="2.5" fill="none"/><path d="M18 24c0-8 6-14 14-14s14 6 14 14" stroke="#fff" stroke-width="2.5" fill="none"/><circle cx="32" cy="14" r="4" stroke="#fff" stroke-width="2.5" fill="none"/><circle cx="26" cy="36" r="5" stroke="#fff" stroke-width="2.2" fill="none"/><circle cx="38" cy="36" r="5" stroke="#fff" stroke-width="2.2" fill="none"/><line x1="31" y1="36" x2="33" y2="36" stroke="#fff" stroke-width="2"/><path d="M28 44c2 2 4 2 6 0" stroke="#fff" stroke-width="2" stroke-linecap="round" fill="none"/><path d="M36 33l38 37" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><path d="M54 20l2-6 2 6-6 2 6 2-2 6-2-6 6-2z" fill="#fff"/></svg></span> Léon</div>
                <div class="qx-logo-sub">DATA QUALITY</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(f'<div class="qx-nav-label">PRINCIPAL</div>', unsafe_allow_html=True)

        current_page = st.session_state.get("page", "dashboard")
        nav_main = [
            ("dashboard", "Tableau de bord", ":material/dashboard:"),
            ("customer_data", "Données clients", ":material/group:"),
            ("rule_catalog", "Catalogue de règles", ":material/menu_book:"),
            ("run_analysis", "Lancer l'analyse", ":material/play_circle:"),
        ]
        for page_id, label, icon in nav_main:
            is_active = current_page == page_id
            if st.button(
                label,
                key=f"nav_{page_id}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
                icon=icon,
            ):
                st.session_state["page"] = page_id
                st.rerun()

        st.markdown(f'<div class="qx-nav-label">RÉSULTATS</div>', unsafe_allow_html=True)

        nav_results = [
            ("findings", "Anomalies", ":material/warning:", open_findings),
            ("tasks", "Tâches", ":material/checklist:", open_tasks),
        ]
        for page_id, label, icon, badge_count in nav_results:
            badge = f" ({badge_count})" if badge_count else ""
            is_active = current_page == page_id
            if st.button(
                f"{label}{badge}",
                key=f"nav_{page_id}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
                icon=icon,
            ):
                st.session_state["page"] = page_id
                st.rerun()

        st.markdown(f'<div class="qx-nav-label">OUTILS</div>', unsafe_allow_html=True)

        nav_tools = [
            ("exports", "Exports", ":material/download:"),
        ]
        for page_id, label, icon in nav_tools:
            is_active = current_page == page_id
            if st.button(
                label,
                key=f"nav_{page_id}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
                icon=icon,
            ):
                st.session_state["page"] = page_id
                st.rerun()

        st.markdown("---")

        # Theme toggle + Snowflake connection (compact)
        col_theme, col_spacer = st.columns([1, 1])
        with col_theme:
            is_light = st.toggle("☀️", value=st.session_state.get("theme") == "light", key="theme_toggle")
            new_theme = "light" if is_light else "dark"
            if st.session_state.get("theme") != new_theme:
                st.session_state["theme"] = new_theme
                st.rerun()
            st.session_state["theme"] = new_theme

        with st.expander("⚙️ Source", expanded=False):
            _dbs = list_snowflake_databases()
            _cur_db = st.session_state.get("sf_database", "")
            sel_db = st.selectbox(
                "Base de données",
                _dbs or [_cur_db],
                index=(_dbs.index(_cur_db) if _cur_db in _dbs else 0),
                key="sf_db_select",
            )
            _schemas = list_snowflake_schemas(sel_db) if sel_db else []
            _cur_schema = st.session_state.get("sf_schema", "")
            sel_schema = st.selectbox(
                "Schéma",
                _schemas or [_cur_schema],
                index=(_schemas.index(_cur_schema) if _cur_schema in _schemas else 0),
                key="sf_schema_select",
            )
            _tables = list_snowflake_tables(sel_db, sel_schema) if sel_db and sel_schema else []
            _cur_table = st.session_state.get("sf_table", "DIM_ACCOUNT")
            sel_table = st.selectbox(
                "Table",
                _tables or [_cur_table],
                index=(_tables.index(_cur_table) if _cur_table in _tables else 0),
                key="sf_table_select",
            )
            if st.button("Valider", type="primary", use_container_width=True, key="sf_validate"):
                st.session_state["sf_database"] = sel_db
                st.session_state["sf_schema"] = sel_schema
                st.session_state["sf_table"] = sel_table
                load_dim_account.clear()
                list_snowflake_databases.clear()
                list_snowflake_schemas.clear()
                list_snowflake_tables.clear()
                st.toast(f"Source : {sel_db}.{sel_schema}.{sel_table}")
                st.rerun()

        with st.expander("📂 Uploader un fichier", expanded=False):
            uploaded_file = st.file_uploader(
                "CSV ou Excel",
                type=["csv", "xlsx", "xls"],
                key="sidebar_file_upload",
                label_visibility="collapsed",
            )
            if uploaded_file is not None:
                if st.button("Charger le fichier", type="primary", use_container_width=True, key="sidebar_upload_btn"):
                    try:
                        if uploaded_file.name.endswith(".csv"):
                            _udf = pd.read_csv(uploaded_file, dtype=str)
                        else:
                            _udf = pd.read_excel(uploaded_file, dtype=str)
                        _udf.columns = [c.strip() for c in _udf.columns]
                        st.session_state["uploaded_df"] = _udf
                        st.session_state["uploaded_filename"] = uploaded_file.name
                        st.session_state["source_mode"] = "file"
                        st.toast(f"✓ {uploaded_file.name} — {len(_udf)} lignes chargées")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erreur lecture : {e}")
            if st.session_state.get("uploaded_filename"):
                st.caption(f"Fichier actif : {st.session_state['uploaded_filename']}")
                # Option to create Snowflake table from uploaded file
                _up_db = st.session_state.get("sf_database", "QUALITY_TEST")
                _up_sch = st.session_state.get("sf_schema", "COMMERCIAL_DATA")
                _default_tbl = st.session_state["uploaded_filename"].rsplit(".", 1)[0].upper().replace(" ", "_").replace("-", "_")
                _tbl_name = st.text_input("Nom table Snowflake", value=_default_tbl, key="sidebar_tbl_name")
                _target_fqn = f"{_up_db}.{_up_sch}.{_tbl_name}"
                if st.button("Créer table sur Snowflake", key="sidebar_create_sf_table", use_container_width=True):
                    with st.spinner(f"Création de {_target_fqn}…"):
                        _ok = stage_dataframe_to_snowflake(st.session_state["uploaded_df"], _target_fqn)
                    if _ok:
                        st.session_state["sf_table"] = _tbl_name
                        st.session_state["source_mode"] = "snowflake"
                        list_snowflake_tables.clear()
                        load_dim_account.clear()
                        add_audit_entry("Table créée depuis CSV", f"{st.session_state['uploaded_filename']} → {_target_fqn}")
                        st.toast(f"✓ Table `{_target_fqn}` créée")
                        st.rerun()
                    else:
                        st.error("Erreur lors de la création.")
                if st.button("Revenir à Snowflake", key="sidebar_back_sf", use_container_width=True):
                    st.session_state["source_mode"] = "snowflake"
                    st.session_state.pop("uploaded_df", None)
                    st.session_state.pop("uploaded_filename", None)
                    st.rerun()
# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def page_dashboard():
    t = get_theme()
    # Load findings — merge DB + session anomalies
    if st.session_state.get("source_mode") == "file":
        findings = st.session_state.get("findings", [])
        # Also include session anomalies from latest analysis
        _upload_anoms = st.session_state.get("fr_upload_anomalies", [])
        if _upload_anoms:
            _seen = {f.get("id") for f in findings}
            for a in _upload_anoms:
                if a.get("id") not in _seen:
                    findings.append(a)
    elif st.session_state.get("fr_scan_done", False):
        # Use cached findings (ttl=60s) — don't clear on every render
        if "findings" not in st.session_state or not st.session_state["findings"]:
            st.session_state["findings"] = load_dq_findings()
        findings = st.session_state["findings"]
    else:
        # No analysis run yet — start with empty findings (clean dashboard)
        findings = []

    # --- Data preparation ---
    _df_active, _source_label = _get_active_data()
    _accounts = _df_active.to_dict("records") if not _df_active.empty else []
    _src_table = st.session_state.get("sf_table", "")
    _src_db = st.session_state.get("sf_database", "")
    _src_schema = st.session_state.get("sf_schema", "")

    records = len(_accounts) or 1
    _ws = st.session_state.get("wizard_stats", {})
    # Filter findings to only those belonging to the current source table
    _table_fqn = _dim_account_fqn()
    _table_fqn_upper = _table_fqn.upper()
    _table_name_only = st.session_state.get("sf_table", "").upper()

    # Match by source_table column (lowercase keys from _sf_query)
    _relevant_findings = [
        f for f in findings
        if str(f.get("source_table") or "").upper() == _table_fqn_upper
        or str(f.get("source_table") or "").upper().endswith(f".{_table_name_only}")
    ]

    # Fallback: if no SOURCE_TABLE match, try matching by account_id
    if not _relevant_findings and _table_name_only:
        _account_ids_in_source = set()
        for a in _accounts:
            _aid = a.get("account_id") or a.get("ACCOUNT_ID") or ""
            if _aid:
                _account_ids_in_source.add(str(_aid).strip())
        if _account_ids_in_source:
            _relevant_findings = [f for f in findings if str(f.get("account_id", "")).strip() in _account_ids_in_source]

    # Final fallback: only show all findings if an analysis was run in this session
    # (avoid showing stale findings from previous sessions on first load)
    if not _relevant_findings and findings and st.session_state.get("fr_scan_done", False):
        _relevant_findings = findings

    # Determine if analysis was ever run on this table
    _analysis_done = bool(_ws) or bool(_relevant_findings) or st.session_state.get("fr_scan_done", False)

    open_count = sum(1 for f in _relevant_findings if f["status"] == "Open")
    review_count = sum(1 for f in _relevant_findings if f["status"] == "In Review")
    resolved_count = sum(1 for f in _relevant_findings if f["status"] == "Resolved")
    dismissed_count = sum(1 for f in _relevant_findings if f["status"] == "Dismissed")
    open_tasks = open_count + review_count
    high_count = sum(1 for f in _relevant_findings if f["severity"] == "HIGH")
    med_count = sum(1 for f in _relevant_findings if f["severity"] == "MEDIUM")
    low_count = sum(1 for f in _relevant_findings if f["severity"] == "LOW")

    if _ws:
        compliance_score = _ws.get("score", 0)
    elif _analysis_done:
        _affected_ids = {f["account_id"] for f in _relevant_findings if f["status"] in ("Open", "In Review")}
        compliance_score = max(0, round((records - len(_affected_ids)) / records * 100)) if records else 0
    else:
        compliance_score = None  # Not yet analyzed
    resolution_rate = round((resolved_count + dismissed_count) / len(_relevant_findings) * 100) if _relevant_findings else 0

    # Delta calculation — skip expensive query if no analysis done
    _delta = 0
    _delta_str = "—"
    if _relevant_findings and _analysis_done:
        try:
            _prev_score_df = _sf_query(f"""
                SELECT ROUND(100.0 * (1 - COUNT(DISTINCT account_id)::FLOAT /
                    NULLIF((SELECT COUNT(*) FROM {_table_fqn}), 0)), 0) AS prev_score
                FROM QUALITY_TEST.DATA_QUALITY.DQ_FINDINGS
                WHERE status IN ('Open','In Review')
                  AND created_at < DATEADD('day', -1, CURRENT_DATE())
                  AND (source_table = '{_table_fqn}' OR source_table IS NULL)
            """)
            if not _prev_score_df.empty and _prev_score_df.iloc[0]['prev_score'] is not None:
                _prev_score = max(0, int(_prev_score_df.iloc[0]['prev_score']))
                _delta = (compliance_score or 0) - _prev_score
                _delta_str = f"{_delta:+d} pts"
        except Exception:
            pass

    # Completeness — compute from in-memory data (no extra SQL query)
    _completeness = 0
    if not _df_active.empty:
        _completeness_targets = {
            "siren", "siret", "company_name", "naf", "country", "legal_form",
            "nom", "ville", "pays", "adresse", "n° tva", "adresse complète",
            "vat", "city", "address", "raison_sociale", "raison sociale",
            "nom_entreprise", "denomination", "code_postal", "cp",
            "tva_intra", "num_tva", "forme_juridique", "code_ape",
            "account_id", "name", "num_siren", "num_siret",
        }
        _check_cols = [c for c in _df_active.columns
                       if c.lower().strip() in _completeness_targets]
        # Fallback: if no known columns found, use ALL columns
        if not _check_cols:
            _check_cols = list(_df_active.columns)
        _subset = _df_active[_check_cols]
        _filled = _subset.apply(lambda col: col.notna() & (col.astype(str).str.strip() != ""))
        _completeness = int(round(_filled.sum().sum() / max(1, len(_df_active) * len(_check_cols)) * 100))

    # Subject/Rule data
    subject_counts = {}
    for f in _relevant_findings:
        subject_counts[f["subject"]] = subject_counts.get(f["subject"], 0) + 1
    _hits_data = load_rule_hits() if _analysis_done else []

    # Show empty state if no data and no findings
    if not _relevant_findings and not _src_table:
        st.info("Configurez une source de données dans le menu **Données clients** pour commencer.")

    # =====================================================================
    # ROW 1 — KPI Cards
    # =====================================================================
    _obj = 80
    _score_display = f"{compliance_score}" if compliance_score is not None else "—"
    _score_suffix = '<span style="font-size:1.2rem;font-weight:600;">%</span>' if compliance_score is not None else ""
    if compliance_score is not None:
        _score_diff = compliance_score - _obj
        _score_badge_color = "#dc2626" if _score_diff < 0 else "#0d9488"
        _score_badge_text = f"{abs(_score_diff)} pts" if _score_diff != 0 else "="
        _score_context = f"sous l'objectif de {_obj} %" if _score_diff < 0 else f"au-dessus de {_obj} %"
    else:
        _score_diff = 0
        _score_badge_color = "#94a3b8"
        _score_badge_text = "Non analysé"
        _score_context = "Lancez une analyse"

    _anom_badge_color = "#0d9488" if _delta >= 0 else "#dc2626"
    _anom_badge_text = f"+{_delta}" if _delta > 0 else str(_delta) if _delta < 0 else "="

    _incomp = max(0, records - round(records * _completeness / 100)) if _completeness else records

    kpi_html = f"""
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px;">
        <!-- Score conformité -->
        <div style="background:{t['card_bg']};border:1px solid {t['border']};border-radius:14px;padding:22px 22px 18px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <div style="font-size:0.68rem;font-weight:600;color:{t['text_secondary']};text-transform:uppercase;letter-spacing:0.06em;">Score de conformité</div>
                <div style="width:32px;height:32px;border-radius:8px;background:rgba(22,163,74,0.1);display:flex;align-items:center;justify-content:center;">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#0d9488" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                </div>
            </div>
            <div style="font-size:2.4rem;font-weight:800;color:{t['text_primary']};line-height:1;">{_score_display}{_score_suffix}</div>
            <div style="display:flex;align-items:center;gap:8px;margin-top:10px;">
                <span style="background:{_score_badge_color};color:#fff;padding:2px 8px;border-radius:6px;font-size:0.65rem;font-weight:700;">
                    {'↓' if _score_diff < 0 else '↑'} {_score_badge_text}</span>
                <span style="font-size:0.7rem;color:{t['text_secondary']};">{_score_context}</span>
            </div>
        </div>
        <!-- Anomalies -->
        <div style="background:{t['card_bg']};border:1px solid {t['border']};border-radius:14px;padding:22px 22px 18px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <div style="font-size:0.68rem;font-weight:600;color:{t['text_secondary']};text-transform:uppercase;letter-spacing:0.06em;">Anomalies</div>
                <div style="width:32px;height:32px;border-radius:8px;background:rgba(234,179,8,0.1);display:flex;align-items:center;justify-content:center;">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#eab308" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                </div>
            </div>
            <div style="font-size:2.4rem;font-weight:800;color:{t['text_primary']};line-height:1;">{len(_relevant_findings)}</div>
            <div style="display:flex;align-items:center;gap:8px;margin-top:10px;">
                <span style="background:{_anom_badge_color};color:#fff;padding:2px 8px;border-radius:6px;font-size:0.65rem;font-weight:700;">
                    ↑ {_anom_badge_text}</span>
                <span style="font-size:0.7rem;color:{t['high']};font-weight:600;">{high_count} critiques</span>
                <span style="font-size:0.7rem;color:{t['text_secondary']};">à traiter</span>
            </div>
        </div>
        <!-- Tâches ouvertes -->
        <div style="background:{t['card_bg']};border:1px solid {t['border']};border-radius:14px;padding:22px 22px 18px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <div style="font-size:0.68rem;font-weight:600;color:{t['text_secondary']};text-transform:uppercase;letter-spacing:0.06em;">Tâches ouvertes</div>
                <div style="width:32px;height:32px;border-radius:8px;background:rgba(2,132,199,0.1);display:flex;align-items:center;justify-content:center;">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#14b8a6" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
                </div>
            </div>
            <div style="font-size:2.4rem;font-weight:800;color:{t['text_primary']};line-height:1;">{open_tasks}</div>
            <div style="display:flex;align-items:center;gap:8px;margin-top:10px;">
                <span style="background:{t['card_bg']};border:1px solid {t['border']};color:{t['text_primary']};padding:2px 8px;border-radius:6px;font-size:0.65rem;font-weight:600;">
                    {review_count} en revue</span>
                <span style="font-size:0.7rem;color:{t['text_secondary']};">{resolved_count} résolues cette semaine</span>
            </div>
        </div>
        <!-- Complétude données -->
        <div style="background:{t['card_bg']};border:1px solid {t['border']};border-radius:14px;padding:22px 22px 18px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <div style="font-size:0.68rem;font-weight:600;color:{t['text_secondary']};text-transform:uppercase;letter-spacing:0.06em;">Complétude données</div>
                <div style="width:32px;height:32px;border-radius:8px;background:rgba(22,163,74,0.1);display:flex;align-items:center;justify-content:center;">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#0d9488" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
                </div>
            </div>
            <div style="font-size:2.4rem;font-weight:800;color:{t['text_primary']};line-height:1;">{_completeness}<span style="font-size:1.2rem;font-weight:600;">%</span></div>
            <div style="display:flex;align-items:center;gap:8px;margin-top:10px;">
                <span style="background:#0d9488;color:#fff;padding:2px 8px;border-radius:6px;font-size:0.65rem;font-weight:700;">
                    +2 pts</span>
                <span style="font-size:0.7rem;color:{t['text_secondary']};">{_incomp} enregistrement(s) incomplet(s)</span>
            </div>
        </div>
    </div>
    """
    st.markdown(kpi_html, unsafe_allow_html=True)

    # =====================================================================
    # ROW 2 — Trend Chart + Conformité Ring
    # =====================================================================
    col_chart, col_ring = st.columns([1.6, 1])

    with col_chart:
        _trend_data = load_compliance_trend()
        if _trend_data:
            trend_df = pd.DataFrame(_trend_data)
            fig_trend = go.Figure()
            fig_trend.add_trace(go.Scatter(
                x=trend_df["date"], y=trend_df["score"],
                mode="lines+markers",
                line=dict(color="#0d9488", width=2.5, shape="spline"),
                marker=dict(size=6, color="#0d9488"),
                fill="tozeroy",
                fillcolor="rgba(13,148,136,0.08)",
                name="Score",
            ))
            fig_trend.add_hline(y=80, line_dash="dot", line_color="#94a3b8", opacity=0.6,
                               annotation_text="Objectif 80", annotation_position="right")
            fig_trend = plotly_layout(fig_trend, t, height=260)
            fig_trend.update_layout(
                yaxis_range=[0, 100], showlegend=True,
                legend=dict(orientation="h", x=0.6, y=1.12, font=dict(size=10)),
            )
            st.markdown(
                f'<div style="background:{t["card_bg"]};border:1px solid {t["border"]};border-radius:14px;padding:20px 22px;">'
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:2px;">'
                f'<div style="width:3px;height:18px;border-radius:2px;background:{t["accent"]};"></div>'
                f'<span style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};">Évolution du score de conformité</span></div>'
                f'<div style="font-size:0.72rem;color:{t["text_secondary"]};margin-left:11px;margin-bottom:8px;">7 derniers jours · objectif 80 %</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.plotly_chart(fig_trend, use_container_width=True)
        else:
            st.markdown(
                f'<div style="background:{t["card_bg"]};border:1px solid {t["border"]};border-radius:14px;padding:60px 20px;text-align:center;color:{t["text_secondary"]};font-size:0.85rem;">'
                f'Le graphique apparaîtra après la première analyse.</div>',
                unsafe_allow_html=True,
            )

    with col_ring:
        # Conformité donut ring
        _cs = compliance_score if compliance_score is not None else 0
        _ring_color = "#0d9488" if _cs >= 70 else ("#eab308" if _cs >= 40 else "#dc2626")
        _ring_status = "Conforme" if _cs >= 80 else "À surveiller" if _cs >= 50 else "Critique"
        _ring_status_color = "#0d9488" if _cs >= 80 else "#eab308" if _cs >= 50 else "#dc2626"
        if compliance_score is None:
            _ring_color = "#94a3b8"
            _ring_status = "Non analysé"
            _ring_status_color = "#94a3b8"
        _pct = _cs
        _ring_bg = t["border_subtle"]
        _ring_score_display = f"{compliance_score}%" if compliance_score is not None else "—"
        st.markdown(
            f'<div style="background:{t["card_bg"]};border:1px solid {t["border"]};border-radius:14px;padding:24px 22px;text-align:center;">'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:20px;justify-content:flex-start;">'
            f'<div style="width:3px;height:18px;border-radius:2px;background:{t["accent"]};"></div>'
            f'<span style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};">Conformité globale</span></div>'
            f'<div style="position:relative;width:180px;height:180px;margin:0 auto;">'
            f'<svg viewBox="0 0 36 36" style="width:180px;height:180px;transform:rotate(-90deg);">'
            f'<path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="{_ring_bg}" stroke-width="3"/>'
            f'<path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="{_ring_color}" stroke-width="3" stroke-dasharray="{_pct}, 100" stroke-linecap="round"/>'
            f'</svg>'
            f'<div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center;">'
            f'<div style="font-size:2.2rem;font-weight:800;color:{t["text_primary"]};line-height:1;">{_ring_score_display}</div>'
            f'<div style="font-size:0.65rem;font-weight:600;color:{t["text_secondary"]};text-transform:uppercase;letter-spacing:0.1em;margin-top:4px;">Conformité</div>'
            f'</div></div>'
            f'<div style="margin-top:16px;display:inline-flex;align-items:center;gap:5px;padding:4px 12px;border-radius:20px;background:rgba({",".join(str(int(_ring_status_color[i:i+2], 16)) for i in (1,3,5))},0.1);font-size:0.72rem;font-weight:600;color:{_ring_status_color};">'
            f'⊘ {_ring_status}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # =====================================================================
    # ROW 3 — Severity + Status
    # =====================================================================
    col_sev, col_status = st.columns(2)

    with col_sev:
        total_f = len(_relevant_findings) or 1
        high_pct = round(high_count / total_f * 100)
        med_pct = round(med_count / total_f * 100)
        low_pct = round(low_count / total_f * 100)
        st.markdown(
            f'<div style="background:{t["card_bg"]};border:1px solid {t["border"]};border-radius:14px;padding:22px 24px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">'
            f'<div style="display:flex;align-items:center;gap:8px;">'
            f'<div style="width:3px;height:18px;border-radius:2px;background:{t["accent"]};"></div>'
            f'<span style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};">Répartition par sévérité</span></div>'
            f'<span style="font-size:0.72rem;color:{t["text_secondary"]};">{len(_relevant_findings)} anomalies</span></div>'
            # Élevée
            f'<div style="margin-bottom:18px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
            f'<div style="display:flex;align-items:center;gap:8px;">'
            f'<span style="width:10px;height:10px;border-radius:50%;background:#ef4444;"></span>'
            f'<span style="font-size:0.82rem;color:{t["text_primary"]};">Élevée</span></div>'
            f'<span style="font-size:0.88rem;font-weight:700;color:{t["text_primary"]};">{high_count}</span></div>'
            f'<div style="height:8px;border-radius:4px;background:{t["border_subtle"]};">'
            f'<div style="height:100%;width:{max(high_pct,2)}%;border-radius:4px;background:#ef4444;"></div></div></div>'
            # Moyenne
            f'<div style="margin-bottom:18px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
            f'<div style="display:flex;align-items:center;gap:8px;">'
            f'<span style="width:10px;height:10px;border-radius:50%;background:#f59e0b;"></span>'
            f'<span style="font-size:0.82rem;color:{t["text_primary"]};">Moyenne</span></div>'
            f'<span style="font-size:0.88rem;font-weight:700;color:{t["text_primary"]};">{med_count}</span></div>'
            f'<div style="height:8px;border-radius:4px;background:{t["border_subtle"]};">'
            f'<div style="height:100%;width:{max(med_pct,2)}%;border-radius:4px;background:#f59e0b;"></div></div></div>'
            # Faible
            f'<div>'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
            f'<div style="display:flex;align-items:center;gap:8px;">'
            f'<span style="width:10px;height:10px;border-radius:50%;background:#14b8a6;"></span>'
            f'<span style="font-size:0.82rem;color:{t["text_primary"]};">Faible</span></div>'
            f'<span style="font-size:0.88rem;font-weight:700;color:{t["text_primary"]};">{low_count}</span></div>'
            f'<div style="height:8px;border-radius:4px;background:{t["border_subtle"]};">'
            f'<div style="height:100%;width:{max(low_pct,2)}%;border-radius:4px;background:#14b8a6;"></div></div></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    with col_status:
        st.markdown(
            f'<div style="background:{t["card_bg"]};border:1px solid {t["border"]};border-radius:14px;padding:22px 24px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">'
            f'<div style="display:flex;align-items:center;gap:8px;">'
            f'<div style="width:3px;height:18px;border-radius:2px;background:{t["accent"]};"></div>'
            f'<span style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};">Statuts de traitement</span></div>'
            f'<span style="font-size:0.72rem;color:{t["text_secondary"]};">Sujet : conformité</span></div>'
            f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">'
            # Ouvert
            f'<div style="background:{t["border_subtle"]};border-radius:10px;padding:16px 18px;">'
            f'<div style="font-size:1.8rem;font-weight:800;color:#2563eb;line-height:1;">{open_count}</div>'
            f'<div style="display:flex;align-items:center;gap:5px;margin-top:6px;">'
            f'<span style="width:7px;height:7px;border-radius:50%;background:#2563eb;"></span>'
            f'<span style="font-size:0.75rem;color:{t["text_secondary"]};">Ouvert</span></div></div>'
            # En revue
            f'<div style="background:{t["border_subtle"]};border-radius:10px;padding:16px 18px;">'
            f'<div style="font-size:1.8rem;font-weight:800;color:#f59e0b;line-height:1;">{review_count}</div>'
            f'<div style="display:flex;align-items:center;gap:5px;margin-top:6px;">'
            f'<span style="width:7px;height:7px;border-radius:50%;background:#f59e0b;"></span>'
            f'<span style="font-size:0.75rem;color:{t["text_secondary"]};">En revue</span></div></div>'
            # Résolu
            f'<div style="background:{t["border_subtle"]};border-radius:10px;padding:16px 18px;">'
            f'<div style="font-size:1.8rem;font-weight:800;color:#0d9488;line-height:1;">{resolved_count}</div>'
            f'<div style="display:flex;align-items:center;gap:5px;margin-top:6px;">'
            f'<span style="width:7px;height:7px;border-radius:50%;background:#0d9488;"></span>'
            f'<span style="font-size:0.75rem;color:{t["text_secondary"]};">Résolu</span></div></div>'
            # Rejeté
            f'<div style="background:{t["border_subtle"]};border-radius:10px;padding:16px 18px;">'
            f'<div style="font-size:1.8rem;font-weight:800;color:#94a3b8;line-height:1;">{dismissed_count}</div>'
            f'<div style="display:flex;align-items:center;gap:5px;margin-top:6px;">'
            f'<span style="width:7px;height:7px;border-radius:50%;background:#94a3b8;"></span>'
            f'<span style="font-size:0.75rem;color:{t["text_secondary"]};">Rejeté</span></div></div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    # =====================================================================
    # ROW 4 — Rules + Anomalies
    # =====================================================================
    col_rules, col_anomalies = st.columns([1, 1.3])

    with col_rules:
        if _hits_data:
            rules_df = pd.DataFrame(_hits_data).sort_values("hits", ascending=False).head(8)
            bars_html = ""
            max_hits = rules_df["hits"].max() or 1
            for _, row in rules_df.iterrows():
                pct = round(row["hits"] / max_hits * 100)
                bars_html += (
                    f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">'
                    f'<div style="width:44px;font-size:0.78rem;font-weight:600;color:{t["text_secondary"]};">{row["rule"]}</div>'
                    f'<div style="flex:1;height:8px;border-radius:4px;background:{t["border_subtle"]};">'
                    f'<div style="height:100%;width:{pct}%;border-radius:4px;background:#0d9488;"></div></div>'
                    f'<div style="width:24px;font-size:0.78rem;font-weight:700;color:{t["text_primary"]};text-align:right;">{int(row["hits"])}</div>'
                    f'</div>'
                )
            st.markdown(
                f'<div style="background:{t["card_bg"]};border:1px solid {t["border"]};border-radius:14px;padding:22px 24px;">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">'
                f'<div style="display:flex;align-items:center;gap:8px;">'
                f'<div style="width:3px;height:18px;border-radius:2px;background:{t["accent"]};"></div>'
                f'<span style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};">Règles déclenchées</span></div>'
                f'<span style="font-size:0.72rem;color:{t["text_secondary"]};">Top 8 · par occurrences</span></div>'
                f'{bars_html}</div>',
                unsafe_allow_html=True,
            )

    with col_anomalies:
        recent = _relevant_findings[:6] if _relevant_findings else []
        rows_html = ""
        for f in recent:
            # Avatar
            name = f.get("company_name", "?")
            initial = name[0].upper() if name else "?"
            sev = f.get("severity", "LOW")
            if sev == "HIGH":
                av_bg = "#dc2626"
                badge_text = "CRITIQUE"
                badge_bg = "rgba(220,38,38,0.1)"
                badge_color = "#dc2626"
            elif sev == "MEDIUM":
                av_bg = "#f59e0b"
                badge_text = "MOYENNE"
                badge_bg = "rgba(245,158,11,0.1)"
                badge_color = "#92400e"
            else:
                av_bg = "#3b82f6"
                badge_text = "FAIBLE"
                badge_bg = "rgba(59,130,246,0.1)"
                badge_color = "#1d4ed8"
            rows_html += (
                f'<div style="display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid {t["border_subtle"]};">'
                f'<div style="width:36px;height:36px;border-radius:10px;background:{av_bg};display:flex;align-items:center;'
                f'justify-content:center;color:#fff;font-weight:700;font-size:0.82rem;flex-shrink:0;">{initial}</div>'
                f'<div style="flex:1;min-width:0;">'
                f'<div style="font-size:0.82rem;font-weight:600;color:{t["text_primary"]};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{html.escape(name)}</div>'
                f'<div style="display:flex;align-items:center;gap:6px;margin-top:3px;">'
                f'<span style="background:{badge_bg};color:{badge_color};padding:1px 7px;border-radius:4px;font-size:0.6rem;font-weight:700;">{badge_text}</span>'
                f'<span style="font-size:0.7rem;color:{t["text_secondary"]};">{html.escape(f.get("finding_type", ""))}</span></div>'
                f'</div>'
                f'<div style="font-size:0.68rem;color:{t["text_secondary"]};white-space:nowrap;">{html.escape(f.get("rule_id", "")[:8])}</div>'
                f'</div>'
            )
        if not rows_html:
            rows_html = f'<div style="text-align:center;padding:30px 0;font-size:0.8rem;color:{t["text_secondary"]};">Aucune anomalie détectée</div>'
        st.markdown(
            f'<div style="background:{t["card_bg"]};border:1px solid {t["border"]};border-radius:14px;padding:22px 24px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">'
            f'<div style="display:flex;align-items:center;gap:8px;">'
            f'<div style="width:3px;height:18px;border-radius:2px;background:{t["accent"]};"></div>'
            f'<span style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};">Dernières anomalies</span></div>'
            f'<span style="font-size:0.72rem;color:{t["accent"]};font-weight:600;cursor:pointer;">Tout voir →</span></div>'
            f'{rows_html}</div>',
            unsafe_allow_html=True,
        )

    # =====================================================================
    # ROW 5 — Top Accounts
    # =====================================================================
    acct_hits = {}
    for f in _relevant_findings:
        acct_hits[f["account_id"]] = acct_hits.get(f["account_id"], {"name": f["company_name"], "count": 0})
        acct_hits[f["account_id"]]["count"] += 1
    top_accounts = sorted(acct_hits.values(), key=lambda x: x["count"], reverse=True)[:8]

    if top_accounts:
        acct_cards = ""
        for acc in top_accounts:
            name = acc["name"]
            initials = "".join(w[0] for w in name.split()[:2]).upper() if name else "?"
            acct_cards += (
                f'<div style="display:flex;align-items:center;gap:12px;padding:12px 16px;'
                f'background:{t["border_subtle"]};border-radius:10px;">'
                f'<div style="width:38px;height:38px;border-radius:10px;background:#1e293b;display:flex;align-items:center;'
                f'justify-content:center;color:#fff;font-weight:700;font-size:0.72rem;flex-shrink:0;">{initials}</div>'
                f'<div style="flex:1;min-width:0;">'
                f'<div style="font-size:0.82rem;font-weight:600;color:{t["text_primary"]};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{html.escape(name)}</div>'
                f'<div style="font-size:0.68rem;color:{t["text_secondary"]};">{acc["count"]} anomalie{"s" if acc["count"] > 1 else ""}</div></div>'
                f'<div style="width:28px;height:28px;border-radius:50%;background:rgba(220,38,38,0.1);display:flex;align-items:center;'
                f'justify-content:center;font-size:0.72rem;font-weight:700;color:#dc2626;flex-shrink:0;">{acc["count"]}</div>'
                f'</div>'
            )
        st.markdown(
            f'<div style="background:{t["card_bg"]};border:1px solid {t["border"]};border-radius:14px;padding:22px 24px;margin-top:16px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">'
            f'<div style="display:flex;align-items:center;gap:8px;">'
            f'<div style="width:3px;height:18px;border-radius:2px;background:{t["accent"]};"></div>'
            f'<span style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};">Comptes les plus impactés</span></div>'
            f'<span style="font-size:0.72rem;color:{t["text_secondary"]};">nombre d\'anomalies</span></div>'
            f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;">{acct_cards}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


def page_customer_data():
    page_header("Données clients", "Portefeuille comptes B2B — recherche, filtres et détail par enregistrement.")

    search = st.text_input("Rechercher", placeholder="Raison sociale, SIREN, SIRET, ID compte…")
    df, _source_label = _get_active_data()
    if df.empty:
        df = pd.DataFrame(columns=["account_id", "company_name", "siren", "siret", "address", "naf", "status"])
    st.caption(f"Source : `{_source_label}`")
    total_records = len(df)
    if search:
        mask = df.apply(lambda row: search.lower() in " ".join(str(v).lower() for v in row), axis=1)
        df = df[mask]

    rename_map = {
        "account_id": "ID compte", "company_name": "Raison sociale",
        "siren": "SIREN", "siret": "SIRET", "vat": "N° TVA",
        "address": "Adresse", "naf": "NAF", "country": "Pays",
        "legal_form": "Forme juridique",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    if "Statut" in df.columns:
        df["Statut"] = df["Statut"].map(TR_ACCOUNT_STATUS).fillna(df["Statut"])

    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(f"{len(df)} sur {total_records} enregistrements affichés")


def page_run_analysis():
    t = get_theme()
    accent = t['accent']
    page_header(
        "Lancer l'analyse",
        "Configurez et exécutez un contrôle qualité sur vos données.",
        badges=["Moteur SQL", "INSEE 29M+"],
    )

    if "wizard_step" not in st.session_state:
        st.session_state["wizard_step"] = 1
    if "selected_subjects" not in st.session_state:
        st.session_state["selected_subjects"] = ["compliance", "duplicates"]

    step = st.session_state["wizard_step"]
    steps = ["Sélection des sujets", "Périmètre", "Data Cleaning", "Exécution", "Résultats"]

    # --- Premium wizard stepper with connected line ---
    step_items = ""
    for i, label in enumerate(steps, 1):
        if i < step:
            dot_style = f"width:28px;height:28px;border-radius:50%;background:{t['success']};color:#fff;display:flex;align-items:center;justify-content:center;font-size:0.7rem;font-weight:700;"
            dot_content = "✓"
            label_style = f"font-size:0.72rem;color:{t['success']};font-weight:600;margin-top:4px;"
        elif i == step:
            dot_style = f"width:28px;height:28px;border-radius:50%;background:{accent};color:#fff;display:flex;align-items:center;justify-content:center;font-size:0.75rem;font-weight:700;box-shadow:0 0 0 3px {t['accent_soft']};"
            dot_content = str(i)
            label_style = f"font-size:0.72rem;color:{accent};font-weight:700;margin-top:4px;"
        else:
            dot_style = f"width:28px;height:28px;border-radius:50%;background:{t['border_subtle']};color:{t['text_secondary']};display:flex;align-items:center;justify-content:center;font-size:0.75rem;font-weight:600;border:1px solid {t['border']};"
            dot_content = str(i)
            label_style = f"font-size:0.72rem;color:{t['text_secondary']};font-weight:500;margin-top:4px;"

        connector = ""
        if i < len(steps):
            line_color = t['success'] if i < step else t['border']
            connector = f'<div style="flex:1;height:2px;background:{line_color};margin:0 4px;"></div>'

        step_items += f'<div style="display:flex;flex-direction:column;align-items:center;min-width:60px;"><div style="{dot_style}">{dot_content}</div><div style="{label_style}">{label}</div></div>{connector}'

    st.markdown(
        f'<div style="background:{t["card_bg"]};border:1px solid {t["border"]};border-radius:12px;padding:14px 20px;margin-bottom:12px;">'
        f'<div style="display:flex;align-items:center;justify-content:center;">{step_items}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if step == 1:
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">'
            f'<div style="width:3px;height:16px;border-radius:2px;background:{accent};"></div>'
            f'<span style="font-size:0.88rem;font-weight:700;color:{t["text_primary"]};">Étape 1 — Sélection des sujets</span>'
            f'</div>'
            f'<p style="font-size:0.8rem;color:{t["text_secondary"]};margin:0 0 10px 13px;">Choisissez les dimensions de qualité à contrôler. La priorité indique l\'impact métier.</p>',
            unsafe_allow_html=True,
        )
        selected = []
        for subj in ANALYSIS_SUBJECTS:
            checked = subj["id"] in st.session_state["selected_subjects"]
            col_chk, col_content = st.columns([0.06, 0.94], gap="small")
            with col_chk:
                is_selected = st.checkbox(
                    " ",
                    value=checked,
                    key=f"subj_{subj['id']}",
                    label_visibility="collapsed",
                )
            with col_content:
                # Enhanced subject card with rule count badge
                border_color = accent if is_selected else t['border']
                bg_card = f"linear-gradient(135deg, {t['accent_soft']} 0%, {t['card_bg']} 60%)" if is_selected else t['card_bg']
                check_icon = f'<div style="width:20px;height:20px;border-radius:50%;background:{accent};display:inline-flex;align-items:center;justify-content:center;margin-right:8px;"><svg width="12" height="12" fill="none" viewBox="0 0 24 24"><path d="M5 13l4 4L19 7" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg></div>' if is_selected else ""
                prio = subj.get("priority", "P2")
                prio_colors = {"P1": ("#ef4444", "rgba(239,68,68,0.12)"), "P2": ("#f59e0b", "rgba(245,158,11,0.12)"), "P3": ("#3b82f6", "rgba(59,130,246,0.12)")}
                pc, pbg = prio_colors.get(prio, ("#94a3b8", t['border_subtle']))
                st.markdown(
                    f'<div style="background:{bg_card};border:1px solid {border_color};border-radius:10px;padding:12px 16px;margin-bottom:6px;'
                    f'{"box-shadow:0 0 0 1px " + accent + ";" if is_selected else ""}">'
                    f'<div style="display:flex;align-items:center;justify-content:space-between;">'
                    f'<div style="display:flex;align-items:center;">{check_icon}<strong style="color:{t["text_primary"]};font-size:0.88rem;">{html.escape(subj["name"])}</strong></div>'
                    f'<div style="display:flex;gap:6px;">'
                    f'<span style="font-size:0.65rem;padding:2px 7px;border-radius:999px;background:{pbg};color:{pc};font-weight:600;">{prio}</span>'
                    f'<span style="font-size:0.65rem;padding:2px 7px;border-radius:999px;background:{t["accent_soft"]};color:{accent};font-weight:600;">{subj["rules"]} règles</span>'
                    f'</div></div>'
                    f'<div style="font-size:0.76rem;color:{t["text_secondary"]};margin-top:4px;">{html.escape(subj["description"])}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            if is_selected:
                selected.append(subj["id"])
        st.session_state["selected_subjects"] = selected
        if st.button("Suivant : Périmètre", type="primary"):
            st.session_state["wizard_step"] = 2
            st.rerun()

    elif step == 2:
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">'
            f'<div style="width:3px;height:16px;border-radius:2px;background:{accent};"></div>'
            f'<span style="font-size:0.88rem;font-weight:700;color:{t["text_primary"]};">Étape 2 — Périmètre & règles</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        selected_names = [s["name"] for s in ANALYSIS_SUBJECTS if s["id"] in st.session_state["selected_subjects"]]
        total_rules = sum(s["rules"] for s in ANALYSIS_SUBJECTS if s["id"] in st.session_state["selected_subjects"])
        table_fqn = _dim_account_fqn()
        # Check if file uploaded as source (wizard upload OR sidebar upload)
        if "wizard_uploaded_df" in st.session_state:
            _src_count = len(st.session_state["wizard_uploaded_df"])
            _src_label = f"Fichier importé ({st.session_state.get('wizard_file_upload', 'fichier')})"
        elif st.session_state.get("source_mode") == "file" and "uploaded_df" in st.session_state:
            _src_count = len(st.session_state["uploaded_df"])
            _src_label = f"Fichier importé ({st.session_state.get('uploaded_filename', 'fichier')})"
        elif table_fqn and not table_fqn.startswith(".."):
            _src_count = len(load_dim_account(table_fqn))
            _src_label = html.escape(table_fqn)
        else:
            _src_count = 0
            _src_label = "Aucune source"
        card(
            f'<strong>Sujets :</strong> {", ".join(html.escape(n) for n in selected_names)}<br>'
            f'<strong>Source :</strong> <code>{_src_label}</code><br>'
            f'<strong>Enregistrements :</strong> {_src_count} comptes<br>'
            f'<strong>Règles à exécuter :</strong> {total_rules}<br>'
            f'<strong>Moteur :</strong> Snowflake (staging + SQL)<br>'
            f'<strong>Durée estimée :</strong> ~{max(5, _src_count * total_rules // 10)} secondes'
        )

        extra_table = st.selectbox(
            "Table additionnelle (autre jeu de règles)",
            ["— Aucune —"] + [t for t in FR_AUDIT_TABLES if t != table_fqn],
            key="wizard_extra_table",
            help="Analyser une 2e table avec les mêmes règles personnalisées.",
        )

        # --- Upload fichier comme source alternative ---
        st.markdown("---")
        t = get_theme()
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">'
            f'<div style="width:24px;height:24px;border-radius:6px;background:{t["accent_soft"]};display:flex;align-items:center;justify-content:center;">'
            f'<svg width="12" height="12" fill="none" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" stroke="{t["accent"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
            f'</div>'
            f'<span style="font-size:0.85rem;font-weight:600;color:{t["text_primary"]};">Ou importer un fichier</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        wizard_upload = st.file_uploader(
            "Fichier CSV / Excel",
            type=["csv", "txt", "tsv", "xlsx", "xls", "xlsm"],
            key="wizard_file_upload",
        )
        if wizard_upload:
            try:
                df_uploaded = load_uploaded_file(wizard_upload)
                st.success(f"**{wizard_upload.name}** · {len(df_uploaded)} lignes · {len(df_uploaded.columns)} colonnes")
                st.session_state["wizard_uploaded_df"] = df_uploaded
                st.session_state["wizard_source"] = "file"
            except ValueError as exc:
                st.error(str(exc))
        else:
            st.session_state.pop("wizard_uploaded_df", None)
            st.session_state["wizard_source"] = "snowflake"

        # --- JOIN Table Configuration (Cortex AI) ---
        st.markdown("---")
        t = get_theme()
        st.markdown(
            f'<div style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};margin-bottom:8px;">Joindre une table secondaire</div>'
            f'<div style="font-size:0.78rem;color:{t["text_secondary"]};margin-bottom:12px;">Cortex AI suggère automatiquement la clé de jointure et des règles qualité.</div>',
            unsafe_allow_html=True,
        )
        join_enabled = st.toggle("Activer la jointure", key="wizard_join_enabled")

        if join_enabled:
            _db = st.session_state.get("sf_database", "")
            _sch = st.session_state.get("sf_schema", "")
            _all_tables = list_snowflake_tables(_db, _sch)
            _available = [tb for tb in _all_tables if f"{_db}.{_sch}.{tb}" != table_fqn]

            if not _available:
                st.info("Aucune autre table disponible dans ce schéma.")
            else:
                secondary_name = st.selectbox("Table secondaire", _available, key="wizard_join_table_select")
                secondary_fqn = f"{_db}.{_sch}.{secondary_name}"

                # Load columns for both tables
                primary_cols = load_table_columns(table_fqn)
                sec_cols = load_table_columns(secondary_fqn)

                if primary_cols and sec_cols:
                    # Cortex AI suggests join key (cached in session)
                    cache_key = f"_join_ai_{table_fqn}_{secondary_fqn}"
                    if cache_key not in st.session_state:
                        with st.spinner("Cortex AI analyse les clés de jointure..."):
                            suggestion = suggest_join_key_cortex(primary_cols, sec_cols, table_fqn, secondary_fqn)
                            st.session_state[cache_key] = suggestion

                    suggestion = st.session_state.get(cache_key, {})
                    confidence = suggestion.get("confidence", "low")
                    conf_color = "#0d9488" if confidence == "high" else ("#d97706" if confidence == "medium" else t["text_secondary"])

                    st.markdown(
                        f'<div style="font-size:0.72rem;color:{conf_color};margin-bottom:8px;">'
                        f'Suggestion Cortex AI (confiance: {confidence})</div>',
                        unsafe_allow_html=True,
                    )

                    col_k1, col_k2 = st.columns(2)
                    with col_k1:
                        suggested_pk = suggestion.get("primary_key", "").upper()
                        pk_index = 0
                        upper_primary = [c.upper() for c in primary_cols]
                        if suggested_pk in upper_primary:
                            pk_index = upper_primary.index(suggested_pk)
                        join_key_a = st.selectbox("Clé (table principale)", primary_cols, index=pk_index, key="wiz_jk_primary")

                    with col_k2:
                        suggested_sk = suggestion.get("secondary_key", "").upper()
                        sk_index = 0
                        upper_sec = [c.upper() for c in sec_cols]
                        if suggested_sk in upper_sec:
                            sk_index = upper_sec.index(suggested_sk)
                        join_key_b = st.selectbox("Clé (table secondaire)", sec_cols, index=sk_index, key="wiz_jk_secondary")

                    join_type = st.radio("Type de jointure", ["LEFT JOIN", "INNER JOIN"], horizontal=True, key="wiz_join_type")

                    # Store join config
                    st.session_state["wizard_join_config"] = {
                        "table": secondary_fqn,
                        "key_primary": join_key_a,
                        "key_secondary": join_key_b,
                        "join_type": join_type,
                    }

                    # --- AI Rule Suggestions for secondary table ---
                    st.markdown("---")
                    if st.button("Suggérer des règles avec Cortex AI", type="primary", key="wiz_suggest_rules"):
                        with st.spinner("Cortex AI analyse la table secondaire..."):
                            sample_df = _sf_query(f"SELECT * FROM {secondary_fqn} LIMIT 5")
                            sample_rows = sample_df.to_dict("records") if not sample_df.empty else []
                            suggestions = suggest_rules_cortex(secondary_fqn, sec_cols, sample_rows)
                            st.session_state["wizard_ai_suggestions"] = suggestions

                    if "wizard_ai_suggestions" in st.session_state and st.session_state["wizard_ai_suggestions"]:
                        st.markdown(
                            f'<div style="font-size:0.85rem;font-weight:600;color:{t["text_primary"]};margin:12px 0 8px;">'
                            f'Règles suggérées par Cortex AI ({len(st.session_state["wizard_ai_suggestions"])})</div>',
                            unsafe_allow_html=True,
                        )
                        accepted_rules = []
                        for i, rule in enumerate(st.session_state["wizard_ai_suggestions"]):
                            col_chk, col_info = st.columns([0.06, 0.94])
                            with col_chk:
                                keep = st.checkbox(" ", value=True, key=f"ai_rule_accept_{i}", label_visibility="collapsed")
                            with col_info:
                                sev_cls = {"HIGH": "qx-badge-high", "MEDIUM": "qx-badge-medium", "LOW": "qx-badge-low"}.get(rule.get("severity", "MEDIUM"), "")
                                st.markdown(
                                    f'<div style="padding:8px 12px;background:{t["border_subtle"]};border-radius:8px;margin-bottom:4px;">'
                                    f'<span class="qx-badge {sev_cls}" style="margin-right:8px;">{rule.get("severity", "MEDIUM")}</span>'
                                    f'<strong>{html.escape(rule.get("name", ""))}</strong> — '
                                    f'<code>{html.escape(rule.get("target_field", ""))}</code> '
                                    f'<span style="color:{t["text_secondary"]};font-size:0.75rem;">({rule.get("rule_type", "")})</span>'
                                    f'<div style="font-size:0.72rem;color:{t["text_secondary"]};margin-top:2px;">{html.escape(rule.get("description", ""))}</div>'
                                    f'</div>',
                                    unsafe_allow_html=True,
                                )
                            if keep:
                                accepted_rules.append(rule)
                        st.session_state["wizard_ai_rules"] = accepted_rules
                        if accepted_rules:
                            st.caption(f"{len(accepted_rules)} règle(s) acceptée(s)")
                else:
                    st.warning("Impossible de charger les colonnes des tables.")
        else:
            # Clear join config if disabled
            st.session_state.pop("wizard_join_config", None)
            st.session_state.pop("wizard_ai_rules", None)
            st.session_state.pop("wizard_ai_suggestions", None)

        st.markdown("---")

        _render_rules_and_dedup_config("wizard")

        for subj in ANALYSIS_SUBJECTS:
            if subj["id"] in st.session_state["selected_subjects"]:
                rules = [r for r in RULE_TEMPLATES if r["subject"] == subj["name"]]
                for r in rules:
                    card(f'<code>{html.escape(r["id"])}</code> — {html.escape(r["name"])}')
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Retour"):
                st.session_state["wizard_step"] = 1
                st.rerun()
        with c2:
            if st.button("Suivant : Data Cleaning", type="primary"):
                st.session_state["wizard_step"] = 3
                st.rerun()

    elif step == 3:
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">'
            f'<div style="width:3px;height:16px;border-radius:2px;background:{accent};"></div>'
            f'<span style="font-size:0.88rem;font-weight:700;color:{t["text_primary"]};">Étape 3 — Nettoyage & Dédoublonnage</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        t = get_theme()
        table_fqn = _dim_account_fqn()
        # Use uploaded file if available in any form (avoid empty table query)
        if st.session_state.get("wizard_source") == "file" and "wizard_uploaded_df" in st.session_state:
            df = st.session_state["wizard_uploaded_df"]
        elif "uploaded_df" in st.session_state and not st.session_state["uploaded_df"].empty:
            df = st.session_state["uploaded_df"]
        else:
            # Load from Snowflake table
            load_dim_account.clear()
            raw_data = load_dim_account(table_fqn)
            df = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
        mapping = _mapping_for_table(table_fqn, list(df.columns)) if not df.empty else {}

        # --- Mandatory pipeline order description ---
        st.markdown(
            f'<div style="background:{t["card_bg"]};border:1px solid {t["border"]};border-radius:14px;padding:20px 24px;margin-bottom:16px;">'
            f'<div style="font-size:0.88rem;font-weight:700;color:{t["text_primary"]};margin-bottom:12px;">Ordre de traitement (obligatoire)</div>'
            f'<div style="display:flex;flex-direction:column;gap:10px;">'
            f'<div style="display:flex;gap:10px;align-items:flex-start;">'
            f'<span style="background:{accent};color:#fff;font-size:0.68rem;font-weight:700;padding:2px 7px;border-radius:4px;flex-shrink:0;">1</span>'
            f'<div><strong style="color:{t["text_primary"]};font-size:0.8rem;">Détection des doublons parfaits</strong>'
            f'<div style="font-size:0.72rem;color:{t["text_secondary"]};margin-top:2px;">Lignes strictement identiques sur l\'ensemble des colonnes pertinentes (égalité exacte, après normalisation : espaces superflus, casse).</div></div></div>'
            f'<div style="display:flex;gap:10px;align-items:flex-start;">'
            f'<span style="background:#7c3aed;color:#fff;font-size:0.68rem;font-weight:700;padding:2px 7px;border-radius:4px;flex-shrink:0;">2</span>'
            f'<div><strong style="color:{t["text_primary"]};font-size:0.8rem;">Détection des erreurs</strong>'
            f'<div style="font-size:0.72rem;color:{t["text_secondary"]};margin-top:2px;">Identifier les valeurs aberrantes, incohérentes ou mal formatées (fautes de frappe, formats divergents) et proposer un nettoyage.</div></div></div>'
            f'<div style="display:flex;gap:10px;align-items:flex-start;">'
            f'<span style="background:#d97706;color:#fff;font-size:0.68rem;font-weight:700;padding:2px 7px;border-radius:4px;flex-shrink:0;">3</span>'
            f'<div><strong style="color:{t["text_primary"]};font-size:0.8rem;">Détection par similarité</strong>'
            f'<div style="font-size:0.72rem;color:{t["text_secondary"]};margin-top:2px;">Après le nettoyage, calcul de similarité entre les lignes avec un seuil configurable. Deux lignes dépassant ce seuil sont signalées comme doublons potentiels.</div></div></div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            f'<div style="background:{t["card_bg"]};border:1px solid {t["border"]};border-radius:14px;padding:16px 20px;margin-bottom:16px;">'
            f'<div style="font-size:0.82rem;color:{t["text_secondary"]};">Table source</div>'
            f'<div style="font-size:0.95rem;font-weight:700;color:{t["text_primary"]};">{table_fqn} · {len(df)} lignes</div>'
            f'<div style="font-size:0.72rem;color:{t["text_secondary"]};margin-top:4px;">La table originale ne sera jamais modifiée. Un backup est créé automatiquement.</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        if df.empty:
            st.warning("Aucune donnée à traiter.")
        else:
            # Initialize pipeline state
            if "dedup_pipeline_state" not in st.session_state:
                st.session_state["dedup_pipeline_state"] = "ready"

            pipeline_state = st.session_state["dedup_pipeline_state"]

            if pipeline_state == "ready":
                # Configuration panel
                st.markdown(f'<div style="font-size:0.85rem;font-weight:700;color:{t["text_primary"]};margin-bottom:8px;">Configuration</div>', unsafe_allow_html=True)

                sim_threshold = st.slider("Seuil de similarité (Phase 3)", min_value=50, max_value=100, value=85, step=5, key="dedup_threshold", help="Deux lignes au-dessus de ce seuil seront considérées comme doublons potentiels.")

                # Column selection for comparison
                all_cols = list(df.columns)
                # Default: company name + SIREN (NOT SIRET which is unique per establishment)
                default_cols = [c for c in all_cols if any(k in c.lower() for k in ("name", "nom", "siren", "company", "raison")) and "siret" not in c.lower()]
                if not default_cols:
                    default_cols = all_cols[:3]
                compare_cols = st.multiselect("Colonnes pour la détection", all_cols, default=default_cols, key="dedup_compare_cols")

                col_a = st.columns(1)[0]
                with col_a:
                    if st.button("Lancer le pipeline (3 phases)", type="primary", key="dedup_start", use_container_width=True):
                        with st.spinner("Création du backup + analyse..."):
                            # Safety: create backup
                            _dedup_create_backup(df, table_fqn)
                            # Phase 1: exact duplicates
                            _, exact_groups = _dedup_phase1_exact(df, compare_cols or all_cols)
                            # Phase 2: errors
                            df_cleaned, corrections = _dedup_phase2_errors(df, mapping)
                            # Phase 3: similarity (exclude Phase 1 indices)
                            _phase1_indices = set()
                            for _g in exact_groups:
                                _phase1_indices.update(_g.get("indices", []))
                            sim_groups = _dedup_phase3_similarity(df_cleaned, compare_cols or default_cols, threshold=sim_threshold / 100.0, exclude_indices=_phase1_indices)

                            st.session_state["dedup_exact_groups"] = exact_groups
                            st.session_state["dedup_corrections"] = corrections
                            st.session_state["dedup_cleaned_df"] = df_cleaned
                            st.session_state["dedup_sim_groups"] = sim_groups
                            st.session_state["dedup_pipeline_state"] = "review"
                        st.rerun()

            elif pipeline_state == "review":
                exact_groups = st.session_state.get("dedup_exact_groups", [])
                corrections = st.session_state.get("dedup_corrections", [])
                sim_groups = st.session_state.get("dedup_sim_groups", [])

                tab1, tab2, tab3 = st.tabs([
                    f"Phase 1 · Doublons exacts ({len(exact_groups)})",
                    f"Phase 2 · Corrections ({len(corrections)})",
                    f"Phase 3 · Similarité ({len(sim_groups)})",
                ])

                # --- Tab 1: Exact duplicates — flat table ---
                with tab1:
                    if exact_groups:
                        _display_cols = list(df.columns)[:6]  # First 6 columns of the file
                        rows = []
                        for i, grp in enumerate(exact_groups):
                            for idx in grp.get("indices", []):
                                if idx < len(df):
                                    row = {"Groupe": f"E{i+1}", "Clé": grp.get("match_key", "")}
                                    for col in _display_cols:
                                        row[col] = str(df.iloc[idx].get(col, ""))[:60]
                                    rows.append(row)
                        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                                     height=min(500, 35 * len(rows) + 40))
                        st.caption(f"{len(rows)} lignes dans {len(exact_groups)} groupe(s)")
                    else:
                        st.success("Aucun doublon exact trouvé.")

                # --- Tab 2: Corrections — flat list ---
                with tab2:
                    if corrections:
                        for corr in corrections:
                            st.markdown(f"- **{corr['desc']}** — colonne `{corr.get('col', '')}` ({corr['count']} lignes)")
                    else:
                        st.success("Aucune erreur de formatage détectée.")

                # --- Tab 3: Similarity — flat table ---
                with tab3:
                    if sim_groups:
                        # Show ALL relevant columns (name + identifiers)
                        _display_cols = list(df.columns)[:6]  # First 6 columns of the file
                        rows = []
                        for i, grp in enumerate(sim_groups):
                            for idx in grp.get("indices", []):
                                if idx < len(df):
                                    row = {"Groupe": f"S{i+1}", "Similarité": f"~{grp.get('similarity', 85)}%"}
                                    for col in _display_cols:
                                        row[col] = str(df.iloc[idx].get(col, ""))[:60]
                                    rows.append(row)
                        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                                     height=min(500, 35 * len(rows) + 40))
                        st.caption(f"{len(rows)} lignes dans {len(sim_groups)} groupe(s)")
                    else:
                        st.success("Aucun doublon par similarité trouvé.")

                # Store all groups as accepted by default
                st.session_state["dedup_accepted_exact"] = exact_groups
                st.session_state["dedup_accepted_sim"] = sim_groups
                st.session_state["dedup_apply_corrections"] = True

                # --- Actions ---
                st.markdown("---")
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    if st.button("Retour", key="dedup_back_to_config"):
                        st.session_state["dedup_pipeline_state"] = "ready"
                        st.rerun()
                with col_b:
                    if st.button("Valider et appliquer", type="primary", key="dedup_validate", use_container_width=True):
                        working_df = st.session_state.get("dedup_cleaned_df", df) if st.session_state.get("dedup_apply_corrections", True) else df.copy()
                        removed_total = 0

                        # Apply exact dedup
                        accepted_exact = st.session_state.get("dedup_accepted_exact", [])
                        if accepted_exact:
                            working_df, n = _dedup_apply_decisions(working_df, accepted_exact, "keep_first")
                            removed_total += n

                        # Apply similarity dedup
                        accepted_sim = st.session_state.get("dedup_accepted_sim", [])
                        if accepted_sim:
                            working_df, n = _dedup_apply_decisions(working_df, accepted_sim, "keep_first")
                            removed_total += n

                        st.session_state["wiz_clean_df"] = working_df
                        st.session_state["wiz_removed_count"] = removed_total
                        corrections_count = len(st.session_state.get("dedup_corrections", []))

                        # Persist
                        persist_dedup_result(
                            f"WIZ-{_now().strftime('%Y%m%d%H%M%S')}", table_fqn,
                            len(df), len(working_df), removed_total,
                            st.session_state.get("dedup_compare_cols", ["siren"]), "pipeline_3phase",
                            st.session_state.get("dedup_threshold", 85) / 100.0,
                        )
                        add_audit_entry("Pipeline 3 phases", f"{removed_total} doublons supprimés, {corrections_count} corrections")
                        st.session_state["dedup_pipeline_state"] = "done"
                        st.rerun()
                with col_c:
                    if st.button("Tout rejeter", key="dedup_reject_all"):
                        st.session_state["wiz_clean_df"] = df
                        st.session_state["dedup_pipeline_state"] = "done"
                        st.rerun()

            elif pipeline_state == "done":
                df_cleaned = st.session_state.get("wiz_clean_df", df)
                removed = st.session_state.get("wiz_removed_count", 0)
                backup_name = st.session_state.get("dedup_backup_name", "")

                if removed > 0:
                    st.success(f"**{removed} doublon(s)** supprimés. Données de travail : **{len(df_cleaned)} lignes**.")
                else:
                    st.info("Aucune modification appliquée. Données prêtes.")

                if backup_name:
                    st.caption(f"Backup sauvegardé : `QUALITY_TEST.DATA_QUALITY.{backup_name}`")

                with st.expander("Aperçu données de travail", expanded=False):
                    st.dataframe(df_cleaned.head(20), use_container_width=True, hide_index=True)

                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Recommencer", key="dedup_restart"):
                        st.session_state["dedup_pipeline_state"] = "ready"
                        st.rerun()
                with c2:
                    if st.button("Lancer l'analyse des règles", type="primary", key="wiz_to_exec"):
                        st.session_state["wizard_step"] = 4
                        st.rerun()

    elif step == 4:
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">'
            f'<div style="width:3px;height:16px;border-radius:2px;background:{accent};"></div>'
            f'<span style="font-size:0.88rem;font-weight:700;color:{t["text_primary"]};">Étape 4 — Exécution des règles</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        progress = st.progress(0, text="Initialisation du moteur Snowflake…")
        import time
        selected = st.session_state.get("selected_subjects", ["compliance", "duplicates"])
        table_fqn = _dim_account_fqn()
        extra_table = st.session_state.get("wizard_extra_table", "— Aucune —")
        enabled_rules = st.session_state.get("wizard_enabled_rules", [r["id"] for r in FR_BUSINESS_RULES] + ["INSEE"])
        dedup_keys = st.session_state.get("wizard_dedup_keys", DEFAULT_DEDUP_KEYS)
        auto_dedup = st.session_state.get("wizard_auto_dedup", True)
        dedup_strategy = st.session_state.get("wizard_dedup_strategy", "keep_first")
        custom_rules = [
            {"id": r["id"], "name": r["name"], "field": r["target_field"],
             "pattern": r.get("pattern", ""), "severity": r.get("severity", "MEDIUM"),
             "rule_type": r.get("rule_type", "regex")}
            for r in list_custom_rules(active_only=True)
        ]

        # Merge AI-suggested rules
        ai_rules = [
            {"id": f"AI-{i+1:02d}", "name": r.get("name", ""), "field": r.get("target_field", ""),
             "pattern": r.get("pattern", ""), "severity": r.get("severity", "MEDIUM"),
             "rule_type": r.get("rule_type", "regex")}
            for i, r in enumerate(st.session_state.get("wizard_ai_rules", []))
        ]
        all_custom_rules = custom_rules + ai_rules

        # Join config
        join_config = st.session_state.get("wizard_join_config") if st.session_state.get("wizard_join_enabled") else None

        # Determine the df to analyze: uploaded file > cleaned from dedup > Snowflake table
        _df_override = None
        _source_label = table_fqn
        if st.session_state.get("wizard_source") == "file" and "wizard_uploaded_df" in st.session_state:
            _df_override = st.session_state["wizard_uploaded_df"]
            _source_label = st.session_state.get("wizard_file_upload", "fichier")
        elif "wiz_clean_df" in st.session_state and not st.session_state.get("wiz_clean_df", pd.DataFrame()).empty:
            _df_override = st.session_state["wiz_clean_df"]
        elif st.session_state.get("source_mode") == "file" and "uploaded_df" in st.session_state:
            # Sidebar upload: use that file as source for analysis
            _df_override = st.session_state["uploaded_df"]
            _source_label = st.session_state.get("uploaded_filename", "fichier")

        tables_to_run = [table_fqn]
        if extra_table and extra_table != "— Aucune —":
            tables_to_run.append(extra_table)

        messages = [f"Connexion Snowflake · {len(tables_to_run)} table(s)…"]
        if join_config:
            messages.append(f"Jointure avec {join_config['table'].split('.')[-1]}…")
        for tbl in tables_to_run:
            messages.append(f"Staging + dédoublonnage · {tbl.split('.')[-1]}…")
            messages.append(f"Exécution règles {', '.join(enabled_rules[:5])}…")
        if ai_rules:
            messages.append(f"Exécution {len(ai_rules)} règle(s) Cortex AI…")
        messages += ["Recoupement registre INSEE SIRENE…", "Calcul score conformité…"]

        all_anomalies = []
        combined_stats = {"total_rows": 0, "anomaly_count": 0, "affected_rows": 0, "clean_rows": 0, "high": 0, "med": 0, "low": 0}

        for i, msg in enumerate(messages):
            progress.progress((i + 1) / len(messages), text=msg)
            time.sleep(0.08)

        t0 = time.time()
        for tbl in tables_to_run:
            mapping = _mapping_for_table(tbl, list(_df_override.columns) if _df_override is not None and tbl == table_fqn else None)
            anomalies, stats, _, _, _ = run_snowflake_dq_analysis(
                tbl, mapping, enabled_rules, dedup_keys, auto_dedup, dedup_strategy,
                all_custom_rules, join_config=join_config if tbl == table_fqn else None,
                df_override=_df_override if tbl == table_fqn else None,
            )
            all_anomalies.extend(anomalies)
            combined_stats["total_rows"] += stats.get("total_rows", 0)
            combined_stats["anomaly_count"] += stats.get("anomaly_count", 0)
            combined_stats["affected_rows"] += stats.get("affected_rows", 0)
            combined_stats["clean_rows"] += stats.get("clean_rows", 0)
            combined_stats["high"] += sum(1 for a in anomalies if a.get("severity") == "HIGH")
            combined_stats["med"] += sum(1 for a in anomalies if a.get("severity") == "MEDIUM")
            combined_stats["low"] += sum(1 for a in anomalies if a.get("severity") == "LOW")

        records = combined_stats["total_rows"] or 1
        combined_stats["score"] = round(combined_stats["clean_rows"] / records * 100) if records else 0
        combined_stats["active_rules"] = enabled_rules
        combined_stats["duration_s"] = round(time.time() - t0, 1)
        combined_stats["engine"] = "snowflake"

        st.session_state["wizard_stats"] = combined_stats
        # Persist results to DB and update session findings
        _store_analysis_results(all_anomalies, combined_stats, _source_label, "snowflake")
        # Also update the main findings session state so Anomalies/Tasks pages see them
        load_dq_findings.clear()
        st.session_state["findings"] = load_dq_findings()
        st.session_state["wizard_step"] = 5
        st.rerun()

    elif step == 5:
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">'
            f'<div style="width:3px;height:16px;border-radius:2px;background:{accent};"></div>'
            f'<span style="font-size:0.88rem;font-weight:700;color:{t["text_primary"]};">Étape 5 — Résultats</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.subheader("Étape 5 — Résultats")
        ws = st.session_state.get("wizard_stats", {})
        total = ws.get("total_rows", len(load_dim_account(_dim_account_fqn())) or 0)
        n_anom = ws.get("anomaly_count", len(get_all_fr_anomalies()))
        score = ws.get("score", 0)
        score_before = ws.get("score_before", score)
        high = ws.get("high", 0)
        med = ws.get("med", 0)
        low = ws.get("low", 0)
        duration = ws.get("duration_s", 0)
        engine = ws.get("engine", "snowflake")
        dedup = ws.get("dedup", {})

        # Score big display
        score_color = "green" if score >= 80 else ("orange" if score >= 50 else "red")
        st.markdown(
            f'<div class="qx-score-big">'
            f'<div class="qx-score-big-value">{score}%</div>'
            f'<div class="qx-score-big-label">Score conformité</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # KPI row
        k1, k2, k3, k4 = st.columns(4)
        with k1:
            st.metric("Lignes analysées", total, f"{engine}")
        with k2:
            st.metric("Anomalies", n_anom, f"{high} HIGH · {med} MED · {low} LOW")
        with k3:
            st.metric("Doublons supprimés", dedup.get("removed", 0))
        with k4:
            st.metric("Durée", f"{duration}s")

        # Detail card
        card(
            f'<span style="color:{t["success"]};font-size:1.1rem;font-weight:700;">✓ Analyse terminée</span><br><br>'
            f'<strong>Enregistrements :</strong> {total}<br>'
            f'<strong>Anomalies :</strong> {n_anom} ({high} élevées · {med} moyennes · {low} faibles)<br>'
            f'<strong>Score :</strong> {score}%'
            + (f' (avant nettoyage : {score_before}%)' if score_before != score else '')
        )

        # Anomaly list preview
        anomalies = st.session_state.get("fr_upload_anomalies", [])
        if anomalies:
            st.markdown("##### Aperçu des anomalies détectées")
            preview_data = []
            for a in anomalies[:20]:
                preview_data.append({
                    "Règle": a.get("rule_id", ""),
                    "Compte": a.get("company_name", "")[:30],
                    "Champ": a.get("field_label", ""),
                    "Valeur": str(a.get("field_value", ""))[:20],
                    "Attendu": str(a.get("expected_value", ""))[:25],
                    "Sévérité": a.get("severity", ""),
                })
            st.dataframe(pd.DataFrame(preview_data), use_container_width=True, hide_index=True)
            if len(anomalies) > 20:
                st.caption(f"… et {len(anomalies) - 20} autres anomalies")

        df_clean = st.session_state.get("fr_clean_df", pd.DataFrame())
        df_removed = st.session_state.get("fr_removed_df", pd.DataFrame())
        _render_cleaning_preview(ws, df_clean, df_removed)

        st.markdown("---")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Voir toutes les anomalies", type="primary"):
                st.session_state["page"] = "findings"
                st.session_state["wizard_step"] = 1
                st.rerun()
        with c2:
            if st.button("Relancer l'analyse"):
                st.session_state["wizard_step"] = 1
                st.rerun()


_FINDINGS_PAGE_SIZE = 10


def page_findings():
    page_header("Anomalies", "Examiner, prioriser et traiter les écarts de qualité détectés.")
    t = get_theme()
    accent = t['accent']

    # --- Section header with accent bar ---
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:18px;">'
        f'<div style="width:3px;height:18px;border-radius:2px;background:{accent};"></div>'
        f'<span style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};">Liste des anomalies</span>'
        f'<span style="font-size:0.68rem;padding:3px 10px;background:{t["accent_soft"]};color:{accent};'
        f'border-radius:999px;font-weight:600;">Snowflake connecté</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Filters
    col_s, col_f1, col_f2 = st.columns([2, 1, 1])
    with col_s:
        search = st.text_input("Rechercher", placeholder="Entreprise, règle, type…", key="findings_search")
    with col_f1:
        sev_filter = st.selectbox("Sévérité", ["Toutes", "HIGH", "MEDIUM", "LOW"], key="findings_sev_filter")
    with col_f2:
        status_filter = st.selectbox("Statut", ["Tous", "Open", "In Review", "Resolved", "Dismissed"], key="findings_status_filter")

    # --- Quick web verify ---
    with st.expander("🔍 Vérification web rapide — taper une valeur à vérifier", expanded=False):
        _qv_col1, _qv_col2, _qv_col3 = st.columns([1, 2, 1])
        with _qv_col1:
            _qv_field = st.selectbox("Type de champ", ["SIREN", "SIRET", "TVA", "Raison sociale", "Site web", "Email"], key="qv_field")
        with _qv_col2:
            _qv_value = st.text_input("Valeur à vérifier", placeholder="Ex: 831558663, FR53831558663, academie-x.com…", key="qv_value")
        with _qv_col3:
            st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
            if st.button("🔍 Vérifier", type="primary", key="qv_verify_btn", use_container_width=True, disabled=not _qv_value):
                _qv_finding = {
                    "company_name": _qv_value,
                    "field_label": _qv_field,
                    "field_value": _qv_value,
                    "expected_value": "",
                    "rule_id": "MANUAL",
                    "account_id": "",
                }
                with st.spinner(f"Vérification web de {_qv_field} « {_qv_value} »…"):
                    result = _web_verify_finding(_qv_finding)
                    st.session_state["web_verify_result"] = result
                    st.session_state["web_verify_finding_id"] = None
                st.rerun()

    findings = get_all_fr_anomalies()
    if sev_filter != "Toutes":
        findings = [f for f in findings if f.get("severity") == sev_filter]
    if status_filter != "Tous":
        findings = [f for f in findings if f.get("status") == status_filter]
    if search:
        findings = [f for f in findings if search.lower() in " ".join(str(v).lower() for v in f.values())]

    if not findings:
        st.info("Aucune anomalie ne correspond aux filtres.")
        return

    # --- Stats KPI row ---
    high_c = sum(1 for f in findings if f.get("severity") == "HIGH")
    med_c = sum(1 for f in findings if f.get("severity") == "MEDIUM")
    low_c = sum(1 for f in findings if f.get("severity") == "LOW")
    open_c = sum(1 for f in findings if f.get("status") == "Open")

    st.markdown(
        f"""<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px;">
            <div style="background:{t['card_bg']};border:1px solid {t['border']};border-radius:14px;padding:16px 18px;position:relative;overflow:hidden;">
                <div style="position:absolute;top:0;left:0;width:3px;height:100%;background:#ef4444;"></div>
                <div style="font-size:0.68rem;text-transform:uppercase;letter-spacing:0.06em;color:{t['text_secondary']};font-weight:600;">Élevée</div>
                <div style="font-size:1.6rem;font-weight:800;color:#ef4444;margin-top:4px;">{high_c}</div>
            </div>
            <div style="background:{t['card_bg']};border:1px solid {t['border']};border-radius:14px;padding:16px 18px;position:relative;overflow:hidden;">
                <div style="position:absolute;top:0;left:0;width:3px;height:100%;background:#f59e0b;"></div>
                <div style="font-size:0.68rem;text-transform:uppercase;letter-spacing:0.06em;color:{t['text_secondary']};font-weight:600;">Moyenne</div>
                <div style="font-size:1.6rem;font-weight:800;color:#f59e0b;margin-top:4px;">{med_c}</div>
            </div>
            <div style="background:{t['card_bg']};border:1px solid {t['border']};border-radius:14px;padding:16px 18px;position:relative;overflow:hidden;">
                <div style="position:absolute;top:0;left:0;width:3px;height:100%;background:#3b82f6;"></div>
                <div style="font-size:0.68rem;text-transform:uppercase;letter-spacing:0.06em;color:{t['text_secondary']};font-weight:600;">Faible</div>
                <div style="font-size:1.6rem;font-weight:800;color:#3b82f6;margin-top:4px;">{low_c}</div>
            </div>
            <div style="background:{t['card_bg']};border:1px solid {t['border']};border-radius:14px;padding:16px 18px;position:relative;overflow:hidden;">
                <div style="position:absolute;top:0;left:0;width:3px;height:100%;background:{accent};"></div>
                <div style="font-size:0.68rem;text-transform:uppercase;letter-spacing:0.06em;color:{t['text_secondary']};font-weight:600;">Ouvertes</div>
                <div style="font-size:1.6rem;font-weight:800;color:{accent};margin-top:4px;">{open_c}</div>
            </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # --- Select all toggle ---
    # Rules legend
    _rule_descriptions = {
        "R01": ("Format SIREN", "Vérifie que l'identifiant SIREN comporte 9 chiffres valides.", "SIREN", "HIGH"),
        "R02": ("Format SIRET", "Vérifie que le SIRET comporte 14 chiffres valides.", "SIRET", "HIGH"),
        "R03": ("Cohérence SIRET", "SIRET = SIREN + 5 caractères NIC.", "SIRET", "MEDIUM"),
        "R04": ("TVA intracommunautaire", "Format FR + 11 chiffres avec clé de Luhn.", "TVA", "MEDIUM"),
        "R05": ("Pays FR", "Code pays = FR pour les comptes domestiques.", "Pays", "LOW"),
        "R06": ("Code NAF/APE", "Format XX.XXZ valide.", "NAF", "LOW"),
        "R07": ("Forme juridique", "Champ renseigné (SA, SAS, SARL…).", "Juridique", "LOW"),
        "R08": ("E-facturation", "SIREN + SIRET valides pour PDP.", "SIREN/SIRET", "MEDIUM"),
        "INSEE": ("Validation INSEE", "Croisement avec le registre SIRENE 29M+ entreprises.", "SIREN", "MEDIUM"),
        "DUP": ("Doublon", "SIREN en double dans le fichier/table.", "SIREN", "HIGH"),
    }
    _active_rules_in_data = sorted({f.get("rule_id", "") for f in findings})
    _sev_badge_colors = {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#3b82f6"}
    _legend_items = ""
    for _rid in _active_rules_in_data:
        _info = _rule_descriptions.get(_rid)
        if _info:
            _rname, _rdesc, _rfield, _rsev = _info
            _rc = _sev_badge_colors.get(_rsev, t['accent'])
            _legend_items += (
                f'<div style="position:relative;display:inline-flex;align-items:center;gap:6px;margin-right:14px;margin-bottom:6px;cursor:help;" title="{_rid} — {_rname}. {_rdesc}\nChamp : {_rfield} · Sévérité : {_rsev}">'
                f'<span style="font-size:0.65rem;padding:2px 7px;border-radius:4px;background:{_rc};color:#fff;font-weight:700;">{_rid}</span>'
                f'<span style="font-size:0.75rem;color:{t["text_secondary"]};">{_rname}</span>'
                f'</div>'
            )
    if _legend_items:
        st.markdown(
            f'<div style="background:{t["card_bg"]};border:1px solid {t["border"]};border-radius:8px;padding:10px 14px;margin-bottom:12px;">'
            f'<div style="font-size:0.65rem;text-transform:uppercase;letter-spacing:0.08em;color:{t["text_secondary"]};font-weight:600;margin-bottom:6px;">Légende des règles · Survoler pour détails</div>'
            f'<div style="display:flex;flex-wrap:wrap;align-items:center;">{_legend_items}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    select_all = st.checkbox("Tout sélectionner", value=False, key="findings_select_all")

    # --- Resolve company names from source table if stored names look like IDs ---
    def _looks_like_id(name: str) -> bool:
        if not name:
            return True
        if re.match(r'^[A-Za-z]\d{5,}$', name):
            return True
        if re.match(r'^a3[a-zA-Z0-9]{10,}$', name):
            return True
        if re.match(r'^(IMP|DB)-\d{4}$', name):
            return True
        return False

    _needs_resolve = any(_looks_like_id(f.get("company_name", "")) for f in findings[:200])
    _name_lookup: dict[str, str] = {}
    if _needs_resolve:
        # Query source table and build lookup keyed by row content that may match account_id
        _src_fqn = _dim_account_fqn()
        try:
            _src_df = _sf_query(f"SELECT * FROM {_src_fqn}")
            if _src_df is not None and len(_src_df) > 0:
                _src_cols = list(_src_df.columns)
                _src_mapping = detect_column_mapping(_src_cols)
                _name_col = _src_mapping.get("company_name")
                _id_col = _src_mapping.get("account_id")
                if _name_col and _name_col in _src_df.columns:
                    for _, row in _src_df.iterrows():
                        _n = str(row[_name_col] or "").strip()
                        if _id_col and _id_col in _src_df.columns:
                            _aid = str(row[_id_col] or "").strip()
                            if _aid and _n:
                                _name_lookup[_aid] = _n
                        if _n:
                            _name_lookup[_n] = _n
        except Exception:
            pass

    def _display_company(f: dict) -> str:
        name = f.get("company_name", "")
        if not _looks_like_id(name):
            return name
        # Try to resolve via account_id
        acct = f.get("account_id", "")
        if acct and acct in _name_lookup:
            return _name_lookup[acct]
        # Try name itself as key
        if name and name in _name_lookup:
            return _name_lookup[name]
        return name if name else "—"

    # --- Build table data ---
    table_data = []
    for f in findings[:200]:
        table_data.append({
            "Sélectionner": select_all,
            "Entreprise": _display_company(f),
            "Type": f.get("finding_type", ""),
            "Champ": f.get("field_label", ""),
            "Valeur": str(f.get("field_value", "") or "—"),
            "Attendu": str(f.get("expected_value", "")),
            "Sévérité": f.get("severity", ""),
            "Statut": f.get("status", ""),
            "Règle": f.get("rule_id", ""),
            "_id": f["id"],
        })

    df_table = pd.DataFrame(table_data)

    # Interactive table with checkbox
    edited_df = st.data_editor(
        df_table.drop(columns=["_id"]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Sélectionner": st.column_config.CheckboxColumn("✓", width="small"),
            "Entreprise": st.column_config.TextColumn("Entreprise", width="medium"),
            "Type": st.column_config.TextColumn("Anomalie", width="medium"),
            "Champ": st.column_config.TextColumn("Champ", width="small"),
            "Valeur": st.column_config.TextColumn("Valeur", width="medium"),
            "Attendu": st.column_config.TextColumn("Attendu", width="medium"),
            "Sévérité": st.column_config.SelectboxColumn("Sévérité", options=["HIGH", "MEDIUM", "LOW"], width="small"),
            "Statut": st.column_config.SelectboxColumn("Statut", options=["Open", "In Review", "Resolved", "Dismissed"], width="small"),
            "Règle": st.column_config.TextColumn("Règle", width="small"),
        },
        key="findings_editor",
        num_rows="fixed",
    )

    # Get selected IDs
    selected_mask = edited_df["Sélectionner"].tolist()
    selected_ids = [df_table.iloc[i]["_id"] for i, sel in enumerate(selected_mask) if sel]

    # --- Action bar ---
    st.markdown(f'<div style="font-size:0.82rem;font-weight:600;color:{t["text_primary"]};margin:12px 0 8px;">{len(selected_ids)} sélectionnée(s) sur {len(findings)}</div>', unsafe_allow_html=True)

    act1, act2, act3, act4, act5 = st.columns(5)
    with act1:
        if st.button("Corriger (AI)", type="primary", key="find_bulk_fix", use_container_width=True, disabled=not selected_ids):
            st.session_state.pop("findings_corrections", None)
            with st.spinner(f"Correction via INSEE + Cortex AI ({min(len(selected_ids), 5)} anomalies)..."):
                corrections = []
                for fid in selected_ids[:5]:
                    f = next((x for x in get_all_fr_anomalies() if x["id"] == fid), None)
                    if not f:
                        continue
                    corr = _auto_correct_finding(f)
                    if corr:
                        corrections.append({"id": fid, "company": f["company_name"], "field": f.get("field_label", ""), "old": f.get("field_value", ""), "new": corr})
                if corrections:
                    st.session_state["findings_corrections"] = corrections
                else:
                    st.session_state["findings_corrections_empty"] = True
            st.rerun()
    with act2:
        if st.button("🔍 Vérifier web", key="find_web_verify", use_container_width=True, disabled=not selected_ids):
            _target_id = selected_ids[0]
            _target_f = next((x for x in get_all_fr_anomalies() if x["id"] == _target_id), None)
            if _target_f:
                with st.spinner("Vérification web en cours… scan des sources"):
                    result = _web_verify_finding(_target_f)
                    st.session_state["web_verify_result"] = result
                    st.session_state["web_verify_finding_id"] = _target_id
                st.rerun()
    with act3:
        if st.button("En revue", key="find_bulk_review", use_container_width=True, disabled=not selected_ids):
            for fid in selected_ids:
                update_finding_status(fid, "In Review")
            add_audit_entry("Anomalies en revue", f"{len(selected_ids)} → En revue")
            st.rerun()
    with act4:
        if st.button("Résoudre", key="find_bulk_resolve", use_container_width=True, disabled=not selected_ids):
            for fid in selected_ids:
                update_finding_status(fid, "Resolved")
            add_audit_entry("Anomalies résolues", f"{len(selected_ids)} → Résolu")
            st.rerun()
    with act5:
        if st.button("Rejeter", key="find_bulk_reject", use_container_width=True, disabled=not selected_ids):
            for fid in selected_ids:
                update_finding_status(fid, "Dismissed")
            add_audit_entry("Anomalies rejetées", f"{len(selected_ids)} → Rejeté")
            st.rerun()

    # --- Corrections preview ---
    if st.session_state.get("findings_corrections"):
        st.markdown("---")
        st.markdown(f'<div style="font-size:0.85rem;font-weight:700;color:{t["text_primary"]};margin-bottom:10px;">Corrections Cortex AI</div>', unsafe_allow_html=True)
        corrs = st.session_state["findings_corrections"]
        corr_df = pd.DataFrame([{"Entreprise": c["company"], "Champ": c["field"], "Ancien": c["old"], "Nouveau (AI)": c["new"]} for c in corrs])
        st.dataframe(corr_df, use_container_width=True, hide_index=True)
        col_v, col_r = st.columns(2)
        with col_v:
            if st.button("Appliquer", type="primary", key="find_apply_corr"):
                for c in corrs:
                    update_finding_status(c["id"], "Resolved")
                add_audit_entry("Corrections AI", f"{len(corrs)} appliquées")
                st.session_state.pop("findings_corrections", None)
                st.rerun()
        with col_r:
            if st.button("Annuler", key="find_cancel_corr"):
                st.session_state.pop("findings_corrections", None)
                st.rerun()
    elif st.session_state.pop("findings_corrections_empty", False):
        st.markdown("---")
        st.info("Aucune correction automatique trouvée pour la sélection (entreprise étrangère ou pas de référence INSEE disponible).")

    # --- Web Verification Result Panel ---
    # Clear result if the selected finding changed
    _prev_verify_id = st.session_state.get("web_verify_finding_id")
    _current_sel = selected_ids[0] if selected_ids else None
    if _prev_verify_id and _current_sel and _prev_verify_id != _current_sel:
        st.session_state.pop("web_verify_result", None)
        st.session_state.pop("web_verify_finding_id", None)
    if st.session_state.get("web_verify_result"):
        st.markdown("---")
        vr = st.session_state["web_verify_result"]
        _vr_verdict = vr.get("verdict", "incertain")
        _vr_conf = vr.get("confidence", 0)
        _vr_expl = vr.get("explanation", "")
        _vr_suggested = vr.get("suggested_value")
        _vr_action = vr.get("suggested_action", "")

        # Verdict colors
        if _vr_verdict == "coherent":
            _v_color = "#0d9488"
            _v_bg = "rgba(13,148,136,0.08)"
            _v_label = "Cohérent — donnée correcte"
            _v_icon = "✓"
        elif _vr_verdict == "incoherent":
            _v_color = "#dc2626"
            _v_bg = "rgba(220,38,38,0.06)"
            _v_label = "Incohérent — erreur probable"
            _v_icon = "✕"
        else:
            _v_color = "#f59e0b"
            _v_bg = "rgba(245,158,11,0.08)"
            _v_label = "Incertain — vérification manuelle"
            _v_icon = "?"

        # Confidence bar color
        _conf_color = "#0d9488" if _vr_conf >= 70 else "#f59e0b" if _vr_conf >= 40 else "#dc2626"

        # Sources badges
        _src_html = ""
        for s in vr.get("sources", []):
            _src_html += f'<span style="display:inline-flex;align-items:center;gap:4px;padding:4px 10px;background:{t["border_subtle"]};border-radius:6px;font-size:0.7rem;font-weight:500;color:{t["text_primary"]};">🌐 {html.escape(s)}</span> '

        st.markdown(
            f'<div style="background:{t["card_bg"]};border:1px solid {t["border"]};border-radius:14px;padding:24px;margin-top:16px;">'
            # Header
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">'
            f'<div style="display:flex;align-items:center;gap:10px;">'
            f'<div style="width:32px;height:32px;border-radius:8px;background:{t["accent"]};display:flex;align-items:center;justify-content:center;">'
            f'<span style="color:#fff;font-size:0.8rem;font-weight:700;">AI</span></div>'
            f'<div><div style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};">Vérification web</div>'
            f'<div style="font-size:0.7rem;color:{t["text_secondary"]};">{html.escape(vr.get("company", ""))} · champ « {html.escape(vr.get("field_label", ""))} »</div></div>'
            f'</div></div>'
            # Field info
            f'<div style="background:{t["border_subtle"]};border-radius:10px;padding:14px 18px;margin-bottom:16px;">'
            f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;font-size:0.78rem;">'
            f'<div><span style="color:{t["text_secondary"]};">Entreprise</span><br/><strong style="color:{t["text_primary"]};">{html.escape(vr.get("company", ""))}</strong></div>'
            f'<div><span style="color:{t["text_secondary"]};">Champ</span><br/><strong style="color:{t["text_primary"]};">{html.escape(vr.get("field_label", ""))}</strong></div>'
            f'<div><span style="color:{t["text_secondary"]};">Valeur dans le fichier</span><br/><strong style="color:{t["text_primary"]};">{html.escape(str(vr.get("field_value", "") or "— (vide)"))}</strong></div>'
            f'<div><span style="color:{t["text_secondary"]};">Attendu (référence)</span><br/><strong style="color:{_v_color};">{html.escape(str(vr.get("expected_value", "")))}</strong></div>'
            f'</div></div>'
            # Sources
            f'<div style="margin-bottom:14px;">'
            f'<div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;">'
            f'<span style="color:#0d9488;font-size:0.85rem;">✓</span>'
            f'<span style="font-size:0.82rem;font-weight:600;color:{t["text_primary"]};">Scan web</span>'
            f'<span style="font-size:0.65rem;padding:2px 8px;background:{t["accent_soft"]};color:{t["accent"]};border-radius:999px;font-weight:600;">{len(vr.get("sources", []))} sources</span></div>'
            f'<div style="display:flex;flex-wrap:wrap;gap:6px;">{_src_html}</div></div>'
            # Summary
            f'<div style="margin-bottom:14px;">'
            f'<div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;">'
            f'<span style="color:#0d9488;font-size:0.85rem;">✓</span>'
            f'<span style="font-size:0.82rem;font-weight:600;color:{t["text_primary"]};">Résumé</span></div>'
            f'<div style="background:{t["border_subtle"]};border-radius:8px;padding:12px 16px;font-size:0.8rem;color:{t["text_primary"]};line-height:1.5;">'
            f'{html.escape(vr.get("web_summary", ""))}</div></div>'
            # Verdict
            f'<div style="margin-bottom:14px;">'
            f'<div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;">'
            f'<span style="color:{_v_color};font-size:0.85rem;">{_v_icon}</span>'
            f'<span style="font-size:0.82rem;font-weight:600;color:{t["text_primary"]};">Jugement du LLM</span></div>'
            f'<div style="background:{_v_bg};border-radius:10px;padding:16px 18px;border-left:3px solid {_v_color};">'
            f'<div style="font-size:0.88rem;font-weight:700;color:{_v_color};margin-bottom:6px;">{_v_label}</div>'
            f'<div style="font-size:0.78rem;color:{t["text_primary"]};line-height:1.5;margin-bottom:10px;">{html.escape(_vr_expl)}</div>'
            f'<div style="display:flex;align-items:center;gap:8px;">'
            f'<span style="font-size:0.7rem;color:{t["text_secondary"]};">Confiance</span>'
            f'<div style="flex:1;height:6px;background:{t["border"]};border-radius:3px;overflow:hidden;">'
            f'<div style="width:{_vr_conf}%;height:100%;background:{_conf_color};border-radius:3px;"></div></div>'
            f'<span style="font-size:0.75rem;font-weight:700;color:{t["text_primary"]};">{_vr_conf} %</span>'
            f'</div></div></div>'
            # Suggested action
            + (f'<div style="background:{t["border_subtle"]};border-radius:8px;padding:12px 16px;">'
               f'<div style="font-size:0.65rem;text-transform:uppercase;letter-spacing:0.06em;color:{t["text_secondary"]};font-weight:600;margin-bottom:4px;">Action suggérée par l\'IA</div>'
               f'<div style="font-size:0.82rem;font-weight:600;color:{t["accent"]};">{html.escape(_vr_action)}</div>'
               + (f'<div style="font-size:0.75rem;color:{t["text_secondary"]};margin-top:4px;">Valeur suggérée : <strong>{html.escape(str(_vr_suggested))}</strong></div>' if _vr_suggested else "")
               + f'</div>' if _vr_action else "")
            + f'</div>',
            unsafe_allow_html=True,
        )

        # Action buttons for verdict
        _v_col1, _v_col2, _v_col3 = st.columns(3)
        with _v_col1:
            if _vr_suggested and st.button("✓ Accepter la correction", type="primary", key="web_verify_accept"):
                _fid = st.session_state.get("web_verify_finding_id")
                if _fid:
                    update_finding_status(_fid, "Resolved")
                    add_audit_entry("Vérification web", f"Accepté: {vr.get('company', '')} — {vr.get('field_label', '')}")
                st.session_state.pop("web_verify_result", None)
                st.rerun()
        with _v_col2:
            if st.button("✕ Rejeter", key="web_verify_reject"):
                _fid = st.session_state.get("web_verify_finding_id")
                if _fid:
                    update_finding_status(_fid, "Dismissed")
                    add_audit_entry("Vérification web", f"Rejeté: {vr.get('company', '')} — {vr.get('field_label', '')}")
                st.session_state.pop("web_verify_result", None)
                st.rerun()
        with _v_col3:
            if st.button("Fermer", key="web_verify_close"):
                st.session_state.pop("web_verify_result", None)
                st.rerun()

    # Pagination info
    if len(findings) > 200:
        st.caption(f"Affichage limité à 200 sur {len(findings)} anomalies. Utilisez les filtres pour affiner.")


def page_tasks():
    page_header("Tâches", "Présélection et validation des anomalies — acceptez, corrigez ou rejetez en masse.")
    t = get_theme()
    accent = t['accent']

    # --- Section header with accent bar ---
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:18px;">'
        f'<div style="width:3px;height:18px;border-radius:2px;background:{accent};"></div>'
        f'<span style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};">File de tâches</span>'
        f'<span style="font-size:0.68rem;padding:3px 10px;background:{t["accent_soft"]};color:{accent};'
        f'border-radius:999px;font-weight:600;">Moteur prêt</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    actionable = [f for f in get_all_fr_anomalies() if f.get("status") in ("Open", "In Review")]
    if not actionable:
        st.success("Toutes les tâches ont été traitées.")
        return

    # Auto-assign priority
    if "task_priorities" not in st.session_state:
        st.session_state["task_priorities"] = {
            f["id"]: ("urgent" if f["severity"] == "HIGH" else ("normal" if f["severity"] == "MEDIUM" else "bas"))
            for f in actionable
        }

    # --- Stats bar with SVG icons ---
    urgent = sum(1 for f in actionable if st.session_state["task_priorities"].get(f["id"]) == "urgent")
    normal = sum(1 for f in actionable if st.session_state["task_priorities"].get(f["id"]) == "normal")
    bas = len(actionable) - urgent - normal

    svg_urgent = '<svg width="22" height="22" fill="none" viewBox="0 0 24 24"><path d="M12 9v4m0 4h.01M12 3l9.66 16.59A1 1 0 0120.66 21H3.34a1 1 0 01-.86-1.41L12 3z" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    svg_normal = '<svg width="22" height="22" fill="none" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" stroke="{}" stroke-width="2"/><path d="M12 8v4l3 3" stroke="{}" stroke-width="2" stroke-linecap="round"/></svg>'.format(accent, accent)
    svg_low = '<svg width="22" height="22" fill="none" viewBox="0 0 24 24"><path d="M5 12h14M12 5l7 7-7 7" stroke="#94a3b8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    svg_total = '<svg width="22" height="22" fill="none" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1" stroke="{}" stroke-width="2"/><rect x="14" y="3" width="7" height="7" rx="1" stroke="{}" stroke-width="2"/><rect x="3" y="14" width="7" height="7" rx="1" stroke="{}" stroke-width="2"/><rect x="14" y="14" width="7" height="7" rx="1" stroke="{}" stroke-width="2"/></svg>'.format(t['text_primary'], t['text_primary'], t['text_primary'], t['text_primary'])

    st.markdown(
        f"""<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:22px;">
            <div style="background:{t['card_bg']};border:1px solid {t['border']};border-radius:14px;padding:18px 20px;position:relative;overflow:hidden;">
                <div style="position:absolute;top:0;left:0;width:3px;height:100%;background:#ef4444;"></div>
                <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                    <div style="font-size:0.68rem;color:{t['text_secondary']};text-transform:uppercase;letter-spacing:0.06em;font-weight:600;">Urgent</div>
                    <div style="width:30px;height:30px;border-radius:8px;background:rgba(239,68,68,0.1);display:flex;align-items:center;justify-content:center;">{svg_urgent}</div>
                </div>
                <div style="font-size:2rem;font-weight:800;color:#ef4444;margin-top:8px;line-height:1;">{urgent}</div>
                <div style="font-size:0.7rem;color:{t['text_secondary']};margin-top:4px;">Anomalies critiques</div>
            </div>
            <div style="background:{t['card_bg']};border:1px solid {t['border']};border-radius:14px;padding:18px 20px;position:relative;overflow:hidden;">
                <div style="position:absolute;top:0;left:0;width:3px;height:100%;background:{accent};"></div>
                <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                    <div style="font-size:0.68rem;color:{t['text_secondary']};text-transform:uppercase;letter-spacing:0.06em;font-weight:600;">Normal</div>
                    <div style="width:30px;height:30px;border-radius:8px;background:{t['accent_soft']};display:flex;align-items:center;justify-content:center;">{svg_normal}</div>
                </div>
                <div style="font-size:2rem;font-weight:800;color:{accent};margin-top:8px;line-height:1;">{normal}</div>
                <div style="font-size:0.7rem;color:{t['text_secondary']};margin-top:4px;">À traiter</div>
            </div>
            <div style="background:{t['card_bg']};border:1px solid {t['border']};border-radius:14px;padding:18px 20px;position:relative;overflow:hidden;">
                <div style="position:absolute;top:0;left:0;width:3px;height:100%;background:#94a3b8;"></div>
                <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                    <div style="font-size:0.68rem;color:{t['text_secondary']};text-transform:uppercase;letter-spacing:0.06em;font-weight:600;">Bas</div>
                    <div style="width:30px;height:30px;border-radius:8px;background:{t['border_subtle']};display:flex;align-items:center;justify-content:center;">{svg_low}</div>
                </div>
                <div style="font-size:2rem;font-weight:800;color:{t['text_secondary']};margin-top:8px;line-height:1;">{bas}</div>
                <div style="font-size:0.7rem;color:{t['text_secondary']};margin-top:4px;">Priorité basse</div>
            </div>
            <div style="background:{t['card_bg']};border:1px solid {t['border']};border-radius:14px;padding:18px 20px;position:relative;overflow:hidden;">
                <div style="position:absolute;top:0;left:0;width:3px;height:100%;background:{t['text_primary']};"></div>
                <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                    <div style="font-size:0.68rem;color:{t['text_secondary']};text-transform:uppercase;letter-spacing:0.06em;font-weight:600;">Total</div>
                    <div style="width:30px;height:30px;border-radius:8px;background:{t['border_subtle']};display:flex;align-items:center;justify-content:center;">{svg_total}</div>
                </div>
                <div style="font-size:2rem;font-weight:800;color:{t['text_primary']};margin-top:8px;line-height:1;">{len(actionable)}</div>
                <div style="font-size:0.7rem;color:{t['text_secondary']};margin-top:4px;">Tâches en file</div>
            </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # --- Filters ---
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        filter_priority = st.selectbox("Priorité", ["Toutes", "urgent", "normal", "bas"], key="tasks_filter_prio")
    with col_f2:
        filter_severity = st.selectbox("Sévérité", ["Toutes", "HIGH", "MEDIUM", "LOW"], key="tasks_filter_sev")
    with col_f3:
        filter_rule = st.selectbox("Règle", ["Toutes"] + sorted({f.get("rule_id", "") for f in actionable}), key="tasks_filter_rule")

    # Apply filters
    filtered = actionable
    if filter_priority != "Toutes":
        filtered = [f for f in filtered if st.session_state["task_priorities"].get(f["id"]) == filter_priority]
    if filter_severity != "Toutes":
        filtered = [f for f in filtered if f.get("severity") == filter_severity]
    if filter_rule != "Toutes":
        filtered = [f for f in filtered if f.get("rule_id") == filter_rule]

    # Sort by priority
    priority_order = {"urgent": 0, "normal": 1, "bas": 2}
    filtered = sorted(filtered, key=lambda f: priority_order.get(st.session_state["task_priorities"].get(f["id"], "normal"), 1))

    # --- Select all toggle ---
    select_all_tasks = st.checkbox("Tout sélectionner", value=True, key="tasks_select_all")

    # --- Build DataFrame for editable table ---
    table_data = []
    for f in filtered[:50]:
        prio = st.session_state["task_priorities"].get(f["id"], "normal")
        table_data.append({
            "Sélectionner": select_all_tasks,
            "Priorité": prio.capitalize(),
            "Entreprise": f.get("company_name", ""),
            "Anomalie": f.get("finding_type", ""),
            "Champ": f.get("field_label", ""),
            "Valeur": str(f.get("field_value", "") or "—"),
            "Attendu": str(f.get("expected_value", "")),
            "Sévérité": f.get("severity", ""),
            "Règle": f.get("rule_id", ""),
            "_id": f["id"],
        })

    if not table_data:
        st.info("Aucune anomalie ne correspond aux filtres.")
        return

    df_table = pd.DataFrame(table_data)

    # Interactive data editor with checkbox column
    edited_df = st.data_editor(
        df_table.drop(columns=["_id"]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Sélectionner": st.column_config.CheckboxColumn("✓", default=True, width="small"),
            "Priorité": st.column_config.SelectboxColumn("Priorité", options=["Urgent", "Normal", "Bas"], width="small"),
            "Sévérité": st.column_config.SelectboxColumn("Sévérité", options=["HIGH", "MEDIUM", "LOW"], width="small"),
            "Entreprise": st.column_config.TextColumn("Entreprise", width="medium"),
            "Anomalie": st.column_config.TextColumn("Anomalie", width="medium"),
            "Champ": st.column_config.TextColumn("Champ", width="small"),
            "Valeur": st.column_config.TextColumn("Valeur", width="medium"),
            "Attendu": st.column_config.TextColumn("Attendu", width="medium"),
            "Règle": st.column_config.TextColumn("Règle", width="small"),
        },
        key="tasks_editor",
        num_rows="fixed",
    )

    # Get selected IDs
    selected_mask = edited_df["Sélectionner"].tolist()
    selected_ids = [df_table.iloc[i]["_id"] for i, sel in enumerate(selected_mask) if sel]

    # --- Action bar ---
    st.markdown(
        f'<div style="font-size:0.82rem;font-weight:600;color:{t["text_primary"]};margin:12px 0 8px;">'
        f'{len(selected_ids)} anomalie(s) sélectionnée(s) sur {len(filtered)}</div>',
        unsafe_allow_html=True,
    )

    act1, act2, act3, act4 = st.columns(4)

    with act1:
        if st.button("Corriger avec AI", type="primary", key="tasks_bulk_fix", use_container_width=True, disabled=not selected_ids):
            with st.spinner(f"Correction via INSEE + Cortex AI ({len(selected_ids)} anomalies)..."):
                corrections = []
                for fid in selected_ids[:10]:
                    f = next((x for x in actionable if x["id"] == fid), None)
                    if not f:
                        continue
                    corr = _auto_correct_finding(f)
                    if corr:
                        corrections.append({"id": fid, "company": f["company_name"], "field": f.get("field_label", ""), "old": f.get("field_value", ""), "new": corr})
                st.session_state["tasks_corrections_preview"] = corrections
            st.rerun()

    with act2:
        if st.button("Accepter", key="tasks_bulk_accept", use_container_width=True, disabled=not selected_ids):
            for fid in selected_ids:
                update_finding_status(fid, "In Review")
            add_audit_entry("Tâches acceptées", f"{len(selected_ids)} anomalies → En revue")
            st.rerun()

    with act3:
        if st.button("Résoudre", key="tasks_bulk_resolve", use_container_width=True, disabled=not selected_ids):
            for fid in selected_ids:
                update_finding_status(fid, "Resolved")
            add_audit_entry("Tâches résolues", f"{len(selected_ids)} anomalies → Résolu")
            st.rerun()

    with act4:
        if st.button("Rejeter", key="tasks_bulk_reject", use_container_width=True, disabled=not selected_ids):
            for fid in selected_ids:
                update_finding_status(fid, "Dismissed")
            add_audit_entry("Tâches rejetées", f"{len(selected_ids)} anomalies → Rejeté")
            st.rerun()

    # --- Corrections preview (after AI fix) ---
    if st.session_state.get("tasks_corrections_preview"):
        st.markdown("---")
        st.markdown(f'<div style="font-size:0.85rem;font-weight:700;color:{t["text_primary"]};margin-bottom:10px;">Corrections proposées par Cortex AI</div>', unsafe_allow_html=True)
        corrs = st.session_state["tasks_corrections_preview"]
        corr_table = pd.DataFrame([{"Entreprise": c["company"], "Champ": c["field"], "Ancien": c["old"], "Nouveau (AI)": c["new"]} for c in corrs])
        st.dataframe(corr_table, use_container_width=True, hide_index=True)

        col_v, col_r = st.columns(2)
        with col_v:
            if st.button("Appliquer les corrections", type="primary", key="tasks_apply_corr"):
                for c in corrs:
                    update_finding_status(c["id"], "Resolved")
                add_audit_entry("Corrections AI appliquées", f"{len(corrs)} valeurs corrigées")
                st.session_state.pop("tasks_corrections_preview", None)
                st.rerun()
        with col_r:
            if st.button("Annuler", key="tasks_cancel_corr"):
                st.session_state.pop("tasks_corrections_preview", None)
                st.rerun()

    # --- Export ---
    st.markdown("---")
    col_exp1, col_exp2, _ = st.columns([1, 1, 2])
    with col_exp1:
        export_df = pd.DataFrame(actionable)
        if not export_df.empty:
            export_df["priorite"] = export_df["id"].map(st.session_state.get("task_priorities", {}))
            st.download_button("Exporter CSV", export_df.to_csv(index=False), file_name="taches_anomalies.csv", mime="text/csv", key="tasks_export_csv")
    with col_exp2:
        jira_data = [{"summary": f"{f['finding_type']} — {f['company_name']}", "description": f"Champ: {f.get('field_label', '')} | Valeur: {f.get('field_value', '')} | Attendu: {f.get('expected_value', '')}", "priority": st.session_state.get("task_priorities", {}).get(f["id"], "normal").capitalize(), "labels": ["data-quality", f["severity"].lower()]} for f in actionable]
        st.download_button("Exporter Jira/Notion", json.dumps(jira_data, ensure_ascii=False, indent=2), file_name="taches_jira.json", mime="application/json", key="tasks_export_jira")


def page_exports():
    t = get_theme()
    accent = t['accent']
    page_header("Exports & Audit", "Rapports, restitution CRM et piste d'audit complète.")

    today_str = _now().strftime("%Y%m%d")
    today_label = _now().strftime("%Y-%m-%d")
    _accounts = load_dim_account(_dim_account_fqn())
    _findings = get_all_fr_anomalies()
    _corrections = get_fr_corrections()

    # --- Section 1: Export rapport ---
    st.markdown(
        f'<div style="background:{t["card_bg"]};border:1px solid {t["border"]};border-radius:14px;padding:22px 24px;margin-bottom:20px;">'
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;">'
        f'<div style="width:3px;height:18px;border-radius:2px;background:{accent};"></div>'
        f'<div style="width:34px;height:34px;border-radius:10px;background:{t["accent_soft"]};display:flex;align-items:center;justify-content:center;">'
        f'<svg width="18" height="18" fill="none" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z" stroke="{accent}" stroke-width="2"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" stroke="{accent}" stroke-width="2" stroke-linecap="round"/></svg>'
        f'</div>'
        f'<div>'
        f'<div style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};">Exports de données</div>'
        f'<div style="font-size:0.75rem;color:{t["text_secondary"]};">Téléchargez les données analysées en CSV pour votre CRM ou vos rapports.</div>'
        f'</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    exports = [
        {"name": f"dim_account_{today_str}.csv", "date": today_label, "type": "Comptes clients",
         "df": pd.DataFrame(_accounts) if _accounts else pd.DataFrame()},
        {"name": f"rapport_anomalies_{today_str}.csv", "date": today_label, "type": "Anomalies",
         "df": pd.DataFrame(_findings) if _findings else pd.DataFrame()},
        {"name": f"corrections_crm_{today_str}.csv", "date": today_label, "type": "Corrections CRM",
         "df": pd.DataFrame(_corrections) if _corrections else pd.DataFrame()},
    ]

    exp_cols = st.columns(len(exports))
    exp_icons = [
        '<svg width="20" height="20" fill="none" viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" stroke="{}" stroke-width="2"/><circle cx="9" cy="7" r="4" stroke="{}" stroke-width="2"/><path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" stroke="{}" stroke-width="2"/></svg>'.format(accent, accent, accent),
        '<svg width="20" height="20" fill="none" viewBox="0 0 24 24"><path d="M12 9v4m0 4h.01M12 3l9.66 16.59A1 1 0 0120.66 21H3.34a1 1 0 01-.86-1.41L12 3z" stroke="#ef4444" stroke-width="2" stroke-linecap="round"/></svg>',
        '<svg width="20" height="20" fill="none" viewBox="0 0 24 24"><path d="M9 11l3 3L22 4" stroke="{}" stroke-width="2" stroke-linecap="round"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11" stroke="{}" stroke-width="2"/></svg>'.format(t['success'], t['success']),
    ]
    for i, exp in enumerate(exports):
        with exp_cols[i]:
            rows = len(exp["df"])
            icon_html = exp_icons[i] if i < len(exp_icons) else ""
            st.markdown(
                f'<div style="background:{t["card_bg"]};border:1px solid {t["border"]};border-radius:14px;padding:18px 20px;text-align:center;">'
                f'<div style="width:36px;height:36px;border-radius:10px;background:{t["accent_soft"]};display:inline-flex;align-items:center;justify-content:center;margin-bottom:10px;">{icon_html}</div>'
                f'<div style="font-size:0.72rem;font-weight:700;color:{accent};text-transform:uppercase;letter-spacing:0.05em;">{html.escape(exp["type"])}</div>'
                f'<div style="font-size:1.8rem;font-weight:800;color:{t["text_primary"]};margin:6px 0;">{rows}</div>'
                f'<div style="font-size:0.7rem;color:{t["text_secondary"]};">lignes · {html.escape(exp["date"])}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if not exp["df"].empty:
                st.download_button(
                    f"Télécharger",
                    exp["df"].to_csv(index=False),
                    file_name=exp["name"],
                    mime="text/csv",
                    key=f"dl_{exp['name']}",
                    use_container_width=True,
                )

    # --- Section 2: Piste d'audit ---
    st.markdown(
        f'<div style="background:{t["card_bg"]};border:1px solid {t["border"]};border-radius:14px;padding:22px 24px;margin-top:24px;">'
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;">'
        f'<div style="width:3px;height:18px;border-radius:2px;background:{accent};"></div>'
        f'<div style="width:34px;height:34px;border-radius:10px;background:{t["accent_soft"]};display:flex;align-items:center;justify-content:center;">'
        f'<svg width="18" height="18" fill="none" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke="{accent}" stroke-width="2"/><path d="M12 6v6l4 2" stroke="{accent}" stroke-width="2" stroke-linecap="round"/></svg>'
        f'</div>'
        f'<div>'
        f'<div style="display:flex;align-items:center;gap:8px;">'
        f'<span style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};">Piste d\'Audit Temporelle</span>'
        f'<span style="font-size:0.62rem;padding:2px 8px;background:{t["accent_soft"]};color:{accent};border-radius:4px;font-weight:600;">DQ_AUDIT_LOG</span>'
        f'</div>'
        f'<div style="font-size:0.75rem;color:{t["text_secondary"]};">Chaque action utilisateur est tracée et persistée dans Snowflake.</div>'
        f'</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    audit_entries = load_dq_audit_log()
    if audit_entries:
        audit_df = pd.DataFrame(audit_entries)
        # Build styled audit table
        display_cols = []
        if "time" in audit_df.columns:
            display_cols.append("time")
        if "action" in audit_df.columns:
            display_cols.append("action")
        if "detail" in audit_df.columns:
            display_cols.append("detail")
        if "user" in audit_df.columns:
            display_cols.append("user")

        if display_cols:
            show_df = audit_df[display_cols].head(20)
            show_df.columns = [{"time": "Timestamp", "action": "Action", "detail": "Détail", "user": "Utilisateur"}.get(c, c) for c in display_cols]
            st.dataframe(show_df, use_container_width=True, hide_index=True)
        else:
            st.dataframe(audit_df.head(20), use_container_width=True, hide_index=True)

        st.caption(f"Toutes les décisions sont persistées dans `DQ_AUDIT_LOG` · Snowflake `QUALITY_TEST.DATA_QUALITY`")
    else:
        st.info("Aucune entrée d'audit pour le moment. Les actions seront tracées automatiquement.")


# Available enrichment columns from Marketplace SIRENE
SIRENE_ENRICHMENT_COLS = {
    "denomination": "Raison sociale officielle",
    "activite_principale": "Code NAF/APE",
    "libelle_sous_classe": "Libellé activité",
    "categorie_juridique": "Catégorie juridique (code)",
    "etat_administratif": "Statut (Active/Radiée)",
    "categorie_entreprise": "Taille (PME/ETI/GE)",
    "tranche_effectifs": "Tranche effectifs",
    "adresse_complete": "Adresse siège (composée)",
    "code_postal": "Code postal",
    "libelle_commune": "Commune",
    "libelle_departement": "Département",
    "libelle_region": "Région",
}


def enrich_with_sirene(df: pd.DataFrame, join_key: str, columns: list[str]) -> pd.DataFrame:
    """Enrich a DataFrame by joining to the Marketplace SIRENE on SIREN or SIRET."""
    if df.empty or not columns:
        return df
    siren_values = df[join_key].dropna().unique().tolist()
    if not siren_values:
        return df
    values_sql = ",".join(f"'{str(v).strip()}'" for v in siren_values[:5000])

    # Build SELECT columns
    col_map = {
        "denomination": "u.DENOMINATION",
        "activite_principale": "u.ACTIVITE_PRINCIPALE",
        "libelle_sous_classe": "u.LIBELLE_SOUS_CLASSE",
        "categorie_juridique": "u.CATEGORIE_JURIDIQUE",
        "etat_administratif": "u.ETAT_ADMINISTRATIF",
        "categorie_entreprise": "u.CATEGORIE_ENTREPRISE",
        "tranche_effectifs": "u.TRANCHE_EFFECTIFS",
        "adresse_complete": "CONCAT_WS(' ', e.NUMERO_VOIE, e.TYPE_VOIE, e.LIBELLE_VOIE, e.CODE_POSTAL, e.LIBELLE_COMMUNE)",
        "code_postal": "e.CODE_POSTAL",
        "libelle_commune": "e.LIBELLE_COMMUNE",
        "libelle_departement": "e.LIBELLE_DEPARTEMENT",
        "libelle_region": "e.LIBELLE_REGION",
    }
    select_cols = ", ".join(f"{col_map[c]} AS {c}" for c in columns if c in col_map)
    if not select_cols:
        return df

    if join_key.lower() in ("siren",):
        join_condition = f"u.SIREN IN ({values_sql})"
        key_col = "u.SIREN AS _join_key"
        etab_join = "LEFT JOIN " + _SIRENE_ETAB + " e ON e.SIRET = u.SIREN || u.NIC_SIEGE"
    else:
        join_condition = f"e.SIRET IN ({values_sql})"
        key_col = "e.SIRET AS _join_key"
        etab_join = "JOIN " + _SIRENE_ETAB + f" e ON e.SIREN = u.SIREN AND e.SIRET IN ({values_sql})"

    query = f"""
        SELECT {key_col}, {select_cols}
        FROM {_SIRENE_UL} u
        {etab_join}
        WHERE {join_condition}
    """
    ref_df = _sf_query(query)
    if ref_df.empty:
        return df

    # Merge
    enriched = df.merge(
        ref_df.rename(columns={"_join_key": join_key}),
        on=join_key,
        how="left",
        suffixes=("", "_sirene"),
    )
    return enriched


def _suggest_join_key_ai(columns: list[str]) -> str:
    """Use Cortex AI to suggest which column is the best join key for SIRENE enrichment."""
    prompt = (
        f"Given these DataFrame columns: {columns}\n"
        f"Which single column is the best join key to match against the French SIRENE register? "
        f"SIRENE can be joined on SIREN (9 digits) or SIRET (14 digits).\n"
        f"Return ONLY the exact column name (one word, no quotes, no explanation)."
    )
    try:
        df = _sf_query(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', $${prompt}$$) AS result")
        if not df.empty:
            suggestion = str(df.iloc[0]['result']).strip().strip('"').strip("'")
            if suggestion in columns:
                return suggestion
    except Exception:
        pass
    # Fallback: look for siren/siret in column names
    for col in columns:
        if "siren" in col.lower():
            return col
        if "siret" in col.lower():
            return col
    return columns[0] if columns else ""


def _render_enrichment_ui():
    """UI for enriching data with Marketplace SIRENE columns."""
    _accounts = load_dim_account(_dim_account_fqn())
    if not _accounts:
        st.info("Aucune donnée dans DIM_ACCOUNT. Importez des données d'abord.")
        return

    df = pd.DataFrame(_accounts)
    available_cols = [c for c in df.columns if c not in ("vat", "country", "legal_form")]

    # Join key selection
    col1, col2 = st.columns([1, 2])
    with col1:
        suggested_key = _suggest_join_key_ai(list(df.columns)) if "siren" not in df.columns else "siren"
        default_idx = available_cols.index(suggested_key) if suggested_key in available_cols else 0
        join_key = st.selectbox(
            "Clé de jointure SIRENE",
            available_cols,
            index=default_idx,
            help="Colonne utilisée pour le rapprochement avec le registre SIRENE. L'IA propose la meilleure option.",
            key="enrich_join_key",
        )
    with col2:
        selected_cols = st.multiselect(
            "Colonnes à enrichir",
            list(SIRENE_ENRICHMENT_COLS.keys()),
            default=["denomination", "etat_administratif", "activite_principale", "adresse_complete"],
            format_func=lambda x: SIRENE_ENRICHMENT_COLS.get(x, x),
            key="enrich_columns",
        )

    if not selected_cols:
        st.warning("Sélectionnez au moins une colonne à enrichir.")
        return

    if st.button("Enrichir avec SIRENE", type="primary", key="btn_enrich"):
        with st.spinner(f"Enrichissement via SIRENE ({len(df)} lignes × {len(selected_cols)} colonnes)…"):
            enriched_df = enrich_with_sirene(df, join_key, selected_cols)
        st.success(f"Enrichissement terminé · {len(enriched_df)} lignes")
        st.dataframe(enriched_df, use_container_width=True, hide_index=True)
        csv_data = enriched_df.to_csv(index=False, sep=";")
        st.download_button(
            "Télécharger CSV enrichi",
            csv_data,
            file_name="donnees_enrichies_sirene.csv",
            mime="text/csv",
            key="dl_enriched",
        )


def _render_insee_lookup():
    """Recherche SIRENE via le registre national Marketplace (29M+ entreprises)."""
    query = st.text_input(
        "Recherche SIRENE",
        placeholder="SIREN, SIRET ou raison sociale…",
        key="fr_insee_query",
    )
    if not query:
        st.caption("29.6M+ entreprises · Registre national SIRENE (Marketplace Snowflake)")
        return

    _accounts = load_dim_account(_dim_account_fqn())
    insee_result = crm_result = None
    q = query.strip().replace(" ", "")
    if q.isdigit() and len(q) == 9:
        insee_result = lookup_sirene(q)
        crm_result = next((a for a in _accounts if str(a.get("siren", "")) == q), None)
    elif q.isdigit() and len(q) == 14:
        siren_code = q[:9]
        insee_result = lookup_sirene(siren_code)
        crm_result = next(
            (a for a in _accounts if str(a.get("siret", "")) == q or str(a.get("siren", "")) == siren_code),
            None,
        )
    else:
        # Search by name in the Marketplace
        search_df = _sf_query(f"""
            SELECT SIREN, DENOMINATION AS raison_sociale, ACTIVITE_PRINCIPALE AS naf,
                   ETAT_ADMINISTRATIF AS statut, CATEGORIE_JURIDIQUE AS categorie_juridique
            FROM {_SIRENE_UL}
            WHERE UPPER(DENOMINATION) LIKE '%{query.upper().replace("'", "''")}%'
            LIMIT 10
        """)
        if not search_df.empty:
            insee_result = search_df.to_dict("records")[0]
            if len(search_df) > 1:
                st.info(f"{len(search_df)} résultats trouvés — affichage du premier.")
        crm_result = next(
            (a for a in _accounts if query.lower() in str(a.get("company_name", "")).lower()), None
        )

    if not insee_result and not crm_result:
        st.warning("Aucun résultat dans le registre SIRENE.")
        return

    c1, c2 = st.columns(2)
    with c1:
        if insee_result:
            card(
                f'<strong>INSEE · {html.escape(insee_result["raison_sociale"])}</strong><br>'
                f'SIREN {html.escape(insee_result["siren"])} · NAF {html.escape(insee_result["naf"])}<br>'
                f'{html.escape(insee_result["adresse"])}'
            )
    with c2:
        if crm_result:
            card(
                f'<strong>CRM · {html.escape(crm_result["company_name"])}</strong><br>'
                f'SIREN {html.escape(crm_result["siren"])} · SIRET {html.escape(crm_result["siret"])}'
            )


def _fr_tab_configurator():
    st.markdown("#### Exécution batch Snowflake")
    st.caption("Lancer `SP_EXECUTE_BUSINESS_RULES()` sur la table configurée dans **Source & analyse**")

    table = _dim_account_fqn()
    card(
        f'<strong>Table configurée</strong> · <code>{html.escape(table)}</code><br>'
        f'<span style="color:var(--text-secondary);font-size:0.85rem;">'
        f'Configurez d\'abord la source dans l\'onglet <strong>Source & analyse</strong>, '
        f'puis lancez la procédure stockée ici (connexion Snowflake à brancher).</span>'
    )

    if st.button("Lancer SP_EXECUTE_BUSINESS_RULES()", type="primary", key="fr_run_sp"):
        with st.spinner("Appel CALL SP_EXECUTE_BUSINESS_RULES()…"):
            sp_result = call_sp_business_rules(table)
        if sp_result.startswith("Erreur"):
            st.error(sp_result)
        else:
            st.success(f"Procédure exécutée · {sp_result}")
            add_audit_entry("SP exécutée", f"SP_EXECUTE_BUSINESS_RULES({table})")
        st.rerun()


# ---------------------------------------------------------------------------
# Tab: Règles métier (Custom Rules)
# ---------------------------------------------------------------------------



def _fr_tab_custom_rules():
    t = get_theme()
    accent = t['accent']
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:18px;">'
        f'<div style="width:3px;height:18px;border-radius:2px;background:{accent};"></div>'
        f'<div>'
        f'<div style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};">Règles métier</div>'
        f'<div style="font-size:0.75rem;color:{t["text_secondary"]};">Créez, gérez et exécutez vos propres règles de qualité — persistées sur Snowflake.</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # --- Standard rules (read-only display) ---
    with st.expander("Règles standard (R01–R08 + INSEE)", expanded=False):
        cols = st.columns(2)
        for i, rule in enumerate(FR_BUSINESS_RULES):
            with cols[i % 2]:
                st.markdown(
                    f'<div class="qx-rule-card active">'
                    f'<div class="qx-rule-card-badge on">✓</div>'
                    f'<div class="qx-rule-card-id">{html.escape(rule["id"])}</div>'
                    f'<div class="qx-rule-card-name">{html.escape(rule["name"])}</div>'
                    f'<div class="qx-rule-card-check">{html.escape(rule["check"])}</div>'
                   
 f'</div>',
                    unsafe_allow_html=True,
                )

    st.markdown("---")

    # --- Custom rules from database ---
    st.markdown("#### Vos règles personnalisées")
    custom_rules = list_custom_rules(active_only=False)

    if custom_rules:
        for cr in custom_rules:
            is_active = cr.get("is_active", True)
            card_cls = "qx-rule-card active" if is_active else "qx-rule-card"
            badge_cls = "qx-rule-card-badge on" if is_active else "qx-rule-card-badge off"
            field_label = IMPORT_FIELD_LABELS.get(cr.get("target_field", ""), cr.get("target_field", ""))
            type_label = RULE_TYPES.get(cr.get("rule_type", ""), cr.get("rule_type", ""))
            sev = cr.get("severity", "MEDIUM")
            sev_class = f"qx-badge qx-badge-{'high' if sev == 'HIGH' else ('medium' if sev == 'MEDIUM' else 'low')}"
            st.markdown(
                f'<div class="{card_cls}">'
                f'<div class="{badge_cls}">{"✓" if is_active else "—"}</div>'
                f'<div class="qx-rule-card-id">{html.escape(str(cr.get("id", "")))}</div>'
                f'<div class="qx-rule-card-name">{html.escape(str(cr.get("name", "")))}</div>'
                f'<div class="qx-rule-card-check">{html.escape(field_label)} · {html.escape(type_label)} · '
                f'<span class="{sev_class}">{html.escape(sev)}</span></div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            bc1, bc2 = st.columns(2)
            with bc1:
                if st.button(
                    "Désactiver" if is_active else "Activer",
                    key=f"toggle_{cr['id']}",
                    use_container_width=True,
                ):
                    toggle_custom_rule(cr["id"], not is_active)
                    st.rerun()
            with bc2:
                if st.button("Supprimer", key=f"del_{cr['id']}", use_container_width=True):
                    delete_custom_rule(cr["id"])
                    st.rerun()
    else:
        st.markdown(
            '<div class="qx-empty-state">Aucune règle personnalisée — ajoutez votre premier contrôle métier ci-dessous.</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # --- Form to add new rule ---
    st.markdown("#### Ajouter une règle")
    with st.form("add_custom_rule_form", clear_on_submit=True):
        fc1, fc2 = st.columns(2)
        with fc1:
            rule_name = st.text_input("Nom de la règle", placeholder="Ex: Email corporate valide")
            rule_field = st.selectbox(
                "Champ cible",
                options=list(IMPORT_FIELD_LABELS.keys()),
                format_func=lambda k: IMPORT_FIELD_LABELS[k],
            )
        with fc2:
            rule_type = st.selectbox(
                "Type de contrôle",
                options=list(RULE_TYPES.keys()),
                format_func=lambda k: RULE_TYPES[k],
            )
            rule_severity = st.selectbox("Sévérité", ["HIGH", "MEDIUM", "LOW"])

        rule_pattern = st.text_input(
            "Pattern / valeurs",
            help="Regex pour 'regex', valeurs séparées par virgule pour 'in_list', format min:max pour 'length'. Vide pour 'not_empty'.",
        )
        rule_desc = st.text_input("Description (optionnel)", placeholder="Vérifie que l'email est au format standard")

        submitted = st.form_submit_button("Créer la règle", type="primary", use_container_width=True)
        if submitted and rule_name.strip():
            cid = create_custom_rule(
                name=rule_name.strip(),
                target_field=rule_field,
                rule_type=rule_type,
                pattern=rule_pattern.strip(),
                severity=rule_severity,
                description=rule_desc.strip(),
            )
            st.success(f"Règle **{cid}** créée et persistée sur Snowflake.")
            st.rerun()


# ---------------------------------------------------------------------------
# Tab: Data Cleaning (auto-dedup + scoring + preview)
# ---------------------------------------------------------------------------

def _fr_tab_data_cleaning():
    t = get_theme()
    accent = t['accent']
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:18px;">'
        f'<div style="width:3px;height:18px;border-radius:2px;background:{accent};"></div>'
        f'<div>'
        f'<div style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};">Data Cleaning</div>'
        f'<div style="font-size:0.75rem;color:{t["text_secondary"]};">Dédoublonnage Cortex AI puis analyse des anomalies sur données propres.</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Use uploaded file if available, otherwise load from Snowflake
    if st.session_state.get("source_mode") == "file" and "uploaded_df" in st.session_state:
        df = st.session_state["uploaded_df"].copy()
        table = st.session_state.get("uploaded_filename", "Fichier uploadé")
        st.info(f"📂 Source : **{table}** ({len(df)} lignes)")
    else:
        table = _dim_account_fqn()
        raw_data = load_dim_account(table)
        if not raw_data:
            st.warning("Aucune donnée dans la table source.")
            return
        df = pd.DataFrame(raw_data)
    mapping = _mapping_for_table(table, list(df.columns))

    # Track current step
    if "dc_step" not in st.session_state:
        st.session_state["dc_step"] = 1

    step = st.session_state["dc_step"]

    # --- Step indicator ---
    steps_html = ""
    labels = ["Détection doublons", "Confirmation cleaning", "Analyse anomalies"]
    for i, label in enumerate(labels, 1):
        cls = "qx-step-done" if i < step else ("qx-step-active" if i == step else "qx-step-pending")
        icon = "✓" if i < step else str(i)
        steps_html += f'<span class="qx-step {cls}">{icon} {label}</span> '
    st.markdown(f'<div class="qx-wizard-track">{steps_html}</div>', unsafe_allow_html=True)

    # =========================================================================
    # STEP 1: Detect duplicates with Cortex AI
    # =========================================================================
    if step == 1:
        st.markdown(f"**Table :** `{table}` · **{len(df)} lignes**")
        st.markdown("Cortex AI compare les enregistrements et identifie les doublons (SIREN identiques, noms similaires, adresses proches).")

        if st.button("Lancer la détection", type="primary", key="dc_detect", use_container_width=True):
            with st.spinner("Cortex AI analyse les doublons…"):
                comp_col = mapping.get("company_name") or "COMPANY_NAME"
                siren_col = mapping.get("siren") or "SIREN"
                id_col = mapping.get("account_id") or "ACCOUNT_ID"
                addr_col = mapping.get("address") or "ADDRESS"

                records_for_ai = []
                for idx, row in df.iterrows():
                    records_for_ai.append({
                        "idx": int(idx),
                        "id": _cell_str(row[id_col]) if id_col in row.index else str(idx),
                        "name": _cell_str(row[comp_col]) if comp_col in row.index else "",
                        "siren": _cell_str(row[siren_col]) if siren_col in row.index else "",
                        "address": _cell_str(row[addr_col]) if addr_col in row.index else "",
                    })

                # Cortex AI has token limits — process in batches of 200 records max
                _batch_size = 200
                all_duplicate_groups = []
                _group_offset = 0
                for _batch_start in range(0, len(records_for_ai), _batch_size):
                    _batch = records_for_ai[_batch_start:_batch_start + _batch_size]
                    records_json = json.dumps(_batch, ensure_ascii=False)
                    prompt = f"""Tu es un expert data quality. Analyse ces enregistrements et identifie les GROUPES DE DOUBLONS.
Criteres :
- SIREN identique (meme apres nettoyage espaces/tirets)
- Noms tres similaires (abreviations, inversions, casse)
- Meme adresse avec nom legerement different

Enregistrements :
{records_json}

Reponds UNIQUEMENT en JSON valide, un array de groupes :
[{{"group_id": 1, "records": [idx1, idx2], "confidence": 0.95, "reason": "SIREN identique"}}]
Si aucun doublon : []
JSON :"""

                    try:
                        cortex_result = _sf_query(f"""
                            SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', '{prompt.replace("'", "''")}') AS result
                        """)
                        if not cortex_result.empty:
                            raw_response = str(cortex_result.iloc[0, 0])
                            json_match = re.search(r'\[.*\]', raw_response, re.DOTALL)
                            if json_match:
                                _batch_groups = json.loads(json_match.group())
                                for g in _batch_groups:
                                    g["group_id"] = g.get("group_id", 0) + _group_offset
                                all_duplicate_groups.extend(_batch_groups)
                    except Exception:
                        pass  # Continue with next batch
                    _group_offset += 1000

                duplicate_groups = all_duplicate_groups

                st.session_state["dc_groups"] = duplicate_groups
                st.session_state["dc_df"] = df
                st.session_state.pop("dc_merged_df", None)
                st.session_state.pop("dc_anomalies", None)

                if duplicate_groups:
                    st.session_state["dc_step"] = 2
                else:
                    # No duplicates — skip to analysis directly
                    st.session_state["dc_merged_df"] = df
                    st.session_state["dc_step"] = 3
            st.rerun()

    # =========================================================================
    # STEP 2: Show groups + user confirms cleaning
    # =========================================================================
    elif step == 2:
        groups = st.session_state.get("dc_groups", [])
        st.success(f"**{len(groups)} groupe(s) de doublons** détectés")

        for i, group in enumerate(groups):
            record_indices = group.get("records", [])
            confidence = group.get("confidence", 0)
            reason = group.get("reason", "")
            with st.expander(f"Groupe {i+1} — {reason} (confiance {confidence*100:.0f}%)", expanded=True):
                group_rows = df.iloc[record_indices] if all(idx < len(df) for idx in record_indices) else pd.DataFrame()
                if not group_rows.empty:
                    st.dataframe(group_rows, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("**Confirmer le nettoyage ?** Cortex va fusionner chaque groupe en un seul enregistrement optimal.")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Confirmer et fusionner", type="primary", key="dc_confirm_merge", use_container_width=True):
                with st.spinner("Cortex AI fusionne les doublons…"):
                    merged_rows = []
                    removed_indices = set()

                    for group in groups:
                        record_indices = group.get("records", [])
                        if len(record_indices) < 2:
                            continue
                        group_rows = df.iloc[record_indices]
                        group_data = group_rows.to_dict("records")
                        cols = list(df.columns)

                        merge_prompt = f"""Fusionne ces doublons en UN seul enregistrement optimal.
Colonnes : {json.dumps(cols)}
Enregistrements :
{json.dumps(group_data, ensure_ascii=False, default=str)}

Regles : garder SIREN/SIRET valide (9/14 chiffres), nom le plus complet, adresse la plus complete, NAF format XXXXZ.
Reponds UNIQUEMENT en JSON — un seul objet :
JSON :"""

                        try:
                            merge_result = _sf_query(f"""
                                SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', '{merge_prompt.replace("'", "''")}') AS result
                            """)
                            if not merge_result.empty:
                                raw_merge = str(merge_result.iloc[0, 0])
                                json_match = re.search(r'\{.*\}', raw_merge, re.DOTALL)
                                if json_match:
                                    merged_record = json.loads(json_match.group())
                                    merged_rows.append((record_indices[0], merged_record))
                                    removed_indices.update(record_indices[1:])
                                else:
                                    removed_indices.update(record_indices[1:])
                            else:
                                removed_indices.update(record_indices[1:])
                        except Exception:
                            removed_indices.update(record_indices[1:])

                    # Build cleaned DataFrame
                    df_cleaned = df.drop(index=list(removed_indices)).reset_index(drop=True)
                    for keep_idx, merged_record in merged_rows:
                        mask = df_cleaned.index == keep_idx
                        if mask.any():
                            for col_name, val in merged_record.items():
                                if col_name in df_cleaned.columns:
                                    df_cleaned.loc[mask, col_name] = val

                    run_id = f"CORTEX-DEDUP-{_now().strftime('%Y%m%d%H%M%S')}"
                    persist_dedup_result(run_id, table, len(df), len(df_cleaned), len(removed_indices), ["cortex_ai"], "merge_intelligent", 0.0)
                    add_audit_entry("Cleaning Cortex", f"{len(removed_indices)} doublons fusionnes sur {table}")

                    st.session_state["dc_merged_df"] = df_cleaned
                    st.session_state["dc_removed_count"] = len(removed_indices)
                    st.session_state["dc_run_id"] = run_id
                    st.session_state["dc_step"] = 3
                st.rerun()
        with c2:
            if st.button("Ignorer les doublons", key="dc_skip_merge", use_container_width=True):
                st.session_state["dc_merged_df"] = df
                st.session_state["dc_removed_count"] = 0
                st.session_state["dc_step"] = 3
                st.rerun()

    # =========================================================================
    # STEP 3: Run analysis on cleaned data + show results
    # =========================================================================
    elif step == 3:
        df_clean = st.session_state.get("dc_merged_df", df)
        removed_count = st.session_state.get("dc_removed_count", 0)

        if removed_count > 0:
            st.success(f"Cleaning terminé : **{removed_count} doublon(s)** fusionnés. Données nettoyées : **{len(df_clean)} lignes**.")
        else:
            st.info(f"Aucun doublon supprimé. Analyse sur **{len(df_clean)} lignes**.")

        # Run analysis if not already done
        if "dc_anomalies" not in st.session_state:
            with st.spinner("Analyse des anomalies (R01-R08 + INSEE + règles custom) sur données nettoyées…"):
                custom_rules_db = [
                    {"id": r["id"], "name": r["name"], "field": r["target_field"],
                     "pattern": r.get("pattern", ""), "severity": r.get("severity", "MEDIUM"),
                     "rule_type": r.get("rule_type", "regex")}
                    for r in list_custom_rules(active_only=True)
                ]
                enabled = [r["id"] for r in FR_BUSINESS_RULES] + ["INSEE"]
                anomalies, stats = analyze_uploaded_dataframe(
                    df_clean, mapping, source="snowflake",
                    enabled_rules=enabled, skip_duplicate_check=True,
                    custom_rules=custom_rules_db,
                )
                st.session_state["dc_anomalies"] = anomalies
                st.session_state["dc_stats"] = stats

        anomalies = st.session_state["dc_anomalies"]
        stats = st.session_state["dc_stats"]


        # --- Confidence scoring per row ---
        st.markdown("---")
        st.markdown("#### Score de confiance par ligne")
        st.caption("Chaque ligne reçoit un score basé sur le ratio règles passées / règles applicables.")

        # Compute per-row scores
        active_custom = list_custom_rules(active_only=True)
        custom_for_scoring = [
            {"id": r["id"], "name": r["name"], "field": r["target_field"],
             "pattern": r.get("pattern", ""), "severity": r.get("severity", "MEDIUM"),
             "rule_type": r.get("rule_type", "regex")}
            for r in active_custom
        ]
        row_scores = []
        for idx, row in df_clean.iterrows():
            row_num = int(idx) + 1
            failed_rules = []
            def _v(field):
                col = mapping.get(field)
                return _cell_str(row[col]) if col and col in row.index else ""
            siren = _digits_only(_v("siren"))
            siret = _digits_only(_v("siret"))
            applicable = 0
            passed = 0
            if mapping.get("siren"):
                applicable += 1
                if siren and _valid_siren(siren):
                    passed += 1
                elif not siren:
                    passed += 0  # missing = fail only if mandatory
                    failed_rules.append("R01")
                else:
                    failed_rules.append("R01")
            if mapping.get("siret"):
                applicable += 1
                if siret and _valid_siret(siret):
                    passed += 1
                elif not siret:
                    failed_rules.append("R02")
                else:
                    failed_rules.append("R02")
            if mapping.get("siren") and mapping.get("siret") and siren and siret and _valid_siren(siren) and _valid_siret(siret):
                # Only check coherence if both are valid
                applicable += 1
                if _siret_matches_siren(siren, siret):
                    passed += 1
                else:
                    failed_rules.append("R03")
            if mapping.get("vat"):
                vat_val = _v("vat").upper().replace(" ", "")
                if vat_val:  # Only score if value exists
                    applicable += 1
                    if re.match(r'^FR[0-9A-Z]{11}$', vat_val):
                        passed += 1
                    else:
                        failed_rules.append("R04")
            if mapping.get("naf"):
                naf_val = _v("naf").replace(".", "")
                if naf_val:  # Only score if value exists
                    applicable += 1
                    if re.match(r'^[0-9]{4}[A-Za-z]$', naf_val):
                        passed += 1
                    else:
                        failed_rules.append("R06")
            if mapping.get("legal_form"):
                lf = _v("legal_form").strip()
                if lf:  # Only score if value exists
                    applicable += 1
                    passed += 1  # has value = pass
                else:
                    # Check if extractable from company name
                    company = _v("company_name")
                    if _extract_legal_form(company):
                        pass  # don't penalize, it's in the name
                    else:
                        applicable += 1
                        failed_rules.append("R07")
            for cr in custom_for_scoring:
                col = mapping.get(cr["field"])
                if not col or col not in row.index:
                    continue
                applicable += 1
                raw = _cell_str(row[col])
                rt = cr.get("rule_type", "regex")
                pat = cr.get("pattern", "")
                if rt == "not_empty":
                    ok = bool(raw.strip())
                elif rt == "regex":
                    ok = bool(re.search(pat, raw)) if pat else bool(raw.strip())
                elif rt == "in_list":
                    ok = raw.strip().upper() in [v.strip().upper() for v in pat.split(",")]
                elif rt == "length":
                    parts = pat.split(":")
                    mn = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0
                    mx = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 9999
                    ok = mn <= len(raw) <= mx
                else:
                    ok = True
                if ok:
                    passed += 1
                else:
                    failed_rules.append(cr["id"])
            score = round(passed / applicable * 100, 1) if applicable else 100.0
            row_scores.append({
                "Compte": _v("company_name")[:25] or _v("account_id") or str(row_num),
                "Score": score,
                "Passées": passed,
                "Total": applicable,
                "Échouées": ", ".join(failed_rules) if failed_rules else "—",
            })

        # Summary metrics
        avg_score = round(sum(s["Score"] for s in row_scores) / len(row_scores), 1) if row_scores else 0
        high_q = sum(1 for s in row_scores if s["Score"] >= 80)
        critical = sum(1 for s in row_scores if s["Score"] < 50)

        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            st.metric("Score moyen", f"{avg_score}%")
        with sc2:
            st.metric("Lignes fiables (≥80%)", f"{high_q}/{len(row_scores)}")
        with sc3:
            st.metric("Lignes critiques (<50%)", critical)

        # Per-row table
        score_df = pd.DataFrame(row_scores)
        if not score_df.empty:
            st.dataframe(
                score_df.style.map(
                    lambda v: f"background-color: {'#c6efce' if v >= 80 else ('#ffeb9c' if v >= 50 else '#ffc7ce')}"
                    if isinstance(v, (int, float)) and 0 <= v <= 100 else "",
                    subset=["Score"],
                ),
                use_container_width=True,
                hide_index=True,
            )

        # --- Preview cleaned data ---
        with st.expander("Aperçu des données nettoyées", expanded=False):
            st.dataframe(df_clean, use_container_width=True, hide_index=True)

        st.markdown("---")

        # --- Actions ---
        st.markdown("#### Actions")
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("Écrire sur Snowflake", type="primary", key="dc_write", use_container_width=True):
                st.session_state["dc_confirm_write"] = True
                st.rerun()
        with c2:
            if st.button("Recommencer", key="dc_restart", use_container_width=True):
                for k in ["dc_step", "dc_groups", "dc_merged_df", "dc_anomalies", "dc_stats", "dc_removed_count", "dc_run_id", "dc_confirm_write"]:
                    st.session_state.pop(k, None)
                st.rerun()
        with c3:
            if anomalies:
                if st.button("Voir dans Résolution", key="dc_to_resolution", use_container_width=True):
                    st.session_state["fr_upload_anomalies"] = anomalies
                    st.session_state["fr_upload_stats"] = stats
                    st.session_state["_goto_fr_resolution"] = True
                    st.session_state["_fr_active_tab"] = 4
                    st.rerun()

        # Double confirmation for write
        if st.session_state.get("dc_confirm_write"):
            st.error(f"Confirmer l'écriture de **{len(df_clean)} lignes** nettoyées sur `{table}` ? Cette action écrase la table.")
            wc1, wc2 = st.columns(2)
            with wc1:
                if st.button("Confirmer", type="primary", key="dc_confirm_yes"):
                    with st.spinner("Écriture sur Snowflake…"):
                        stage_dataframe_to_snowflake(df_clean, table)
                        load_dim_account.clear()
                        add_audit_entry("Écriture cleaning", f"{table}: {len(df_clean)} lignes, {removed_count} doublons supprimés")
                    st.session_state.pop("dc_confirm_write", None)
                    st.success("Données nettoyées écrites sur Snowflake.")
                    # Reset
                    for k in ["dc_step", "dc_groups", "dc_merged_df", "dc_anomalies", "dc_stats", "dc_removed_count"]:
                        st.session_state.pop(k, None)
                    st.rerun()
            with wc2:
                if st.button("Annuler", key="dc_confirm_no"):
                    st.session_state.pop("dc_confirm_write", None)
                    st.rerun()


def _fr_tab_dashboard():
    t = get_theme()
    accent = t['accent']
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:18px;">'
        f'<div style="width:3px;height:18px;border-radius:2px;background:{accent};"></div>'
        f'<div>'
        f'<div style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};">Tableau de bord France</div>'
        f'<div style="font-size:0.75rem;color:{t["text_secondary"]};">Conformité identifiants légaux & préparation e-facturation</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    _dim_accounts = load_dim_account(_dim_account_fqn())
    n = len(_dim_accounts) if _dim_accounts else 0
    # Compute from real DQ_FINDINGS
    _all_findings = get_all_fr_anomalies()
    _open_findings = [f for f in _all_findings if f["status"] in ("Open", "In Review")]
    _affected = len({f["account_id"] for f in _open_findings})
    total_analysed = n
    fr_score = round((n - _affected) / n * 100) if n else 0
    # E-invoicing ready = accounts without R01/R02/R03 failures
    _r123_fails = {f["account_id"] for f in _open_findings if f.get("rule_id") in ("R01", "R02", "R03")}
    einvoicing_ready = max(0, n - len(_r123_fails))
    source_label = "Calculé depuis DQ_FINDINGS"

    open_fr = len(_open_findings)
    st.markdown(
        '<div class="qx-kpi-grid">'
        + kpi_card("Score DQ France", f"{fr_score}%", source_label, "neutral")
        + kpi_card("EINVOICING_READY_COUNT", str(einvoicing_ready), f"sur {total_analysed} comptes FR", "neutral")
        + kpi_card("Anomalies ouvertes", str(open_fr), "SIREN / SIRET / TVA", "down")
        + kpi_card("Corrections", str(len(get_fr_corrections())), "DQ_CORRECTIONS", "neutral")
        + '</div>',
        unsafe_allow_html=True,
    )

    col_g, col_sla = st.columns([1, 1.4])
    with col_g:
        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=einvoicing_ready,
            title={"text": "Comptes prêts e-facturation", "font": {"size": 13, "color": t["text_secondary"]}},
            gauge={
                "axis": {"range": [0, total_analysed]},
                "bar": {"color": t["success"]},
                "steps": [{"range": [0, total_analysed], "color": "rgba(34,197,94,0.1)"}],
            },
            number={"suffix": f" / {total_analysed}", "font": {"size": 36, "color": t["text_primary"]}},
        ))
        fig = plotly_layout(fig, t, height=260)
        st.plotly_chart(fig, use_container_width=True)

    with col_sla:
        sla_rules = compute_fr_sla(_open_findings, total_analysed)
        computed_label = " (calculé)" if _open_findings else " (aucune analyse)"
        st.markdown(f"**SLA · Taux de conformité par règle{computed_label}**")
        for rule in sla_rules:
            color = t["success"] if rule["sla_pct"] >= 90 else t["medium"] if rule["sla_pct"] >= 75 else t["high"]
            st.markdown(
                f'<div style="margin-bottom:10px;">'
                f'<div style="display:flex;justify-content:space-between;font-size:0.85rem;margin-bottom:4px;">'
                f'<span><strong>{rule["id"]}</strong> · {html.escape(rule["name"])}</span>'
                f'<span style="color:{color};font-weight:600;">{rule["sla_pct"]}%</span></div>'
                f'<div style="background:var(--border);border-radius:4px;height:8px;overflow:hidden;">'
                f'<div style="width:{rule["sla_pct"]}%;background:{color};height:100%;"></div></div>'
                f'<div style="font-size:0.75rem;color:var(--text-secondary);margin-top:2px;">'
                f'{rule["ok"]}/{rule["total"]} conformes · {html.escape(rule["check"])}</div></div>',
                unsafe_allow_html=True,
            )

    if not _open_findings:
        st.info(
            "Lancez une analyse dans l'onglet **Source & Analyse** pour obtenir les SLA et le score calculés "
            "sur vos données réelles."
        )
    else:
        st.caption(
            "Validation INSEE SIRENE active · registre national 29.6M+ entreprises (Marketplace Snowflake)"
        )


def _fr_tab_resolution():
    t = get_theme()
    accent = t['accent']
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:18px;">'
        f'<div style="width:3px;height:18px;border-radius:2px;background:{accent};"></div>'
        f'<div>'
        f'<div style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};">Centre de résolution</div>'
        f'<div style="font-size:0.75rem;color:{t["text_secondary"]};">Anomalies SIREN / SIRET / TVA · écriture dans DQ_CORRECTIONS</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    open_anomalies = [a for a in get_all_fr_anomalies() if a["status"] in ("Open", "In Review")]
    if not open_anomalies:
        st.success("Aucune anomalie France en attente de résolution.")
    else:
        import_count = sum(1 for a in open_anomalies if a.get("source") == "import")
        if import_count:
            st.caption(f"{import_count} anomalie(s) provenant d'un import fichier · {len(open_anomalies)} au total")

        def _accept_one(aid):
            a = next((x for x in open_anomalies if x["id"] == aid), None)
            if a:
                fr_resolve_anomaly(aid, "Accepted", corrected_value=a.get("expected_value", ""))

        def _reject_one(aid, reason=""):
            fr_resolve_anomaly(aid, "Rejected", rejection_reason=reason or "Non applicable")

        _render_bulk_action_table(open_anomalies, _accept_one, _reject_one, key_prefix="fr_res")

        with st.expander("Détail individuel (correction manuelle)", expanded=False):
            for a in open_anomalies[:20]:
                source_badge = (
                    '<span class="qx-badge" style="background:rgba(59,130,246,0.15);color:var(--low);">Fichier</span> '
                    if a.get("source") == "import" else (
                    '<span class="qx-badge" style="background:rgba(34,197,94,0.15);color:var(--success);">Table</span> '
                    if a.get("source") == "snowflake" else "")
                )
                row_hint = f' · Ligne {a["row_num"]}' if a.get("row_num") else ""
                st.markdown(
                    f'<div class="qx-card">'
                    f'<div style="display:flex;justify-content:space-between;margin-bottom:10px;">'
                    f'<div>{severity_badge("HIGH" if a["rule_id"] in ("R01","R02","R03","R04","INSEE") else "MEDIUM")} '
                    f'{source_badge}'
                    f'<span class="qx-badge" style="background:var(--accent-soft);color:var(--accent);">{html.escape(a["rule_id"])}</span> '
                    f'<strong>{html.escape(a["company_name"])}</strong> '
                    f'<span style="color:var(--text-secondary);">· {html.escape(a["account_id"])}{row_hint}</span></div>'
                    f'<span style="color:var(--text-secondary);font-size:0.8rem;">{html.escape(a["id"])}</span></div>'
                    f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:0.9rem;">'
                    f'<div style="background:rgba(239,68,68,0.06);padding:10px;border-radius:6px;border:1px solid var(--border);">'
                    f'<div style="font-size:0.75rem;color:var(--text-secondary);">FIELD_VALUE · {html.escape(a["field_label"])}</div>'
                    f'<div style="font-weight:600;margin-top:4px;">{html.escape(a["field_value"]) or "—"}</div></div>'
                    f'<div style="background:rgba(34,197,94,0.06);padding:10px;border-radius:6px;border:1px solid var(--border);">'
                    f'<div style="font-size:0.75rem;color:var(--text-secondary);">EXPECTED_VALUE</div>'
                    f'<div style="font-weight:600;margin-top:4px;">{html.escape(a["expected_value"])}</div></div>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Accepter & corriger", key=f"fr_acc_{a['id']}", type="primary", use_container_width=True):
                        st.session_state[f"fr_show_accept_{a['id']}"] = True
                with c2:
                    if st.button("Rejeter", key=f"fr_rej_{a['id']}", use_container_width=True):
                        st.session_state[f"fr_show_reject_{a['id']}"] = True

                if st.session_state.get(f"fr_show_accept_{a['id']}"):
                    corrected_value = st.text_input(
                        "Nouvelle valeur",
                        value=a.get("expected_value", ""),
                        key=f"fr_corrected_val_{a['id']}",
                    )
                    if st.button("Confirmer — écrire sur Snowflake", key=f"fr_confirm_acc_{a['id']}", type="primary"):
                        fr_resolve_anomaly(a["id"], "Accepted", corrected_value=corrected_value)
                        st.session_state.pop(f"fr_show_accept_{a['id']}", None)
                        st.rerun()

                if st.session_state.get(f"fr_show_reject_{a['id']}"):
                    reason = st.text_input("Motif", key=f"fr_reason_{a['id']}")
                    if st.button("Confirmer rejet", key=f"fr_confirm_rej_{a['id']}", type="primary"):
                        fr_resolve_anomaly(a["id"], "Rejected", rejection_reason=reason or "Non applicable")
                        st.session_state.pop(f"fr_show_reject_{a['id']}", None)
                        st.rerun()
                st.markdown("---")

    st.markdown("---")
    st.markdown("##### Enrichissement INSEE SIRENE")
    st.caption("Enrichissez vos données avec le registre national (29M+ entreprises)")
    _render_enrichment_ui()

    with st.expander("Recherche SIRENE"):
        _render_insee_lookup()


def _fr_tab_audit_export():
    t = get_theme()
    accent = t['accent']
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:18px;">'
        f'<div style="width:3px;height:18px;border-radius:2px;background:{accent};"></div>'
        f'<div>'
        f'<div style="font-size:0.92rem;font-weight:700;color:{t["text_primary"]};">Audit & Export</div>'
        f'<div style="font-size:0.75rem;color:{t["text_secondary"]};">Corrections acceptées · rapport e-facturation</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    corrections = get_fr_corrections()
    accepted = [c for c in corrections if c["status"] == "Accepted"]

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**CSV UPDATE · corrections CRM**")
        if accepted:
            df_corr = pd.DataFrame([{
                "ACCOUNT_ID": c["account_id"],
                "FIELD": c["field"],
                "OLD_VALUE": c["field_value"],
                "NEW_VALUE": c["expected_value"],
                "RULE_ID": c["rule_id"],
                "CORRECTION_STATUS": "READY_FOR_CRM",
            } for c in accepted])
            st.dataframe(df_corr, use_container_width=True, hide_index=True)
            st.download_button(
                "Télécharger UPDATE corrections",
                df_corr.to_csv(index=False),
                file_name="fr_update_corrections.csv",
                mime="text/csv",
                key="fr_dl_update",
            )
        else:
            st.caption("Aucune correction acceptée pour l'instant — utilisez le centre de résolution.")

    with col2:
        st.markdown("**Rapport HTML · e-facturation**")
        _fr_anom = get_all_fr_anomalies()
        _total = len(load_dim_account(_dim_account_fqn())) or 1
        _sla_rules = compute_fr_sla(_fr_anom, _total)
        _einvoicing = 0
        for r in _sla_rules:
            if r.get("rule_id") == "R08":
                _einvoicing = r.get("ok_count", 0)
                break
        _score = round((1 - len(_fr_anom) / max(_total * 7, 1)) * 100, 1)
        html_report = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><title>Rapport Léon FR</title></head>
<body style="font-family:sans-serif;padding:2rem;">
<h1>Rapport conformité France</h1>
<p>Généré le {_now().strftime("%d/%m/%Y %H:%M")}</p>
<ul>
<li>Score DQ France : <strong>{_score}%</strong></li>
<li>EINVOICING_READY_COUNT : <strong>{_einvoicing}</strong> / {_total}</li>
<li>Corrections acceptées : <strong>{len(accepted)}</strong></li>
<li>Corrections rejetées : <strong>{len(corrections) - len(accepted)}</strong></li>
</ul>
<h2>SLA règles R01–R08</h2>
<ul>
{"".join(f'<li>{r["id"]} {r["name"]} : {r["sla_pct"]}% ({r["ok"]}/{r["total"]} conformes)</li>' for r in _sla_rules)}
</ul>
</body></html>"""
        st.download_button(
            "Télécharger rapport HTML",
            html_report,
            file_name="rapport_conformite_fr.html",
            mime="text/html",
            key="fr_dl_html",
        )
        card(
            f'<strong>Aperçu</strong><br>'
            f'EINVOICING_READY_COUNT · <strong>{_einvoicing}</strong> / {_total} comptes<br>'
            f'Score DQ · <strong>{_score}%</strong>'
        )

    if corrections:
        st.markdown("**Historique DQ_CORRECTIONS**")
        hist = pd.DataFrame([{
            "ID": c["id"],
            "Anomalie": c["anomaly_id"],
            "Compte": c["account_id"],
            "Champ": c["field"],
            "Action": "Acceptée" if c["status"] == "Accepted" else "Rejetée",
            "Motif rejet": c["rejection_reason"] or "—",
            "Horodatage": c["timestamp"],
        } for c in corrections])
        st.dataframe(hist, use_container_width=True, hide_index=True)

    # Export certifié INSEE
    if st.button("Exporter avec statut INSEE vérifié", key="fr_export_insee"):
        _accounts = load_dim_account(_dim_account_fqn())
        if _accounts:
            export_df = pd.DataFrame(_accounts)
            sirene_cache = load_sirene_cache()
            export_df["statut_sirene"] = export_df["siren"].apply(
                lambda s: sirene_cache.get(str(s), {}).get("statut", "Inconnu") if s else "Inconnu"
            )
            export_df["statut_sirene"] = export_df["statut_sirene"].map(
                {"A": "Active", "C": "Radiée"}).fillna(export_df["statut_sirene"])
            export_df["date_verification_insee"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
            csv_data = export_df.to_csv(index=False, sep=";")
            st.download_button(
                "Télécharger CSV (INSEE vérifié)",
                csv_data,
                file_name="export_insee_verifie.csv",
                mime="text/csv",
            )


def page_france():
    page_header(
        "France · Conformité & E-Facturation",
        "Module dédié SIREN, SIRET, TVA intracom et préparation facturation électronique PDP.",
        badges=["R01–R08", "INSEE 29M+", "E-invoicing"],
    )

    # If redirected to resolution, set the active tab
    _fr_tab_names = [
        "Source & Analyse",
        "Règles métier",
        "Data Cleaning",
        "Tableau de bord",
        "Centre de résolution",
        "Audit & Export",
    ]
    _default_tab = 0
    if st.session_state.pop("_goto_fr_resolution", False):
        _default_tab = 4  # Centre de résolution

    if "_fr_active_tab" not in st.session_state:
        st.session_state["_fr_active_tab"] = _default_tab
    elif _default_tab == 4:
        st.session_state["_fr_active_tab"] = 4

    _selected_tab = st.radio(
        "Section", _fr_tab_names,
        index=st.session_state["_fr_active_tab"],
        horizontal=True, label_visibility="collapsed",
        key="_fr_tab_radio",
    )
    st.session_state["_fr_active_tab"] = _fr_tab_names.index(_selected_tab)

    if _selected_tab == "Source & Analyse":
        _fr_tab_source_analyse()
    elif _selected_tab == "Règles métier":
        _fr_tab_custom_rules()
    elif _selected_tab == "Data Cleaning":
        _fr_tab_data_cleaning()
    elif _selected_tab == "Tableau de bord":
        _fr_tab_dashboard()
    elif _selected_tab == "Centre de résolution":
        _fr_tab_resolution()
    elif _selected_tab == "Audit & Export":
        _fr_tab_audit_export()


def page_rule_catalog():
    page_header("Catalogue de règles", "Modèles prêts à l'emploi pour la qualité des données B2B françaises.")

    cols = st.columns(2)
    for i, rule in enumerate(RULE_TEMPLATES):
        with cols[i % 2]:
            card(
                f'<div style="display:flex;justify-content:space-between;">'
                f'<strong style="font-size:1.1rem;">{html.escape(rule["id"])}</strong>'
                f'</div>'
                f'<div style="margin:8px 0;font-weight:600;">{html.escape(rule["name"])}</div>'
                f'<div style="color:var(--text-secondary);font-size:0.9rem;">{html.escape(rule["description"])}</div>'
                f'<div style="margin-top:10px;">'
                f'<span class="qx-badge" style="background:var(--accent-soft);color:var(--accent);">'
                f'{html.escape(subject_label(rule["subject"]))}</span></div>'
            )

    st.markdown("---")

    # --- Custom rules section (from France tab) ---
    _fr_tab_custom_rules()


# ---------------------------------------------------------------------------
# Floating Chatbox: Ask AI (Cortex Analyst)
# ---------------------------------------------------------------------------

SEMANTIC_VIEW_FQN = "QUALITY_TEST.DATA_QUALITY.SV_QUALITIX"


def _call_cortex_analyst(messages: list[dict]) -> dict:
    """Call Cortex Analyst REST API via the Snowflake connector's session."""
    conn = _get_conn()
    if conn is None:
        return {"error": "Not connected to Snowflake"}
    token = conn.rest.token
    # Build the correct host: account with underscores → hyphens for DNS
    account = conn.account or st.secrets.get("connections", {}).get("snowflake", {}).get("account", "")
    host = account.replace("_", "-") + ".snowflakecomputing.com"
    port = 443
    scheme = "https"
    url = f"{scheme}://{host}:{port}/api/v2/cortex/analyst/message"
    headers = {
        "Authorization": f'Snowflake Token="{token}"',
        "Content-Type": "application/json",
    }
    body = {
        "messages": messages,
        "semantic_view": SEMANTIC_VIEW_FQN,
    }
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=60)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    except Exception as e:
        return {"error": str(e)}


def _render_chat_panel():
    """Render the right-side AI chat panel (modern floating style)."""
    t = get_theme()

    if "analyst_history" not in st.session_state:
        st.session_state["analyst_history"] = []

    # Panel wrapper with clean styling
    st.markdown(
        f"""<div style="background:{t['card_bg']};border:1px solid {t['border']};border-radius:14px;
        padding:16px 18px;margin-bottom:8px;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">
            <div style="display:flex;align-items:center;gap:8px;">
                <div style="width:28px;height:28px;border-radius:8px;background:{t['accent']};
                    display:flex;align-items:center;justify-content:center;color:#fff;font-size:0.7rem;font-weight:700;">AI</div>
                <div>
                    <div style="font-weight:700;color:{t['text_primary']};font-size:0.85rem;">Cortex Analyst</div>
                    <div style="font-size:0.65rem;color:{t['text_secondary']};">Text-to-SQL</div>
                </div>
            </div>
            <div style="font-size:0.6rem;padding:3px 8px;background:{t['border_subtle']};border-radius:4px;color:{t['text_secondary']};">BETA</div>
        </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # Close button — subtle
    if st.button("✕ Fermer", key="close_chat_panel"):
        st.session_state["chatbox_open"] = False
        st.rerun()

    # Suggestions (only if no history)
    if not st.session_state["analyst_history"]:
        suggestions = ["Combien d'anomalies au total ?", "Quelles entreprises sont les plus impactées ?", "Anomalies critiques ouvertes ?"]
        for i, s in enumerate(suggestions):
            if st.button(s, key=f"chatbox_sug_{i}", use_container_width=True):
                st.session_state["chatbox_pending"] = s
                st.rerun()

    # Chat history
    chat_container = st.container(height=350)
    with chat_container:
        for entry in st.session_state["analyst_history"]:
            # User message
            st.markdown(
                f'<div style="background:{t["border_subtle"]};border-radius:10px;padding:10px 14px;margin:8px 0;'
                f'font-size:0.82rem;color:{t["text_primary"]};">{html.escape(entry["question"])}</div>',
                unsafe_allow_html=True,
            )
            # Assistant response
            if entry.get("text"):
                st.markdown(
                    f'<div style="border-left:3px solid {t["accent"]};padding:8px 14px;margin:8px 0;'
                    f'font-size:0.82rem;color:{t["text_primary"]};background:{t["accent_soft"]};border-radius:0 8px 8px 0;">'
                    f'{html.escape(entry["text"])}</div>',
                    unsafe_allow_html=True,
                )
            if entry.get("sql"):
                with st.expander("SQL", expanded=False):
                    st.code(entry["sql"], language="sql")
            if entry.get("dataframe") is not None and not entry["dataframe"].empty:
                st.dataframe(entry["dataframe"], use_container_width=True, height=120)
            if entry.get("error"):
                st.error(entry["error"])

    # Clear history
    if st.session_state["analyst_history"]:
        if st.button("Effacer", key="clear_chat"):
            st.session_state["analyst_history"] = []
            st.rerun()

    # Input
    pending = st.session_state.pop("chatbox_pending", None)
    user_input = st.text_input(
        "Question",
        value=pending or "",
        key="chatbox_text_input",
        placeholder="Posez votre question...",
        label_visibility="collapsed",
    )
    send_clicked = st.button("Envoyer", key="chatbox_send", use_container_width=True, type="primary")
    question = user_input.strip() if send_clicked and user_input.strip() else None
    if pending and not question:
        question = pending

    if question:
        api_messages = []
        for h in st.session_state["analyst_history"]:
            api_messages.append({
                "role": "user",
                "content": [{"type": "text", "text": h["question"]}],
            })
            analyst_content = []
            if h.get("text"):
                analyst_content.append({"type": "text", "text": h["text"]})
            if h.get("sql"):
                analyst_content.append({"type": "sql", "statement": h["sql"]})
            if analyst_content:
                api_messages.append({"role": "analyst", "content": analyst_content})
        api_messages.append({
            "role": "user",
            "content": [{"type": "text", "text": question}],
        })

        with st.spinner("Cortex Analyst..."):
            result = _call_cortex_analyst(api_messages)

        entry = {"question": question, "text": None, "sql": None, "dataframe": None, "error": None}

        if "error" in result:
            entry["error"] = result["error"]
        else:
            message = result.get("message", {})
            for content_block in message.get("content", []):
                ctype = content_block.get("type")
                if ctype == "text":
                    entry["text"] = content_block.get("text", "")
                elif ctype == "sql":
                    sql = content_block.get("statement", "")
                    entry["sql"] = sql
                    df = _sf_query(sql)
                    if not df.empty:
                        entry["dataframe"] = df
                elif ctype == "suggestions":
                    sugs = content_block.get("suggestions", [])
                    if sugs:
                        entry["text"] = "Suggestions : " + " | ".join(sugs)

        st.session_state["analyst_history"].append(entry)
        st.rerun()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def page_login():
    from i18n import t, get_lang

    theme_key = st.session_state.get("theme", "light")
    is_dark = theme_key == "dark"
    tk = THEMES[theme_key]

    # --- Login page CSS ---
    bg = "#0c1322" if is_dark else "#f8fafc"
    card_bg = "#1e293b" if is_dark else "#ffffff"
    border_c = "#334155" if is_dark else "#e2e8f0"
    text_h = "#f1f5f9" if is_dark else "#0f172a"
    text_p = "#94a3b8" if is_dark else "#64748b"
    accent = "#2dd4bf" if is_dark else "#0d9488"
    input_bg = "#0f172a" if is_dark else "#ffffff"
    input_border = "#475569" if is_dark else "#e2e8f0"
    input_text = "#f1f5f9" if is_dark else "#0f172a"

    st.markdown(f"""<style>
    [data-testid="stAppViewContainer"] {{ background: {bg} !important; }}
    [data-testid="stHeader"] {{ background: transparent !important; }}
    [data-testid="stSidebar"] {{ display: none !important; }}
    [data-testid="stMainBlockContainer"] {{ padding-top: 0.5rem !important; max-width: 100% !important; }}
    .login-form-card {{
        background: {card_bg}; border: 1px solid {border_c};
        border-radius: 16px; padding: 2rem 2rem 1.5rem;
    }}
    .login-form-card label, .login-form-card p,
    .login-form-card [data-testid="stWidgetLabel"] p,
    .login-form-card [data-testid="stWidgetLabel"] span {{
        color: {text_h} !important;
    }}
    .login-form-card input {{
        background: {input_bg} !important; color: {input_text} !important;
        border: 1px solid {input_border} !important; border-radius: 8px !important;
        -webkit-text-fill-color: {input_text} !important;
    }}
    .login-form-card input::placeholder {{ color: {text_p} !important; opacity: 0.7; }}
    .login-form-card [data-testid="stFormSubmitButton"] button {{
        background: {accent} !important;
        color: #fff !important; font-weight: 600 !important;
        border: none !important; border-radius: 10px !important; padding: 0.7rem !important;
        box-shadow: 0 4px 14px rgba(3,105,161,0.3) !important;
        font-size: 0.92rem !important;
    }}
    .login-form-card [data-testid="stFormSubmitButton"] button:hover {{
        background: #075985 !important;
    }}
    [data-testid="stMainBlockContainer"] label,
    [data-testid="stMainBlockContainer"] [data-testid="stWidgetLabel"] p,
    [data-testid="stMainBlockContainer"] [data-testid="stWidgetLabel"] span {{
        color: {text_h} !important;
    }}
    [data-testid="stRadio"] label, [data-testid="stRadio"] p {{
        color: {text_h} !important;
    }}
    [data-testid="stSelectbox"] label, [data-testid="stSelectbox"] p {{
        color: {text_h} !important;
    }}
    .login-footer {{
        text-align: center; margin-top: 1.5rem; font-size: 0.72rem; color: {text_p};
    }}
    </style>""", unsafe_allow_html=True)

    # --- Top bar: Language + Appearance ---
    _, col_lang, col_theme = st.columns([5, 1, 1])
    with col_lang:
        lang_opts = ["FR Fr...", "GB English"]
        lang_default = 0 if get_lang() == "fr" else 1
        lang_sel = st.selectbox(
            t("prefs.language"), lang_opts, index=lang_default, key="login_lang_sel",
            label_visibility="visible",
        )
        new_lang = "fr" if "FR" in lang_sel else "en"
        if new_lang != st.session_state.get("lang", "fr"):
            st.session_state["lang"] = new_lang
            st.rerun()
    with col_theme:
        theme_opts = [f"{'☀️' if not is_dark else '🌙'} S..."] if is_dark else [f"{'☀️'} L..."]
        theme_opts = ["🌙 Sombre", "☀️ Clair"] if get_lang() == "fr" else ["🌙 Dark", "☀️ Light"]
        theme_default = 0 if is_dark else 1
        theme_sel = st.selectbox(
            t("prefs.theme"), theme_opts, index=theme_default, key="login_theme_sel",
            label_visibility="visible",
        )
        new_theme = "dark" if "ombre" in theme_sel.lower() or "dark" in theme_sel.lower() else "light"
        if new_theme != st.session_state.get("theme", "light"):
            st.session_state["theme"] = new_theme
            st.rerun()

    st.markdown("<div style='height:0.5rem;'></div>", unsafe_allow_html=True)

    # --- Main 2-column layout ---
    col_hero, col_form = st.columns([1.1, 0.9], gap="large")

    # --- LEFT: Hero branding ---
    with col_hero:
        hero_accent = "#5eead4" if is_dark else "#0d9488"
        hero_text = "#ffffff" if is_dark else "#0f172a"
        hero_sub = "rgba(203,213,225,0.7)" if is_dark else "#64748b"
        hero_bg = "transparent"
        step_bg = card_bg
        step_border = border_c
        step_accent = accent
        tag_bg = f"{'rgba(2,132,199,0.08)' if is_dark else 'rgba(3,105,161,0.06)'}"
        tag_border = f"{'rgba(2,132,199,0.2)' if is_dark else 'rgba(3,105,161,0.15)'}"
        tag_color = accent

        hero_html = f"""
        <div style="padding:1.5rem 0 1rem 0.5rem;font-family:'Inter','Segoe UI',sans-serif;">
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:1.8rem;">
                <div style="width:42px;height:42px;border-radius:50%;background:{accent};
                    display:flex;align-items:center;justify-content:center;
                    box-shadow:0 2px 10px rgba(13,148,136,0.3);"><svg viewBox="0 0 64 64" width="26" height="26" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="32" cy="38" r="18" stroke="#fff" stroke-width="2.5" fill="none"/><path d="M22 56c0-6 4.5-10 10-10s10 4 10 10" stroke="#fff" stroke-width="2.5" stroke-linecap="round" fill="none"/><ellipse cx="32" cy="24" rx="14" ry="4" stroke="#fff" stroke-width="2.5" fill="none"/><path d="M18 24c0-8 6-14 14-14s14 6 14 14" stroke="#fff" stroke-width="2.5" fill="none"/><circle cx="32" cy="14" r="4" stroke="#fff" stroke-width="2.5" fill="none"/><circle cx="26" cy="36" r="5" stroke="#fff" stroke-width="2.2" fill="none"/><circle cx="38" cy="36" r="5" stroke="#fff" stroke-width="2.2" fill="none"/><line x1="31" y1="36" x2="33" y2="36" stroke="#fff" stroke-width="2"/><path d="M28 44c2 2 4 2 6 0" stroke="#fff" stroke-width="2" stroke-linecap="round" fill="none"/><path d="M36 33l38 37" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><path d="M54 20l2-6 2 6-6 2 6 2-2 6-2-6 6-2z" fill="#fff"/></svg></div>
                <div>
                    <div style="font-size:1.15rem;font-weight:800;color:{hero_text};letter-spacing:-0.5px;">
                        {t('app.brand')}</div>
                    <div style="font-size:0.6rem;letter-spacing:0.18em;color:{text_p};text-transform:uppercase;margin-top:1px;">
                        {t('app.tagline')}</div>
                </div>
            </div>
            <div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;
                color:{accent};margin-bottom:0.6rem;">{t('login.eyebrow')}</div>
            <div style="width:32px;height:3px;background:{accent};border-radius:2px;margin-bottom:1.5rem;"></div>
            <div style="font-size:2.2rem;font-weight:800;color:{hero_text};line-height:1.15;
                letter-spacing:-1px;margin-bottom:1rem;">
                {t('login.headline')}<br>
                <span style="color:{hero_accent};font-style:italic;">{t('login.headline_em')}</span>
            </div>
            <div style="font-size:0.85rem;color:{hero_sub};line-height:1.7;max-width:440px;margin-bottom:2rem;">
                {t('login.lead')}
            </div>
            <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:1.8rem;">
                <div style="background:{step_bg};border:1px solid {step_border};border-radius:10px;padding:12px 18px;min-width:110px;">
                    <div style="font-size:0.62rem;font-weight:700;color:{step_accent};">01</div>
                    <div style="font-size:0.82rem;font-weight:600;color:{hero_text};margin-top:2px;">{t('login.step.ingest')}</div>
                </div>
                <div style="background:{step_bg};border:1px solid {step_border};border-radius:10px;padding:12px 18px;min-width:110px;">
                    <div style="font-size:0.62rem;font-weight:700;color:{step_accent};">02</div>
                    <div style="font-size:0.82rem;font-weight:600;color:{hero_text};margin-top:2px;">{t('login.step.control')}</div>
                </div>
                <div style="background:{step_bg};border:1px solid {step_border};border-radius:10px;padding:12px 18px;min-width:110px;">
                    <div style="font-size:0.62rem;font-weight:700;color:{step_accent};">03</div>
                    <div style="font-size:0.82rem;font-weight:600;color:{hero_text};margin-top:2px;">{t('login.step.fix')}</div>
                </div>
                <div style="background:{step_bg};border:1px solid {step_border};border-radius:10px;padding:12px 18px;min-width:110px;">
                    <div style="font-size:0.62rem;font-weight:700;color:{step_accent};">04</div>
                    <div style="font-size:0.82rem;font-weight:600;color:{hero_text};margin-top:2px;">{t('login.step.audit')}</div>
                </div>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
                <span style="background:{tag_bg};border:1px solid {tag_border};color:{tag_color};
                    padding:4px 12px;border-radius:20px;font-size:0.68rem;font-weight:500;">Snowflake Native</span>
                <span style="background:{tag_bg};border:1px solid {tag_border};color:{tag_color};
                    padding:4px 12px;border-radius:20px;font-size:0.68rem;font-weight:500;">INSEE SIRENE 29M+</span>
                <span style="background:{tag_bg};border:1px solid {tag_border};color:{tag_color};
                    padding:4px 12px;border-radius:20px;font-size:0.68rem;font-weight:500;">E-facturation R01-R08</span>
                <span style="background:{tag_bg};border:1px solid {tag_border};color:{tag_color};
                    padding:4px 12px;border-radius:20px;font-size:0.68rem;font-weight:500;">Cortex Analyst</span>
            </div>
        </div>
        """
        st.markdown(hero_html, unsafe_allow_html=True)

    # --- RIGHT: Login form ---
    with col_form:
        # Demo badge
        badge_bg = "rgba(2,132,199,0.08)" if is_dark else "rgba(3,105,161,0.06)"
        badge_border = "rgba(2,132,199,0.3)" if is_dark else "rgba(3,105,161,0.2)"
        st.markdown(
            f'<div style="display:inline-flex;align-items:center;gap:6px;padding:5px 14px;'
            f'background:{badge_bg};border:1px solid {badge_border};border-radius:20px;'
            f'font-size:0.68rem;font-weight:600;color:{accent};text-transform:uppercase;'
            f'letter-spacing:0.08em;margin-bottom:1rem;">'
            f'<span style="width:7px;height:7px;border-radius:50%;background:{accent};"></span>'
            f' {t("login.badge.demo")}</div>',
            unsafe_allow_html=True,
        )

        # Dynamic subtitle from session defaults
        _sub_user = st.session_state.get("sf_user", "SNOWADMIN")
        _sub_acct = st.session_state.get("sf_account", "SFSEEUROPE-TEST_DEMO_ACCOUNT_AS")
        st.markdown(
            f'<div style="font-size:1.05rem;font-weight:700;color:{text_h};margin-bottom:2px;">'
            f'{t("login.form.title")}</div>'
            f'<div style="font-size:0.78rem;color:{text_p};margin-bottom:0.8rem;">'
            f'{_sub_user} · {_sub_acct}</div>',
            unsafe_allow_html=True,
        )

        # Auth method toggle
        st.markdown(
            f'<p style="font-size:0.75rem;font-weight:600;color:{text_h};margin-bottom:0.4rem;">'
            f'{t("login.auth.label")}</p>',
            unsafe_allow_html=True,
        )
        auth_options = [t("login.auth.password"), t("login.auth.sso")]
        auth_choice = st.radio(
            t("login.auth.label"), auth_options, index=0,
            horizontal=True, key="login_auth_method", label_visibility="collapsed",
        )
        use_sso = auth_choice == t("login.auth.sso")

        with st.form("sf_login_form"):
            account = st.text_input(
                t("login.field.account"),
                value=st.session_state.get("sf_account", "SFSEEUROPE-TEST_DEMO_ACCOUNT_AS"),
                placeholder="orgname-accountname",
            )
            user = st.text_input(
                t("login.field.user"),
                value=st.session_state.get("sf_user", "SNOWADMIN"),
                placeholder="SNOWFLAKE_USER",
            )
            if not use_sso:
                password = st.text_input(
                    t("login.field.password"), type="password", placeholder="••••••••",
                )
            else:
                password = ""
            c1, c2 = st.columns(2)
            with c1:
                passcode = st.text_input(
                    t("login.field.mfa"), placeholder=t("login.field.mfa_placeholder"),
                )
            with c2:
                warehouse = st.text_input(
                    t("login.field.warehouse"),
                    value=st.session_state.get("sf_warehouse", "COMPUTE_WH"),
                    placeholder="COMPUTE_WH",
                )
            submitted = st.form_submit_button(
                t("login.submit"),
                type="primary", use_container_width=True,
            )

    # Footer
    st.markdown(
        f'<p style="text-align:center;font-size:0.72rem;color:{text_p};margin-top:1.5rem;">'
        f'{t("login.caption")}</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="login-footer">{t("app.footer")}</div>',
        unsafe_allow_html=True,
    )

    if submitted:
        if not account.strip() or not user.strip():
            st.error(t("login.error.missing_fields"))
        elif not password and not use_sso:
            st.error(t("login.error.missing_password"))
        else:
            with st.spinner(t("login.spinner")):
                try:
                    _build_conn.clear()
                    authenticator = "externalbrowser" if use_sso else ""
                    conn = _build_conn(
                        account.strip(), user.strip(), password,
                        warehouse.strip() or "COMPUTE_WH", passcode.strip(), authenticator,
                    )
                    conn.cursor().execute("SELECT 1")
                    # Detect current database & schema from the connection
                    try:
                        cur = conn.cursor()
                        cur.execute("SELECT CURRENT_DATABASE(), CURRENT_SCHEMA()")
                        row = cur.fetchone()
                        if row:
                            if row[0]:
                                st.session_state["sf_database"] = row[0]
                            if row[1]:
                                st.session_state["sf_schema"] = row[1]
                    except Exception:
                        pass
                    st.session_state["sf_account"] = account.strip()
                    st.session_state["sf_user"] = user.strip()
                    st.session_state["sf_password"] = password
                    st.session_state["sf_passcode"] = passcode.strip()
                    st.session_state["sf_warehouse"] = warehouse.strip() or "COMPUTE_WH"
                    st.session_state["sf_authenticator"] = authenticator
                    st.session_state["authenticated"] = True
                    load_dq_findings.clear()
                    load_dim_account.clear()
                    st.rerun()
                except Exception as exc:
                    st.error(t("login.error.failed", error=str(exc)))


PAGE_RENDERERS = {
    "dashboard": page_dashboard,
    "customer_data": page_customer_data,
    "run_analysis": page_run_analysis,
    "findings": page_findings,
    "tasks": page_tasks,
    "exports": page_exports,
    # "france": page_france,
    "rule_catalog": page_rule_catalog,
}


def main():
    st.set_page_config(
        page_title="Léon — Qualité des données",
        page_icon="L",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    if "theme" not in st.session_state:
        st.session_state["theme"] = "light"
    if "page" not in st.session_state:
        st.session_state["page"] = "dashboard"

    inject_css()

    if not st.session_state.get("authenticated"):
        page_login()
        return

    init_session_data()
    render_sidebar()

    # Layout: if chatbox open -> page | chat panel side-by-side
    if "chatbox_open" not in st.session_state:
        st.session_state["chatbox_open"] = False

    if st.session_state["chatbox_open"]:
        col_page, col_chat = st.columns([3, 1.2])
        with col_page:
            renderer = PAGE_RENDERERS.get(st.session_state["page"], page_dashboard)
            renderer()
        with col_chat:
            _render_chat_panel()
    else:
        renderer = PAGE_RENDERERS.get(st.session_state["page"], page_dashboard)
        renderer()


if __name__ == "__main__":
    main()