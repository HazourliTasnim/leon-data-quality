-- =============================================================================
-- Qualitix — Backend Snowflake Setup
-- Crée uniquement l'infrastructure DQ (DIM_ACCOUNT = source existante)
-- Exécuter dans Snowflake Worksheets → Run All
-- =============================================================================

USE DATABASE QUALITY_TEST;

-- Schémas (si pas encore créés)
CREATE SCHEMA IF NOT EXISTS QUALITY_TEST.COMMERCIAL_DATA;
CREATE SCHEMA IF NOT EXISTS QUALITY_TEST.DATA_QUALITY;


-- Table des anomalies détectées
CREATE TABLE IF NOT EXISTS QUALITY_TEST.DATA_QUALITY.DQ_FINDINGS (
    id              VARCHAR(50)   NOT NULL PRIMARY KEY,
    account_id      VARCHAR(50),
    company_name    VARCHAR(255),
    severity        VARCHAR(10),
    status          VARCHAR(20)   DEFAULT 'Open',
    subject         VARCHAR(50),
    rule_id         VARCHAR(10),
    field           VARCHAR(100),
    field_label     VARCHAR(100),
    field_value     VARCHAR(500),
    expected_value  VARCHAR(500),
    finding_type    VARCHAR(255),
    description     VARCHAR(1000),
    created_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Table des corrections (acceptées / rejetées)
CREATE TABLE IF NOT EXISTS QUALITY_TEST.DATA_QUALITY.DQ_CORRECTIONS (
    id                  VARCHAR(50)   NOT NULL PRIMARY KEY,
    anomaly_id          VARCHAR(50),
    account_id          VARCHAR(50),
    company_name        VARCHAR(255),
    field               VARCHAR(100),
    field_value         VARCHAR(500),
    expected_value      VARCHAR(500),
    rule_id             VARCHAR(10),
    action              VARCHAR(20),
    rejection_reason    VARCHAR(500),
    correction_status   VARCHAR(50),
    created_at          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Journal d'audit
CREATE TABLE IF NOT EXISTS QUALITY_TEST.DATA_QUALITY.DQ_AUDIT_LOG (
    id          NUMBER        AUTOINCREMENT PRIMARY KEY,
    action      VARCHAR(255),
    detail      VARCHAR(1000),
    user_name   VARCHAR(255),
    created_at  TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Cache SIRENE (référentiel INSEE)
CREATE TABLE IF NOT EXISTS QUALITY_TEST.COMMERCIAL_DATA.DIM_SIRENE (
    siren           VARCHAR(9)    NOT NULL PRIMARY KEY,
    raison_sociale  VARCHAR(255),
    siret           VARCHAR(14),
    naf             VARCHAR(10),
    adresse         VARCHAR(500),
    statut          VARCHAR(20)   DEFAULT 'Actif',
    updated_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);


-- Règles métier personnalisées (persistées)
CREATE TABLE IF NOT EXISTS QUALITY_TEST.DATA_QUALITY.DQ_CUSTOM_RULES (
    id              VARCHAR(20)   NOT NULL PRIMARY KEY,
    name            VARCHAR(255)  NOT NULL,
    description     VARCHAR(1000),
    target_field    VARCHAR(100)  NOT NULL,
    rule_type       VARCHAR(20)   DEFAULT 'regex',
    pattern         VARCHAR(500),
    severity        VARCHAR(10)   DEFAULT 'MEDIUM',
    is_active       BOOLEAN       DEFAULT TRUE,
    created_by      VARCHAR(255)  DEFAULT CURRENT_USER(),
    created_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Résultats de dédoublonnage (audit)
CREATE TABLE IF NOT EXISTS QUALITY_TEST.DATA_QUALITY.DQ_DEDUP_RESULTS (
    id              NUMBER        AUTOINCREMENT PRIMARY KEY,
    run_id          VARCHAR(50)   NOT NULL,
    source_table    VARCHAR(255),
    original_count  NUMBER,
    clean_count     NUMBER,
    removed_count   NUMBER,
    dedup_keys      VARCHAR(500),
    strategy        VARCHAR(50),
    fuzzy_threshold NUMBER(3,2),
    created_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Scoring qualité par ligne
CREATE TABLE IF NOT EXISTS QUALITY_TEST.DATA_QUALITY.DQ_SCORING (
    id              NUMBER        AUTOINCREMENT PRIMARY KEY,
    run_id          VARCHAR(50)   NOT NULL,
    account_id      VARCHAR(50),
    row_num         NUMBER,
    score           NUMBER(5,2),
    rules_passed    NUMBER,
    rules_total     NUMBER,
    flags           VARCHAR(2000),
    created_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);


-- =============================================================================
-- Stored procedure : exécute R01-R07 sur DIM_ACCOUNT et écrit dans DQ_FINDINGS
-- =============================================================================

CREATE OR REPLACE PROCEDURE QUALITY_TEST.DATA_QUALITY.SP_EXECUTE_BUSINESS_RULES(TABLE_NAME VARCHAR)
RETURNS VARCHAR
LANGUAGE JAVASCRIPT
EXECUTE AS CALLER
AS
$$
try {
    var ts = new Date().toISOString().replace(/[-:TZ.]/g,'').slice(0,17);
    var n  = 0;

    function run(sql) { snowflake.execute({sqlText: sql}); }

    // Supprimer les anciens findings Open pour ne pas doubler
    run(`DELETE FROM QUALITY_TEST.DATA_QUALITY.DQ_FINDINGS
         WHERE status = 'Open'
           AND account_id IN (SELECT account_id FROM ` + TABLE_NAME + `)`);

    // R01 — Format SIREN (9 chiffres)
    run(`INSERT INTO QUALITY_TEST.DATA_QUALITY.DQ_FINDINGS
         (id,account_id,company_name,severity,status,subject,rule_id,
          field,field_label,field_value,expected_value,finding_type,description)
         SELECT 'F-'||'`+ts+`-R01-'||ROW_NUMBER() OVER (ORDER BY account_id),
                account_id, company_name, 'HIGH', 'Open', 'Compliance', 'R01',
                'siren','SIREN', COALESCE(siren,''),
                '9 chiffres numériques', 'Format SIREN invalide',
                'Le SIREN doit contenir exactement 9 chiffres numériques'
         FROM `+TABLE_NAME+`
         WHERE siren IS NULL
            OR LENGTH(REGEXP_REPLACE(COALESCE(siren,''),'[^0-9]','')) <> 9`);
    n++;

    // R02 — Format SIRET (14 chiffres)
    run(`INSERT INTO QUALITY_TEST.DATA_QUALITY.DQ_FINDINGS
         (id,account_id,company_name,severity,status,subject,rule_id,
          field,field_label,field_value,expected_value,finding_type,description)
         SELECT 'F-'||'`+ts+`-R02-'||ROW_NUMBER() OVER (ORDER BY account_id),
                account_id, company_name, 'HIGH', 'Open', 'Compliance', 'R02',
                'siret','SIRET', COALESCE(siret,''),
                '14 chiffres numériques', 'Format SIRET invalide',
                'Le SIRET doit contenir exactement 14 chiffres numériques'
         FROM `+TABLE_NAME+`
         WHERE siret IS NULL
            OR LENGTH(REGEXP_REPLACE(COALESCE(siret,''),'[^0-9]','')) <> 14`);
    n++;

    // R03 — Cohérence SIRET commence par SIREN
    run(`INSERT INTO QUALITY_TEST.DATA_QUALITY.DQ_FINDINGS
         (id,account_id,company_name,severity,status,subject,rule_id,
          field,field_label,field_value,expected_value,finding_type,description)
         SELECT 'F-'||'`+ts+`-R03-'||ROW_NUMBER() OVER (ORDER BY account_id),
                account_id, company_name, 'HIGH', 'Open', 'Compliance', 'R03',
                'siret','SIRET', COALESCE(siret,''),
                COALESCE(siren,'')||' + NIC 5 chiffres', 'Incohérence SIREN/SIRET',
                'Le SIRET doit commencer par le SIREN'
         FROM `+TABLE_NAME+`
         WHERE LENGTH(REGEXP_REPLACE(COALESCE(siren,''),'[^0-9]','')) = 9
           AND LENGTH(REGEXP_REPLACE(COALESCE(siret,''),'[^0-9]','')) = 14
           AND LEFT(REGEXP_REPLACE(COALESCE(siret,''),'[^0-9]',''),9)
               <> REGEXP_REPLACE(COALESCE(siren,''),'[^0-9]','')`);
    n++;

    // R04 — TVA intracommunautaire FR (FR + 11 caractères)
    run(`INSERT INTO QUALITY_TEST.DATA_QUALITY.DQ_FINDINGS
         (id,account_id,company_name,severity,status,subject,rule_id,
          field,field_label,field_value,expected_value,finding_type,description)
         SELECT 'F-'||'`+ts+`-R04-'||ROW_NUMBER() OVER (ORDER BY account_id),
                account_id, company_name, 'MEDIUM', 'Open', 'Compliance', 'R04',
                'vat','N° TVA intracom', COALESCE(vat,''),
                'FR + 11 caractères', 'Format TVA invalide',
                'Le N° TVA doit commencer par FR suivi de 11 caractères'
         FROM `+TABLE_NAME+`
         WHERE vat IS NOT NULL AND TRIM(vat) <> ''
           AND NOT REGEXP_LIKE(COALESCE(vat,''),'^FR[0-9A-Z]{11}$')`);
    n++;

    // R05 — Code pays FR pour comptes domestiques
    run(`INSERT INTO QUALITY_TEST.DATA_QUALITY.DQ_FINDINGS
         (id,account_id,company_name,severity,status,subject,rule_id,
          field,field_label,field_value,expected_value,finding_type,description)
         SELECT 'F-'||'`+ts+`-R05-'||ROW_NUMBER() OVER (ORDER BY account_id),
                account_id, company_name, 'MEDIUM', 'Open', 'Compliance', 'R05',
                'country','Pays', COALESCE(country,''),
                'FR', 'Code pays non-FR',
                'Les comptes domestiques doivent avoir le code pays FR'
         FROM `+TABLE_NAME+`
         WHERE country IS NOT NULL
           AND UPPER(TRIM(country)) NOT IN ('FR','FRA','FRANCE')`);
    n++;

    // R06 — Format NAF/APE (4 chiffres + 1 lettre)
    run(`INSERT INTO QUALITY_TEST.DATA_QUALITY.DQ_FINDINGS
         (id,account_id,company_name,severity,status,subject,rule_id,
          field,field_label,field_value,expected_value,finding_type,description)
         SELECT 'F-'||'`+ts+`-R06-'||ROW_NUMBER() OVER (ORDER BY account_id),
                account_id, company_name, 'MEDIUM', 'Open', 'Compliance', 'R06',
                'naf','Code NAF/APE', COALESCE(naf,''),
                'Format XXXXZ (ex: 6202A)', 'Format NAF invalide',
                'Le code NAF doit suivre le format XXXXZ (4 chiffres + 1 lettre)'
         FROM `+TABLE_NAME+`
         WHERE naf IS NOT NULL AND TRIM(naf) <> ''
           AND NOT REGEXP_LIKE(REPLACE(COALESCE(naf,''),'.',''),'^[0-9]{4}[A-Za-z]$')`);
    n++;

    // R07 — Forme juridique manquante
    run(`INSERT INTO QUALITY_TEST.DATA_QUALITY.DQ_FINDINGS
         (id,account_id,company_name,severity,status,subject,rule_id,
          field,field_label,field_value,expected_value,finding_type,description)
         SELECT 'F-'||'`+ts+`-R07-'||ROW_NUMBER() OVER (ORDER BY account_id),
                account_id, company_name, 'MEDIUM', 'Open', 'Compliance', 'R07',
                'legal_form','Forme juridique', '',
                'SA, SAS, SARL, SE…', 'Forme juridique absente',
                'Le champ forme juridique est obligatoire'
         FROM `+TABLE_NAME+`
         WHERE (legal_form IS NULL OR TRIM(legal_form) = '')
           AND NOT REGEXP_LIKE(
               UPPER(COALESCE(company_name,'')),
               '.*(\\bSAS\\b|\\bSARL\\b|\\bSA\\b|\\bSE\\b|\\bSCA\\b|\\bSNC\\b|\\bEURL\\b|\\bSCI\\b|\\bGIE\\b|\\bSASU\\b|\\bEARL\\b)')`);
    n++;

    return 'OK — ' + n + ' règles R01-R07 exécutées sur ' + TABLE_NAME;

} catch(e) {
    return 'Erreur SP: ' + e.message;
}
$$;


-- =============================================================================
-- Vérification finale
-- =============================================================================
SELECT 'DQ_FINDINGS'    AS table_name, COUNT(*) AS rows FROM QUALITY_TEST.DATA_QUALITY.DQ_FINDINGS
UNION ALL SELECT 'DQ_CORRECTIONS', COUNT(*) FROM QUALITY_TEST.DATA_QUALITY.DQ_CORRECTIONS
UNION ALL SELECT 'DQ_AUDIT_LOG',   COUNT(*) FROM QUALITY_TEST.DATA_QUALITY.DQ_AUDIT_LOG
UNION ALL SELECT 'DIM_SIRENE',     COUNT(*) FROM QUALITY_TEST.COMMERCIAL_DATA.DIM_SIRENE;
