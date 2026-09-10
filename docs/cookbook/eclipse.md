# Préparer Eclipse — état de la correction 0.13.2

Le prototype de navigation par dossiers liés a été retiré. L'import Eclipse réel
reste à implémenter ; aucune commande Eclipse de production n'est livrée ici.

Le parcours retenu consiste à déclarer les sources et un nœud de configuration,
puis à exécuter `poly hydrate`. Les façades sous `poly add` sont apportées par les
drivers. Le driver Eclipse fournira `eclipse-configuration` avec son schéma
versionné, ses valeurs initiales et la configuration de son adaptateur headless.

La déclaration partagée sera conservée dans `poly.yaml`, sous le nœud parent,
et commitée avec le dépôt racine. Les chemins d'installation Eclipse/JDK locaux
seront des paramètres de l'environnement. L'hydratation enchaînera checkout,
inspections de structure, cohérence du workspace et import réel, dans un plan
explicite consultable avant exécution.

Le [contrat implémenté](../architecture/configuration-hydration.md) est testé avec
une [fixture externe](../../examples/eclipse-contract/README.md). Cette fixture
crée seulement une requête XML ; elle ne remplace pas l'adaptateur Eclipse.

Si le prototype a été utilisé, `poly.eclipse.json` et le dossier `.eclipse` créés
précédemment sont désormais ignorés par Poly. Les examiner avant de les supprimer
manuellement, en conservant les éventuelles modifications personnelles. La
correction ne supprime pas les fichiers du workspace utilisateur.

Les exigences d'import complet, de natures et de working sets restent décrites
dans [le contrat Eclipse](../architecture/eclipse-workspace-import.md).
