# Récupération des données stations (fetch_stations.py)

Le script `src/download/fetch_stations.py` récupère les métadonnées des stations météo de Météo France:

## Stockage de l'identifiant portail Météo-France (client_id)
L’identifiant client (client_id : client_secret) est stocké localement dans: .secrets/mf_api_id
Ce fichier n’est **jamais commit**.

## Génération d’un token OAuth2 (1h de validité)
`src/utils/auth_mf.py` gère exclusivement la génération du token MF (via `client_credentials`)
Il écrit le token dans `.secrets/mf_token.json`.

## Récupération du token avec cache
`src/utils/token_provider.py` fournit l’accès au token:
* si token valide → il renvoie le cache
* sinon → il déclenche une nouvelle génération via `auth_mf`

Les scripts n’appellent **jamais** directement la génération brute. Ils appellent uniquement:

```python
from src.utils.token_provider import get_api_key
```

## Téléchargement des stations Météo-France
`src/download/fetch_stations.py` utilise `get_api_key()` et appelle l’API DPClim avec le header requis:
Authorization: Bearer <token>

Les listes de stations sont téléchargées par:
* échelle temporelle (`infrahoraire-6m`, `horaire`, `quotidienne`)
* département (exemple: 38, 73, 74)
Et les JSON sont stockés localement sous: data/metadonnees/download/stations/{echelle}/stations_{departement}.json
Un limiteur a été mis en place pour respecter la contrainte (50 requêtes/minute).

## Combinaison finale des stations
À la fin du script `fetch_stations.py`, un post-processing automatique est déclenché:
`src/download/combine_stations.py` agrège tous les fichiers JSON téléchargés.

Cette étape:
* déduplique les stations par ID
* sélectionne les meilleures coordonnées lorsqu’il y a conflit
* normalise les noms de station
* filtre pour ne garder que les stations situées > 500 m d’altitude
* écrit le fichier final unique: data/metadonnees/stations.json

Ce fichier devient la **source de vérité globale** pour tous les autres pipelines (observations, commandes CSV, Zarr, etc.).



Workflow 3 couches:

| couche                            | rôle                                          |
| --------------------------------- | --------------------------------------------- |
| auth_mf                           | génération brute du token                     |
| token_provider                    | sélection cache vs génération                 |
| fetch_stations + combine_stations | logique métier = récupération + structuration |
