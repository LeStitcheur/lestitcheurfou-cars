# Architecture

## Vue d'ensemble

```
src/lsfcars/
├── app.py              point d'entrée (arguments, OpenGL, QApplication, test de démarrage)
├── core/               sans Qt Widgets
│   ├── paths.py        dossiers de données (LSFCARS_HOME), ressources, exemples
│   ├── logging_setup.py  fichier tournant + tampon mémoire pour l'UI
│   └── diagnostics.py  rapport système / bibliothèques / OpenGL
├── project/            sans Qt
│   ├── model.py        Project, SceneObject, Transform, VehicleType, VehicleRole
│   ├── store.py        persistance SQLite .lsfc, migrations, import d'assets
│   ├── session.py      projet ouvert + maillages chargés + état « modifié »
│   └── recent.py       projets récents (recent.json)
├── scene/              pur numpy, testable sans GPU
│   ├── mesh.py         MeshData (positions, normales, couleurs, indices)
│   ├── loader.py       import trimesh -> MeshData
│   ├── camera.py       caméra orbitale (axe vertical +Y)
│   ├── mathutils.py    matrices 4x4
│   └── picking.py      lancer de rayon pour la sélection
└── ui/                 PySide6
    ├── main_window.py  orchestration : navigation, docks, menus, actions
    ├── viewport.py     rendu OpenGL (classes Qt), interaction
    ├── panels/         explorateur, propriétés, journal
    ├── dialogs/        nouveau projet, diagnostics
    ├── home_page.py    gestionnaire de projets
    ├── workshop_page.py  ateliers à venir (descriptifs, sans fonction simulée)
    ├── theme.py        palette et feuille de style
    └── gl_setup.py     format OpenGL / rendu logiciel
```

Dépendances autorisées : `ui → project → scene → core`. La logique métier reste hors de `ui/`.

## Format de projet `.lsfc`

Base SQLite, écrite dans un fichier temporaire puis substituée (`os.replace`) : un plantage
pendant l'enregistrement ne corrompt pas le projet existant. L'ouverture copie la base en mémoire
et ne modifie jamais le fichier.

| Table | Colonnes |
|---|---|
| `meta` | `key`, `value` — `format`, `schema_version`, `app_version`, `name`, `vehicle_type`, `role`, `description`, `created_at`, `updated_at` (ISO 8601 UTC), `camera` (JSON) |
| `scene_objects` | `id`, `position`, `name`, `asset_path` (relatif, `/`), `transform` (JSON), `visible` |

Évolution du schéma : incrémenter `SCHEMA_VERSION` et ajouter le script dans `_MIGRATIONS`
(`store.py`). Un projet plus récent que le logiciel est refusé avec un message explicite.

## Rendu 3D

- `QOpenGLWidget` + `QOpenGLShaderProgram` / `QOpenGLBuffer` / `QOpenGLVertexArrayObject`.
- PyOpenGL est volontairement écarté : il charge l'`opengl32.dll` système et ne fonctionne pas
  avec le Mesa embarqué par Qt (`opengl32sw.dll`), indispensable en CI et sur les machines sans
  pilote correct.
- Shaders compatibles GLSL 3.30 core et 1.30 (Mesa logiciel = OpenGL 3.0) ; la directive
  `#version` est ajoutée selon le contexte obtenu.
- Envoi GPU différé au premier rendu ; libération différée au rendu suivant (contexte courant).
- Éclairage : lumière principale + appoint, spéculaire, rendu double face ; la sélection ajoute
  une teinte et un liseré bleu électrique.

## Choix techniques

| Besoin | Choix | Raison |
|---|---|---|
| Interface | PySide6-Essentials | Licence LGPL, modules suffisants, exécutable plus léger |
| Import 3D | trimesh | MIT, pur Python + numpy, GLB/glTF/OBJ/STL/PLY |
| Normales | calcul numpy maison | évite la dépendance à scipy de trimesh |
| Persistance | SQLite | standard, transactionnel, inspectable, migrations simples |
| Packaging | PyInstaller (fichier unique) | un seul `LeStitcheurFouCars.exe` à distribuer |

## Extensions prévues

- `blender/` : pilotage de Blender en processus auxiliaire (conversion, optimisation).
- `ai/` : interface `GenerationBackend` avec adaptateurs locaux et cloud ; clés API stockées hors
  du dépôt (coffre Windows).
- `fivem/` : export de ressource (`fxmanifest.lua`, métadonnées véhicule), contrôles de conformité.
