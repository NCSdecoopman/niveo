# Lambda d'export des observations (lambda_function.py)

But
- Scanne la table DynamoDB pour exporter les observations.
- Filtre automatiquement les entrées expirées (champ `expires_at`).
- Sérialise en JSON et pousse le fichier vers un dépôt GitHub via l'API (ou, si trop volumineux, pousse une version gzip).

Fonctionnement (étapes)
1. Lecture des variables d'environnement (voir section suivante).
2. _scan_ complet de la table DynamoDB (`_scan_all`) :
   - Possibilité de projection via `DDB_PROJECTION`.
   - Gestion d'un alias `#d` si `date` est présent dans la projection (mot réservé).
   - Conversion des types DynamoDB (Decimal → int/float).
   - Filtrage TTL : ignore les items dont `expires_at` ≤ epoch courant.
3. Tri stable des items pour obtenir des diffs Git lisibles : tri par `(id, date)`.
4. Sérialisation JSON compacte (`ensure_ascii=False`, separators serrés).
5. Récupération du token GitHub depuis Secrets Manager.
6. Envoi vers GitHub :
   - Si le JSON ≤ `MAX_JSON_MB` → mise à jour (ou création) de `GH_PATH`.
   - Sinon → fallback : compression gzip envoyée sur `FALLBACK_GZ_PATH` (si défini), sinon erreur.

Variables d'environnement utilisées
- TABLE_NAME : nom de la table DynamoDB.
- DDB_PROJECTION : (optionnel) projection DDB, ex: `"id,#d,HNEIGEF,NEIGETOT,NEIGETOT06"`.
- GH_OWNER, GH_REPO, GH_BRANCH (défaut `"main"`), GH_PATH : repo / chemin de destination.
- GH_TOKEN_SECRET_ARN : ARN du secret contenant le token GitHub.
- MAX_JSON_MB : taille maxi du JSON en mégaoctets (par défaut 95 dans le code).
- FALLBACK_GZ_PATH : chemin GitHub pour le fichier .json.gz si fallback utilisé.

Comportement GitHub
- Utilise l'API `PUT /repos/{owner}/{repo}/contents/{path}`.
- Commit message : `chore(observations): export daily YYYY-MM-DD [skip ci]`.
- Committer / author : `ncsdecoopman-bot` (email noreply).

Permissions & dépendances IAM requises (voir Terraform)
- dynamodb:Scan sur la table.
- secretsmanager:GetSecretValue sur le secret du token.
- logs: Create/Put pour CloudWatch Logs.
- Lambda runtime : Python 3.12 (code compatible).

Points d'attention
- Si le secret GitHub est manquant ou invalide, la fonction lèvera une exception.
- Si le JSON dépasse la taille et `FALLBACK_GZ_PATH` n'est pas défini → RuntimeError.
- La projection doit utiliser l'alias `#d` pour `date` si `date` est un mot réservé.

# Workflow GitHub Actions — invoke-ddb-export

Ajoute un workflow permettant de déclencher manuellement la Lambda d'export (`ddb-export-observations-to-github`) depuis l'interface GitHub (workflow_dispatch).