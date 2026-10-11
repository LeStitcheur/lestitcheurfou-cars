# Design system — Dark Premium, Automotive Creation Studio

Depuis la version 0.3.0, LeStitcheurFou Cars utilise sa propre direction artistique
**Dark Premium** : un studio de création automobile sombre, sobre et lisible, à accents bleus.
L'identité rouge/rose inspirée de LeStitcheur Control (v0.2) est abandonnée.

Code : `src/lsfcars/ui/design/`

| Module | Contenu |
|---|---|
| `tokens.py` | `ColorTokens`, `TypographyTokens`, `SpacingTokens` (densités), `AnimationTokens`, `AppTheme`, teintes de badges |
| `qss.py` | `ComponentStyles` : feuille de style Qt et palette générées depuis les tokens |
| `fonts.py` | polices système (Segoe UI Variable / Segoe UI, Cascadia Mono) |
| `icons.py` | icônes Lucide colorées à la volée, logo de l'application |
| `components.py`, `sidebar.py`, `topbar.py` | composants réutilisables |

## Palette officielle (exclusive)

| Rôle | Token | Valeur |
|---|---|---|
| Fond principal | `ColorTokens.BG_MAIN` | `#0B0E14` |
| Fond secondaire (barre supérieure, navigation) | `BG_SECONDARY` | `#111722` |
| Panneaux | `PANEL` | `#151B26` |
| Surfaces (boutons, champs actifs) | `SURFACE` | `#202A3B` |
| Bordures | `BORDER` | `#2A3445` |
| **Bleu principal** (sélection, bouton principal, élément actif) | `PRIMARY` | `#2563EB` |
| **Bleu électrique** (focus, onglet actif, indicateurs, liseré) | `ELECTRIC` | `#38BDF8` |
| Texte principal | `TEXT` | `#F3F6FC` |
| Texte secondaire | `TEXT_SECONDARY` | `#94A3B8` |
| Succès | `SUCCESS` | `#22C55E` |
| Avertissement | `WARNING` | `#F59E0B` |
| Erreur | `ERROR` | `#EF4444` |

Les nuances intermédiaires (survols, fonds teintés des badges, bordures actives, textes
atténués) sont **dérivées** de ces douze valeurs par `mix()` ou `rgba()` dans `tokens.py` ;
aucune autre couleur n'est inventée. Les couleurs d'état ne servent qu'à communiquer un état.
Les axes X/Y/Z du viewport utilisent la convention universelle des outils 3D, exprimée avec la
palette (erreur, succès, bleu).

Règle vérifiée par `tests/test_design_system.py` : aucun code hexadécimal ni `rgb()` en dehors
de `tokens.py` dans `src/lsfcars/ui/`. Le moteur de rendu (`render/renderer.py`) lit aussi ses
couleurs (fond, grille, sélection) dans les tokens.

## Typographie

- Texte : Segoe UI Variable Text (repli Segoe UI), 13 px (12 px en mode compact).
- Titres : Segoe UI Variable Display, graisse 600.
- Code et XML : Cascadia Mono (repli Consolas).
- Petites capitales espacées via `fonts.font(..., spacing, caps=True)` (Qt n'interprète pas
  `letter-spacing` en QSS).

Aucune police tierce n'est embarquée.

## Espacements et animations

- Échelle : 4 / 8 / 12 / 16 / 24 / 32 px ; deux densités (`NORMAL`, `COMPACT`).
- Barre supérieure 44 px, navigation 224 px (60 px repliée).
- Animations courtes : 120 / 170 / 260 ms ; toasts 4,2 s ; aucune animation permanente.

## Composants

| Composant | Usage |
|---|---|
| `LSButton` | `primary` (bleu principal), `secondary`, `ghost`, `danger` (actions destructives), option `small`, `chip` |
| `LSIconButton` | bouton icône, état coché bleu |
| `LSCard`, `LSPanel` | cartes et panneaux `#151B26` |
| `LSSectionHeader`, `Breadcrumb`, `eyebrow`, `heading` | en-têtes de page (point final bleu électrique) |
| `LSStatsGrid`, `LSIconBox` | statistiques |
| `LSBadge` | teintes `blue`, `electric`, `neutral` (information) et `green`, `amber`, `red` (états) |
| `LSInput`, `LSSelect`, `LSTabs`, `LSProgress` | champs, listes, onglets (soulignement électrique), progression (dégradé bleu) |
| `LSPropertyField` | champs X/Y/Z à glisser |
| `LSModal`, `NotificationCenter` | modales et notifications |
| `LSSidebar` | navigation moderne : élément actif sur fond bleu translucide avec liseré électrique ; point ambre « à venir » |
| `LSTopbar` | barre supérieure compacte : logo, projet et état, recherche, notifications |

## Disposition des écrans de travail

- Barre supérieure compacte, navigation latérale rétractable.
- Viewport central occupant la majorité de l'espace.
- Explorateur / hiérarchie à gauche, propriétés et informations à droite.
- Diagnostics, journal et progression en bas ; tous les panneaux sont redimensionnables.

Références ergonomiques (sans copie) : Blender, Substance Painter, Unreal Engine, Figma,
configurateurs automobiles haut de gamme.

## Captures

`docs/screenshots/` : 1920×1080 (100 %, 125 %) et 2560×1440 (150 %), générées par
`python scripts/capture_screens.py screens LARGEUR HAUTEUR ECHELLE` (le visuel du tableau de
bord : `python scripts/capture_screens.py hero`).
