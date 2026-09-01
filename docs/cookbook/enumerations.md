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

## Couleurs du rendu interactif

Le paramètre `--color` accepte les valeurs suivantes pour les rapports texte.

| Valeur | Signification | Par défaut | Contraintes |
|---|---|---:|---|
| `auto` | Active les couleurs uniquement sur un terminal compatible. | Oui | `NO_COLOR` désactive les couleurs. |
| `always` | Force les séquences de couleur ANSI. | Non | Réservé au format `text`. |
| `never` | Supprime toute séquence de couleur. | Non | Réservé au format `text`. |

Source : `src/poly/cli.py`, option `--color`.

## Natures publiées par les drivers intégrés

Cet ensemble n'est pas fermé : les drivers externes peuvent publier leurs
propres natures. `poly nature list` donne l'inventaire faisant autorité pour
l'installation courante.

| Valeur intégrée | Signification | Driver |
|---|---|---|
| `git/repository` | Frontière Git observée. | `poly.driver.git` |
| `maven/aggregator` | Projet Maven agrégeant des modules. | `poly.driver.maven` |
| `maven/module` | Projet membre d'un réacteur Maven. | `poly.driver.maven` |
| `maven/project` | Projet décrit par un POM Maven. | `poly.driver.maven` |
| `poly/module` | Nœud de composition de type module. | `poly.constructor` |
| `poly/repository` | Nœud de composition de type repository. | `poly.constructor` |
| `poly/workspace` | Nœud racine du workspace. | `poly.constructor` |

Source : manifestes enregistrés dans `src/poly/construction.py` et
`src/poly/drivers/`.

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
