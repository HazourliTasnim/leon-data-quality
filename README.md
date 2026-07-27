# Qualitix — Qualité des données B2B

Application **Streamlit** déployée sur **Snowflake Streamlit in Snowflake (SiS)**.  
Interface SaaS de pilotage de la qualité des données clients, avec un module **France** dédié (SIREN, SIRET, TVA, e-facturation).

> **État actuel :** UI complète + données mock en session. Connexion Snowflake, API INSEE live et procédures stockées : à brancher.

---

## Lancer l'application

```bash
cd brother_dq
streamlit run app.py
```

→ http://localhost:8501

**Déploiement SiS :** voir `snowflake.yml` — entité `BROTHER_DQ_APP`, schéma `DATA_QUALITY`, warehouse `COMPUTE_WH`.

---

## Architecture (vue d'ensemble)

| Couche | Rôle |
|--------|------|
| **Streamlit (`app.py`)** | Navigation, tableaux de bord, workflows utilisateur |
| **Snowflake (cible)** | `DIM_ACCOUNT`, `DQ_FINDINGS`, `DQ_CORRECTIONS`, `SP_EXECUTE_BUSINESS_RULES()` |
| **Référentiel INSEE** | Croisement SIRENE (mock 24 SIREN en démo) |

**8 pages :** Tableau de bord · Données clients · Lancer l'analyse · Anomalies · Tâches · Exports · **France** · Catalogue de règles

---

# Script de démo (~12 min)

*Speech prêt à lire — adapter le ton à l'audience (métier, DSI, Snowflake).*

---

## 0. Introduction (1 min)

> « Bonjour. Aujourd'hui je vous présente **Qualitix**, notre plateforme de **qualité des données B2B**.
>
> Le problème qu'on adresse : un portefeuille clients hétérogène — CRM, fichiers fournisseurs, extractions Snowflake — avec des **identifiants légaux français** souvent incorrects ou incohérents. Ça bloque la conformité, la facturation électronique, et la confiance dans les reportings.
>
> Qualitix centralise trois choses : **mesurer** la qualité, **détecter** les anomalies, et **corriger** avec traçabilité. L'application tourne nativement dans **Snowflake** : les données ne sortent pas du cloud. »

**À l'écran :** sidebar Qualitix, toggle **Mode clair** si l'audience préfère.

---

## 1. Tableau de bord — la vision exécutive (2 min)

> « On commence par le **tableau de bord**. En un coup d'œil : score de conformité, volume d'anomalies, tâches ouvertes, périmètre contrôlé.
>
> Ici on voit **54 %** de conformité — en dessous de notre objectif à **70 %**. La courbe sur 30 jours montre une dégradation : ce n'est pas qu'un snapshot, c'est un **pilotage dans le temps**.
>
> Le radar décompose la qualité par dimension — identifiants, adresse, conformité, doublons, web, contact. On identifie tout de suite où agir.
>
> En bas : les **anomalies critiques** et le **journal d'audit** — qui a fait quoi, quand. Indispensable pour la gouvernance des données. »

**À montrer :** KPIs · courbe de tendance · jauge · donut sévérité · radar · audit log.

---

## 2. Données clients — la source de vérité (1 min)

> « Avant d'analyser, on vérifie la **source**. Cette vue correspond à notre table **`DIM_ACCOUNT`** dans Snowflake : 25 comptes de démo, grands comptes français.
>
> Recherche instantanée par raison sociale, SIREN ou ID. En production, c'est un `SELECT` live sur Snowflake — pas d'export Excel intermédiaire. »

**À montrer :** taper `Danone` ou `552032534` dans la recherche.

---

## 3. Lancer l'analyse — le wizard métier (2 min)

> « Le cœur du produit : **Lancer l'analyse**. Un assistant en 4 étapes, pensé pour un utilisateur métier, pas pour un data engineer.
>
> **Étape 1** — je choisis mes **sujets** : conformité, doublons, adresse, web. Chaque sujet active un jeu de règles.
>
> **Étape 2** — je valide le **périmètre** : 25 comptes, N règles, durée estimée.
>
> **Étape 3** — exécution : chargement DIM_ACCOUNT, règles T-01 à T-07, détection doublons, **recoupement INSEE SIRENE**.
>
> **Étape 4** — résultats : 12 anomalies, score recalculé. Un clic et j'atterris dans la **boîte de réception**. »

**À montrer :** cocher Conformité + Doublons → Suivant → Lancer l'analyse → Voir les anomalies.

---

## 4. Anomalies & Tâches — le workflow de résolution (2 min)

> « La **boîte de réception des anomalies**, c'est l'inbox opérationnelle. Filtres par **sévérité** et **statut**, recherche full-text.
>
> Exemple concret : **Danone et Bouygues partagent le même SIREN** — doublon critique, règle T-03.
>
> **TotalEnergies** : TVA intracommunautaire manquante. **AXA** : adresse différente du registre INSEE.
>
> Chaque carte porte un ID, une règle, une description actionnable.
>
> Dans **Tâches**, l'équipe data stewardship **accepte** ou **rejette** : Accept → *En revue*, Reject → *Rejeté*. Chaque action alimente le journal d'audit et met à jour les compteurs dans la sidebar. »

**À montrer :** filtre **Élevée** · carte F-001 (doublon SIREN) · Tâches → Accepter une anomalie → toast + compteur sidebar.

---

## 5. France — conformité & e-facturation (3 min) ★ highlight

> « Le module **France** est notre différenciateur pour le marché français : **SIREN, SIRET, TVA, préparation e-facturation PDP**.
>
> **Onglet Source & Analyse** — point d'entrée unifié. Deux modes :
> - **Table Snowflake** : `DIM_ACCOUNT`, mapping colonnes prédéfini, aperçu, puis analyse ;
> - **Fichier CSV/Excel** : import fournisseur, **détection automatique des colonnes** (alias raison_sociale, num_siren, tva_intra…), mapping manuel si besoin.
>
> **Même moteur** dans les deux cas : règles **R01–R04** (format SIREN, SIRET, cohérence SIRET=SIREN+5, TVA FR) + **croisement INSEE mock** (nom, adresse, NAF).
>
> Je lance l'analyse… KPIs, détail ligne par ligne, export CSV, envoi vers le **centre de résolution**. »

**À montrer :** France → Source & Analyse → **Analyser la table** → résultats → **Envoyer vers le centre de résolution**.

> « **Tableau de bord France** : score DQ 74 %, **EINVOICING_READY_COUNT** — combien de comptes sont prêts pour la facturation électronique — SLA par règle R01 à R08.
>
> **Centre de résolution** : comparaison **FIELD_VALUE vs EXPECTED_VALUE**. J'accepte → écriture simulée dans **`DQ_CORRECTIONS`**. Je peux aussi rejeter avec motif.
>
> **Audit & Export** : scripts UPDATE SQL, rapport HTML, recherche SIRENE mock — tapez `542051180` pour voir l'écart d'adresse TotalEnergies CRM vs INSEE. »

**Bonus fichier :** télécharger le modèle CSV, uploader une ligne invalide (`ACC-003;Test Invalid;123;…`) pour montrer la détection.

---

## 6. Catalogue & Exports — gouvernance (1 min)

> « Le **catalogue de règles** documente T-01 à T-07 : conformité, SIRET, doublons, NAF, adresse, web, format contact. Priorités P1/P2/P3.
>
> **Exports** : rapports CSV prêts pour le CRM ou l'équipe conformité — corrections, anomalies, audit.
>
> En sidebar : **usage mensuel** et modèle **Freemium** — 25 enregistrements sur 100. La montée en charge passe par l'offre Pro. »

---

## 7. Clôture (30 s)

> « Qualitix, c'est : **pilotage** (dashboard), **détection** (règles + INSEE), **résolution** (workflow + corrections tracées), le tout **dans Snowflake**.
>
> Prochaines étapes : brancher `st.connection` sur `DIM_ACCOUNT` et `DQ_FINDINGS`, activer l'API INSEE SIRENE live, et déployer `SP_EXECUTE_BUSINESS_RULES()` en production.
>
> Questions ? »

---

## Aide-mémoire démo

| Action | Valeur / clic |
|--------|----------------|
| Recherche client | `Danone`, `552032534`, `TotalEnergies` |
| Doublon SIREN | F-001 / F-002 — SIREN `552032534` |
| Écart INSEE adresse | SIREN `542051180` (TotalEnergies) |
| Import CSV test | Ligne `ACC-003;Test Invalid;123;55203253400099;FRBAD;…` |
| Règles France | R01 SIREN · R02 SIRET · R03 cohérence · R04 TVA |
| Règles globales | T-01 à T-07 (catalogue) |

---

## Limites connues (à mentionner si on vous challenge)

- Données **mock** en `session_state` — pas de requête Snowflake réelle
- INSEE : cache simulé (24 SIREN), pas d'appel API live
- `SP_EXECUTE_BUSINESS_RULES()` : simulation avec spinner
- Export certifié « INSEE vérifié » : non implémenté
- Enrichissement auto INSEE dans le centre de résolution : à venir

---

## Fichiers du projet

```
brother_dq/
├── app.py                 # Application Streamlit (~2 400 lignes)
├── environment.yml        # Dépendances SiS (streamlit, pandas, plotly, openpyxl)
├── snowflake.yml          # Déploiement Streamlit in Snowflake
├── .streamlit/config.toml # Thème (accent orange #f59e0b)
└── README.md              # Ce fichier
```

---

## Checklist avant la démo

- [ ] `streamlit run app.py` — port 8501 accessible
- [ ] Hard refresh (Cmd+Shift+R) si thème incohérent
- [ ] Mode clair ou sombre selon salle / projecteur
- [ ] Repartir du **Tableau de bord** (page par défaut)
- [ ] Préparer le fichier CSV test ou utiliser le modèle intégré
- [ ] Durée cible : **10–12 min** + questions
