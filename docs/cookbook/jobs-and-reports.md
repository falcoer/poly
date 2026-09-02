# Planification, exécution et rapports

Cette catégorie couvre les verbes technologiques, les plans sans effet de bord,
les sélections et les rapports persistés.

## Table des matières

- [Comment prévisualiser puis exécuter un job ?](#comment-prévisualiser-puis-exécuter-un-job-)
- [Comment suivre une opération longue ?](#comment-suivre-une-opération-longue-)
- [Comment vérifier un module Maven précis ?](#comment-vérifier-un-module-maven-précis-)
- [Comment consulter le statut de tous les dépôts Git ?](#comment-consulter-le-statut-de-tous-les-dépôts-git-)
- [Comment relire un rapport persistant dans un autre format ?](#comment-relire-un-rapport-persistant-dans-un-autre-format-)

## Comment prévisualiser puis exécuter un job ?

Tous les verbes directs acceptent `--plan` pour une prévisualisation isolée.
`--prepare` ajoute leurs actions au plan courant unique ; `poly plan` le relit
et `poly exec` exécute exactement sa version persistée.

### Bash

```bash
# Racine du workspace
workspace_path="workspace"
# Verbe disponible, par exemple status ou verify
verb="status"

poly "$verb" --workspace "$workspace_path" --prepare
poly plan --workspace "$workspace_path"
poly exec --workspace "$workspace_path"
```

### PowerShell

```powershell
# Racine du workspace
$workspacePath = "workspace"
# Verbe disponible, par exemple status ou verify
$verb = "status"

poly $verb --workspace $workspacePath --prepare
poly plan --workspace $workspacePath
poly exec --workspace $workspacePath
```

### Résultat attendu

Les deux premières commandes n'ont aucun effet sur les sources. La troisième
exécute le plan affiché sans relancer l'inspection ni la planification.

## Comment suivre une opération longue ?

Le format texte interactif affiche et vide immédiatement le titre de la
commande et le plan figé. Chaque action affiche ensuite `RUNNING` au démarrage,
puis `OK`, `KO` ou `WARN` dès que son état terminal est connu. Le résumé final
n'est donc plus le premier retour visible d'un `hydrate`, d'un build ou d'un
test long.

### Bash

```bash
poly hydrate --workspace workspace
```

### PowerShell

```powershell
poly hydrate --workspace workspace
```

### Résultat attendu

Les lignes arrivent au fil de l'eau dans le terminal. `-q` conserve uniquement
le résultat final ; `-v` ajoute la commande exacte et les sorties de processus ;
`-vv` ajoute le rapport canonique complet en fin d'exécution. Les formats
`json`, `yaml` et `xml` restent émis en un document complet, sans lignes de
progression intercalées.

## Comment vérifier un module Maven précis ?

Le driver Maven sélectionne le plus haut réacteur local utilisable et construit
une commande `mvn -pl ... -am verify`. L'identifiant sélectionné est celui de
l'inventaire Poly, pas nécessairement le chemin du module.

### Bash

```bash
# Racine contenant les POM inspectés
workspace_path="workspace"
# Identifiant stable du module déclaré ou inspecté
node_id="service-api-reactor"

poly inspect --workspace "$workspace_path"
poly verify \
  --workspace "$workspace_path" \
  --select "$node_id" \
  --plan
poly verify \
  --workspace "$workspace_path" \
  --select "$node_id"
```

### PowerShell

```powershell
# Racine contenant les POM inspectés
$workspacePath = "workspace"
# Identifiant stable du module déclaré ou inspecté
$nodeId = "service-api-reactor"

poly inspect --workspace $workspacePath
poly verify `
  --workspace $workspacePath `
  --select $nodeId `
  --plan
poly verify `
  --workspace $workspacePath `
  --select $nodeId
```

### Résultat attendu

Le plan montre la commande Maven exacte. L'exécution utilise un dépôt Maven
local au run afin de rendre les matérialisations et dépendances explicites.

## Comment consulter le statut de tous les dépôts Git ?

`status` négocie une action par nœud de nature `git/repository`. Les nœuds non
Git restent visibles comme candidats rejetés sans empêcher les actions valides.

### Bash

```bash
# Racine du workspace
workspace_path="workspace"
# Format de rapport : text, json, yaml ou xml
report_format="text"

poly status \
  --workspace "$workspace_path" \
  --format "$report_format"
```

### PowerShell

```powershell
# Racine du workspace
$workspacePath = "workspace"
# Format de rapport : text, json, yaml ou xml
$reportFormat = "text"

poly status `
  --workspace $workspacePath `
  --format $reportFormat
```

### Résultat attendu

Le rapport contient la sortie `git status --short --branch` et l'état de chaque
action Git planifiée.

## Comment relire un rapport persistant dans un autre format ?

Les plans et exécutions sont persistés sous `.poly/runs/<plan-id>/`. `report`
rend le même document canonique dans l'un des quatre formats publics.

### Bash

```bash
# Racine du workspace ayant exécuté le job
workspace_path="workspace"
# Identifiant affiché sur la ligne « Plan: » du rapport précédent
run_id="0123456789abcdef0123"
# Format cible : text, json, yaml ou xml
report_format="yaml"

poly report "$run_id" \
  --workspace "$workspace_path" \
  --format "$report_format"
```

### PowerShell

```powershell
# Racine du workspace ayant exécuté le job
$workspacePath = "workspace"
# Identifiant affiché sur la ligne « Plan: » du rapport précédent
$runId = "0123456789abcdef0123"
# Format cible : text, json, yaml ou xml
$reportFormat = "yaml"

poly report $runId `
  --workspace $workspacePath `
  --format $reportFormat
```

### Résultat attendu

Poly restitue le plan ou le rapport final correspondant. Remplacer l'identifiant
d'exemple par celui réellement affiché lors du job.
