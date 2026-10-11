# LeStitcheurFou Cars

[![CI](https://github.com/LeStitcheur/lestitcheurfou-cars/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/LeStitcheur/lestitcheurfou-cars/actions/workflows/ci.yml)
[![Build Windows](https://github.com/LeStitcheur/lestitcheurfou-cars/actions/workflows/build-windows.yml/badge.svg?branch=develop)](https://github.com/LeStitcheur/lestitcheurfou-cars/actions/workflows/build-windows.yml)

Atelier Windows de création, d'adaptation et d'export de véhicules **Lore Friendly** pour **GTA V / FiveM**.

> Statut : **v0.4.0 — Vehicle Editor : modélisation réelle, carrosserie, composants, roues, habitacle**.
> Voir [CHANGELOG.md](CHANGELOG.md) pour ce qui fonctionne réellement aujourd'hui.

![Vehicle Editor — mode Édition](docs/screenshots/1920x1080@1_mode_edition.png)
![Bodywork Studio et bibliothèque](docs/screenshots/1920x1080@1_bodywork_bibliotheque.png)
![Wheel Editor](docs/screenshots/1920x1080@1_wheel_editor.png)
![Vehicle Import Studio](docs/screenshots/1920x1080@1_import_studio.png)

## Vision

LeStitcheurFou Cars a pour objectif de permettre de :

- importer un modèle 3D (GLB, OBJ…) ou un véhicule GTA V / FiveM existant ;
- générer une proposition 3D depuis des images de référence (IA locale ou cloud) ;
- adapter les véhicules au style Lore Friendly ;
- les modifier dans un éditeur 3D intégré ;
- créer des configurations LSPD / EMS, ajouter accessoires et équipements d'urgence ;
- créer et personnaliser des livrées ;
- optimiser les modèles et exporter une ressource FiveM compatible.

Tous les types de véhicules sont prévus : voitures, SUV, motos, camions, bateaux, hélicoptères, aéronefs.

## Fonctionnalités de la v0.4.0

| Fonction | État |
|---|---|
| **Vehicle Editor** : modes Objet, Édition (sommets / arêtes / faces), Composant | ✅ |
| Édition réelle du maillage : déplacer, pivoter, échelle, extrusion, inset, fusion, suppression, normales, symétrie, séparation, projection UV | ✅ |
| Biseau d'arêtes (Blender en processus auxiliaire) | ✅ si Blender est installé |
| **Bodywork Studio** : panneaux, proportions, création de pièces originales, symétrie gauche / droite | ✅ |
| **Component Library** locale (25 composants originaux, import, presets, recherche, filtres) | ✅ |
| **Replace Component** avec prévisualisation, options et historique réversible | ✅ |
| **Wheel Editor** : identification, voie, empattement, alignement, échelle, pivots, profils, aperçu de rotation | ✅ |
| **Interior Studio** : isolation, carrosserie masquée, caméra intérieure, configurations civil / police / EMS / commandement | ✅ |
| **Attachment Points** : création, axes, contraintes, métadonnées, association | ✅ |
| Matériaux étendus : carte de normales, UV, 9 presets automobiles, shader GTA V indicatif | ✅ |
| Historique : transactions, budget mémoire, points de restauration ; rapport de compatibilité FiveM | ✅ |
| `.lsfc` v4 (géométrie locale, ancrages, variantes ; migration v1 → v4) | ✅ |
| Design **Dark Premium** (palette bleue officielle, design system centralisé) | ✅ |
| **Vehicle Import Studio** : dossier FiveM, ZIP, RPF non chiffré, fichiers isolés, installation GTA V | ✅ |
| Analyse automatique : fichiers, modèles, variantes `_hi`, textures, métadonnées, dépendances, diagnostics | ✅ |
| Décodage natif `.yft` (squelette, géométrie, roues, shaders) et `.ytd` (DXT, BC, non compressés) | ✅ |
| Lecteur de métadonnées (vehicles, handling, carvariations, carcols…) avec vérifications croisées | ✅ |
| Inspection : composants classés, isolement, vue éclatée non destructive, filaire, os, ancrages, stats | ✅ |
| Inspecteur de textures : aperçu, format, transparence, mémoire, export PNG / DDS | ✅ |
| Import dans le projet avec manifeste versionné, métadonnées d'os conservées | ✅ |
| Blender / Sollumz : détection et sondage réels, tâches annulables | ✅ (Sollumz non testé : non installé) |
| Collisions `.ybn` (géométrie), export FiveM, écriture des formats GTA V | 🕓 non implémentés |
| Matériaux, projets, sauvegarde auto (v0.2) | ✅ |
| Livrées, LSPD, EMS / SAMD, IA, Lore Friendly, Optimisation, Export FiveM | 🕓 « Bientôt », non fonctionnels |

Vehicle Editor, outils et limites : [docs/VEHICLE_EDITOR.md](docs/VEHICLE_EDITOR.md).
Compatibilité détaillée des formats et limites : [docs/FIVEM_IMPORT.md](docs/FIVEM_IMPORT.md).
Design system : [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md).

## Installation (utilisateur)

Téléchargez `LeStitcheurFouCars.exe` depuis la page [Releases](https://github.com/LeStitcheur/lestitcheurfou-cars/releases)
ou depuis les artifacts du workflow **Build Windows**. Voir [docs/INSTALLATION.md](docs/INSTALLATION.md).

## Démarrage rapide (développeur)

```powershell
git clone https://github.com/LeStitcheur/lestitcheurfou-cars.git
cd lestitcheurfou-cars
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m lsfcars
```

Tests : `pytest` — Build Windows : `scripts\build_windows.ps1` —
addon de démonstration (synthétique) : `python scripts\generate_demo_addon.py`.

## Documentation

- [Guide utilisateur](docs/GUIDE_UTILISATEUR.md)
- [Vehicle Editor](docs/VEHICLE_EDITOR.md)
- [Vehicle Import Studio et formats GTA V / FiveM](docs/FIVEM_IMPORT.md)
- [Design system Dark Premium](docs/DESIGN_SYSTEM.md)
- [Installation](docs/INSTALLATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Contribuer](CONTRIBUTING.md)

## Licence

Licence du projet : à définir par le propriétaire du dépôt (aucun fichier `LICENSE` pour l'instant,
ce qui équivaut à « tous droits réservés »).

## Avertissement légal

Ce projet n'est ni affilié ni approuvé par Rockstar Games ou Take-Two Interactive.
Le dépôt ne contient et ne doit contenir **aucun fichier propriétaire GTA V**, aucun secret ni aucun
modèle sous licence restrictive. LeStitcheurFou Cars ne contourne aucun chiffrement, DRM ou
protection de ressource (archives officielles chiffrées, FiveM Asset Escrow) : ces contenus sont
détectés et refusés avec une explication.
