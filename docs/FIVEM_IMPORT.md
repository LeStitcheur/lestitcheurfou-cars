# Vehicle Import Studio — import GTA V / FiveM

Module de la version 0.3.0. Il analyse une ressource de véhicule, affiche ses composants dans
le viewport, inspecte ses textures et ses métadonnées, puis l'importe dans un projet
`.lsfc` sans jamais modifier les fichiers d'origine.

## Sources acceptées

| Source | Comment l'ouvrir |
|---|---|
| Dossier de ressource FiveM (`fxmanifest.lua`, `stream/`, `data/`) | bouton **Dossier** ou glisser-déposer |
| Ressource compressée `.zip` | bouton **ZIP** |
| Archive RPF7 **non chiffrée** (`dlc.rpf` d'addon, archives OpenIV « OPEN ») | bouton **RPF** |
| Fichiers isolés `.yft`, `.ydr`, `.ytd`, `.ybn`, `.meta`, `.xml`, `.obj`, `.fbx`, `.glb`, `.gltf` | bouton **Fichier** |
| Installation GTA V de l'utilisateur | bouton **Installation GTA V** : inventaire des archives, ouverture des archives lisibles |

## Compatibilité réelle des formats

« Reconnaître un format ne signifie pas pouvoir le convertir. » Chaque statut ci-dessous
correspond à ce que le code fait réellement, vérifié par des tests.

| Format | Ce que fait LeStitcheurFou Cars | Statut | Validation |
|---|---|---|---|
| `.yft` (fragment, gen8) | Décodage natif : squelette, géométrie du niveau de détail haut, enfants physiques (roues), shaders, références de textures, découpage par os | **Pris en charge** | fichiers synthétiques (tests) + 93 `.yft` d'un addon réel (validation locale) |
| `.ydr` (drawable, gen8) | Même décodeur que le drawable des `.yft` | **Expérimental** | aucun `.ydr` réel disponible : non validé sur fichier réel |
| `.ytd` (gen8) | Lecture du dictionnaire, décodage DXT1/3/5, BC4/5 (ATI1/2), BC7, A8R8G8B8, X8R8G8B8, A8B8G8R8, A1R5G5B5, A8, L8 ; export PNG et DDS | **Pris en charge** | synthétique + 19/19 textures d'un addon réel (DXT1, DXT5, A8R8G8B8) ; BC4/5/7 et formats 16/8 bits : synthétiques ou non testés sur fichier réel |
| `.meta` / `.xml` | vehicles, handling, carvariations, carcols, vehiclelayouts, content.xml, setup2.xml, dlctext, shop_vehicle ; types inconnus affichés tels quels | **Pris en charge (lecture)** | synthétique + addon réel ; aucune écriture |
| `.rpf` RPF7 « OPEN » | Parcours, archives imbriquées, extraction des fichiers binaires et ressources | **Pris en charge** | synthétique + `dlc.rpf` réel |
| `.rpf` chiffrée (AES / NG, archives officielles) | Détectée et **refusée** avec explication | **Refusé** | synthétique (en-têtes AES et NG) |
| `.zip` | Parcours, RPF contenues dans le ZIP | **Pris en charge** | synthétique |
| `fxmanifest.lua` / `__resource.lua` | `files`, `data_file`, dépendances, fichiers déclarés manquants | **Partiel** (analyse par motifs, Lua non exécuté) | synthétique |
| `.ybn` (collision) | En-tête RSC7 vérifié ; la géométrie de collision n'est **pas** décodée | **Partiel** | synthétique |
| `.fxap` (FiveM Asset Escrow) | Ressource signalée comme protégée ; **aucun déchiffrement** | **Refusé** | synthétique |
| `.obj`, `.glb`, `.gltf` | Importateur trimesh existant | **Pris en charge** | tests v0.1 / v0.2 |
| `.fbx` | Conversion via Blender (si installé) | **Dépend de Blender** | test réel avec Blender 5.2.2 |
| Ressources RSC8 (« gen9 », éditions récentes) | Détectées, non prises en charge | **Non pris en charge** | — |
| `.awc`, `.rel` (audio), `.ytyp`, `.ymap`… | Reconnus, ignorés | **Non pris en charge** | — |

## Statuts de diagnostic

| Statut | Signification |
|---|---|
| Compatible | Fichier lu et **réellement décodé** |
| Partiellement compatible | Reconnu, lu en partie (collision : en-tête seulement ; dictionnaire partiellement décodé) |
| Dépendance manquante | Valide, mais un fichier requis manque (`.ytd` du véhicule, fichier déclaré dans le manifeste, Blender pour un FBX) |
| Erreur | Corrompu, tronqué, chiffré ou protégé |
| Format non pris en charge | Reconnu mais non exploité |

Un fichier n'est jamais déclaré compatible sans décodage effectif. Une ressource invalide ne fait
jamais planter l'application : chaque fichier est analysé isolément.

## Inspection du véhicule

- **Hiérarchie** : par composant (classement d'après les noms d'os GTA V : carrosserie, châssis,
  portes, capot, coffre, roues, vitres, phares, habitacle, tableau de bord, sièges, accessoires ;
  tout le reste en « Non classée »), par os, ou points d'ancrage (os sans géométrie).
- **Modes** : complet, isolé, éclaté (intensité réglable), filaire, matériaux, os, ancrages,
  statistiques. Le mode **Collisions** est affiché « non implémenté ».
- **Vue éclatée** : décalages appliqués à l'affichage seulement ; « Réinitialiser » revient à la
  vue assemblée, le modèle n'est jamais modifié.
- **Sélection** : clic dans le viewport ou la hiérarchie ; la fiche indique catégorie, os
  (index, étiquette, pivot d'origine), shader, dimensions, géométrie et matériau.

## Import dans un projet

« Importer dans le projet » :

1. copie le `.yft` et ses `.ytd` dans `assets/<modèle>/` du projet ;
2. copie les métadonnées et le manifeste dans `assets/fivem/<ressource>/` ;
3. ajoute le modèle à la scène (os = groupes avec leurs transformations d'origine, pièces =
   maillages), ce qui permet toutes les éditions du Studio 3D (transformation, renommage,
   duplication, masquage, verrouillage, matériaux, annuler / rétablir) ;
4. enregistre dans le `.lsfc` (format 3) un **manifeste versionné** : ressource d'origine,
   fichiers et leur statut, copies, modèle, textures, métadonnées, dépendances, diagnostics.

Les nœuds importés conservent leurs métadonnées d'origine (`extra.gta` : index et étiquette
d'os, pivot, quaternion, rôle, shader). Renommer un os, supprimer une pièce d'origine, modifier
la hiérarchie ou appliquer une échelle non uniforme affiche un avertissement
« Compatibilité FiveM ».

## Blender et Sollumz

- Blender est détecté (Program Files, `LSFCARS_BLENDER`, chemin des paramètres, `PATH`).
- Sollumz est sondé dans la configuration réelle de Blender : présence, version, état, liste des
  opérateurs `bpy.ops.sollumz.*` réellement disponibles. Aucune API n'est supposée.
- « Importer via Sollumz » n'est proposé que si un opérateur d'import est détecté ; la tâche
  s'exécute dans un processus séparé avec journal, délai maximal et annulation. En cas d'échec,
  l'opération est signalée comme manuelle.
- État vérifié sur la machine de développement : Blender 5.2.2 détecté, **Sollumz non installé**.
  L'import via Sollumz n'a donc **pas pu être testé** avec un vrai Sollumz (seuls les
  comportements « absent » et « opérateurs sondés » sont testés avec des réponses simulées).

## Limitations connues

- Seul le niveau de détail **haut** est importé ; les autres sont listés.
- Les matériaux importés sont simplifiés (couleur, rugosité, métallicité, opacité, texture
  diffuse) ; les paramètres de shader GTA (cartes normales, spéculaires, teintes de peinture)
  sont lus mais pas rendus.
- Les textures partagées par le jeu (`vehshare`…) ne sont pas dans les addons : elles sont
  listées comme absentes.
- Géométrie de collision `.ybn` non décodée ; variantes de dégâts et tissus non importés.
- Aucune **écriture** de formats GTA V : l'export FiveM reste à venir.
- Affichage 3D des os non implémenté (pivots visibles dans la fiche de sélection et la hiérarchie).

## Règles légales et de sécurité

- Aucun contournement de chiffrement, de DRM ou de restriction d'accès : archives chiffrées et
  ressources Asset Escrow sont refusées avec une explication.
- Les fichiers sources ne sont jamais modifiés (lecture seule, copies dans le projet).
- Le dépôt ne contient aucun fichier GTA V : l'addon de démonstration `samples/fivem/lsfdemo`
  est **synthétique** (créé par `scripts/generate_demo_addon.py`) et n'est pas versionné.
- Les tests sur une ressource réelle sont facultatifs : `LSFCARS_REAL_RESOURCE=<chemin> pytest
  tests/test_real_resources.py` ; sans cette variable ils sont ignorés et ne prétendent rien valider.
