# Journal des modifications

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/),
versionnement [SemVer](https://semver.org/lang/fr/).

## [Non publié]

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

[Non publié]: https://github.com/LeStitcheur/lestitcheurfou-cars/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/LeStitcheur/lestitcheurfou-cars/releases/tag/v0.1.0
