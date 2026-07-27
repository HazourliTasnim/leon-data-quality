"""Internationalization — French / English for Léon."""

from __future__ import annotations

import streamlit as st

from locales.en_extra import EN_EXTRA

DEFAULT_LOCALE = "fr"

TRANSLATIONS: dict[str, dict[str, str]] = {
    "prefs.language": {"fr": "Langue", "en": "Language"},
    "prefs.theme": {"fr": "Apparence", "en": "Appearance"},
    "theme.dark": {"fr": "Sombre", "en": "Dark"},
    "theme.light": {"fr": "Clair", "en": "Light"},
    "app.title": {"fr": "Léon — Qualité des données", "en": "Léon — Data Quality"},
    "app.brand": {"fr": "Léon", "en": "Léon"},
    "app.tagline": {"fr": "DATA QUALITY", "en": "DATA QUALITY"},
    "app.footer": {"fr": "© 2026 Léon · Qualité des données & Gouvernance", "en": "© 2026 Léon · Data Quality & Governance"},
    "header.greeting": {"fr": "Bonjour {user}. {subtitle}", "en": "Hello {user}. {subtitle}"},
    "header.default_subtitle": {"fr": "Bienvenue sur votre espace qualité.", "en": "Welcome to your data quality workspace."},
    "header.ask_ai": {"fr": "💬 Ask AI", "en": "💬 Ask AI"},
    "header.close": {"fr": "✕ Fermer", "en": "✕ Close"},
    "header.user_default": {"fr": "Utilisateur", "en": "User"},
    "nav.section.main": {"fr": "PRINCIPAL", "en": "MAIN"},
    "nav.section.results": {"fr": "RÉSULTATS", "en": "RESULTS"},
    "nav.section.tools": {"fr": "OUTILS", "en": "TOOLS"},
    "nav.dashboard": {"fr": "Tableau de bord", "en": "Dashboard"},
    "nav.customer_data": {"fr": "Données clients", "en": "Customer Data"},
    "nav.run_analysis": {"fr": "Lancer l'analyse", "en": "Run Analysis"},
    "nav.findings": {"fr": "Anomalies", "en": "Findings"},
    "nav.tasks": {"fr": "Tâches", "en": "Tasks"},
    "nav.exports": {"fr": "Exports", "en": "Exports"},
    "nav.france": {"fr": "France", "en": "France"},
    "nav.rule_catalog": {"fr": "Catalogue de règles", "en": "Rule Catalog"},
    "page_subtitle.dashboard": {"fr": "KPIs, tendance conformité et activité récente.", "en": "KPIs, compliance trend and recent activity."},
    "page_subtitle.customer_data": {"fr": "Portefeuille comptes B2B — recherche, filtres et détail.", "en": "B2B account portfolio — search, filters and detail."},
    "page_subtitle.run_analysis": {"fr": "Wizard guidé — sujets, data cleaning et exécution Snowflake.", "en": "Guided wizard — subjects, data cleaning and Snowflake execution."},
    "page_subtitle.findings": {"fr": "Examiner, prioriser et traiter les écarts détectés.", "en": "Review, prioritize and resolve detected discrepancies."},
    "page_subtitle.tasks": {"fr": "Présélection et validation en masse — accepter ou rejeter.", "en": "Bulk pre-selection and validation — accept or reject."},
    "page_subtitle.exports": {"fr": "Rapports, restitution CRM et piste d'audit complète.", "en": "Reports, CRM handoff and full audit trail."},
    "page_subtitle.france": {"fr": "SIREN, SIRET, TVA intracom et e-facturation PDP.", "en": "SIREN, SIRET, intra-EU VAT and PDP e-invoicing."},
    "page_subtitle.rule_catalog": {"fr": "Modèles prêts à l'emploi pour la qualité B2B française.", "en": "Ready-to-use templates for French B2B data quality."},
    "demo.mode_toggle": {"fr": "Mode démo", "en": "Demo mode"},
    "demo.sidebar_title": {"fr": "Parcours démo · étape {step}/{total}", "en": "Demo tour · step {step}/{total}"},
    "demo.banner_step": {"fr": "Étape {step} / {total}", "en": "Step {step} / {total}"},
    "demo.prev": {"fr": "◀ Préc.", "en": "◀ Prev"},
    "demo.next": {"fr": "Suiv. ▶", "en": "Next ▶"},
    "demo.restart": {"fr": "Recommencer", "en": "Restart"},
    "demo.shortcuts": {"fr": "Raccourcis démo", "en": "Demo shortcuts"},
    "demo.step1.title": {"fr": "Vision exécutive", "en": "Executive overview"},
    "demo.step1.hint": {"fr": "Score conformité, tendance et activité récente.", "en": "Compliance score, trend and recent activity."},
    "demo.step2.title": {"fr": "Lancer l'analyse", "en": "Run Analysis"},
    "demo.step2.hint": {"fr": "Wizard 5 étapes — sujets, cleaning, exécution SQL.", "en": "5-step wizard — subjects, cleaning, SQL execution."},
    "demo.step3.title": {"fr": "Anomalies", "en": "Findings"},
    "demo.step3.hint": {"fr": "Filtrer HIGH · rechercher SIREN 552032534 (doublon).", "en": "Filter HIGH · search SIREN 552032534 (duplicate)."},
    "demo.step4.title": {"fr": "Tâches", "en": "Tasks"},
    "demo.step4.hint": {"fr": "Sélection groupée · accepter / rejeter en masse.", "en": "Bulk selection · accept / reject in bulk."},
    "demo.step5.title": {"fr": "France", "en": "France"},
    "demo.step5.hint": {"fr": "INSEE, résolution assistée, règles R01–R08.", "en": "INSEE, assisted resolution, rules R01–R08."},
    "demo.step6.title": {"fr": "Cortex Analyst", "en": "Cortex Analyst"},
    "demo.step6.hint": {"fr": "💬 Ask AI — « Combien d'anomalies HIGH ouvertes ? »", "en": "💬 Ask AI — “How many open HIGH findings?”"},
    "demo.search.danone": {"fr": "Doublon SIREN classique", "en": "Classic SIREN duplicate"},
    "demo.search.total": {"fr": "TotalEnergies — SIREN", "en": "TotalEnergies — SIREN"},
    "demo.search.insee": {"fr": "Écart adresse INSEE", "en": "INSEE address mismatch"},
    "sidebar.source": {"fr": "⚙️ Source", "en": "⚙️ Source"},
    "sidebar.database": {"fr": "Base de données", "en": "Database"},
    "sidebar.schema": {"fr": "Schéma", "en": "Schema"},
    "sidebar.table": {"fr": "Table", "en": "Table"},
    "sidebar.source_toast": {"fr": "Source : {db}.{schema}.{table}", "en": "Source: {db}.{schema}.{table}"},
    "common.validate": {"fr": "Valider", "en": "Apply"},
    "common.next": {"fr": "Suivant", "en": "Next"},
    "common.back": {"fr": "Retour", "en": "Back"},
    "common.cancel": {"fr": "Annuler", "en": "Cancel"},
    "common.apply": {"fr": "Appliquer", "en": "Apply"},
    "common.download": {"fr": "Télécharger", "en": "Download"},
    "common.search": {"fr": "Rechercher", "en": "Search"},
    "common.select_all": {"fr": "☑ Tout sélectionner", "en": "☑ Select all"},
    "common.deselect_all": {"fr": "☐ Tout désélectionner", "en": "☐ Deselect all"},
    "common.accept": {"fr": "Accepter", "en": "Accept"},
    "common.reject": {"fr": "Rejeter", "en": "Reject"},
    "common.resolve": {"fr": "Résoudre", "en": "Resolve"},
    "common.review": {"fr": "En revue", "en": "In Review"},
    "common.send": {"fr": "Envoyer", "en": "Send"},
    "common.clear": {"fr": "Effacer", "en": "Clear"},
    "common.modify": {"fr": "Modifier", "en": "Edit"},
    "common.none": {"fr": "— Aucune —", "en": "— None —"},
    "common.records": {"fr": "enregistrements", "en": "records"},
    "filter.all": {"fr": "Tous", "en": "All"},
    "filter.all_f": {"fr": "Toutes", "en": "All"},
    "filter.severity": {"fr": "Sévérité", "en": "Severity"},
    "filter.status": {"fr": "Statut", "en": "Status"},
    "severity.high": {"fr": "Élevée", "en": "High"},
    "severity.medium": {"fr": "Moyenne", "en": "Medium"},
    "severity.low": {"fr": "Faible", "en": "Low"},
    "severity.critical": {"fr": "critiques", "en": "critical"},
    "status.open": {"fr": "Ouvert", "en": "Open"},
    "status.in_review": {"fr": "En revue", "en": "In Review"},
    "status.resolved": {"fr": "Résolu", "en": "Resolved"},
    "status.dismissed": {"fr": "Rejeté", "en": "Dismissed"},
    "status.active": {"fr": "Actif", "en": "Active"},
    "status.inactive": {"fr": "Inactif", "en": "Inactive"},
    "subject.compliance": {"fr": "Conformité", "en": "Compliance"},
    "subject.duplicates": {"fr": "Doublons", "en": "Duplicates"},
    "subject.address": {"fr": "Adresse", "en": "Address"},
    "subject.web": {"fr": "Web", "en": "Web"},
    "col.select": {"fr": "Sélectionner", "en": "Select"},
    "col.company": {"fr": "Entreprise", "en": "Company"},
    "col.anomaly": {"fr": "Anomalie", "en": "Anomaly"},
    "col.field": {"fr": "Champ", "en": "Field"},
    "col.rule": {"fr": "Règle", "en": "Rule"},
    "login.eyebrow": {"fr": "Gouvernance des données B2B", "en": "B2B Data Governance"},
    "login.headline": {"fr": "La qualité de vos données,", "en": "Your data quality,"},
    "login.headline_em": {"fr": "sous contrôle.", "en": "under control."},
    "login.lead": {
        "fr": "Plateforme enterprise connectée à Snowflake — détection d'anomalies, conformité réglementaire française et correction assistée par Cortex Analyst.",
        "en": "Enterprise platform connected to Snowflake — anomaly detection, French regulatory compliance and Cortex Analyst-assisted correction.",
    },
    "login.step.ingest": {"fr": "Ingérer", "en": "Ingest"},
    "login.step.control": {"fr": "Contrôler", "en": "Control"},
    "login.step.fix": {"fr": "Corriger", "en": "Fix"},
    "login.step.audit": {"fr": "Auditer", "en": "Audit"},
    "login.badge.demo": {"fr": "Environnement démo", "en": "Demo environment"},
    "login.form.title": {"fr": "Connexion Snowflake", "en": "Snowflake login"},
    "login.form.subtitle": {"fr": "Snowadmin · EDW_DB_SANDBOX.HAZOURLI", "en": "Snowadmin · EDW_DB_SANDBOX.HAZOURLI"},
    "login.auth.label": {"fr": "Authentification", "en": "Authentication"},
    "login.auth.password": {"fr": "Mot de passe", "en": "Password"},
    "login.auth.sso": {"fr": "SSO (navigateur)", "en": "SSO (browser)"},
    "login.field.account": {"fr": "Compte", "en": "Account"},
    "login.field.user": {"fr": "Utilisateur", "en": "User"},
    "login.field.password": {"fr": "Mot de passe", "en": "Password"},
    "login.field.mfa": {"fr": "MFA", "en": "MFA"},
    "login.field.mfa_placeholder": {"fr": "Optionnel", "en": "Optional"},
    "login.field.warehouse": {"fr": "Warehouse", "en": "Warehouse"},
    "login.submit": {"fr": "Se connecter à Léon", "en": "Sign in to Léon"},
    "login.caption": {"fr": "Connexion chiffrée TLS · Aucune donnée stockée localement", "en": "TLS encrypted connection · No data stored locally"},
    "login.error.missing_fields": {"fr": "Veuillez remplir le compte et l'utilisateur.", "en": "Please fill in account and user."},
    "login.error.missing_password": {"fr": "Veuillez entrer votre mot de passe.", "en": "Please enter your password."},
    "login.error.failed": {"fr": "Connexion échouée : {error}", "en": "Connection failed: {error}"},
    "login.spinner": {"fr": "Connexion à Snowflake…", "en": "Connecting to Snowflake…"},
    "dashboard.kpi_compliance": {"fr": "Score conformité", "en": "Compliance score"},
    "dashboard.kpi_findings": {"fr": "Anomalies", "en": "Findings"},
    "dashboard.kpi_open_tasks": {"fr": "Tâches ouvertes", "en": "Open tasks"},
    "dashboard.kpi_completeness": {"fr": "Complétude données", "en": "Data completeness"},
    "dashboard.in_review": {"fr": "en revue", "en": "in review"},
    "dashboard.chart_title": {"fr": "Score de conformité", "en": "Compliance score"},
    "dashboard.chart_empty": {"fr": "Le graphique apparaîtra après la première analyse.", "en": "Chart will appear after the first analysis."},
    "dashboard.section.severity": {"fr": "Sévérité", "en": "Severity"},
    "dashboard.section.resolution": {"fr": "Résolution", "en": "Resolution"},
    "dashboard.section.statuses": {"fr": "Statuts", "en": "Statuses"},
    "dashboard.section.subjects": {"fr": "Sujets", "en": "Subjects"},
    "dashboard.resolved_of": {"fr": "{done} sur {total} traités", "en": "{done} of {total} processed"},
    "dashboard.rules_triggered": {"fr": "Règles déclenchées", "en": "Rules triggered"},
    "dashboard.latest_findings": {"fr": "Dernières anomalies", "en": "Latest findings"},
    "dashboard.top_accounts": {"fr": "Comptes les plus impactés", "en": "Most impacted accounts"},
    "customer_data.subtitle": {"fr": "Portefeuille comptes B2B — recherche, filtres et détail par enregistrement.", "en": "B2B account portfolio — search, filters and per-record detail."},
    "customer_data.search_placeholder": {"fr": "Raison sociale, SIREN, SIRET, ID compte…", "en": "Company name, SIREN, SIRET, account ID…"},
    "customer_data.records_shown": {"fr": "{shown} sur {total} enregistrements affichés", "en": "{shown} of {total} records displayed"},
    "findings.subtitle": {"fr": "Examiner, prioriser et traiter les écarts de qualité détectés.", "en": "Review, prioritize and resolve detected quality gaps."},
    "tasks.subtitle": {"fr": "Présélection et validation des anomalies — acceptez, corrigez ou rejetez en masse.", "en": "Pre-selection and validation of findings — accept, fix or reject in bulk."},
    "exports.subtitle": {"fr": "Rapports, restitution CRM et piste d'audit complète.", "en": "Reports, CRM handoff and full audit trail."},
    "rule_catalog.subtitle": {"fr": "Modèles prêts à l'emploi pour la qualité des données B2B françaises.", "en": "Ready-to-use templates for French B2B data quality."},
    "bulk.title": {"fr": "Actions groupées", "en": "Bulk actions"},
    "bulk.accept_n": {"fr": "✓ Accepter ({count})", "en": "✓ Accept ({count})"},
    "bulk.reject_n": {"fr": "✗ Rejeter ({count})", "en": "✗ Reject ({count})"},
    "bulk.confirm_reject": {"fr": "Confirmer le rejet groupé", "en": "Confirm bulk rejection"},
    "bulk.accept_toast": {"fr": "✓ {count} anomalie(s) acceptée(s)", "en": "✓ {count} finding(s) accepted"},
    "bulk.reject_toast": {"fr": "✗ {count} anomalie(s) rejetée(s)", "en": "✗ {count} finding(s) rejected"},
    "chat.title": {"fr": "Cortex Analyst", "en": "Cortex Analyst"},
    "chat.subtitle": {"fr": "Text-to-SQL", "en": "Text-to-SQL"},
    "chat.close": {"fr": "✕ Fermer", "en": "✕ Close"},
    "chat.placeholder": {"fr": "Posez votre question...", "en": "Ask your question..."},
    "chat.suggestion1": {"fr": "Combien d'anomalies au total ?", "en": "How many findings in total?"},
    "chat.suggestion2": {"fr": "Quelles entreprises sont les plus impactées ?", "en": "Which companies are most impacted?"},
    "chat.suggestion3": {"fr": "Anomalies critiques ouvertes ?", "en": "Open critical findings?"},
    "chat.demo_suggestion1": {"fr": "Combien d'anomalies HIGH ouvertes ?", "en": "How many open HIGH findings?"},
    "chat.demo_suggestion2": {"fr": "Top 5 entreprises par nombre d'anomalies", "en": "Top 5 companies by number of findings"},
    "chat.demo_suggestion3": {"fr": "Score de conformité moyen par sujet", "en": "Average compliance score by subject"},
    "fr_rule.active_rules": {"fr": "Règles actives", "en": "Active rules"},
    "fr_rule.INSEE.name": {"fr": "Registre SIRENE", "en": "SIRENE register"},
    "fr_rule.INSEE.check": {"fr": "29M+ entreprises", "en": "29M+ businesses"},
    "wizard.step.subjects": {"fr": "Sélection des sujets", "en": "Subject selection"},
    "wizard.step.scope": {"fr": "Périmètre", "en": "Scope"},
    "wizard.step.cleaning": {"fr": "Data Cleaning", "en": "Data Cleaning"},
    "wizard.step.execution": {"fr": "Exécution", "en": "Execution"},
    "wizard.step.results": {"fr": "Résultats", "en": "Results"},
    "wizard.badge_sql": {"fr": "Moteur SQL", "en": "SQL engine"},
    "wizard.badge_insee": {"fr": "INSEE", "en": "INSEE"},
    "wizard.subtitle": {"fr": "Wizard guidé — sélection des sujets, configuration des règles et exécution Snowflake.", "en": "Guided wizard — subject selection, rule configuration and Snowflake execution."},
    "wizard.step2.title": {"fr": "Étape 2 — Périmètre & règles", "en": "Step 2 — Scope & rules"},
    "wizard.step3.title": {"fr": "Étape 3 — Nettoyage & Dédoublonnage", "en": "Step 3 — Cleaning & deduplication"},
    "wizard.next_scope": {"fr": "Suivant : Périmètre", "en": "Next: Scope"},
    "wizard.next_cleaning": {"fr": "Suivant : Data Cleaning", "en": "Next: Data Cleaning"},
    "wizard.step1.title": {"fr": "Étape 1 — Sélection des sujets", "en": "Step 1 — Subject selection"},
    "wizard.step2.title": {"fr": "Étape 2 — Périmètre & règles", "en": "Step 2 — Scope & rules"},
    "wizard.step3.title": {"fr": "Étape 3 — Nettoyage & Dédoublonnage", "en": "Step 3 — Cleaning & deduplication"},
    "wizard.step4.title": {"fr": "Étape 4 — Exécution des règles", "en": "Step 4 — Rule execution"},
    "wizard.step5.title": {"fr": "Étape 5 — Résultats", "en": "Step 5 — Results"},
    "tasks.all_done": {"fr": "Toutes les tâches ont été traitées.", "en": "All tasks have been processed."},
    "france.subtitle": {"fr": "Module dédié SIREN, SIRET, TVA intracom et préparation facturation électronique PDP.", "en": "Dedicated module for SIREN, SIRET, intra-EU VAT and PDP e-invoicing preparation."},
    "france.tab.source": {"fr": "Source & Analyse", "en": "Source & Analysis"},
    "france.tab.rules": {"fr": "Règles métier", "en": "Business rules"},
    "france.tab.resolution": {"fr": "Centre de résolution", "en": "Resolution center"},
    "france.tab.audit": {"fr": "Audit & Export", "en": "Audit & Export"},
}


def get_lang() -> str:
    return st.session_state.get("lang", DEFAULT_LOCALE)


def _build_fr_en_catalog() -> dict[str, str]:
    """Build FR→EN lookup from semantic keys + extra catalog."""
    catalog: dict[str, str] = dict(EN_EXTRA)
    for entry in TRANSLATIONS.values():
        fr, en = entry.get("fr"), entry.get("en")
        if fr and en:
            catalog[fr] = en
    return catalog


_FR_EN_CATALOG: dict[str, str] | None = None


def _catalog() -> dict[str, str]:
    global _FR_EN_CATALOG
    if _FR_EN_CATALOG is None:
        _FR_EN_CATALOG = _build_fr_en_catalog()
    return _FR_EN_CATALOG


def tr(text: str, **kwargs) -> str:
    """Smart translator — French source string in code, English from central catalog."""
    if not text:
        return text
    lang = get_lang()
    if lang == "fr":
        out = text
    else:
        out = _catalog().get(text, text)
    return out.format(**kwargs) if kwargs else out


def t(key: str, **kwargs) -> str:
    loc = get_lang()
    entry = TRANSLATIONS.get(key, {})
    text = entry.get(loc) or entry.get(DEFAULT_LOCALE) or key
    return text.format(**kwargs) if kwargs else text


def get_pages() -> list[tuple[str, str, str]]:
    return [
        ("dashboard", t("nav.dashboard"), ":material/dashboard:"),
        ("customer_data", t("nav.customer_data"), ":material/group:"),
        ("run_analysis", t("nav.run_analysis"), ":material/play_circle:"),
        ("findings", t("nav.findings"), ":material/warning:"),
        ("tasks", t("nav.tasks"), ":material/checklist:"),
        ("exports", t("nav.exports"), ":material/download:"),
        ("france", t("nav.france"), ":material/public:"),
        ("rule_catalog", t("nav.rule_catalog"), ":material/menu_book:"),
    ]


def get_page_subtitle(page_id: str) -> str:
    return t(f"page_subtitle.{page_id}") if f"page_subtitle.{page_id}" in TRANSLATIONS else t("header.default_subtitle")


def get_demo_script() -> list[dict]:
    return [
        {"step": 1, "page": "dashboard", "title": t("demo.step1.title"), "hint": t("demo.step1.hint")},
        {"step": 2, "page": "run_analysis", "title": t("demo.step2.title"), "hint": t("demo.step2.hint")},
        {"step": 3, "page": "findings", "title": t("demo.step3.title"), "hint": t("demo.step3.hint")},
        {"step": 4, "page": "tasks", "title": t("demo.step4.title"), "hint": t("demo.step4.hint")},
        {"step": 5, "page": "france", "title": t("demo.step5.title"), "hint": t("demo.step5.hint")},
        {"step": 6, "page": "dashboard", "title": t("demo.step6.title"), "hint": t("demo.step6.hint"), "action": "chat"},
    ]


def get_demo_search_hints() -> list[tuple[str, str]]:
    return [
        ("Danone", t("demo.search.danone")),
        ("552032534", t("demo.search.total")),
        ("542051180", t("demo.search.insee")),
    ]


def tr_severity(severity: str) -> str:
    mapping = {
        "All": t("filter.all"),
        "HIGH": t("severity.high"),
        "MEDIUM": t("severity.medium"),
        "LOW": t("severity.low"),
    }
    return mapping.get(severity, severity)


def tr_status(status: str) -> str:
    mapping = {
        "All": t("filter.all"),
        "Open": t("status.open"),
        "In Review": t("status.in_review"),
        "Resolved": t("status.resolved"),
        "Dismissed": t("status.dismissed"),
    }
    return mapping.get(status, status)


def tr_subject(subject: str) -> str:
    mapping = {
        "Compliance": t("subject.compliance"),
        "Duplicates": t("subject.duplicates"),
        "Address": t("subject.address"),
        "Web": t("subject.web"),
    }
    return mapping.get(subject, subject)


def tr_account_status(status: str) -> str:
    mapping = {"Active": t("status.active"), "Inactive": t("status.inactive")}
    return mapping.get(status, status)


def get_severity_filter_opts() -> list[tuple[str, str]]:
    return [
        (t("filter.all"), "All"),
        (t("severity.high"), "HIGH"),
        (t("severity.medium"), "MEDIUM"),
        (t("severity.low"), "LOW"),
    ]


def get_status_filter_opts() -> list[tuple[str, str]]:
    return [
        (t("filter.all"), "All"),
        (t("status.open"), "Open"),
        (t("status.in_review"), "In Review"),
        (t("status.resolved"), "Resolved"),
        (t("status.dismissed"), "Dismissed"),
    ]


_FR_RULE_KEYS = {
    "R01": ("fr_rule.R01.name", "fr_rule.R01.check"),
    "R02": ("fr_rule.R02.name", "fr_rule.R02.check"),
    "R03": ("fr_rule.R03.name", "fr_rule.R03.check"),
    "R04": ("fr_rule.R04.name", "fr_rule.R04.check"),
    "R05": ("fr_rule.R05.name", "fr_rule.R05.check"),
    "R06": ("fr_rule.R06.name", "fr_rule.R06.check"),
    "R07": ("fr_rule.R07.name", "fr_rule.R07.check"),
    "R08": ("fr_rule.R08.name", "fr_rule.R08.check"),
}

# Seed FR rule name/check keys in TRANSLATIONS
TRANSLATIONS.update({
    "fr_rule.R01.name": {"fr": "Format SIREN", "en": "SIREN format"},
    "fr_rule.R01.check": {"fr": "9 chiffres numériques", "en": "9 numeric digits"},
    "fr_rule.R02.name": {"fr": "Format SIRET", "en": "SIRET format"},
    "fr_rule.R02.check": {"fr": "14 chiffres numériques", "en": "14 numeric digits"},
    "fr_rule.R03.name": {"fr": "Cohérence SIRET", "en": "SIRET consistency"},
    "fr_rule.R03.check": {"fr": "SIRET = SIREN + 5 caractères", "en": "SIRET = SIREN + 5 characters"},
    "fr_rule.R04.name": {"fr": "Numéro de TVA", "en": "VAT number"},
    "fr_rule.R04.check": {"fr": "11 caractères alphanumériques (clé Luhn)", "en": "11 alphanumeric characters (Luhn key)"},
    "fr_rule.R05.name": {"fr": "Pays FR", "en": "Country FR"},
    "fr_rule.R05.check": {"fr": "Code pays = FR pour comptes domestiques", "en": "Country code = FR for domestic accounts"},
    "fr_rule.R06.name": {"fr": "Code NAF/APE", "en": "NAF/APE code"},
    "fr_rule.R06.check": {"fr": "Format XX.XXZ", "en": "Format XX.XXZ"},
    "fr_rule.R07.name": {"fr": "Forme juridique", "en": "Legal form"},
    "fr_rule.R07.check": {"fr": "Champ renseigné (SA, SAS, SARL…)", "en": "Field populated (SA, SAS, SARL…)"},
    "fr_rule.R08.name": {"fr": "Identifiant e-facturation", "en": "E-invoicing identifier"},
    "fr_rule.R08.check": {"fr": "SIREN + SIRET valides pour PDP", "en": "Valid SIREN + SIRET for PDP"},
    "rule.T01.name": {"fr": "Contrôle conformité", "en": "Compliance check"},
    "rule.T01.desc": {"fr": "Valide les identifiants légaux obligatoires (SIREN, TVA, forme juridique) selon la réglementation française.", "en": "Validates mandatory legal identifiers (SIREN, VAT, legal form) per French regulations."},
    "rule.T02.name": {"fr": "Validation SIRET", "en": "SIRET validation"},
    "rule.T02.desc": {"fr": "Vérifie la clé SIRET et recoupe avec le registre INSEE SIRENE.", "en": "Checks SIRET key and cross-references INSEE SIRENE register."},
    "rule.T03.name": {"fr": "Détection de doublons", "en": "Duplicate detection"},
    "rule.T03.desc": {"fr": "Identifie les doublons SIREN/SIRET dans la base clients.", "en": "Identifies SIREN/SIRET duplicates in the customer base."},
    "rule.T04.name": {"fr": "Fraîcheur code NAF", "en": "NAF code freshness"},
    "rule.T04.desc": {"fr": "Contrôle les codes NAF/APE par rapport à la dernière nomenclature INSEE.", "en": "Checks NAF/APE codes against latest INSEE nomenclature."},
    "rule.T05.name": {"fr": "Validation adresse", "en": "Address validation"},
    "rule.T05.desc": {"fr": "Compare les adresses enregistrées avec le siège SIRENE.", "en": "Compares registered addresses with SIRENE headquarters."},
    "rule.T06.name": {"fr": "Présence web", "en": "Web presence"},
    "rule.T06.desc": {"fr": "Vérifie la disponibilité du site corporate et la cohérence du domaine e-mail.", "en": "Checks corporate website availability and email domain consistency."},
    "rule.T07.name": {"fr": "Format contact", "en": "Contact format"},
    "rule.T07.desc": {"fr": "Contrôle le format standard des téléphones et adresses e-mail.", "en": "Checks standard phone and email formats."},
    "analysis.compliance.name": {"fr": "Conformité", "en": "Compliance"},
    "analysis.compliance.desc": {"fr": "Identifiants légaux, TVA, champs réglementaires", "en": "Legal IDs, VAT, regulatory fields"},
    "analysis.duplicates.name": {"fr": "Doublons", "en": "Duplicates"},
    "analysis.duplicates.desc": {"fr": "Détection de doublons SIREN/SIRET", "en": "SIREN/SIRET duplicate detection"},
    "analysis.address.name": {"fr": "Adresse", "en": "Address"},
    "analysis.address.desc": {"fr": "Validation d'adresse vs INSEE", "en": "Address validation vs INSEE"},
    "analysis.web.name": {"fr": "Web", "en": "Web"},
    "analysis.web.desc": {"fr": "Contrôles site web et domaine e-mail", "en": "Website and email domain checks"},
})


def get_fr_business_rules() -> list[dict]:
    rules = []
    for rid, (name_key, check_key) in _FR_RULE_KEYS.items():
        rules.append({"id": rid, "name": t(name_key), "check": t(check_key)})
    return rules


def get_rule_templates() -> list[dict]:
    return [
        {"id": "T-01", "name": t("rule.T01.name"), "description": t("rule.T01.desc"), "subject": "Compliance", "priority": "P1"},
        {"id": "T-02", "name": t("rule.T02.name"), "description": t("rule.T02.desc"), "subject": "Compliance", "priority": "P1"},
        {"id": "T-03", "name": t("rule.T03.name"), "description": t("rule.T03.desc"), "subject": "Duplicates", "priority": "P1"},
        {"id": "T-04", "name": t("rule.T04.name"), "description": t("rule.T04.desc"), "subject": "Compliance", "priority": "P2"},
        {"id": "T-05", "name": t("rule.T05.name"), "description": t("rule.T05.desc"), "subject": "Address", "priority": "P2"},
        {"id": "T-06", "name": t("rule.T06.name"), "description": t("rule.T06.desc"), "subject": "Web", "priority": "P3"},
        {"id": "T-07", "name": t("rule.T07.name"), "description": t("rule.T07.desc"), "subject": "Compliance", "priority": "P3"},
    ]


def get_analysis_subjects() -> list[dict]:
    return [
        {"id": "compliance", "name": t("analysis.compliance.name"), "description": t("analysis.compliance.desc"), "rules": 4, "priority": "P1", "subject_key": "Compliance"},
        {"id": "duplicates", "name": t("analysis.duplicates.name"), "description": t("analysis.duplicates.desc"), "rules": 1, "priority": "P1", "subject_key": "Duplicates"},
        {"id": "address", "name": t("analysis.address.name"), "description": t("analysis.address.desc"), "rules": 1, "priority": "P2", "subject_key": "Address"},
        {"id": "web", "name": t("analysis.web.name"), "description": t("analysis.web.desc"), "rules": 2, "priority": "P3", "subject_key": "Web"},
    ]
