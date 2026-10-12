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

Direction **Dark Premium — Automotive Creation Studio** (v0.3). L'identité rouge/rose de
LeStitcheur Control est définitivement abandonnée : ne pas la réintroduire. Palette exclusive de
12 couleurs dans `ui/design/tokens.py` (`ColorTokens`) ; les nuances sont dérivées par `mix()` /
`rgba()`. Aucune couleur littérale ailleurs dans `ui/` (test `test_design_system.py`).
Voir `docs/DESIGN_SYSTEM.md`.
Ne pas utiliser `NoButtons` sur les QDoubleSpinBox (valeur invisible avec la feuille de style).

## FiveM / GTA V (v0.3)

- `fivem/` : lecteurs purs (rpf, rsc, ytd, yft, meta), `resource.py` (analyse et statuts),
  `structure.py` (classification), `sollumz.py`, `gta_install.py`, `project_import.py`,
  `synthetic.py` (fichiers de test et addon de démonstration, **pas** un exporteur).
- Ne jamais simuler une conversion ni déclarer « Compatible » sans décodage effectif.
- Ne jamais déchiffrer : archives AES/NG et Asset Escrow sont refusées avec explication.
- Aucun fichier GTA V tiers dans le dépôt ni dans les tests versionnés ; tests réels
  facultatifs via `LSFCARS_REAL_RESOURCE`.
- Détails et tableau de compatibilité : `docs/FIVEM_IMPORT.md`.

## Vehicle Editor (v0.4)

- `scene/editmesh.py` : édition de maillage pure numpy (topologie soudée, sélections, opérations) ;
  chaque opération retourne un **nouveau** `MeshData` (immuable) et signale ses effets sur les UV.
- `scene/shapes.py` : formes paramétriques originales (aucun asset tiers).
- Géométrie locale : `SceneGraph.meshes` + nœud `asset_id=None, mesh_key=<clé>` ; enregistrée
  dans la table `meshes` du `.lsfc` v4. Les fichiers importés ne sont jamais modifiés.
- `editor/` (sans Qt) : `operations.py` (`VehicleEditor`, toutes les opérations via l'historique),
  `vehicle.py` (axes, catégories, rôles, roues, habitacle, ancrages), `library.py`
  (bibliothèque locale), `compat.py` (avertissements et rapport FiveM), `edit_state.py` (modes),
  `blender_ops.py` (biseau Blender).
- `ui/editor/` : panneaux (outils, géométrie, ancrages, ateliers, historique, compatibilité) et
  bibliothèque / Replace Component. Page : `ui/studio/studio_page.py`.
- Ne jamais présenter un outil comme disponible si son algorithme ne l'est pas (biseau désactivé
  sans Blender). Ne jamais promettre la jouabilité FiveM d'un véhicule modifié.
- Détails : `docs/VEHICLE_EDITOR.md`.

## AI Vehicle Creator (v0.7)

- `ai/` (sans Qt) : `manager.py` (registre, configuration, routage, `JobQueue`, cache),
  `engines/` (`base.py` interface commune ; `silhouette.py` intégré ; `triposr.py` + worker
  `workers/triposr_worker.py` lancé par le Python du moteur ; `comfyui.py`, `meshy.py`,
  `anthropic.py`), `hardware.py`, `secrets.py` (DPAPI), `http.py` (reprises, journal sans
  contenu), `references.py`, `vision.py`, `lore.py`, `mesh_assist.py`, `texture.py`,
  `raster3d.py` (miniatures), `creator.py` (`AIVehicleCreator`, document `ai`). Interface :
  `ui/ai/`.
- État dans `documents["ai"]` (format 1) + blobs `ref-*` / `thumb-*` ; modèles générés importés
  comme fichiers du projet ; annexes dans `assets/ai/<id>/`. Schéma `.lsfc` inchangé (v6).
- Moteurs locaux hors dépôt et hors exe : `%USERPROFILE%\.lestitcheurfoucars\engines`
  (`LSFCARS_ENGINES`) ; tests isolés par `conftest.py`. Jamais de clé API en dur, dans un
  projet ou un journal.
- Ne jamais présenter un adaptateur comme vérifié s'il n'a été testé que contre un serveur
  simulé (`SIMULATED_ONLY`) ; aucun transfert cloud ni opération payante sans confirmation ;
  ne jamais afficher de coût inventé ; un maillage généré n'est jamais « compatible FiveM ».
- Détails : `docs/AI_VEHICLE_CREATOR.md`.

## Livery Studio (v0.6)

- `livery/` : `model.py` (document versionné, calques, variantes), `surface.py` (UV ↔ 3D, pinceau
  3D, analyse UV, placement orienté, symétrie 3D), `raster.py`, `blend.py`, `render2d.py` (QtGui),
  `bands.py`, `compositor.py` (mises à jour partielles), `logos.py`, `templates.py`, `export.py`,
  `studio.py` (`LiveryStudio`, toutes les opérations via l'historique). Interface : `ui/livery/`.
- `.lsfc` v6 : `documents["livery"]` + tables `images` / `blobs` ; seuls les éléments cités par un
  document sont enregistrés. Commandes `SetImage`, `PatchImage`, `AddBlob`.
- La peinture 3D doit modifier les texels (jamais une superposition écran) ; viewport, canvas et
  export partagent la même composition (`session.live_textures`).
- Ne jamais modifier les UV sans confirmation ; ne jamais annoncer un fichier YTD (aucun écrit).
- `QTreeWidget` / `QListWidget` : vider avec `clear_items` (pas `clear()`) ; textures OpenGL
  détachées si leur contexte disparaît (`Renderer._abandon_textures`).
- Détails : `docs/LIVERY_STUDIO.md`.

## Emergency Studio (v0.5)

- `emergency/` (sans Qt) : `model.py` (services, profils, feux, motifs, sirènes, variantes,
  `StudioState`), `equipment.py` (équipements procéduraux originaux, `EquipmentLibrary`),
  `studio.py` (`EmergencyStudio`), `sirens.py` (tonalités synthétisées), `adapters.py` (export).
- État dans `SceneGraph.documents["emergency"]`, modifié uniquement par `SetDocument` dans une
  `CompositeCommand` ; table `documents` du `.lsfc` v5.
- La prévisualisation lumineuse est une simulation viewport : ne jamais la présenter comme un
  rendu en jeu. Aucun export ne garantit l'utilisation ELS / non-ELS en jeu ; un format non
  supporté (ELS classique) est refusé avec explication.
- Aucun son, logo ou modèle propriétaire ; services et marques fictifs.
- Détails : `docs/EMERGENCY_STUDIO.md`.

## Architecture v0.2-v0.3 (src/lsfcars)

- `scene/` : graphe (`graph.py`), transformations, matériaux, historique (`commands.py`),
  sélection, caméra, gizmos (math pure), picking.
- `importers/` : trimesh (GLB/glTF/OBJ/STL/PLY), FBX via Blender, `.yft`/`.ydr` natifs.
- `ui/import_studio/` : Vehicle Import Studio (page, panneaux, tâches annulables).
- `scene/inspection.py` : vue éclatée et statistiques (affichage seulement, non destructif).
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
