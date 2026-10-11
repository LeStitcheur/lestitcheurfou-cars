# Design system — suite LeStitcheur

LeStitcheurFou Cars reprend l'identité de **LeStitcheur Control** (même auteur). Les valeurs
proviennent de son code source (`src/design.css`, couche « workspace 2 », version 2.10) ;
elles priment sur la palette indicative du cahier des charges lorsqu'elles diffèrent.

Code : `src/lsfcars/ui/design/` — `tokens.py`, `qss.py`, `fonts.py`, `icons.py`,
`components.py`, `sidebar.py`, `topbar.py`.

## Couleurs

| Rôle | Token | Valeur |
|---|---|---|
| Fond de l'application | `BG` | `#090b0e` |
| Barre de titre / sidebar | `TITLEBAR`, `SIDEBAR` | `#0d1014` |
| Panneaux / cartes | `PANEL`, `CARD` | `#11151a`, `#12171d` |
| Surfaces interactives | `SURFACE`, `SURFACE_HOVER` | `#1b222b`, `#242e3a` |
| Bordures | `BORDER`, `DIVIDER` | `#29313b`, `#262f39` |
| **Accent de marque** | `ACCENT` | `#ff4157` |
| Accent secondaire / survol | `ACCENT_2`, `ACCENT_HOVER` | `#ff5268`, `#ff647f` |
| Texte actif | `ACCENT_TEXT` | `#ff7384` |
| Accent sombre | `ACCENT_DARK` | `#35151f` |
| Textes | `TEXT`, `TEXT_2`, `TEXT_MUTED`, `TEXT_FAINT` | `#f4f6f9`, `#94a8c3`, `#687587`, `#596675` |
| États | `SUCCESS`, `WARNING`, `ERROR` | `#2cc58a`, `#f4b54a`, `#ff526e` |
| Axes techniques (gizmos) | `AXIS_X/Y/Z` | `#ff5b5b`, `#7bd88f`, `#4f9dff` |

Le rouge/rose est la couleur de marque ; le bleu-gris est réservé aux textes secondaires.

## Typographie

- Texte : **DM Sans** 400–700 (OFL 1.1), base 13 px (12 px en mode compact).
- Marque : **Barlow Condensed** 600–700 (OFL 1.1).
- Titres de page : 29 px, graisse 650, **point final rouge**.
- Petites capitales espacées : 9 px, graisse 700, via `fonts.font(..., spacing, caps=True)`
  (Qt n'interprète pas `letter-spacing` en QSS).

Polices converties depuis LeStitcheur Control par `scripts/import_brand_assets.py`,
licences jointes dans `resources/fonts/`.

## Icônes et emblème

Icônes **Lucide** (ISC), trait 1,7, colorées à la volée. Emblème LSF partagé :
`resources/brand/emblem.svg`.

## Composants

| Composant | Usage |
|---|---|
| `LSButton` | `primary` (rouge), `secondary`, `ghost`, `danger`, option `small` |
| `LSIconButton` | bouton icône, état coché rouge sombre |
| `LSCard` | carte anthracite arrondie, en-tête optionnel, `interactive` |
| `LSSectionHeader`, `Breadcrumb`, `eyebrow`, `heading` | en-tête de page |
| `LSStatsGrid`, `LSStatCell`, `LSIconBox` | cartes statistiques |
| `LSBadge` | badges `neutral`, `red`, `green`, `amber`, `blue` |
| `LSInput`, `LSSelect`, `LSTabs`, `LSProgress` | champs, listes, onglets, progression |
| `LSPropertyField` | champs X/Y/Z, libellés d'axe à glisser (Maj : réglage fin) |
| `LSModal` | modale ; raccourcis `confirm`, `ask_save`, `error`, `info` |
| `NotificationCenter`, `LSNotification` | toasts (fondu 160 ms) et historique de la cloche |
| `tooltip()` | infobulles françaises avec raccourci |
| `LSSidebar` | navigation sectionnée, actif rouge + liseré, point ambre « à venir », rétractable |
| `LSTopbar` | barre de titre sans cadre : logo, projet + état, recherche, cloche, contrôles Windows |

Variantes par propriétés dynamiques (`variant`, `size`, `role`, `tint`) ; après changement :
`components.set_prop()`.

## Interactions

Transitions courtes (survol, repli de sidebar 170 ms, toasts 160 ms), aucune animation
permanente. Actions destructives confirmées et annulables. Mode compact disponible.

## Captures

`docs/screenshots/` : 1920×1080 (100 %, 125 %) et 2560×1440 (150 %), générées par
`python scripts/capture_screens.py screens LARGEUR HAUTEUR ECHELLE`.
