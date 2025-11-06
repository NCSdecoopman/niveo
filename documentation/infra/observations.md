# Intégration CI/CD

1. Récupération du jour J-1:

```bash
DATE=$(date -u -d "yesterday" +%F)
python -m src.download.fetch_observations --date "$DATE" --stations data/metadonnees/stations.json \
  > data/observations/"$DATE".csv
```

2. Nettoyage du registre:

```bash
python -m src.utils.cleanup_missing_observations --days 11
```

3. Relance des manquants:

```bash
python -m src.download.fetch_missing_observations \
  --missing data/metadonnees/missing_observations.json \
  --stations data/metadonnees/stations.json \
  > data/observations/retries_"$DATE".csv
```

## Sorties attendues

* CSV du jour: `id,date,HNEIGEF,NEIGETOT,NEIGETOT06`
* Logs détaillés par run dans `logs/observations/`
* Registre des manquants à jour: `data/metadonnees/missing_observations.json`

Ce triptyque “**fetch → register missing → retry**” garantit la convergence quand Météo-France publie tardivement plusieurs jours à la fois.


Voici à ajouter à la suite (juste après ta section actuelle) :
Même style. Même granularité. Même structure que “Stations Weekly”.

# Workflow GitHub Actions : **Observations Daily**

But : exécuter `fetch_observations.py` chaque matin vers 07:00 Europe/Paris pour récupérer **J-1**, ingérer le CSV dans DynamoDB, maintenir le registre des observations manquantes, relancer les manquantes récentes, puis archiver les logs et les CSV du run.

## Déclencheurs

* **CRON**

  * `0 5 * * *` : ~07:00 en été (UTC+2)
  * `0 6 * * *` : ~07:00 en hiver (UTC+1)

* **Manuel** (`workflow_dispatch`)

  * possibilité de choisir `days_back` → ex: lancer manuellement **J-10** si besoin.

La garde `.github/scripts/should_run.sh daily-07:00` garantit la bonne heure locale (Europe/Paris).

## Permissions

```yaml
permissions:
  id-token: write   # OIDC AWS
  contents: write   # si l’on versionne missing_observations.json
```

## Secrets requis

* `AWS_ROLE_ARN` : rôle AWS OIDC
* `AWS_REGION`
* `MF_BASIC_AUTH_B64`

## Logique

1. Calcule la date cible J-X (`steps.date.outputs.YMD`)
2. Nettoyage du registre `missing_observations.json` (par défaut conserve 11 jours)
3. Relance ciblée des manquants via `fetch_missing_observations.py`
   → nouveau CSV envoyé en flux vers DynamoDB
   → mise à jour atomique de `missing_observations.json`
4. `fetch_observations.py` produit le CSV sur stdout
   → dupliqué localement avec `tee`
   → envoyé en flux vers DynamoDB (`stdin_to_dynamodb --table Observations --pk id --sk date`)
5. Archive du CSV et des logs en artefacts


## Table DynamoDB

* Table : **Observations**
* Partition key : `id`
* Sort key : `date` (timestamp strict du record)
* Mode : idempotent. Même `(id,date)` fait un overwrite propre.

Toutes les écritures vers DynamoDB ajoutent également l’attribut `expires_at` (Unix epoch seconds) ce qui active la purge automatique à J+11 via TTL DynamoDB. Aucun workflow supplémentaire côté AWS n’est nécessaire pour la suppression des anciennes observations.


## Flux de données

| élément                          | destination                                |
| -------------------------------- | ------------------------------------------ |
| CSV observation J-1              | DynamoDB + artefact CSV                    |
| logs fetch                       | artefacts GitHub `logs/observations/*.log` |
| missing_observations.json        | maintenu local + éventuellement versionné  |
| stations.json (source de vérité) | lu depuis le repo (généré weekly)          |


## Résultat

Ce workflow garantit la convergence progressive même si Météo-France publie des données J+1, J+2, J+3 **en retard**. Le système converge seul.
