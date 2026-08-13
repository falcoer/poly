# Prise en main et inspection

Cette catégorie couvre la création d'une composition locale et la découverte
des fonctions disponibles.

## Table des matières

- [Comment initialiser un workspace local vide ?](#comment-initialiser-un-workspace-local-vide-)
- [Comment inspecter la composition et les technologies détectées ?](#comment-inspecter-la-composition-et-les-technologies-détectées-)
- [Comment connaître les drivers et contrôleurs disponibles ?](#comment-connaître-les-drivers-et-contrôleurs-disponibles-)
- [Comment ajouter puis retirer un module structurel ?](#comment-ajouter-puis-retirer-un-module-structurel-)

## Comment initialiser un workspace local vide ?

`poly init` initialise un répertoire existant. Il crée les fichiers de
composition commitables et l'état local reconstructible, sans exiger que la
racine soit déjà un dépôt Git.

### Bash

```bash
# Répertoire existant à initialiser ; chemin absolu ou relatif
workspace_path="../poly-demo"
# Nom humain du workspace ; chaîne non vide
workspace_name="Poly Demo"

mkdir -p "$workspace_path"
uv run poly init \
  --workspace "$workspace_path" \
  --name "$workspace_name"
```

### PowerShell

```powershell
# Répertoire existant à initialiser ; chemin absolu ou relatif
$workspacePath = "../poly-demo"
# Nom humain du workspace ; chaîne non vide
$workspaceName = "Poly Demo"

New-Item -ItemType Directory -Path $workspacePath -Force | Out-Null
uv run poly init `
  --workspace $workspacePath `
  --name $workspaceName
```

### Résultat attendu

Le répertoire contient `poly.yaml`, `poly.lock.yaml`, `.gitignore` et un
répertoire `.poly/`. Seuls les trois premiers éléments sont destinés au dépôt
racine. Relancer la commande réconcilie l'état généré sans modifier la
composition déclarée.

## Comment inspecter la composition et les technologies détectées ?

`poly inspect` compile le manifeste, vérifie le lock et enrichit les identités
déclarées avec les observations Git et Maven. L'inspection locale ne contacte
aucun dépôt distant.

### Bash

```bash
# Racine d'un workspace Poly initialisé
workspace_path="../poly-demo"
# Format : text, json, yaml ou xml
report_format="json"

uv run poly inspect \
  --workspace "$workspace_path" \
  --format "$report_format"
```

### PowerShell

```powershell
# Racine d'un workspace Poly initialisé
$workspacePath = "../poly-demo"
# Format : text, json, yaml ou xml
$reportFormat = "json"

uv run poly inspect `
  --workspace $workspacePath `
  --format $reportFormat
```

### Résultat attendu

Le rapport contient les nœuds, leurs natures, leurs relations, leurs métadonnées
et les verbes applicables. Il reconstruit aussi `.poly/state/inventory.json`.

## Comment connaître les drivers et contrôleurs disponibles ?

Les commandes de gestion `drivers` et `controllers` décrivent respectivement
les extensions technologiques enregistrées et les capacités d'exécution
disponibles.

### Bash

```bash
# Racine du workspace à utiliser comme contexte
workspace_path="../poly-demo"

uv run poly drivers --workspace "$workspace_path"
uv run poly controllers --workspace "$workspace_path"
uv run poly actions --workspace "$workspace_path"
```

### PowerShell

```powershell
# Racine du workspace à utiliser comme contexte
$workspacePath = "../poly-demo"

uv run poly drivers --workspace $workspacePath
uv run poly controllers --workspace $workspacePath
uv run poly actions --workspace $workspacePath
```

### Résultat attendu

Poly affiche les drivers `poly.constructor`, `poly.driver.git` et
`poly.driver.maven`, le contrôleur local et le catalogue des actions
actuellement négociables.

## Comment ajouter puis retirer un module structurel ?

Un [module](glossary.md#module) décrit une unité technique, sans créer une
nouvelle frontière Git. `remove` ne supprime jamais son répertoire physique et
refuse un nœud qui possède encore des enfants.

### Bash

```bash
# Racine du workspace Poly
workspace_path="../poly-demo"
# Identifiant stable sans espace
node_id="api-reactor"
# Chemin relatif au parent
node_path="modules/api"

uv run poly add "$node_id" \
  --workspace "$workspace_path" \
  --path "$node_path" \
  --nature maven/reactor
uv run poly remove "$node_id" --workspace "$workspace_path"
```

### PowerShell

```powershell
# Racine du workspace Poly
$workspacePath = "../poly-demo"
# Identifiant stable sans espace
$nodeId = "api-reactor"
# Chemin relatif au parent
$nodePath = "modules/api"

uv run poly add $nodeId `
  --workspace $workspacePath `
  --path $nodePath `
  --nature maven/reactor
uv run poly remove $nodeId --workspace $workspacePath
```

### Résultat attendu

La première commande ajoute le nœud à `poly.yaml`. La seconde retire seulement
sa déclaration ; aucun répertoire utilisateur n'est effacé.

