# Contribuer à LeStitcheurFou Cars

## Environnement

Prérequis : Windows 10/11, Python 3.12 ou plus récent, Git.

```powershell
git clone https://github.com/LeStitcheur/lestitcheurfou-cars.git
cd lestitcheurfou-cars
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m lsfcars
```

## Branches

| Branche | Rôle |
|---|---|
| `main` | Versions publiées. Chaque release est un tag `vX.Y.Z` sur `main`. |
| `develop` | Intégration continue des fonctionnalités terminées. |
| `feature/<nom>` | Une fonctionnalité, créée depuis `develop`. |
| `fix/<nom>` | Une correction, créée depuis `develop` (ou `main` pour un correctif urgent). |

Flux : `feature/*` → pull request vers `develop` → pull request `develop` → `main` pour publier.

Règles : pas de `push --force` sur `main` ni `develop`, pas de réécriture de l'historique partagé.

## Commits

Messages en français, au format [Conventional Commits](https://www.conventionalcommits.org/fr/) :

```
feat: atelier de livrées — calques de couleur
fix: le cadrage ignore les objets masqués
docs: guide d'installation
test: couverture du chargement glTF
ci: cache pip sur les runners Windows
```

## Avant d'ouvrir une pull request

```powershell
ruff check .
ruff format .
pytest
```

- Mettre à jour `CHANGELOG.md` (section « Non publié »).
- Ne jamais présenter une fonctionnalité simulée comme fonctionnelle.
- La CI (lint + tests Windows) doit être verte.

## Interdits

Ne jamais versionner : secrets ou clés API, fichiers propriétaires GTA V (`.rpf`, `.yft`,
`.ytd`…), modèles 3D ou poids d'IA sous licence restrictive. Le `.gitignore` en bloque une partie,
mais la vigilance reste nécessaire.

## Publier une version

1. Sur `develop` : mettre à jour `__version__` dans `src/lsfcars/__init__.py` et `CHANGELOG.md`.
2. Pull request `develop` → `main`, puis fusion.
3. Créer et pousser le tag sur `main` :
   ```powershell
   git checkout main ; git pull
   git tag v0.2.0
   git push origin v0.2.0
   ```
4. Le workflow **Build Windows** vérifie que le tag correspond à la version, construit
   l'exécutable et publie la release avec les notes du CHANGELOG.

## Tests

- `tests/` : pytest + pytest-qt. Les données de l'application sont isolées via `LSFCARS_HOME`.
- `LSFCARS_SOFTWARE_GL=1` force le rendu OpenGL logiciel (machines sans GPU).
- `LSFCARS_REQUIRE_GL=1` fait échouer les tests de rendu si OpenGL est indisponible (utilisé en CI).

Voir aussi [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
