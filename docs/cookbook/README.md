# Cookbook Poly

Ce cookbook propose un tour pratique de Poly 0.10.1, depuis la création d'un
workspace jusqu'à son hydratation Git et à l'exécution de jobs. Les exemples
utilisent l'interface publique réellement exposée par la CLI.

## Prérequis généraux

- la commande `poly` est disponible conformément à la
  [procédure d'installation](../../README.md#installation) ;
- les exemples sont lancés depuis un répertoire de travail pouvant recevoir les
  dossiers `poly-demo` ou `workspace` ;
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

## Validation des exemples

| Périmètre | Validation |
|---|---|
| Initialisation, inspection et composition locale | Exécuté par les tests CLI. |
| Ajout atomique sans worktree, résolution, hydratation et mise à jour Git | Exécuté avec des dépôts Git locaux temporaires. |
| Pull externe puis `lock --from-workspace` | Exécuté avec le même effet qu'un pull EGit. |
| Bootstrap récursif depuis un dépôt racine | Exécuté avec deux dépôts enfants imbriqués. |
| URL `git.example.com` des recettes | **Non exécuté** : serveur volontairement fictif à remplacer. |
| Exemples PowerShell | Vérifiés statiquement contre les mêmes options CLI ; non exécutés faute de PowerShell dans l'environnement de validation. |
