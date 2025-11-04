Voici la doc du workflow “récupération quotidienne des observations”, calquée sur la base précédente et alignée sur le code fourni.

# Récupération quotidienne des observations (`fetch_observations.py`)

Le script interroge DPClim pour la **dernière mesure du jour** par station et par pas autorisé, puis écrit un **CSV minimal** sur stdout.

* Logs: `logs/observations/AAAAMMJJHHMMSS.log` (UTC)
* Format des lignes de log:
  `[id] : Etat de la connection | Données récupérées : Oui/Non | Raison si échec`
* Sortie standard: `id,date,HNEIGEF,NEIGETOT,NEIGETOT06`
* Dépendances: `requests`, `python-dateutil`

## Authentification OAuth2 et cache

Identique au workflow stations.

```python
from src.api.token_provider import get_api_key, clear_token_cache
```

* `get_api_key(use_cache=True)` fournit le token (cache si valide, régénération sinon).
* Sur `401/403`, le script purge le cache (`clear_token_cache()`) et réessaie.

En-têtes HTTP:

```
accept: application/json
authorization: Bearer <token>
```

## Paramètres, pas, fenêtres et rate limiting

* Base API: `METEO_BASE_URL` (défaut: `https://public-api.meteofrance.fr/public/DPClim/v1`)
* Limite: `METEO_MAX_RPM` (défaut `50` req/min) avec fenêtre glissante 60 s
* Pas gérés: `["quotidienne","horaire","infrahoraire-6m"]`
* Fenêtre temporelle ciblée par jour `--date YYYY-MM-DD`:

  * quotidienne/horaire: `00:00:00Z → 23:59:59Z`
  * 6 min: `00:00:00Z → 23:54:00Z` (le jour courant est borné à “now” arrondi au 6 min)

## Sélection des colonnes et union

Colonnes conservées par pas:

* quotidienne: `HNEIGEF`, `NEIGETOT`, `NEIGETOT06`
* horaire: `HNEIGEF`, `NEIGETOT`
* 6 min: aucune colonne neige retenue ici

Union dédupliquée exportée dans le CSV:

```
["HNEIGEF","NEIGETOT","NEIGETOT06"]
```

Note: alias `NEIGETOTX` est remappé vers `NEIGETOT` si nécessaire.

## Entrées du script

* `--date` (obligatoire) : `YYYY-MM-DD` en UTC
* `--stations` : chemin vers le `data/metadonnees/stations.json` fusionné (avec `_scales`)
* `--id` : optionnel, cible **une** station précise
* `--logdir` : dossier des logs horodatés (défaut `logs/observations`)

### Exemple

Toutes les stations du fichier fusionné pour le 2025-11-02:

```bash
python -m src.download.fetch_observations \
  --date "2025-11-02" \
  --stations data/metadonnees/stations.json
```

Une station précise:

```bash
python -m src.download.fetch_observations \
  --date "2025-11-02" --id 38002401 \
  --stations data/metadonnees/stations.json
```

## Logique de sélection par station

1. Lit `_scales` de la station. Si `DPCLIM_STRICT_SCALES=true` (défaut), seuls ces pas sont tentés, dans l’ordre global `[quotidienne, horaire, 6m]`.
2. Appelle `/information-station` (cache LRU) et vérifie si un paramètre associé au pas est **actif** le jour cible.
3. Pour chaque pas actif:

   * Crée la commande: `GET /commande-station/{pas}` avec fenêtre jour.
   * Polling `GET /commande/fichier` jusqu’à contenu prêt:

     * `200/201` → OK
     * `204` → attend (respect `Retry-After`)
     * `429` → attend `Retry-After` puis retry
     * `401/403` → refresh token puis retry
   * Parse le CSV retourné, détecte la colonne temporelle (`date|datetime|time|heure`), retient la **dernière** ligne du jour cible.
4. Garde la meilleure ligne trouvée (max datetime) parmi les pas actifs.
5. Écrit sur stdout:
   `id,date(HH:MM:SSZ),HNEIGEF,NEIGETOT,NEIGETOT06`
   Si **toutes** les valeurs utiles sont vides → pas d’écriture et enregistrement dans le **registre des manquants**.

## Registre des manquants

### Append au registre (`src/utils/missing_registry.py`)

Si aucune donnée exploitable n’est trouvée pour `(id,date)`:

```python
from src.utils.missing_registry import append_missing
append_missing(station_id, date_str)
```

* Fichier: `data/metadonnees/missing_observations.json`
  (surcharge via `MISSING_OBS_JSON`)
* Format: liste de `{ "id": <int>, "date": "YYYY-MM-DD", ["reason": "..."] }`
* Écriture **atomique**, déduplication sur `(id,date)`.

### Nettoyage du registre (quotidien)

Script: **cleanup_missing_observations.py**

* Supprime les entrées plus vieilles que `N` jours (défaut `11`)
* CLI:

  ```bash
  python -m src.utils.cleanup_missing_observations \
    --days 11 \
    --path data/metadonnees/missing_observations.json \
    [--dry-run]
  ```
* Sortie: rapport synthétique sur stdout.

## Relance ciblée des manquants

Script: **fetch_missing_observations.py**

* Lit `missing_observations.json`
* Pour chaque `(id,date)`, relance:

  ```bash
  python -m src.download.fetch_observations \
    --date <date> --id <id> --stations <stations.json> --logdir <logs>
  ```
* Agrège **un seul CSV** sur stdout (un header global, puis les lignes).
* Si au moins une ligne utile a été renvoyée pour `(id,date)`, l’entrée est **retirée** du JSON (écriture atomique).
* Code retour:

  * `0` si tout a été résolu
  * `1` s’il reste des manquants

### Exemple

```bash
python -m src.download.fetch_missing_observations \
  --missing data/metadonnees/missing_observations.json \
  --stations data/metadonnees/stations.json \
  --logdir logs/observations
```

## Résilience et erreurs

* `_req()` assure 2 tentatives par requête, refresh token sur `401/403`, attente `Retry-After` sur `429`, tolérance aux erreurs réseau transitoires.
* `telecharger_commande()` ne renvoie plus “HTTP0” directement. Il **attend** et réessaie jusqu’au `max_wait_s` (défaut 300 s).
* Logs plus informatifs: pas, fenêtre, id commande, statut HTTP.

## Organisation du workflow

| couche                            | rôle                                                        |
| --------------------------------- | ----------------------------------------------------------- |
| `auth_mf`                         | génération brute du token                                   |
| `token_provider`                  | cache vs régénération + helpers                             |
| `fetch_observations`              | création commandes, polling fichier, parsing dernière ligne |
| `missing_registry.append_missing` | journalisation des `(id,date)` sans donnée                  |
| `cleanup_missing_observations`    | purge des anciennes entrées du registre                     |
| `fetch_missing_observations`      | relance ciblée et retrait des entrées résolues              |

## Intégration CI/CD

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
2. `fetch_observations.py` produit le CSV sur stdout
   → dupliqué localement avec `tee`
   → envoyé en flux vers DynamoDB (`stdin_to_dynamodb --table Observations --pk id --sk date`)
3. Archive du CSV et des logs en artefacts
4. Nettoyage du registre `missing_observations.json` (par défaut conserve 11 jours)
5. Relance ciblée des manquants via `fetch_missing_observations.py`
   → nouveau CSV envoyé en flux vers DynamoDB
   → mise à jour atomique de `missing_observations.json`

## Table DynamoDB

* Table : **Observations**
* Partition key : `id`
* Sort key : `date` (timestamp strict du record)
* Mode : idempotent. Même `(id,date)` fait un overwrite propre.

## Flux de données

| élément                          | destination                                |
| -------------------------------- | ------------------------------------------ |
| CSV observation J-1              | DynamoDB + artefact CSV                    |
| logs fetch                       | artefacts GitHub `logs/observations/*.log` |
| missing_observations.json        | maintenu local + éventuellement versionné  |
| stations.json (source de vérité) | lu depuis le repo (généré weekly)          |


## Résultat

Ce workflow garantit la convergence progressive même si Météo-France publie des données J+1, J+2, J+3 **en retard**. Le système converge seul.
