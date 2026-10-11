# LeStitcheurFou Cars

[![CI](https://github.com/LeStitcheur/lestitcheurfou-cars/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/LeStitcheur/lestitcheurfou-cars/actions/workflows/ci.yml)
[![Build Windows](https://github.com/LeStitcheur/lestitcheurfou-cars/actions/workflows/build-windows.yml/badge.svg?branch=develop)](https://github.com/LeStitcheur/lestitcheurfou-cars/actions/workflows/build-windows.yml)

Atelier Windows de création, d'adaptation et d'export de véhicules **Lore Friendly** pour **GTA V / FiveM**.

> Statut : **v0.1.0 — fondations**. Voir [CHANGELOG.md](CHANGELOG.md) pour ce qui fonctionne réellement aujourd'hui.

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

## Fonctionnalités de la v0.1.0

| Fonction | État |
|---|---|
| Interface PySide6 en français, thème sombre / bleu électrique | ✅ |
| Gestionnaire de projets (création, ouverture, projets récents) | ✅ |
| Sauvegarde / réouverture de projet (fichier `.lsfc` SQLite) | ✅ |
| Viewport 3D OpenGL (grille, éclairage, sélection) | ✅ |
| Import de modèles GLB / glTF / OBJ / STL / PLY | ✅ |
| Navigation 3D (orbite, panoramique, zoom, cadrage) | ✅ |
| Explorateur d'objets et propriétés (transformations, visibilité) | ✅ |
| Logs en direct et diagnostics système | ✅ |
| Ateliers Livrées, LSPD/EMS, IA, Export FiveM | 🕓 interface réservée, non fonctionnels |

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

Tests : `pytest` — Build Windows : `scripts\build_windows.ps1`.

## Documentation

- [Guide utilisateur](docs/GUIDE_UTILISATEUR.md)
- [Installation](docs/INSTALLATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Contribuer](CONTRIBUTING.md)

## Licence

Licence du projet : à définir par le propriétaire du dépôt (aucun fichier `LICENSE` pour l'instant,
ce qui équivaut à « tous droits réservés »).

## Avertissement légal

Ce projet n'est ni affilié ni approuvé par Rockstar Games ou Take-Two Interactive.
Le dépôt ne contient et ne doit contenir **aucun fichier propriétaire GTA V**, aucun secret ni aucun
modèle sous licence restrictive.
