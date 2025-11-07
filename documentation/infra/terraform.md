# Terraform — déploiement de la Lambda d'export (main.tf)

But
Ce fichier Terraform prépare et déploie la Lambda qui exporte les observations vers GitHub, ainsi que les éléments IAM, packaging et (optionnellement) la planification quotidienne.

Variables principales (avec valeurs par défaut)
- aws_region : région AWS, ex `eu-west-3`.
- table_name : nom de la table DDB (par défaut `Observations`).
- repo_owner, repo_name, branch : dépôt GitHub cible.
- secret_name : préfixe du secret contenant le token GitHub.
- enable_schedule : booléen prévu pour activer la planification (false par défaut).

Packaging
- data.archive_file.lambda_zip : zippe `lambda_function.py` en `lambda.zip` pour déploiement.

IAM
- aws_iam_role.lambda_role : rôle assumé par la Lambda.
- aws_iam_policy.lambda_policy : politique qui autorise :
  - `dynamodb:Scan` sur la table (ARN construit depuis variables).
  - `secretsmanager:GetSecretValue` sur le secret (préfixe).
  - permissions Logs (CreateLogGroup/CreateLogStream/PutLogEvents).
- L'attachement role↔policy est fait via aws_iam_role_policy_attachment.

Lambda
- aws_lambda_function.exporter :
  - function_name `ddb-export-observations-to-github`
  - runtime `python3.12`, handler `lambda_function.lambda_handler`
  - zip packagé depuis `data.archive_file.lambda_zip`
  - timeout 900s, memory 512MiB, KMS key `alias/aws/lambda`
  - variables d'environnement (voir fichier `lambda_function.py` pour usage)
  - dépend de l'attachement IAM.

Logs
- aws_cloudwatch_log_group.lg : création d'un log group dédié (rétention 7 jours). Créé avant exécution (dépendance).

Planification (EventBridge)
- aws_cloudwatch_event_rule.daily : règle cron quotidienne `cron(0 7 * * ? *)` (07:00 UTC).
- aws_cloudwatch_event_target.tgt : cible la Lambda.
- aws_lambda_permission.allow_events_daily : autorise Events à invoquer la fonction (statement_id unique via md5(timestamp())).

Usage / déploiement rapide
1. Ajuster les variables (provider, table, secret name, repo).
2. terraform init && terraform apply.

Remarques pratiques
- Le packaging actuel zippe uniquement `lambda_function.py`. Si la Lambda nécessite des dépendances, il faut les inclure dans le zip (layer ou packaging local).
- Vérifier que le secret GitHub existe avec le nom / ARN attendu.
- `enable_schedule` est prévu pour l'optionnalité ; vérifier la logique si on souhaite activer/désactiver la règle cron via une condition Terraform.

# Workflow GitHub Actions — deploy-aws-export

Ajoute un workflow permettant de déployer / appliquer le Terraform sur AWS qui provisionne la Lambda d'export à chaque fois que export/ est changé.