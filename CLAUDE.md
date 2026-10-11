# CLAUDE.md — LeStitcheurFou Cars

Instructions pour les agents travaillant sur ce dépôt.

## Projet

- Nom officiel : **LeStitcheurFou Cars** — exécutable : `LeStitcheurFouCars.exe`.
- L'ancien nom « LoreForge Studio » est abandonné : ne jamais le réintroduire.
- Dépôt : https://github.com/LeStitcheur/lestitcheurfou-cars — branches `main` (releases) et `develop` (intégration).
- Interface et documentation **en français**. Code (identifiants) en anglais, docstrings/commentaires en français.

## Stack

Python 3.12+, PySide6 (Essentials uniquement), trimesh (import 3D), SQLite (projets `.lsfc`),
pytest + pytest-qt, PyInstaller, GitHub Actions.

Rendu : classes OpenGL de Qt (`QOpenGLShaderProgram`, `QOpenGLBuffer`…), **pas PyOpenGL** — PyOpenGL
appelle l'`opengl32.dll` système et casse le rendu logiciel Mesa embarqué par Qt (`--software-gl`,
utilisé en CI). Shaders compatibles GLSL 1.30 et 3.30 (en-tête ajouté selon le contexte).
`glDrawElements` exige `shiboken6.VoidPtr(0)` comme offset.

## Commandes

```powershell
pip install -e ".[dev]"     # installation développeur
python -m lsfcars           # lancer l'application
pytest                      # tests
ruff check . ; ruff format --check .
scripts\build_windows.ps1   # build dist\LeStitcheurFouCars.exe
```

## Identité graphique

Référence : LeStitcheur Control (`../lestitcheur`, `src/design.css`). Ne pas réintroduire le
thème bleu de la v0.1. Toute couleur passe par `ui/design/tokens.py` ; voir `docs/DESIGN_SYSTEM.md`.
Ne pas utiliser `NoButtons` sur les QDoubleSpinBox (valeur invisible avec la feuille de style).

## Architecture v0.2 (src/lsfcars)

- `scene/` : graphe (`graph.py`), transformations, matériaux, historique (`commands.py`),
  sélection, caméra, gizmos (math pure), picking.
- `importers/` : trimesh (GLB/glTF/OBJ/STL/PLY) et FBX via Blender ; formats GTA « prévus ».
- `render/renderer.py` : rendu GL indépendant de l'UI ; `ui/viewport.py` : interaction seule.
- `ui/design/` : design system ; `ui/pages/` ; `ui/studio/` (contrôleur, panneaux, page).
- Toute modification de scène passe par `ProjectSession` → `UndoStack`.

## Architecture v0.1 (historique)

- `core/` : chemins, logs, diagnostics, paramètres — aucune dépendance Qt Widgets.
- `project/` : modèle de projet, types de véhicules, persistance SQLite (`store.py`), projets récents.
- `scene/` : maillages, chargement de modèles, caméra orbitale — pur numpy, testable sans GPU.
- `ui/` : fenêtre principale, viewport OpenGL, panneaux, dialogues, thème.

Règle : la logique métier reste hors de `ui/` pour être testable sans affichage.

## Règles

- Ne jamais présenter une fonctionnalité simulée comme fonctionnelle : les ateliers non implémentés
  sont marqués « Prévu » dans l'interface et la documentation.
- Ne jamais versionner de secrets, de fichiers GTA V (`.rpf`, `.yft`, `.ytd`…) ni de modèles sous licence.
- Pas de `push --force`, pas de réécriture de l'historique distant.
- Branches de fonctionnalité `feature/<nom>` → PR vers `develop` ; releases par tag `vX.Y.Z` sur `main`.
- Mettre à jour `CHANGELOG.md` à chaque changement visible.
- Toute évolution du schéma SQLite passe par une migration dans `project/store.py` (`SCHEMA_VERSION`).
