# Workflow GitHub Actions : **Stations Weekly**

But : exécuter `fetch_stations.py` chaque vendredi vers 23:59 Europe/Paris, ingérer le CSV en flux dans DynamoDB, versionner `data/metadonnees/stations.json` si modifié, et archiver les logs du run.

## Déclencheurs

* **CRON**

  * `59 21 * * 5` : ~23:59 en été (UTC+2)
  * `59 22 * * 5` : ~23:59 en hiver (UTC+1)
* **Manuel** : `workflow_dispatch` depuis l’UI GitHub.

La garde `.github/scripts/should_run.sh fri-23:59` bloque les exécutions CRON hors de 23:59 Europe/Paris (sécurité fuseau).

## Permissions

```yaml
permissions:
  id-token: write   # OIDC vers AWS
  contents: write   # push du stations.json
```

## Secrets requis

* `AWS_ROLE_ARN` : rôle AWS à assumer par OIDC.
* `AWS_REGION` : région AWS (ex. eu-west-3).
* `MF_BASIC_AUTH_B64` : `base64(client_id:client_secret)` portail Météo-France.

## Variables d’environnement

* `METEO_TOKEN_CACHE` : chemin du cache token OAuth2 local au runner.
* `METEO_MAX_RPM` : limite soft de requêtes/minute (par défaut 50).
* `ALT_SELECT` : seuil d’altitude pour la fusion finale (par défaut 1000 m).

## Chaîne d’exécution

1. **Checkout**
2. **Gate fuseau horaire**
   `.github/scripts/should_run.sh fri-23:59` court-circuite si l’heure locale Europe/Paris ne correspond pas.
3. **Python 3.11**
4. **Installation**
   `uv` puis `requests`, `python-dateutil`, `boto3` en site-packages.
5. **AWS OIDC**
   `aws-actions/configure-aws-credentials@v4` assume le rôle `AWS_ROLE_ARN`.
6. **Téléchargement + ingestion DynamoDB**

   ```bash
   python -u -m src.download.fetch_stations \
   | python -m src.upload.stdin_to_dynamodb --table Stations --pk id
   ```

   * `fetch_stations.py` :

     * écrit des JSON bruts par pas/département sous `data/metadonnees/download/stations/**`
     * fusionne en `data/metadonnees/stations.json`
     * émet un **CSV sur stdout** (`id,nom,lon,lat,alt,_scales`)
   * `stdin_to_dynamodb` lit ce CSV et fait des **PutItem** par `id`.
     Idempotent : même `id` ⇒ remplacement de l’item, pas de doublon.
7. **Commit sélectif de `stations.json`**

   * Configure l’identité bot.
   * Vérifie un changement sur `data/metadonnees/stations.json`.
   * Commit + push avec `[skip ci]` si modifié.
     Évite de relancer d’autres workflows.
8. **Archive des logs**

   * Upload `logs/stations/*.log` comme artefact `stations-logs-${{ github.run_id }}`.
   * Rétention 14 jours.

## Flux de données

* **Entrées** : API DPClim Météo-France (OAuth2), secrets MF.
* **Sorties** :

  * Table **DynamoDB `Stations`** : upsert par `id`.
  * Fichier **versionné** : `data/metadonnees/stations.json` (source de vérité pour les workflows quotidiens).
  * **Artefact** GitHub : logs horodatés.
