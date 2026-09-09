# Contributions et préconditions

Cette catégorie explique les contrats consolidés en 0.13.1. Le parcours Eclipse
est pour l'instant une fixture SDK, pas une commande de configuration disponible
pour un workspace utilisateur.

## Table des matières

- [Comment vérifier les contributions disponibles ?](#comment-vérifier-les-contributions-disponibles-)
- [Comment comprendre une action bloquée par ses préconditions ?](#comment-comprendre-une-action-bloquée-par-ses-préconditions-)

## Comment vérifier les contributions disponibles ?

L'inventaire des pilotes expose leur plugin, leurs identités de contributions,
capacités et verbes. Une nature décrit une qualification du nœud ; elle ne
constitue pas une table centrale d'autorisation des verbes. Le pilote décide de
l'applicabilité dans `propose()`.

### Bash

```bash
# Répertoire existant du workspace à examiner
workspace_path="workspace"

poly drivers --workspace "$workspace_path" --format json
```

### PowerShell

```powershell
# Répertoire existant du workspace à examiner
$workspacePath = "workspace"

poly drivers --workspace $workspacePath --format json
```

### Résultat attendu

Le JSON distingue les pilotes chargés et rejetés et expose leurs contributions.
Une contribution déclarée ne garantit pas qu'une action sera proposée pour chaque
nœud. Retirer une nature de `poly.yaml` n'empêche pas un inspecteur de la redétecter.

## Comment comprendre une action bloquée par ses préconditions ?

Consulter le rapport du run permet de distinguer un fait sans producteur, un vrai
cycle et un fait non produit après un échec. Tous les faits requis doivent être
disponibles ; un seul producteur réussi suffit pour chaque fait. Un fait initial
reste disponible, même si une action qui devait aussi le produire échoue.

### Bash

```bash
# Répertoire du workspace ayant produit le rapport
workspace_path="workspace"
# Identifiant réel affiché pour le plan ou le run concerné
run_id="0123456789abcdef0123"

poly report "$run_id" --workspace "$workspace_path" --format json
```

### PowerShell

```powershell
# Répertoire du workspace ayant produit le rapport
$workspacePath = "workspace"
# Identifiant réel affiché pour le plan ou le run concerné
$runId = "0123456789abcdef0123"

poly report $runId --workspace $workspacePath --format json
```

### Résultat attendu

Le rapport conserve les diagnostics et les états des actions. Les rejections
`missing` d'un pilote expliquent une candidature refusée ; elles ne demandent
jamais à Poly de lancer implicitement un autre verbe. Une action bloquée après
l'échec de tous ses producteurs nécessite une nouvelle exécution corrigée.
Un ancien plan gelé conserve ses diagnostics : la correction du planner ne
réécrit pas les rapports historiques.

## Validation

Les commandes d'inventaire et de rapport sont couvertes par les tests CLI
existants ; les préconditions sont exercées par les nouveaux tests séquentiels
et parallèles. Les exemples de rapport ci-dessus sont **Non exécuté** tels quels :
l'identifiant est fictif. Les blocs PowerShell sont vérifiés statiquement ici ;
la CI Windows exécute les tests CLI et la fixture Eclipse.

Le [contrat technique](../architecture/contribution-contracts.md) décrit le flux
SDK façade → résolution du blueprint → proposition du driver → exécution Poly.
L'[exemple Eclipse](../../examples/eclipse-contract/README.md) fournit la recette
de développement testée. La CLI générale hors `add` et le cycle de régénération
restent réservés aux prochains jalons.
