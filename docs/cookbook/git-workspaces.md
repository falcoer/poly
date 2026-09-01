# Composition et cycle Git

Cette catégorie couvre les dépôts indépendants, le lock partagé, l'hydratation
et les évolutions réalisées depuis Eclipse ou un autre client Git.

## Table des matières

- [Comment déclarer puis matérialiser un dépôt Git enfant ?](#comment-déclarer-puis-matérialiser-un-dépôt-git-enfant-)
- [Comment restaurer un workspace complet depuis son dépôt racine ?](#comment-restaurer-un-workspace-complet-depuis-son-dépôt-racine-)
- [Comment réhydrater les dépôts exactement au lock ?](#comment-réhydrater-les-dépôts-exactement-au-lock-)
- [Comment détecter les écarts entre HEAD, le lock et la branche distante ?](#comment-détecter-les-écarts-entre-head-le-lock-et-la-branche-distante-)
- [Comment adopter dans le lock un pull réalisé depuis Eclipse ?](#comment-adopter-dans-le-lock-un-pull-réalisé-depuis-eclipse-)
- [Comment mettre à jour les dépôts depuis leurs branches distantes ?](#comment-mettre-à-jour-les-dépôts-depuis-leurs-branches-distantes-)

## Comment déclarer puis matérialiser un dépôt Git enfant ?

`add --repo` déclare le dépôt, résout la référence et écrit son commit exact dans
le lock sans créer le worktree. `hydrate` matérialise ensuite explicitement la
composition verrouillée. Les fichiers de composition peuvent ainsi être relus
et commités avant tout clone.

### Bash

```bash
# Racine du workspace Poly
workspace_path="poly-demo"
# Identifiant stable du dépôt enfant
node_id="service-api"
# Chemin relatif à la racine du workspace
node_path="services/api"
# URL Git sans identifiants incorporés
repository_url="https://git.example.com/team/service-api.git"
# Branche, tag ou SHA complet ; exemple : main
requested_ref="main"

poly add "$node_id" \
  --workspace "$workspace_path" \
  --path "$node_path" \
  --repo "$repository_url" \
  --ref "$requested_ref"
poly hydrate \
  --workspace "$workspace_path" \
  --select "$node_id"
```

### PowerShell

```powershell
# Racine du workspace Poly
$workspacePath = "poly-demo"
# Identifiant stable du dépôt enfant
$nodeId = "service-api"
# Chemin relatif à la racine du workspace
$nodePath = "services/api"
# URL Git sans identifiants incorporés
$repositoryUrl = "https://git.example.com/team/service-api.git"
# Branche, tag ou SHA complet ; exemple : main
$requestedRef = "main"

poly add $nodeId `
  --workspace $workspacePath `
  --path $nodePath `
  --repo $repositoryUrl `
  --ref $requestedRef
poly hydrate `
  --workspace $workspacePath `
  --select $nodeId
```

### Résultat attendu

Après `add`, aucun répertoire `services/api` n'est créé ; le sélecteur reste
dans `poly.yaml` et son commit exact figure dans `poly.lock.yaml`. Après
`hydrate`, le dépôt est présent sur ce commit et son contenu n'est pas indexable
par le dépôt racine.

### En cas de problème

Une référence introuvable fait échouer `add` sans changement partiel du
manifeste, du lock, de l'état compilé ou du bloc `.gitignore`. Pendant
l'hydratation, Poly refuse une cible non vide qui n'est pas le dépôt attendu, un
`origin` différent, un clone partiel ou un worktree sale nécessitant un déplacement.

## Comment restaurer un workspace complet depuis son dépôt racine ?

Cette forme de `init` clone le dépôt de contrôle, valide ses fichiers de
composition commités, puis hydrate récursivement tous les descendants Git. Elle
ne nécessite aucun `poly add` sur la machine restaurée.

### Bash

```bash
# URL du dépôt racine contenant poly.yaml et poly.lock.yaml commités
root_repository="https://git.example.com/team/workspace.git"
# Nouveau répertoire cible ou répertoire vide
target_path="workspace"
# Référence du dépôt racine
requested_ref="main"

poly init "$root_repository" "$target_path" \
  --ref "$requested_ref"
```

### PowerShell

```powershell
# URL du dépôt racine contenant poly.yaml et poly.lock.yaml commités
$rootRepository = "https://git.example.com/team/workspace.git"
# Nouveau répertoire cible ou répertoire vide
$targetPath = "workspace"
# Référence du dépôt racine
$requestedRef = "main"

poly init $rootRepository $targetPath `
  --ref $requestedRef
```

### Résultat attendu

Le rapport expose les phases `root-bootstrap` et `recursive-hydration`. Chaque
dépôt enfant est positionné sur le commit immuable du lock, y compris lorsqu'il
est imbriqué dans un autre dépôt enfant.

## Comment réhydrater les dépôts exactement au lock ?

`hydrate` restaure les commits partagés. Une hydratation déjà satisfaite est un
no-op. Poly ne déplace pas un worktree sale.

### Bash

```bash
# Racine du workspace à réhydrater
workspace_path="workspace"
# Identifiant facultatif ; chaîne vide signifie tous les nœuds
node_id="service-api"

poly hydrate \
  --workspace "$workspace_path" \
  --select "$node_id"
```

### PowerShell

```powershell
# Racine du workspace à réhydrater
$workspacePath = "workspace"
# Identifiant facultatif ; exemple ciblé
$nodeId = "service-api"

poly hydrate `
  --workspace $workspacePath `
  --select $nodeId
```

### Résultat attendu

Le `HEAD` du dépôt sélectionné correspond au commit de `poly.lock.yaml`. Pour
tous les dépôts, omettre `--select`.

## Comment détecter les écarts entre HEAD, le lock et la branche distante ?

L'inspection locale compare le checkout au lock. `--remote` ajoute une lecture
`git ls-remote`, sans effectuer de `fetch` ni modifier les références locales.

### Bash

```bash
# Racine du workspace à contrôler
workspace_path="workspace"
# Format structuré conseillé pour exploiter les métadonnées
report_format="json"

poly inspect \
  --workspace "$workspace_path" \
  --format "$report_format"
poly inspect \
  --remote \
  --workspace "$workspace_path" \
  --format "$report_format"
```

### PowerShell

```powershell
# Racine du workspace à contrôler
$workspacePath = "workspace"
# Format structuré conseillé pour exploiter les métadonnées
$reportFormat = "json"

poly inspect `
  --workspace $workspacePath `
  --format $reportFormat
poly inspect `
  --remote `
  --workspace $workspacePath `
  --format $reportFormat
```

### Résultat attendu

Les métadonnées `git.lock.state`, `git.remote.commit` et
`git.remote.lock-state` distinguent un checkout courant, avancé, en retard,
divergent ou une branche distante ayant progressé.

## Comment adopter dans le lock un pull réalisé depuis Eclipse ?

Après un pull EGit, le `HEAD` local peut être `ahead-of-lock`. L'adoption est
explicite afin que le dépôt racine montre clairement la nouvelle composition à
commiter.

### Bash

```bash
# Racine du workspace ouvert dans Eclipse
workspace_path="workspace"
# Nœud dont EGit vient d'avancer la branche
node_id="service-api"

poly inspect --workspace "$workspace_path"
poly lock \
  --from-workspace \
  --workspace "$workspace_path" \
  --select "$node_id"
git -C "$workspace_path" diff -- poly.lock.yaml
```

### PowerShell

```powershell
# Racine du workspace ouvert dans Eclipse
$workspacePath = "workspace"
# Nœud dont EGit vient d'avancer la branche
$nodeId = "service-api"

poly inspect --workspace $workspacePath
poly lock `
  --from-workspace `
  --workspace $workspacePath `
  --select $nodeId
git -C $workspacePath diff -- poly.lock.yaml
```

### Résultat attendu

Le lock contient le `HEAD` propre actuellement extrait. Le diff est visible dans
le dépôt racine et peut être relu puis commité avec la composition.

### En cas de problème

La commande refuse un dépôt contenant des modifications non commitées. Il faut
d'abord les commiter ou les mettre de côté avec le client Git choisi.

## Comment mettre à jour les dépôts depuis leurs branches distantes ?

`update` résout les références mobiles, matérialise et vérifie les nouveaux
commits, puis modifie le lock. Celui-ci n'est pas avancé si le checkout échoue.

### Bash

```bash
# Racine du workspace à mettre à jour
workspace_path="workspace"
# Nœud ciblé ; omettre --select pour tous les dépôts
node_id="service-api"

poly update \
  --workspace "$workspace_path" \
  --select "$node_id" \
  --plan
poly update \
  --workspace "$workspace_path" \
  --select "$node_id"
```

### PowerShell

```powershell
# Racine du workspace à mettre à jour
$workspacePath = "workspace"
# Nœud ciblé ; omettre --select pour tous les dépôts
$nodeId = "service-api"

poly update `
  --workspace $workspacePath `
  --select $nodeId `
  --plan
poly update `
  --workspace $workspacePath `
  --select $nodeId
```

### Résultat attendu

La prévisualisation ne change aucun fichier. L'exécution suivante avance le
checkout propre, vérifie son `HEAD` et écrit le nouveau commit dans le lock.
