# Préparer Eclipse — Poly 0.13.2

## Profil livré : navigation de la composition

La commande crée un projet Eclipse général regroupant les répertoires des nœuds
sélectionnés sous forme de dossiers liés. Les nœuds Git et Maven qui désignent le
même répertoire produisent un seul lien. Les noms des liens sont stables, avec un
suffixe dérivé du chemin pour éviter les collisions entre modules homonymes.

Ce profil sert à parcourir et éditer une composition Poly hétérogène. Il ne
configure ni compilation Java, ni classpath m2e/PDE, ni préférences globales,
working sets, JDK, installation Eclipse ou lancement. Pour les services Java,
l'import Maven ou PDE reste une opération distincte dans Eclipse.

## Prévisualiser et générer

Depuis la racine d'un workspace déjà hydraté :

```powershell
poly inspect
poly configure eclipse --name qc2-p17-navigation --plan --format json
poly configure eclipse --name qc2-p17-navigation
```

Sans sélection explicite, la première génération retient tous les nœuds inspectés
hors racine et répertoire `.eclipse`. Tous leurs répertoires doivent exister.
Pour limiter le périmètre, ajouter `--select <identifiant>` aux deux commandes ;
`--select` accepte plusieurs occurrences ou une liste séparée par des virgules.
La racine elle-même est refusée pour éviter un lien récursif vers le projet généré.

Le JSON du plan contient dans `planned_actions[].environment.POLY_ECLIPSE_CHANGES`
un objet JSON sérialisé décrivant `files` (chemins et contenu exact), `changes`
(`create`, `update`, `unchanged`), `inputs` (empreintes attendues) et `directories`
(cibles des liens). `--plan` n'écrit aucun fichier de configuration Eclipse.
Comme les autres commandes Poly, il peut enregistrer un rapport dans `.poly`.

La syntaxe générique équivalente reste disponible :

```powershell
poly run configure --parameter tool=eclipse
```

`--prepare` enregistre une intention différée ; `poly exec` la résout puis exécute
un plan fini. Un aperçu `--plan` n'est pas une transaction réservant les fichiers
pour une future commande : la commande suivante replanifie avec les entrées courantes.

## Ouvrir dans Eclipse

1. Ouvrir un workspace Eclipse, puis **File > Import > General > Existing Projects
   into Workspace**.
2. Choisir le répertoire `<workspace Poly>/.eclipse` comme racine à importer.
3. Sélectionner le projet de navigation et laisser **Copy projects into workspace**
   décoché : la position du projet détermine les chemins relatifs des liens.
4. Parcourir les dossiers dans **Project Explorer**. Après régénération, rafraîchir
   le projet ; le fermer/réouvrir si Eclipse conserve l'ancienne description.

Les liens utilisent `PARENT-1-PROJECT_LOC`, sans chemin machine absolu ni variable à
configurer. Les espaces, accents et caractères URI sont encodés dans le XML.
Ils pointent vers les vrais fichiers : modifier ou supprimer leur contenu agit sur
les sources. Voir les documentations Eclipse sur les
[ressources liées](https://help.eclipse.org/latest/topic/org.eclipse.platform.doc.user/concepts/concepts-13.htm)
et les [variables de chemin](https://help.eclipse.org/latest/topic/org.eclipse.platform.doc.user/concepts/cpathvars.htm).

## Propriété et régénération

| Fichier/périmètre | Propriétaire | Politique |
| --- | --- | --- |
| `poly.eclipse.json` | Utilisateur, configuration partagée | Créé une fois ; jamais remplacé automatiquement. |
| `.eclipse/.project` | Driver Eclipse | Généré entièrement ; remplacement seulement si l'empreinte de provenance est intacte. |
| Autres fichiers et configurations des projets | Utilisateur ou outil d'origine | Hors du périmètre de génération. |
| Workspace Eclipse, `.metadata`, paramètres machine | Eclipse/utilisateur | Aucune génération ni synchronisation. |

Conserver `poly.eclipse.json` dans le dépôt racine. `.eclipse/.project` est portable :
on peut le versionner ou le régénérer à partir du profil. Exemple de profil :

```json
{
  "schema": "poly.eclipse/v1",
  "profile": "navigation",
  "project_name": "qc2-p17-navigation",
  "nodes": ["maven:services/api", "git:web"]
}
```

Adapter les identifiants à `poly inspect`. Après la première génération, modifier
ce fichier pour changer le nom ou la sélection, puis relancer :

```powershell
poly configure eclipse --plan --format json
poly configure eclipse
```

Une régénération identique conserve contenu et dates de modification. Le profil
et la provenance restent utilisables sans `.poly`. Il n'y a pas de blueprint
supplémentaire : le seul profil supporté ne nécessite pas un catalogue paramétrable.

Une modification manuelle de `.eclipse/.project`, y compris une réécriture par
Eclipse, entraîne un refus explicite. Sauvegarder le fichier ailleurs avant de le
retirer et de régénérer ; ne pas modifier son empreinte pour contourner le contrôle.
Les personnalisations doivent rester dans les fichiers hors du périmètre géré.

## Conflits, échecs et suppression

Un profil invalide, un fichier non géré, une sélection manquante ou un répertoire
non hydraté produit un candidat rejeté avec sa cause et une action bloquée sur la
précondition `eclipse/configuration/valid`. Poly retourne un échec ; il ne lance
aucune hydratation implicite. L'action bloquée refuse aussi toute exécution directe.

Le plan fige les contenus et les empreintes du profil, du `.project`, de
`poly.yaml` et de `poly.lock.yaml`. L'exécution contrôle ces empreintes et les
répertoires avant toute écriture. Une édition intervenue depuis la planification
impose de revoir un nouveau plan. Les liens symboliques et jonctions sur les chemins
concernés sont refusés. Les claims `file/write` déclarent les fichiers affectés ;
la ressource d'exécution sérialise les actions Eclipse d'un même plan.

Chaque fichier livré est exposé dans les sorties normales de l'action, y compris
en cas de livraison partielle. Le profil est créé avant le projet ; un échec
d'écriture peut être repris en replanifiant. Le remplacement du projet est atomique
par fichier ; aucune transaction globale ni verrou interprocessus contre un
éditeur externe n'est promis. Fermer le projet pendant la régénération évite une
écriture concurrente d'Eclipse.

Aucune suppression automatique n'est livrée. Pour retirer cette préparation,
fermer le projet et retirer uniquement `.eclipse/.project` après vérification ou
sauvegarde, puis éventuellement `poly.eclipse.json`. Ne pas supprimer le contenu
des dossiers liés. Les fichiers supplémentaires dans `.eclipse` sont préservés.

## Validation

Les tests couvrent CLI, SDK, XML, chemins portables, sélection persistante,
collisions, éditions concurrentes détectables et régénération sans modification.
La matrice CI exécute ces tests sous Linux et Windows. La recette interactive sur
le workspace Eclipse réel reste nécessaire avant clôture et tag du jalon.
