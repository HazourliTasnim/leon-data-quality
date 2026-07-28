# Leon - Data Quality B2B

Application **Streamlit** connectee a **Snowflake** pour le pilotage de la qualite des donnees clients B2B.

Analyse automatisee des identifiants legaux (SIREN, SIRET, TVA intracommunautaire), detection des anomalies, corrections assistees par IA (Cortex AI), et export CRM.

---

## Lancer l'application

```bash
pip install -r requirements.txt
streamlit run app.py
```

Accessible sur http://localhost:8501

---

## Architecture

```
app.py                  # Application principale (Streamlit)
requirements.txt        # Dependances Python
snowflake.yml           # Configuration Snowflake CLI
.streamlit/
  config.toml           # Configuration Streamlit (theme, port)
  secrets.toml          # Identifiants Snowflake (non committe)
input/                  # Fichiers de donnees pour import
```

---

## Fonctionnalites

- **Tableau de bord** : KPIs temps reel (score conformite, anomalies, completude)
- **Donnees clients** : exploration et recherche du portefeuille B2B
- **Catalogue de regles** : regles preconfigurees + import via fichier texte (IA)
- **Lancer l'analyse** : wizard 5 etapes (selection sujets, perimetre, nettoyage, execution, resultats)
- **Anomalies** : liste detaillee avec filtres severite/statut, verification web (Agent IA)
- **Taches** : file de validation (accepter/corriger/rejeter en masse)
- **Exports** : CSV enrichi avec colonnes originales + corrigees cote a cote

---

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| Frontend | Streamlit |
| Backend | Snowflake (SQL, Cortex AI) |
| IA | Cortex Complete (mistral-large2) |
| Referentiel | INSEE SIRENE (29M+ etablissements) |
| Verification web | Pappers API + Google + LLM |

---

## Connexion Snowflake

- **Account** : configure dans `.streamlit/secrets.toml`
- **Database** : `QUALITY_TEST`
- **Schema** : `COMMERCIAL_DATA` (donnees), `DATA_QUALITY` (DQ engine)
- **Warehouse** : `COMPUTE_WH`

---

## Import de regles metier

L'application permet d'uploader un fichier texte (.txt, .pdf, .docx) decrivant des regles en langage naturel. Cortex AI les convertit automatiquement en regles executables (regex, not_empty, in_list, length).

---

## Auteurs

Projet realise par l'equipe Data Quality - Snowflake SE.
