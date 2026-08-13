# Valeurs énumérées

Cette annexe recense les ensembles fermés exposés par les contrats publics
actuels.

## Formats de rapport

Le paramètre `--format` accepte les valeurs suivantes.

| Valeur | Signification | Par défaut | Contraintes |
|---|---|---:|---|
| `text` | Rapport lisible dans un terminal. | Oui | Toutes les commandes de rapport. |
| `json` | Document JSON canonique indenté. | Non | Adapté à l'automatisation. |
| `yaml` | Projection YAML du document canonique. | Non | Adapté à la lecture et aux pipelines. |
| `xml` | Projection XML du document canonique. | Non | Racine `poly-report`. |

Source : `src/poly/cli.py`, constante `REPORT_FORMATS`.

## Types de nœud du manifeste

| Valeur | Signification | Par défaut | Contraintes |
|---|---|---:|---|
| `workspace` | Racine unique de la composition. | Racine seulement | Chemin `.`, sans source ni parent. |
| `repository` | Frontière de source indépendante. | Avec `add --repo` | Seul type autorisé à déclarer `source`. |
| `module` | Unité technique à l'intérieur d'un dépôt. | `poly add` sans `--repo` | N'implique pas un dépôt Git. |

Source : `src/poly/workspace.py`, ensemble `_KINDS`.

## États du lock Git local

| Valeur | Signification | Par défaut | Contraintes |
|---|---|---:|---|
| `current` | `HEAD` correspond exactement au lock. | — | Commit verrouillé disponible. |
| `ahead-of-lock` | Le lock est un ancêtre du `HEAD` local. | — | Cas courant après un pull EGit. |
| `behind-lock` | Le `HEAD` local est un ancêtre du lock. | — | Une hydratation est nécessaire. |
| `diverged` | Aucun commit n'est ancêtre de l'autre. | — | Réparation explicite nécessaire. |
| `locked-commit-unavailable` | L'objet verrouillé n'existe pas localement. | — | Une hydratation peut effectuer un fetch. |

Source : `src/poly/drivers/git.py`, comparaison `_lock_state`.

## État du lock par rapport à la référence distante

| Valeur | Signification | Par défaut | Contraintes |
|---|---|---:|---|
| `current` | La référence distante résout le commit verrouillé. | — | Visible avec `inspect --remote`. |
| `advanced` | La référence distante résout un autre commit. | — | Le lock n'est pas modifié. |

Source : `src/poly/drivers/git.py`, métadonnée `git.remote.lock-state`.

## Types de référence Git verrouillée

| Valeur | Signification | Par défaut | Contraintes |
|---|---|---:|---|
| `branch` | La référence demandée est une branche mobile. | Pour une branche | `update` peut la faire avancer. |
| `tag` | La référence demandée est un tag. | Pour un tag | Le lock conserve le commit immuable résolu. |
| `commit` | La référence demandée est un SHA complet ou une référence directe. | Pour un SHA | Doit être un hash Git complet. |

Source : résolution Git dans `src/poly/drivers/git.py` et schéma du lock.

## États d'un plan

| Valeur | Signification | Par défaut | Contraintes |
|---|---|---:|---|
| `executable` | Le plan est fermé et peut être exécuté. | — | Aucune erreur de négociation. |
| `empty` | Aucune action n'est nécessaire. | — | Exécution réussie sans action. |
| `blocked` | Des contraintes ou diagnostics empêchent l'exécution. | — | Aucune action n'est exécutée. |
| `conflict` | Des actions ou claims sont en conflit. | — | Aucune résolution implicite. |

Source : `src/poly/model.py`, `PlanStatus`.

## États d'une exécution

| Valeur | Signification | Par défaut | Contraintes |
|---|---|---:|---|
| `succeeded` | Toutes les actions exécutables ont réussi. | — | — |
| `failed` | Au moins une action a échoué. | — | Les dépendants restent bloqués. |
| `blocked` | Le plan ou des dépendances empêchent la suite. | — | — |
| `empty` | Le plan ne contenait aucune action. | — | — |

Source : `src/poly/runtime.py`, `RunStatus`.

