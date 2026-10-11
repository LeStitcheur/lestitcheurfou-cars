# Guide utilisateur — LeStitcheurFou Cars 0.3.0

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
