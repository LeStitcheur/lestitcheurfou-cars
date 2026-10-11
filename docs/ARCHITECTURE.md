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

### Ajouts v0.2 / v0.3

```
src/lsfcars/
├── fivem/              lecture GTA V / FiveM, sans Qt
│   ├── rpf.py          archives RPF7 non chiffrées (refus des archives chiffrées)
│   ├── rsc.py          ressources RSC7 : en-tête, blocs, pointeurs, joaat
│   ├── ytd.py          dictionnaires de textures, décodage, export DDS / PNG
│   ├── yft.py          fragments / drawables : squelette, géométrie, shaders, découpage par os
│   ├── meta.py         métadonnées XML, recherche, vérifications croisées
│   ├── resource.py     analyse d'une ressource, statuts, manifeste d'import
│   ├── structure.py    classification des composants, modes d'inspection
│   ├── sollumz.py      Blender / Sollumz : sondage, tâches annulables
│   ├── gta_install.py  inventaire des archives d'une installation
│   ├── project_import.py  copies et provenance dans le projet
│   └── synthetic.py    fichiers synthétiques (tests, addon de démonstration)
├── importers/yft_importer.py  .yft / .ydr → ImportResult (os = groupes, pièces = maillages)
├── scene/inspection.py vue éclatée, statistiques, points d'ancrage (affichage seulement)
└── ui/import_studio/   Vehicle Import Studio (page, panneaux, TaskWorker)
```

## Format de projet `.lsfc`

Base SQLite, écrite dans un fichier temporaire puis substituée (`os.replace`) : un plantage
pendant l'enregistrement ne corrompt pas le projet existant. L'ouverture copie la base en mémoire
et ne modifie jamais le fichier.

| Table | Colonnes |
|---|---|
| `meta` | `key`, `value` — `format`, `schema_version`, `app_version`, `name`, `vehicle_type`, `role`, `description`, `created_at`, `updated_at` (ISO 8601 UTC), `camera` (JSON) |
| `assets` | modèles copiés : chemin relatif, nom et chemin d'origine, SHA-256, format, importateur, notes |
| `materials` | couleur, rugosité, métallicité, opacité, texture, double face |
| `nodes` | hiérarchie : parent, rang, nom, type, transformation (JSON), visibilité, verrou, asset, maillage, matériau, `extra` (JSON, format 3 : métadonnées d'origine GTA V) |
| `resources` | format 3 : ressources FiveM importées — nom, source, type de source, statut, date, `manifest` (JSON versionné) |
| `thumbnail` | miniature PNG |

Historique : format 1 (v0.1, table `scene_objects`), format 2 (v0.2), format 3 (v0.3).

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
- `fivem/` : **export** de ressource (`fxmanifest.lua`, métadonnées, écriture RSC7) — la lecture
  existe depuis la v0.3, l'écriture reste à faire.
