# Journal des modifications

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/),
versionnement [SemVer](https://semver.org/lang/fr/).

## [Non publié]

## [0.3.0] - 2026-10-11

Import FiveM / GTA V, décomposition 3D et restauration d'une identité propre « Dark Premium ».

### Modifié

- Abandon complet de l'identité rouge/rose inspirée de LeStitcheur Control : nouvelle direction
  « Dark Premium — Automotive Creation Studio » (palette officielle de 12 couleurs, bleu principal
  `#2563EB`, bleu électrique `#38BDF8`). Design system centralisé (`ColorTokens`,
  `TypographyTokens`, `SpacingTokens`, `AnimationTokens`, `AppTheme`, `ComponentStyles`) ;
  aucune couleur hors des tokens (vérifié par un test), y compris dans le moteur de rendu.
- Polices système Segoe UI ; polices, emblème et script d'import de LeStitcheur Control retirés ;
  carte profil retirée ; bannière du tableau de bord redessinée. Fonctions inchangées.
- La page « Importer un véhicule » devient le **Vehicle Import Studio**.
- Format de projet `.lsfc` **v3** (migration automatique v1/v2 → v3).

### Ajouté (fonctionnel, testé)

- Paquet `fivem/` (sans Qt) :
  - archives RPF7 non chiffrées : parcours, archives imbriquées, extraction ; archives
    chiffrées (AES / NG) détectées et refusées sans déchiffrement ;
  - ressources RSC7 : en-tête, tailles de blocs, décompression, pointeurs ;
  - `.ytd` : dictionnaire, décodage DXT1/3/5, BC4/5/7 et formats non compressés, export PNG/DDS ;
  - `.yft` / `.ydr` : squelette, géométrie, enfants physiques (roues), shaders et textures,
    découpage par os avec pivots d'origine ;
  - métadonnées XML (vehicles, handling, carvariations, carcols, content, setup2…), recherche,
    vérifications croisées, données inconnues conservées ;
  - analyse de ressource (dossier, ZIP, RPF, fichiers) avec statuts Compatible / Partiel /
    Dépendance manquante / Erreur / Non pris en charge, détection de FiveM Asset Escrow ;
  - classification des composants par noms d'os (« Non classée » sinon) ;
  - adaptateur Blender / Sollumz : détection, sondage des opérateurs réellement présents,
    tâches en processus séparé avec journal, délai et annulation ;
  - inventaire des archives d'une installation GTA V (en-têtes seulement).
- Import natif `.yft` / `.ydr` dans les projets (`YftImporter`), textures des `.ytd` voisins.
- Vehicle Import Studio : explorateur de fichiers filtrable, hiérarchie (composants, os,
  ancrages), viewport d'aperçu, modes d'inspection (complet, isolé, éclaté, filaire, matériaux,
  os, ancrages, statistiques ; collisions marquées « non implémenté »), fiches véhicule et
  fichier, lecteur de métadonnées, inspecteur de textures, onglet Blender, onglet Formats,
  diagnostics, journal, progression et annulation ; import dans le projet avec copies et
  manifeste versionné.
- Métadonnées d'origine conservées sur les nœuds (`extra`) et avertissements « Compatibilité
  FiveM » lors des éditions risquées (renommer un os, supprimer, changer la hiérarchie, échelle
  non uniforme).
- Addon de démonstration synthétique (`scripts/generate_demo_addon.py`), embarqué dans
  l'exécutable et vérifié par le test de démarrage.
- 126 tests automatisés (+36) ; test facultatif sur ressource réelle (`LSFCARS_REAL_RESOURCE`).

### Limites connues

- Collisions `.ybn` non décodées ; seul le niveau de détail haut est importé ; matériaux
  simplifiés ; aucune écriture de formats GTA V (export FiveM à venir).
- `.ydr` non validé sur fichier réel ; import via Sollumz non testé (Sollumz non installé).

## [0.2.0] - 2026-10-11

Studio 3D interactif et identité graphique de la suite LeStitcheur.

### Fonctionnel (testé)

- Identité LeStitcheur Control : tokens issus de son code source, DM Sans / Barlow Condensed,
  icônes Lucide, emblème LSF, fenêtre sans cadre, barre de titre, sidebar noire rétractable,
  accents rouge/rose, composants LS* (voir `docs/DESIGN_SYSTEM.md`).
- Tableau de bord « Bienvenue dans ton garage » : bannière, statistiques réelles, projets
  récents avec miniatures ; pages Mes projets, Projets récents, Import, Matériaux,
  Paramètres, Diagnostics.
- Studio 3D : explorateur hiérarchique (recherche, renommage, masquage, verrouillage,
  regroupement, glisser-déposer, menu contextuel), propriétés (objet, provenance,
  transformations, dimensions), éditeur de matériaux (couleur, rugosité, métallicité,
  opacité, texture, affectation, aperçu immédiat), panneau statistiques / progression / journal.
- Viewport : moteur de rendu séparé, modes solide / filaire / matériaux, perspective et
  orthographique, caméra orbitale et libre, 7 vues, sélection simple et multiple, gizmos
  de translation / rotation / échelle (magnétisme Ctrl), fond studio, grille, axes.
- Annuler / rétablir pour toutes les modifications, duplication, suppression confirmée.
- Import GLB, glTF, OBJ, STL, PLY (hiérarchie, matériaux PBR, textures, UV) en arrière-plan
  avec progression ; FBX via Blender en processus auxiliaire (vérifié) ; formats GTA V /
  FiveM reconnus comme « prévus » sans chargement simulé.
- Format .lsfc v2 : provenance (chemin d'origine, SHA-256, importateur), matériaux,
  hiérarchie, caméra, miniature ; migration automatique des projets v0.1 ; enregistrer sous ;
  sauvegarde automatique et récupération après interruption ; originaux jamais modifiés.
- 90 tests automatisés (rendu OpenGL réel, interface, format, import FBX via Blender).

### Prévu (visible comme « Bientôt », non fonctionnel)

- Bibliothèque de composants, Livrées, ateliers LSPD et EMS / SAMD, Configurations,
  Intelligence artificielle, Lore Friendly, Optimisation, Export FiveM, import d'addons FiveM.

## [0.1.0] - 2026-10-11

Première version : fondations de l'application.

### Fonctionnel

- Interface PySide6 en français, thème sombre à accents bleu électrique, navigation par ateliers.
- Gestionnaire de projets : création (nom, type de véhicule, usage, emplacement), ouverture,
  projets récents, projet de démonstration avec véhicule d'exemple.
- Projets enregistrés dans un fichier SQLite `.lsfc` (enregistrement atomique, ouverture en
  lecture seule, versionnement de schéma avec migrations) ; modèles copiés dans `assets/`.
- Viewport 3D OpenGL : grille au sol, axes, éclairage, surbrillance de la sélection,
  sélection par clic. Fonctionne avec le GPU ou en rendu logiciel (`--software-gl`).
- Import de modèles GLB, glTF (avec fichiers externes), OBJ, STL et PLY (couleurs conservées).
- Navigation : orbite, panoramique, zoom, cadrage (F), vues avant / droite / dessus.
- Explorateur d'objets (visibilité, cadrage, retrait) et panneau de propriétés contextuel
  (projet ou objet : nom, position, rotation, échelle uniforme ou non).
- Journal en direct filtrable, fichier de log tournant, rapport de diagnostics copiable.
- 98 tests automatisés (pytest, pytest-qt, rendu OpenGL réel).
- Build `LeStitcheurFouCars.exe` (PyInstaller) avec test de démarrage automatique.
- GitHub Actions : lint, tests Windows (Python 3.12 et 3.13), build de l'exécutable publié
  comme artifact, release automatique sur tag `vX.Y.Z` depuis `main`.

### Prévu (interface réservée, non fonctionnel)

- Ateliers Livrées, LSPD / EMS, Génération IA et Export FiveM.
- Import de véhicules GTA V / FiveM existants, textures et matériaux.

[Non publié]: https://github.com/LeStitcheur/lestitcheurfou-cars/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/LeStitcheur/lestitcheurfou-cars/releases/tag/v0.3.0
[0.2.0]: https://github.com/LeStitcheur/lestitcheurfou-cars/releases/tag/v0.2.0
[0.1.0]: https://github.com/LeStitcheur/lestitcheurfou-cars/releases/tag/v0.1.0
