# Eclipse : import réel, headless et working sets

Date : 2026-09-09. Statut : exigences utilisateur actées ; conception proposée
pour compléter la 0.13.2. Les mécanismes décrits ici ne sont pas encore implémentés.

## Résultat attendu

Le workspace Eclipse doit contenir de vrais projets enregistrés et ouverts,
localisés dans les répertoires sources existants, avec leurs natures et
configurations techniques. Le projet de navigation à dossiers liés de la PR #26
est un prototype insuffisant pour accepter le jalon.

Trois exigences sont obligatoires :

1. Importer complètement les projets et identifier leurs natures.
2. Prévoir et implémenter l'import automatisé dans le workspace cible par Eclipse
   headless, sans importer manuellement chaque projet dans l'IDE.
3. Définir une convention persistante et configurable de working sets.

## Qualification et import

Les inspecteurs restent propriétaires de la qualification. Le driver Eclipse
observe les descriptions Eclipse existantes ; les observations Maven/Java/PDE
et les relations de composition contribuent à sa décision d'import. Les natures
Poly orientent l'élection de la capacité ; elles ne remplacent pas les identifiants
de natures Eclipse ni la vérification des outils installés.

| Situation observée | Import attendu |
| --- | --- |
| `.project` existant | Charger la description, conserver nom, natures, builders et références ; enregistrer le projet à son emplacement réel. |
| Maven avec `pom.xml` | Utiliser l'import/configuration m2e ; vérifier les natures et configurateurs requis après import. |
| Maven/Tycho et projet PDE | Conserver la description existante et vérifier PDE/Tycho selon le type ; ne pas réduire un plugin ou une feature à un projet Java générique. |
| Java sans Maven | Respecter les descriptions/classpaths existants ; exiger les informations manquantes avant de créer une configuration JDT. |
| Projet sans configurateur connu | Import général seulement si demandé explicitement ; signaler la qualification incomplète. |

Un même chemin canonique observé par plusieurs drivers correspond à un seul projet
Eclipse. Préserver le nom `.project` lorsqu'il existe. Pour un projet Maven nouveau,
retenir le nom issu de l'importeur et contrôler les collisions avant application.
Une collision impose une correspondance explicite persistée ; aucun suffixe opaque
automatique n'est ajouté aux noms de projets. Les renvois vers des noms de projets
doivent rester cohérents.

La sélection d'un dépôt peut couvrir plusieurs projets. La liste complète des
projets et la fermeture nécessaire des modules/références sont présentées avant
gel du plan. Une dépendance hors sélection est diagnostiquée ou incluse selon une
politique explicite. Aucune découverte pendant l'exécution ne doit étendre le plan.

## Exécution headless

Poly conserve la planification finie, les préconditions, les ressources exclusives,
le timeout, l'annulation et les journaux. Un adaptateur Eclipse exécuté dans Equinox
réalise les opérations via les API de workspace et les importeurs techniques.
Cela reste une capacité du driver Eclipse, sans nouveau type de contribution Poly.

La commande Eclipse utilisera notamment `-application <application d'import>` et
`-data <workspace Eclipse>`. L'application d'import doit être réellement fournie,
versionnée et disponible dans l'installation cible : `-application` n'invente pas
un importeur générique. L'empaquetage de l'adaptateur et sa compatibilité avec le
produit Eclipse cible devront être prouvés avant de livrer la commande publique.

Entrées explicites : installation Eclipse, workspace Eclipse cible, requête
d'import figée et configuration machine nécessaire. Les chemins d'installation,
JDK, proxy et dépôts Maven locaux ne sont pas inscrits dans le profil partagé.
L'adaptateur contrôle la présence des bundles requis (Resources, JDT, m2e, PDE,
configurateurs selon la sélection) ; l'absence produit un diagnostic actionnable.
Aucune installation silencieuse de plugins n'est ajoutée à l'import.

Le workspace cible doit être disponible : respecter le verrou Eclipse et refuser
l'import si une autre instance le détient. Désactiver temporairement l'autobuild
pendant l'import et restaurer le réglage ; aucune compilation complète n'est
implicitement demandée. Les résolutions Maven nécessaires à la configuration
doivent être visibles dans les logs et respecter les paramètres fournis.

Le résultat recense pour chaque projet : identifiant Poly, nom Eclipse, emplacement,
natures constatées, import/configuration réussis ou erreurs, fichiers affectés et
diagnostics. Attendre les jobs de configuration nécessaires avant de déclarer
l'import terminé ; un processus lancé n'est pas une preuve d'import réussi.

Les fichiers techniques existants appartiennent à leur projet. Les modifications
induites par les configurateurs m2e/PDE doivent être déclarées et contrôlées ; la
politique de propriété du prototype `.eclipse/.project` ne peut pas être appliquée
telle quelle à ces fichiers. La régénération et la reprise ne doivent ni dupliquer
les projets, ni effacer les personnalisations ou les sources.

## Convention de working sets

Convention proposée par défaut : **`Poly / <workspace> / <dépôt>`**.

Exemple : `Poly / qc2-p17-poly / 021-container-management`, contenant les projets
importés appartenant à ce dépôt, notamment ses modules Maven. L'appartenance vient
des relations de composition et du dépôt propriétaire le plus proche, avec un
repli par emplacement clairement défini si ces relations sont absentes.

- Un working set par dépôt, membres triés et dédupliqués.
- Les segments du nom constituent une convention d'affichage ; ils ne créent pas
  une hiérarchie native de working sets dans Eclipse.
- Identité stable fondée sur le workspace Poly et l'identifiant du dépôt ; le
  libellé reste configurable et les collisions sont signalées.
- Groupes transverses explicites facultatifs ; un projet peut appartenir à plusieurs
  groupes. Le profil conserve leurs identifiants, libellés et sélecteurs.
- Les working sets personnels restent hors du périmètre géré. Un nom préfixé
  `Poly /` ne constitue pas à lui seul une preuve de propriété.
- Conserver la provenance des groupes/membres gérés. Une réconciliation ne retire
  que les appartenances précédemment gérées par Poly et devenues obsolètes ; elle
  préserve les ajouts manuels. Un groupe devenu vide est conservé sauf politique
  de suppression explicitement activée et preuve de propriété.

Les règles partagées doivent vivre hors de `.poly`, dans le profil Eclipse versionné.
Le format final et la migration de `poly.eclipse/v1` seront explicités avant
implémentation : aucun profil `navigation` existant ne sera réinterprété en import
réel sans migration explicite.

## Particularité du Workbench

L'API publique `IWorkingSetManager` est obtenue depuis `IWorkbench`. Il ne faut donc
pas supposer sa disponibilité dans une application Resources purement headless.
La conception proposée sépare l'import headless de la réconciliation des working
sets au premier démarrage du Workbench, par un composant Eclipse dédié utilisant
les API publiques. La faisabilité et le déclenchement de ce composant doivent être
validés sur le produit cible ; un mécanisme de startup désactivé doit être signalé.

Le résultat headless distinguera « projets importés » de « working sets en attente
d'application ». La recette vérifie les groupes après ouverture de l'IDE.
Poly ne doit pas éditer directement les fichiers internes `.metadata` pour simuler
l'import ou la gestion des working sets.

## Critères de recette révisés

- Importer une composition représentative contenant plusieurs dépôts/modules et
  les types Eclipse réellement rencontrés ; vérifier noms, emplacements et natures.
- Vérifier les capacités Java/Maven/PDE appropriées, au-delà de la navigation.
- Exécuter l'import headless puis ouvrir le workspace sans import manuel.
- Contrôler les groupes selon la convention et préserver un working set personnel.
- Répéter l'import et la réconciliation sans doublon ni réécriture inutile.
- Tester collisions, prérequis absents, workspace verrouillé, entrées périmées,
  configurations déjà personnalisées, échec partiel et reprise.
- Vérifier Windows et POSIX avec une véritable distribution Eclipse compatible.
- Conserver le jalon ouvert jusqu'à CI verte et recette réelle explicite.

## Références techniques

- [IWorkspace : descriptions de projets et accès aux métadonnées](https://help.eclipse.org/latest/topic/org.eclipse.platform.doc.isv/reference/api/org/eclipse/core/resources/IWorkspace.html).
- [Lancement Equinox et sélection de l'application/workspace](https://equinox.eclipseprojects.io/launcher/starting_eclipse_commandline.html).
- [m2e : intégration Maven](https://github.com/eclipse-m2e/m2e-core).
- [IWorkingSetManager : accès depuis IWorkbench](https://help.eclipse.org/latest/topic/org.eclipse.platform.doc.isv/reference/api/org/eclipse/ui/IWorkingSetManager.html).
- [IStartup : démarrage du Workbench](https://help.eclipse.org/latest/topic/org.eclipse.platform.doc.isv/reference/api/org/eclipse/ui/IStartup.html).
