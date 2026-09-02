# Cookbook Poly

Ce cookbook propose un tour pratique de Poly 0.12.0, depuis la création d'un
workspace jusqu'à son hydratation Git et à l'exécution de jobs. Les exemples
utilisent l'interface publique réellement exposée par la CLI.

Le parcours de validation 0.12 depuis les artefacts CI, sans checkout des
sources de Poly, est détaillé dans [les notes 0.12.0](../releases/0.12.0.md).
Le parcours des pilotes installés, de leur inventaire et de leur verbe direct
est détaillé dans [la documentation des pilotes externes](../drivers/external.md).

## Prérequis généraux

- la commande `poly` est disponible conformément à la
  [procédure d'installation](../../README.md#installation) ;
- les exemples sont lancés depuis un répertoire de travail simple pouvant
  recevoir `poly-demo`, `workspace`, `poly-dist` ou `poly-fixture` ;
- les dépôts Git privés utilisent l'authentification déjà configurée dans Git,
  sans identifiant incorporé dans les URL.

## Table des matières

- [Prise en main et inspection](getting-started.md)
- [Composition et cycle Git](git-workspaces.md)
- [Planification, exécution et rapports](jobs-and-reports.md)
- [Valeurs énumérées](enumerations.md)
- [Glossaire](glossary.md)

## Parcours conseillé

1. [Initialiser un workspace local](getting-started.md#comment-initialiser-un-workspace-local-vide-).
2. [Déclarer puis hydrater un dépôt enfant](git-workspaces.md#comment-déclarer-puis-matérialiser-un-dépôt-git-enfant-).
3. [Inspecter l'état local et distant](git-workspaces.md#comment-détecter-les-écarts-entre-head-le-lock-et-la-branche-distante-).
4. [Simuler un pull EGit et adopter son résultat](git-workspaces.md#comment-adopter-dans-le-lock-un-pull-réalisé-depuis-eclipse-).
5. [Planifier puis exécuter un job](jobs-and-reports.md#comment-prévisualiser-puis-exécuter-un-job-).
6. Pour une recette de release reproductible, télécharger le wheel et la fixture
   retenus, vérifier `SHA256SUMS`, installer le wheel et exécuter le script POSIX
   ou PowerShell fourni dans la fixture. Les deux scripts appellent la même
   logique d'acceptation et produisent les mêmes preuves canoniques.

## Validation des exemples

| Périmètre | Validation |
|---|---|
| Initialisation, inspection et composition locale | Exécuté par les tests CLI. |
| Ajout atomique sans worktree, résolution, hydratation et mise à jour Git | Exécuté avec des dépôts Git locaux temporaires. |
| Pull externe puis `lock --from-workspace` | Exécuté avec le même effet qu'un pull EGit. |
| Bootstrap récursif depuis un dépôt racine | Exécuté avec plusieurs dépôts enfants indépendants et commits verrouillés. |
| Réacteur Maven multi-module | Exécuté réellement sous Linux et Windows par l'acceptation 0.12. |
| Pilote externe installé depuis wheel | Exécuté dans les clean rooms sans checkout des sources Poly. |
| Suppression/reconstruction de `.poly/` et seconde hydratation | Exécuté avec comparaison d'inventaire, hashes, index Git, HEAD et états Git. |
| Rapports texte, JSON, YAML et XML | Récupérés via `poly report <run-id>` et contrôlés pour parité sémantique. |
| URL `git.example.com` des recettes génériques | **Non exécuté** : serveur volontairement fictif à remplacer. |
| Parcours PowerShell 0.12 | Exécuté réellement sur `windows-latest`; Python est forcé en UTF-8 pour préserver les glyphes des rapports textuels redirigés. |
| Parcours POSIX 0.12 | Exécuté réellement sur `ubuntu-latest`. |

La fixture d'acceptation est une donnée de test versionnée par sa construction
déterministe. Les wheels, rapports et preuves sont des artefacts CI générés. Les
données persistantes d'un workspace réel restent `poly.yaml`, `poly.lock.yaml`
et le bloc `.gitignore` racine; `.poly/` reste reconstructible et jetable.
