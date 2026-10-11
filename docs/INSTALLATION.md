# Installation

## Utilisateur : exécutable Windows

1. Téléchargez `LeStitcheurFouCars.exe` :
   - version publiée : page [Releases](https://github.com/LeStitcheur/lestitcheurfou-cars/releases) ;
   - version de développement : onglet **Actions** › workflow **Build Windows** › dernier
     run réussi › section **Artifacts** (connexion GitHub requise, fichier `.zip` à extraire).
2. Placez l'exécutable où vous voulez (aucune installation nécessaire) et lancez-le.

L'exécutable n'est pas signé numériquement : Windows SmartScreen peut afficher
« Windows a protégé votre ordinateur ». Cliquez sur **Informations complémentaires** puis
**Exécuter quand même** si vous l'avez téléchargé depuis le dépôt officiel.

### Configuration requise

- Windows 10 ou 11, 64 bits.
- Carte graphique compatible OpenGL 3.3 (recommandé). À défaut, un rendu logiciel intégré
  est utilisé avec l'option `--software-gl` (plus lent).

### Emplacements des données

| Donnée | Emplacement |
|---|---|
| Journal, paramètres, projets récents | `%APPDATA%\LeStitcheurFouCars\` |
| Projets (proposé par défaut) | `Documents\LeStitcheurFou Cars\Projets\` |

La variable d'environnement `LSFCARS_HOME` permet de déplacer le dossier de données
(installation portable).

### Options de ligne de commande

```
LeStitcheurFouCars.exe [projet.lsfc] [--software-gl] [--debug] [--version]
```

| Option | Effet |
|---|---|
| `projet.lsfc` | Ouvre ce projet au démarrage |
| `--software-gl` | Rendu OpenGL logiciel (pilote graphique absent ou défaillant) |
| `--debug` | Journal détaillé |
| `--smoke-test MS` | Test de démarrage automatique (utilisé par la CI) |

## Développeur : depuis les sources

```powershell
git clone https://github.com/LeStitcheur/lestitcheurfou-cars.git
cd lestitcheurfou-cars
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m lsfcars
```

Construire l'exécutable :

```powershell
.\scripts\build_windows.ps1
```

Le fichier est produit dans `dist\LeStitcheurFouCars.exe`, puis lancé automatiquement en mode
test de démarrage.

## Dépannage

- **Le viewport affiche « Le rendu 3D n'a pas pu démarrer »** : mettez à jour le pilote
  graphique ou relancez avec `--software-gl`.
- **Un projet s'ouvre avec des fichiers manquants** : les modèles doivent rester dans le dossier
  `assets` du projet. Le journal indique les chemins attendus.
- **Signaler un problème** : menu Aide › Diagnostics… › Copier le rapport, puis ouvrez une
  [issue](https://github.com/LeStitcheur/lestitcheurfou-cars/issues).
