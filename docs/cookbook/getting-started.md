# Prise en main et inspection

Cette catégorie couvre la création d'une composition locale et la découverte
des fonctions disponibles.

## Table des matières

- [Comment initialiser un workspace local vide ?](#comment-initialiser-un-workspace-local-vide-)
- [Comment inspecter la composition et les technologies détectées ?](#comment-inspecter-la-composition-et-les-technologies-détectées-)
- [Comment connaître les drivers et contrôleurs disponibles ?](#comment-connaître-les-drivers-et-contrôleurs-disponibles-)
- [Comment lister et modifier les natures du nœud courant ?](#comment-lister-et-modifier-les-natures-du-nœud-courant-)
- [Comment ajouter puis retirer un module structurel ?](#comment-ajouter-puis-retirer-un-module-structurel-)

## Comment initialiser un workspace local vide ?

`poly init` initialise un répertoire existant. Il crée les fichiers de
composition commitables et l'état local reconstructible, sans exiger que la
racine soit déjà un dépôt Git.

### Bash

```bash
# Répertoire existant à initialiser ; chemin absolu ou relatif
workspace_path="poly-demo"
# Nom humain du workspace ; chaîne non vide
workspace_name="Poly Demo"

mkdir -p "$workspace_path"
poly init \
  --workspace "$workspace_path" \
  --name "$workspace_name"
```

### PowerShell

```powershell
# Répertoire existant à initialiser ; chemin absolu ou relatif
$workspacePath = "poly-demo"
# Nom humain du workspace ; chaîne non vide
$workspaceName = "Poly Demo"

New-Item -ItemType Directory -Path $workspacePath -Force | Out-Null
poly init `
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
workspace_path="poly-demo"
# Format : text, json, yaml ou xml
report_format="json"

poly inspect \
  --workspace "$workspace_path" \
  --format "$report_format"
```

### PowerShell

```powershell
# Racine d'un workspace Poly initialisé
$workspacePath = "poly-demo"
# Format : text, json, yaml ou xml
$reportFormat = "json"

poly inspect `
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
workspace_path="poly-demo"

poly drivers --workspace "$workspace_path"
poly controllers --workspace "$workspace_path"
poly actions --workspace "$workspace_path"
```

### PowerShell

```powershell
# Racine du workspace à utiliser comme contexte
$workspacePath = "poly-demo"

poly drivers --workspace $workspacePath
poly controllers --workspace $workspacePath
poly actions --workspace $workspacePath
```

### Résultat attendu

Poly affiche les drivers `poly.constructor`, `poly.driver.git` et
`poly.driver.maven`, le contrôleur local et le catalogue des actions
actuellement négociables.

`poly drivers` inventorie ces drivers même lorsque le répertoire de contexte ne
contient encore aucun nœud.

## Comment lister et modifier les natures du nœud courant ?

`poly nature list` affiche dans l'ordre alphabétique les natures publiées par les
drivers chargés. Depuis un sous-répertoire, `nature add` et `nature remove`
retrouvent le workspace parent le plus proche et le nœud déclaré le plus précis.
Un `.` explicite désigne ce nœud courant ; plusieurs natures peuvent être
modifiées dans la même commande.

### Bash

```bash
# Répertoire d'un nœud déjà déclaré dans le workspace
node_path="workspace/modules/api"

cd "$node_path"
poly nature list
poly nature add . maven/reactor java/project
poly nature remove . java/project
```

### PowerShell

```powershell
# Répertoire d'un nœud déjà déclaré dans le workspace
$nodePath = "workspace/modules/api"

Set-Location $nodePath
poly nature list
poly nature add . maven/reactor java/project
poly nature remove . java/project
```

### Résultat attendu

Le manifeste du workspace parent conserve `maven/reactor` sur le nœud courant.
Les deux modifications apparaissent comme des jobs planifiés et reportables ;
aucun chemin de workspace n'est requis sur la commande.

## Comment ajouter puis retirer un module structurel ?

Un [module](glossary.md#module) décrit une unité technique, sans créer une
nouvelle frontière Git. `remove` ne supprime jamais son répertoire physique et
refuse un nœud qui possède encore des enfants.

### Bash

```bash
# Racine du workspace Poly
workspace_path="poly-demo"
# Identifiant stable sans espace
node_id="api-reactor"
# Chemin relatif au parent
node_path="modules/api"

poly add module "$node_id" \
  --workspace "$workspace_path" \
  --path "$node_path" \
  --nature maven/reactor
poly remove "$node_id" --workspace "$workspace_path"
```

### PowerShell

```powershell
# Racine du workspace Poly
$workspacePath = "poly-demo"
# Identifiant stable sans espace
$nodeId = "api-reactor"
# Chemin relatif au parent
$nodePath = "modules/api"

poly add module $nodeId `
  --workspace $workspacePath `
  --path $nodePath `
  --nature maven/reactor
poly remove $nodeId --workspace $workspacePath
```

### Résultat attendu

La première commande ajoute le nœud à `poly.yaml`. La seconde retire seulement
sa déclaration ; aucun répertoire utilisateur n'est effacé.
