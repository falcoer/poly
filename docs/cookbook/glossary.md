# Glossaire

## Action

Opération complètement décrite dans un plan gelé. L'exécuteur applique les
actions sans en inventer de nouvelles.

## Composition

Arbre de nœuds déclaré dans `poly.yaml`. Il décrit l'intention du workspace,
indépendamment de l'état local actuellement observé.

## Contrôleur

Capacité d'exécution locale ou distante choisie pour prendre en charge une
action. Le contrôleur local expose notamment l'exécution de processus, la
construction et la matérialisation Git.

## Driver

Extension technologique qui inspecte des nœuds, propose des actions et,
éventuellement, les exécute. Git, Maven et le constructeur sont les drivers
intégrés actuels.

## Hydratation

Restauration des dépôts enfants déclarés aux commits exacts de
`poly.lock.yaml`. Voir [réhydrater les dépôts](git-workspaces.md#comment-réhydrater-les-dépôts-exactement-au-lock-).

## Lock

Fichier `poly.lock.yaml` généré et commité qui associe chaque source enfant à un
commit immuable. Il représente la référence reproductible partagée, pas un
miroir continuellement mis à jour des worktrees locaux.

## Manifeste

Fichier `poly.yaml` écrit à la racine et commité par le dépôt de contrôle. Il est
la source d'intention pour les identifiants, chemins, parents, types et sources.

## Module

Unité technique dans une frontière de source, par exemple un module Maven. Un
module ne constitue pas automatiquement un dépôt Git indépendant.

## Nature

Caractéristique déclarée ou détectée d'un nœud, telle que `git/repository`,
`maven/project` ou `maven/reactor`. Elle détermine les verbes applicables.

## Nœud

Identité stable et sélectionnable de la composition. Les observations Git et
Maven enrichissent cette même identité au lieu d'en créer une concurrente.

## Plan

Ensemble fini et déterministe d'actions, de contraintes et de diagnostics créé
avant toute exécution. `--plan` permet de le consulter sans effets de bord.

## Référence demandée

Branche, tag ou SHA indiqué par `source.ref`. La résolution courante devient un
commit immuable dans le lock.

## Repository

Nœud représentant une frontière de versionnement indépendante. Les repositories
enfants sont des dépôts Git ordinaires, exclus de l'index racine et jamais des
submodules implicites.

## Workspace

Racine logique possédant la composition commitée, le lock et le bloc
`.gitignore` géré par Poly. L'état sous `.poly/` est local et reconstructible.

