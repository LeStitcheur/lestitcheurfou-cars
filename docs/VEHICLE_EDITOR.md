# Vehicle Editor — modélisation, carrosserie, composants et personnalisation 3D

Module de la version 0.4.0. Le **Vehicle Editor** remplace la page « Studio 3D ». Il permet de
modifier réellement un véhicule : sa géométrie, ses pièces, ses matériaux, ses roues et son
habitacle. Il permet aussi de préparer les points d'ancrage des équipements, puis d'enregistrer
le tout dans le projet `.lsfc`.

Aucune fonction n'est simulée. Un outil qui dépend d'un logiciel absent est désactivé et son
infobulle explique pourquoi (exemple : le biseau sans Blender).

## Disposition

| Zone | Contenu |
|---|---|
| Gauche | **Scène** (explorateur), **Bibliothèque** (composants), **Outils** (selon le mode actif) |
| Centre | En-tête : espaces de travail et modes. Viewport 3D avec gizmos, superpositions du mode Édition, axes des points d'ancrage |
| Droite | Atelier de l'espace actif (Carrosserie, Roues ou Habitacle), puis **Propriétés** (objet, transformations, matériau), **Géométrie**, **Ancrages** |
| Bas | **Statistiques**, **Historique** et points de restauration, **Compatibilité FiveM**, Progression, Journal |

Les panneaux sont redimensionnables et rétractables (boutons à droite de l'en-tête). La
disposition, les panneaux masqués et l'espace de travail sont mémorisés.

## Espaces de travail

- **Vehicle Editor** : modélisation générale.
- **Bodywork Studio** : carrosserie.
- **Wheel Editor** : roues.
- **Interior Studio** : habitacle.

## Modes d'édition

### Objet

Sélection, déplacement, rotation et échelle (W / E / R, avec gizmos et champs numériques).
Duplication, duplication miroir, suppression, renommage, masquage, verrouillage, regroupement,
parentage et déparentage (glisser-déposer dans l'explorateur). Alignement de plusieurs objets
sur un plan (minimum, centre ou maximum). Proportions par axe. Réglage des axes du véhicule
(axe latéral, axe longitudinal, sens de l'avant, position du plan de symétrie).

### Édition (Tab)

Modifie la vraie géométrie du maillage sélectionné. Un maillage importé est copié dans le projet
à sa première modification : le fichier importé n'est jamais modifié.

| Opération | Implémentation | Statut |
|---|---|---|
| Sélection de sommets, d'arêtes ou de faces (clic, Maj+clic, Ctrl+clic, A ; option rayons X) | Lancer de rayon et projection écran | ✅ |
| Tout, aucun, inverser, étendre, éléments liés, faces coplanaires | Topologie soudée | ✅ |
| Déplacer, pivoter, mettre à l'échelle (gizmo avec aperçu en direct, ou valeurs numériques) | `scene.editmesh` | ✅ |
| Extrusion de région (le long de la normale moyenne, parois créées) | `scene.editmesh` | ✅ |
| Inset (réduction vers le centre de chaque région, avec une bande de faces) | `scene.editmesh` | ✅ (inset « par mise à l'échelle », pas un inset à épaisseur constante) |
| **Biseau** d'arêtes | `bmesh.ops.bevel` de **Blender**, en processus séparé et annulable | ✅ si Blender est détecté (testé avec Blender 5.2), désactivé sinon |
| Fusion des sommets sélectionnés, fusion par distance | `scene.editmesh` | ✅ |
| Suppression de sommets ou de faces | `scene.editmesh` | ✅ |
| Recalcul des normales, inversion, orientation cohérente | `scene.editmesh` | ✅ |
| Symétrie (axe X, Y ou Z, côté conservé), avec aperçu puis validation | découpe par `trimesh` et copie miroir | ✅ |
| Alignement de la sélection sur un plan | `scene.editmesh` | ✅ |
| Séparation de la sélection en un nouvel objet | `scene.editmesh` | ✅ |
| Projection UV automatique (boîte) | `scene.editmesh` | ✅ |

**UV.** Les déplacements conservent les UV et signalent un étirement important. L'extrusion
projette des UV sur les nouvelles parois ; l'inset réduit les UV de la région. La symétrie
réutilise les UV en miroir. Chaque opération qui touche les UV affiche un avertissement. Si les
UV deviennent invalides, l'application propose la correction « Projection UV automatique ».
L'état des UV est affiché dans l'onglet **Géométrie**.

### Composant

Un clic sélectionne le composant entier. Le composant d'une pièce est déterminé ainsi : groupe
marqué comme composant, sinon os GTA V porteur de la géométrie, sinon groupe de pièces de même
nature.

Dans ce mode, vous pouvez :

- isoler un composant, le remplacer, le dupliquer ;
- créer des variantes, une seule étant visible à la fois ;
- déplacer ou centrer son pivot sans déplacer la pièce ;
- l'associer à un parent ;
- y ajouter des points d'attache ;
- choisir son rôle : **visuel**, **mobile** (roue, porte, capot, coffre) ou **technique FiveM**
  (ancrage, collision, LOD, aide).

## Bodywork Studio

- Liste des panneaux de carrosserie, établie d'après les noms (conventions GTA V ou noms
  explicites), avec isolement.
- Proportions de la sélection : largeur, hauteur et longueur en pourcentage.
- Création de pièces originales, placées d'après l'encombrement du véhicule : pare-chocs,
  aileron, calandre, prise d'air, bas de caisse, lame avant, diffuseur, élargisseur d'aile,
  canard, capot.
- Symétrie gauche / droite : duplication miroir sans échelle négative (la géométrie est
  recalculée), ou symétrisation du maillage en mode Édition.

## Component Library

Bibliothèque locale, rangée dans `%APPDATA%\LeStitcheurFouCars\library`.

- **Contenu d'un composant** :
  - identifiant, nom, catégorie ;
  - modèle 3D, en une ou plusieurs pièces ;
  - matériaux, dimensions, pivot ;
  - points d'attache ;
  - auteur, provenance, licence, compatibilité connue.
- **Catégories** : carrosserie, pare-chocs, spoilers, calandres, phares, feux arrière,
  rétroviseurs, jantes, pneus, sièges, tableaux de bord, accessoires, équipements d'urgence,
  composants personnalisés.
- **Actions** :
  - importer un fichier (GLB, glTF, OBJ, FBX via Blender, STL, PLY, `.yft`) ;
  - aperçu (miniature calculée sans OpenGL), recherche, filtre ;
  - ajouter au véhicule, dupliquer ;
  - enregistrer une pièce du projet comme preset ;
  - supprimer de la bibliothèque.
- **Composants de départ** : 25 formes paramétriques originales, générées localement. Aucun
  asset tiers n'est distribué.
- **Indépendance des projets** : un composant ajouté est **copié** dans le projet. Supprimer
  un composant de la bibliothèque ne modifie aucun projet existant (vérifié par les tests).

## Replace Component

1. Sélectionnez la pièce existante, puis choisissez une pièce de la bibliothèque.
2. Choisissez les options :
   - conserver les transformations ;
   - aligner les pivots ;
   - ajuster les dimensions ;
   - conserver les matériaux (s'il y a un seul matériau d'origine) ;
   - conserver le parent ;
   - conserver les points d'ancrage.
3. **Prévisualiser** : le remplacement est appliqué à l'écran, hors historique. Le rapport
   indique les dimensions, l'échelle appliquée, les matériaux, les ancrages transférés et les
   avertissements (par exemple pour une pièce mobile).
4. **Confirmer** : le remplacement forme une seule étape d'historique ; l'ancienne pièce reste
   récupérable avec Ctrl+Z.

Les os GTA V ne sont jamais modifiés automatiquement. Par défaut, seule la géométrie rattachée
à l'os est remplacée. Supprimer l'os exige de cocher une option explicite.

## Wheel Editor

- **Identification** : os `wheel_*`, puis pièces nommées roue / wheel / pneu / jante. Un groupe
  qui contient plusieurs roues n'est pas compté comme une seule roue. Pour chaque roue, l'éditeur
  calcule le côté, l'essieu, le rayon, la largeur et l'écart entre le pivot et le centre.
- **Profils** :
  - voiture et SUV : 4 roues ;
  - camion : 4, 6, 8 ou 10 roues ;
  - moto : 2 roues ;
  - véhicule spécial : aucun nombre imposé.

  L'éditeur ne suppose pas quatre roues : un nombre inattendu produit un message, pas une
  correction.
- **Réglages** : voie, empattement, alignement des hauteurs, symétrie d'une roue vers l'autre
  côté, diamètre et largeur.
- **Pièces** : remplacement de la jante ou du pneu (Replace Component), centrage du pivot (avec
  un avertissement FiveM pour un os animé).
- **Aperçu de rotation** autour de l'axe latéral de chaque roue. Il ne touche qu'à l'affichage
  et ne modifie pas la scène.

Aucune compatibilité GTA V n'est déduite automatiquement : les contraintes réelles (rayon
déclaré dans `vehicles.meta`, os de roue) restent à valider lors d'un export.

## Interior Studio

- **Affichage** : isolement de l'habitacle, masquage temporaire de la carrosserie (l'habitacle
  reste visible).
- **Caméra intérieure** : placée à la position du conducteur, la souris permet de regarder
  autour.
- **Éléments** : liste des éléments de l'habitacle (sièges, tableau de bord, volant).
- **Ajout depuis la bibliothèque** : siège, tableau de bord, volant, support médical.
- **Configurations** d'habitacle (une seule active à la fois) : civil, police, EMS, véhicule de
  commandement. Vous pouvez ajouter des composants dans la configuration active ou y déplacer la
  sélection.

## Attachment Points

Un point d'ancrage est un nœud de la scène. Chaque point contient :

- un identifiant, un nom, un parent ;
- une position et une rotation (locales au parent) ;
- un type : toit, calandre, pare-chocs, tableau de bord, coffre, portière, support médical,
  éclairage, générique ;
- des contraintes : fixe, glissière avant / arrière, rotation verticale, libre ;
- des métadonnées libres (clé = valeur).

Vous pouvez créer, déplacer, renommer, supprimer et associer un point à un composant. Les axes
sont affichés dans le viewport et sont sélectionnables au clic. Les points sont enregistrés dans
le projet ; ils serviront au futur Emergency Studio.

## Matériaux

Champs disponibles :

- couleur, métallicité, rugosité, transparence ;
- texture de couleur ;
- **carte de normales** avec intensité ;
- **échelle et décalage UV**.

Un matériau peut être réutilisé (affectation) ou dupliqué.

**Presets automobiles** (valeurs originales) : peinture brillante, peinture mate, métal brossé,
chrome, plastique, caoutchouc, verre, tissu, cuir.

Chaque preset suggère un shader GTA V (`vehicle_paint1`, `vehicle_mesh`, `vehicle_tire`,
`vehicle_vehglass`, `vehicle_interior`) **à titre indicatif** : la correspondance n'est pas
garantie.

## Historique et sauvegarde

- **Annulation** : toutes les opérations sont annulables et rétablissables (Ctrl+Z / Ctrl+Y).
  Les transactions regroupent une opération composée (remplacement, séparation, variante) en
  une seule étape. Double-cliquer une ligne de l'historique y ramène la scène.
- **Instantanés de géométrie** : chaque modification crée un nouveau maillage immuable ;
  annuler revient simplement à la référence précédente.
- **Mémoire** :
  - un **budget mémoire** (768 Mo par défaut) oublie les étapes les plus anciennes quand il est
    dépassé ;
  - la géométrie inutilisée est libérée ;
  - les tampons GPU des maillages qui ne sont plus affichés sont détruits.
- **Sauvegarde** : automatique (paramètres) et **points de restauration** nommés
  (`<projet>/restore_points/`).

## Compatibilité FiveM

Des avertissements s'affichent quand vous :

- supprimez une roue ;
- déplacez le pivot d'un os animé ;
- modifiez la hiérarchie des os ;
- remplacez une pièce mobile ;
- modifiez un composant technique (collision, LOD) ;
- rendez des UV invalides ;
- renommez un os ;
- appliquez une échelle non uniforme.

Le **rapport de compatibilité technique** (onglet du bas) compare le projet aux données GTA V
importées : os supprimés, pivots déplacés, hiérarchie modifiée, géométrie d'origine modifiée,
UV invalides, échelles non uniformes, pièces ajoutées non rattachées à un os, roues manquantes.
Il rappelle aussi que les collisions et les LOD ne sont pas vérifiables.

**Il ne promet jamais la jouabilité** : aucun export GTA V n'existe encore, et un véhicule
modifié devra être exporté puis testé en jeu.

## Format `.lsfc` version 4

| Ajout | Contenu |
|---|---|
| Table `meshes` | Géométrie locale (pièces modifiées, créées ou ajoutées), compressée en npz |
| Colonne `materials.extra` | Carte de normales, intensité, échelle et décalage UV, preset, shader GTA V indicatif |
| `meta.editor` | Axes du véhicule, plan de symétrie |
| Nœuds `anchor` et `nodes.extra` | Points d'ancrage, rôle et provenance des composants, ensembles de variantes, configurations d'habitacle |

Les projets aux formats 1, 2 et 3 sont migrés automatiquement à l'ouverture, sans que le fichier
d'origine soit modifié tant qu'il n'est pas enregistré.

## Limitations connues (0.4.0)

- **Inset** : mise à l'échelle vers le centre de la région, pas d'épaisseur constante.
- **Biseau** : disponible seulement avec Blender ; les couleurs par sommet sont uniformisées.
- **Matériaux** : la carte de normales utilise un repère tangent calculé à l'écran (pas de
  tangentes stockées) ; le rendu reste indicatif.
- **Géométrie GTA V** : les éditions s'appliquent à la géométrie du niveau de détail haut.
  Collisions, LOD et dégâts ne sont pas édités.
- **Aucune écriture de formats GTA V** : l'export FiveM reste à faire. Le rapport de
  compatibilité est une aide, pas une validation.
- **Sollumz** n'est pas installé sur la machine de développement : non testé.
- **Profils de roues** : diagnostics indicatifs, sans contraintes GTA V appliquées
  automatiquement.
- **Sélection** : pas de sélection rectangulaire dans le viewport (des outils Tout, Liés,
  Coplanaires et Étendre la remplacent).
