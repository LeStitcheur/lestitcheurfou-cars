# Guide utilisateur — LeStitcheurFou Cars 0.8.0

## Nouveautés 0.8 : Lore Friendly Engine

Référence complète : [LORE_FRIENDLY_ENGINE.md](LORE_FRIENDLY_ENGINE.md).

1. Importez un véhicule (Fichier → Importer, ou bouton « Importer… » du studio). Essai rapide :
   `samples/vehicule_lore.glb`.
2. **Lore Friendly** (barre latérale) → onglet **Source** : choisissez le véhicule puis **Créer un
   design**. La source est verrouillée : elle ne sera jamais modifiée.
3. Onglet **Analyse** → **Analyser** : chaque information indique si elle est mesurée, reconnue,
   issue d'une IA ou inconnue. Double-clic pour corriger.
4. **Marques** : choisissez une marque de l'univers GTA V (référence créative, aucun logo fourni)
   ou créez une marque originale. **Styles** : profil Design DNA et réglages. **Presets** :
   niveau (léger, équilibré, original) et contraintes à conserver.
5. **Propositions** → **Générer** : plusieurs plans avec leurs aperçus rendus. **Appliquer** :
   une variante est créée après confirmation (impacts listés), en une étape annulable.
6. **Transformation** : Front Design Studio, Rear Design Studio, Body Silhouette Studio,
   identité lumineuse — **Prévisualiser** (avant / après) puis **Appliquer**.
7. **Comparaison** (en haut) : côte à côte, séparateur, superposition, filaire, matériaux ;
   **Mesurer les différences**. **Revenir à l'original** à tout moment.
8. Bas de l'écran : **Validation** (workflow, revue d'originalité, vérifications par vous,
   rapport de préparation FiveM), **Provenance** (licences à compléter), **Historique**.
9. Enregistrez (Ctrl+S) ; **Vehicle Editor**, **Livery** ou **Emergency** pour poursuivre.

La revue d'originalité donne des mesures techniques : ce n'est ni un avis juridique ni une
certification, et un véhicule transformé doit être exporté et essayé en jeu avant toute
utilisation FiveM.

## Nouveautés 0.7 : AI Vehicle Creator

Référence complète : [AI_VEHICLE_CREATOR.md](AI_VEHICLE_CREATOR.md).

1. Créez ou ouvrez un projet, puis **AI Vehicle Creator** (barre latérale, section Outils).
   Les moteurs et le matériel sont détectés automatiquement (onglet du bas « Matériel et
   moteurs »).
2. Onglet **Références** → **Importer…** : plusieurs images (avant, arrière, profils, trois
   quarts, dessus…). Vérifiez la vue de chacune, recadrez, annotez les logos réels (ils seront
   masqués) et renseignez la provenance. Essai rapide : `samples/references/demo_*.png`.
3. Onglet **Analyse** → **Analyser** : type proposé, proportions, roues, couleurs, incohérences.
   Corrigez une mesure par double-clic ; saisissez une longueur connue pour des cotes réalistes.
4. Onglet **Génération** (à droite) : mode Automatique / Local / Cloud, moteur (le routage
   explique son choix), profil, puis **Générer**. La progression s'affiche ; l'interface reste
   utilisable ; « Annuler » interrompt la tâche. Un envoi cloud ou une opération payante demande
   toujours votre confirmation.
5. Le modèle apparaît dans la vue 3D. **Maillage** : analyser, corriger (annulable), retourner
   de 180° si l'avant est inversé, recaler sur les proportions mesurées.
6. **Textures** : projection des références, application au modèle, ouverture dans Livery
   Studio. **Lore Friendly** (à gauche) : propositions, noms fictifs, ajustements, provenance.
7. **Historique** : réouvrir, dupliquer, comparer, réutiliser les paramètres. Enregistrez
   (Ctrl+S) puis **Vehicle Editor** pour poursuivre le travail à la main.

Moteur neuronal local facultatif : **Moteurs → TripoSR → Installer…** (environ 5 à 6 Go,
liste des téléchargements affichée avant confirmation). Un maillage généré n'est jamais un
véhicule FiveM prêt à l'emploi.

## Nouveautés 0.6 : Livery Studio

Référence complète : [LIVERY_STUDIO.md](LIVERY_STUDIO.md).

1. Importez un véhicule **avec UV** (le fichier d'essai `samples/vehicule_livree.glb` convient).
   Sans UV, le Livery Studio propose une projection automatique, après confirmation.
2. Ouvrez **Livery Studio** (barre latérale, section Création) puis **Nouveau document** :
   matériaux ciblés, résolution, modèle (LSPD, EMS, SAMD…) et numéro d'unité.
3. **Peindre sur le véhicule** : outil Pinceau (B), clic gauche sur la carrosserie dans la vue 3D
   (Alt + glisser pour tourner autour). La symétrie gauche / droite se coche dans l'outil.
4. **Vue UV 2D** : peinture, formes, textes, sélections et guides directement sur la texture.
   Touches 1 / 2 / 3 : vue 3D, vue UV, vue partagée.
5. Onglets de gauche : **Formes** (bandes 3D, marquages), **Logos**, **Modèles**.
6. Onglet **Calques** : ordre (glisser-déposer), groupes, opacité, mode de fusion, masques.
   **Propriétés** : texte, police, contour, ombre, placement sur une zone, symétrie.
7. Onglet **Livrées** : seconde variante, comparaison, association à une variante d'urgence.
8. Onglet **Export** : PNG, TIFF, WEBP ou DDS avec mipmaps ; le fichier est relu et comparé.
   « Préparer YTD » crée un dossier DDS pour CodeWalker / OpenIV / Sollumz (pas de .ytd).
9. Enregistrez (Ctrl+S) : calques, textes, logos et variantes restent éditables.

## Nouveautés 0.5 : Emergency Studio

Référence complète : [EMERGENCY_STUDIO.md](EMERGENCY_STUDIO.md).

1. Ouvrez un projet et importez un véhicule civil. Dans le Vehicle Editor, vérifiez les **axes
   du véhicule** (sens de l'avant) : les zones de pose en dépendent.
2. Ouvrez **Emergency Studio** (barre latérale, section Personnalisation).
3. Onglet **Service** : choisissez le service (LSPD, BCSO, SAHP, EMS…) et le profil du véhicule,
   puis **Créer la variante**. Le véhicule de base n'est jamais modifié.
4. Onglet **Équipements** : choisissez un équipement et une zone (toit, calandre…) puis
   **Ajouter**, ou glissez-le directement sur la carrosserie dans le viewport. **Paire** pose
   l'équipement à gauche et à droite.
5. Onglet **Éclairage** (à droite) : réglez couleur, intensité, portée et angle des feux ;
   rangez-les dans des groupes.
6. **Timeline lumineuse** (en bas) : créez un motif depuis un preset, cliquez sur les cases pour
   allumer / éteindre un groupe à chaque étape, puis **Appliquer les modifications**.
   **Aperçu lumineux** lance la simulation dans le viewport (ce n'est pas un rendu en jeu).
7. Onglet **Configurations** : intérieur Police / EMS / Fire, sirènes, données de livrée,
   contrôle Lore Friendly.
8. Onglet **Export** : validez puis exportez vers `carcols.meta`, MISS-ELS ou JSON. Les fichiers
   produits sont des données préparatoires : leur fonctionnement en jeu n'est pas garanti.
9. Enregistrez (Ctrl+S) : variantes, équipements, feux et motifs sont conservés dans le `.lsfc`.

## Nouveautés 0.4 : Vehicle Editor

Référence complète : [VEHICLE_EDITOR.md](VEHICLE_EDITOR.md).

1. Ouvrez un projet et importez un véhicule (GLB, OBJ, FBX, ou ressource FiveM via le Vehicle
   Import Studio). La page **Vehicle Editor** s'ouvre.
2. **Choisir un mode** (en-tête du viewport) : **Objet** (déplacer, pivoter, dupliquer,
   grouper…), **Édition** (Tab : modifier les sommets, arêtes et faces du maillage
   sélectionné), **Composant** (un clic sélectionne la pièce entière : roue, porte…).
3. **Modifier la géométrie** (mode Édition, onglet de gauche **Outils**) :
   - choisissez Sommets, Arêtes ou Faces, puis cliquez dans le viewport (Maj : ajouter,
     Ctrl : basculer, A : tout) ;
   - déplacez la sélection avec le gizmo (W / E / R) ;
   - utilisez Extruder, Inset, Biseau (avec Blender), Fusionner, Séparer, Symétrie (aperçu
     puis Valider) ou Projection UV automatique.

   Le fichier importé n'est jamais modifié : la pièce modifiée est enregistrée dans le projet.
4. **Ajouter une pièce** : onglet **Bibliothèque** (recherche, catégories, aperçu), double-clic
   ou « Ajouter au véhicule ». « Preset » enregistre une pièce du projet dans la bibliothèque.
5. **Remplacer une pièce** : sélectionnez-la, puis « Remplacer… ». Choisissez la nouvelle
   pièce et les options, **Prévisualiser**, puis **Confirmer** (Ctrl+Z restaure l'ancienne).
6. **Ateliers** (en-tête) :
   - **Bodywork Studio** : pièces de carrosserie, proportions, miroir ;
   - **Wheel Editor** : voie, empattement, hauteurs, jantes, pivots, aperçu de rotation ;
   - **Interior Studio** : habitacle isolé, carrosserie masquée, caméra intérieure,
     configurations police / EMS.

   Réglez d'abord le sens de l'avant du véhicule dans **Outils** (mode Objet), rubrique
   « Axes du véhicule ».
7. **Points d'ancrage** : onglet **Ancrages** (à droite), puis type, contraintes, métadonnées et
   « Créer ». Les axes s'affichent dans le viewport.
8. **Matériaux** : onglet Propriétés → Matériau. Presets automobiles, carte de normales, UV.
9. En bas :
   - **Historique** : double-clic pour revenir à une étape ; points de restauration ;
   - **Compatibilité FiveM** : rapport technique, sans garantie de jouabilité.
10. Enregistrez avec Ctrl+S : géométrie modifiée, pièces ajoutées, ancrages, variantes,
    matériaux et réglages sont conservés.

# Guide 0.3.0

## Nouveautés 0.3 : Vehicle Import Studio

1. Ouvrez **Vehicle Import Studio** dans la navigation (ou « Importer un addon FiveM » sur le
   tableau de bord).
2. Choisissez une source : **Dossier** (ressource FiveM), **ZIP**, **RPF** (archive non
   chiffrée), **Fichier** (.yft, .ytd, .meta…) ou **Installation GTA V** (inventaire des
   archives de votre copie ; seules les archives non chiffrées peuvent être ouvertes). Le
   glisser-déposer fonctionne aussi.
3. L'analyse s'exécute en arrière-plan (bouton **Annuler** en bas). Chaque fichier reçoit un
   statut : Compatible, Partiellement compatible, Dépendance manquante, Erreur, Format non pris
   en charge. Cliquez un fichier pour sa fiche ; double-cliquez un diagnostic pour retrouver le
   fichier concerné.
4. Onglet **Véhicule** : choisissez le modèle puis **Visualiser** (ou **Version _hi**). Le
   véhicule apparaît au centre, ses composants à gauche (Hiérarchie : par composant, par os,
   points d'ancrage). Décochez un composant pour le masquer (affichage seulement).
5. Inspection : **Isolé**, **Éclaté** (curseur d'intensité), **Filaire**, **Matériaux**,
   **Os**, **Ancrages**, **Statistiques** ; icônes Isoler, Tout afficher, Recentrer,
   Réinitialiser. Le mode Collisions est signalé « non implémenté ».
6. Onglets **Méta** (métadonnées structurées, recherche, vérifications, texte d'origine),
   **Textures** (aperçu, format, transparence, mémoire, export PNG / DDS, préparation pour les
   livrées), **Blender** (détection de Blender et Sollumz), **Formats** (ce qui est réellement
   pris en charge).
7. **Importer dans le projet** : le modèle, ses textures et ses métadonnées sont copiés dans le
   projet (un projet est proposé s'il n'y en a pas), puis le Studio 3D s'ouvre sur le véhicule.
   Les fichiers d'origine ne sont jamais modifiés. Enregistrez (Ctrl+S) : la ressource et son
   manifeste sont conservés dans le `.lsfc`.

Dans le Studio 3D, les pièces importées se modifient comme les autres (transformations,
renommage, duplication, masquage, verrouillage, matériaux, annuler / rétablir). Un avertissement
« Compatibilité FiveM » apparaît si une opération risque de casser le véhicule dans FiveM.

Formats, limites et règles : [FIVEM_IMPORT.md](FIVEM_IMPORT.md).

L'interface adopte la direction **Dark Premium** (bleu principal pour la sélection et les
actions principales, bleu électrique pour le focus et les éléments actifs).

# Guide 0.2.0

## Nouveautés 0.2 en bref

- **Navigation** : sidebar à gauche (Ctrl+B pour la réduire), recherche Ctrl+K, menu
  **Fichier** dans la barre de titre. Les entrées marquées d'un point ambre sont « à venir ».
- **Studio 3D** : explorateur de scène à gauche, viewport au centre, propriétés à droite,
  statistiques / progression / journal en bas. Les séparateurs se déplacent à la souris et
  l'agencement est mémorisé.
- **Outils du viewport** (barre flottante) : Q sélection, W déplacer, E pivoter, R échelle
  (Ctrl pendant le glissement : magnétisme) ; Z change le mode solide / filaire / matériaux ;
  pavé 5 orthographique ; pavé 1/3/7 (Ctrl : vue opposée) ; F centrer ; caméra libre :
  bouton caméra puis ZQSD/WASD + clic droit, E/Espace monter, C descendre.
- **Sélection** : clic sur une pièce, Ctrl+clic pour ajouter/retirer ; dans l'explorateur,
  Maj/Ctrl+clic. F2 renommer, Ctrl+D dupliquer, Ctrl+G grouper, Suppr supprimer (confirmé),
  Ctrl+Z / Ctrl+Y annuler / rétablir.
- **Matériaux** : onglet Matériau des propriétés ou page Matériaux. Les réglages s'affichent
  immédiatement en mode Matériaux.
- **Projets** : Ctrl+S enregistrer, Ctrl+Maj+S enregistrer sous ; sauvegarde automatique
  (Paramètres) et proposition de restauration au démarrage après une interruption.
- **Import** : page Importer un véhicule (glisser-déposer) ; FBX nécessite Blender installé.

Les sections ci-dessous décrivent la version 0.1 et restent valables pour les principes
(structure de projet, formats, journal).

# Guide 0.1.0

Ce guide décrit ce que la version 0.1.0 permet **réellement** de faire. Les ateliers marqués
« Prévu » dans l'application ne sont pas encore disponibles.

## 1. Découvrir l'interface

| Zone | Rôle |
|---|---|
| Rail de gauche | Navigation : Accueil, Atelier 3D, puis les ateliers à venir |
| Accueil | Créer / ouvrir un projet, projets récents, feuille de route |
| Atelier 3D | Viewport central, explorateur d'objets (gauche), propriétés (droite) |
| Journal (bas) | Messages de l'application en direct, filtrables par niveau |
| Barre d'état | Projet ouvert, nombre d'objets et de triangles, carte graphique utilisée |

Les panneaux peuvent être déplacés, détachés ou fermés ; le menu **Affichage** permet de les
réafficher. La disposition est mémorisée.

## 2. Premier essai en 30 secondes

Sur l'accueil, cliquez **Découvrir avec le véhicule d'exemple** : un projet de démonstration est
créé dans `Documents\LeStitcheurFou Cars\Projets` avec un véhicule de test libre de droits.

## 3. Projets

- **Nouveau projet** (`Ctrl+N`) : nom, type de véhicule (voiture, SUV, moto, camion, bateau,
  hélicoptère, avion), usage (civil, LSPD, EMS), emplacement, description.
- **Ouvrir** (`Ctrl+O`) : sélectionnez un fichier `.lsfc`.
- **Enregistrer** (`Ctrl+S`) : enregistre la scène, les propriétés et la position de la caméra.
  Un astérisque `*` dans le titre signale des modifications non enregistrées ; l'application
  propose d'enregistrer avant de fermer.

Structure d'un projet :

```
MonVehicule/
├── MonVehicule.lsfc   ← fichier projet (à ouvrir)
└── assets/            ← copies des modèles importés
```

Pour transmettre un projet, copiez le dossier complet.

## 4. Importer un modèle 3D

**Fichier › Importer un modèle 3D** (`Ctrl+I`) ou bouton **Importer…** de l'explorateur.

Formats acceptés : `.glb`, `.gltf` (avec ses fichiers `.bin` et textures), `.obj` (avec `.mtl`),
`.stl`, `.ply`. Le fichier est vérifié puis **copié** dans `assets/` : l'original n'est jamais
modifié. Les couleurs de sommets et de matériaux sont affichées ; les textures ne le sont pas
encore.

Les fichiers propriétaires GTA V (`.yft`, `.ydr`…) ne sont pas encore pris en charge.

## 5. Naviguer dans la scène

| Action | Souris / clavier |
|---|---|
| Tourner autour de la scène | Clic gauche + glisser |
| Déplacer la vue | Clic droit + glisser, molette enfoncée + glisser, ou Maj + clic gauche |
| Zoomer | Molette |
| Sélectionner un objet | Clic gauche sur l'objet (clic dans le vide : désélectionner) |
| Cadrer la sélection (ou tout) | `F` ou bouton **Cadrer** |
| Vues avant / droite / dessus / perspective | `1` / `3` / `7` / `5` |
| Réinitialiser la vue | `Début` (Home) |
| Désélectionner | `Échap` |

La grille au sol mesure 1 m par case (lignes renforcées tous les 5 m) ; l'axe rouge est X,
l'axe bleu est Z, la hauteur est Y.

## 6. Modifier les objets

Sélectionnez un objet dans l'explorateur ou le viewport. Le panneau **Propriétés** permet de :

- le renommer et le masquer / l'afficher ;
- régler sa **position** (mètres), sa **rotation** (degrés, ordre X puis Y puis Z) et son
  **échelle** (uniforme par défaut — décochez « Échelle uniforme » pour les axes séparés) ;
- revenir à la transformation d'origine.

Sans sélection, le panneau affiche les informations du projet (nom, type, usage, description).

Clic droit dans l'explorateur : cadrer, masquer, retirer. **Retirer** enlève l'objet de la scène
mais conserve son fichier dans `assets/`.

## 7. Journal et diagnostics

- Le panneau **Journal** affiche les opérations et erreurs ; filtrez par niveau.
- **Aide › Diagnostics…** génère un rapport (versions, système, carte graphique) à joindre aux
  signalements de bug.
- **Aide › Ouvrir le dossier des logs** ouvre `%APPDATA%\LeStitcheurFouCars\logs`.

## 8. Ateliers à venir

Livrées, LSPD / EMS, Génération IA et Export FiveM sont visibles dans la navigation pour présenter
la feuille de route ; chaque page indique « Prévu — non disponible dans la v0.1.0 ».
