# Lore Friendly Engine (v0.8)

Transformer un véhicule de référence en **création originale** cohérente avec l'univers de GTA V :
proportions, carrosserie, optiques, calandre, boucliers, éléments distinctifs et identité de
marque — pas seulement un logo.

> **Avertissement.** Le Lore Friendly Engine aide à concevoir un design distinct. Il ne fournit
> **aucune garantie juridique** : ni avis juridique, ni pourcentage de « légalité », ni
> certification de conformité aux règles de Rockstar Games ou de Cfx.re. Un véhicule transformé
> n'est **jamais** présenté comme compatible FiveM sans export et essai en jeu.

![Lore Friendly Studio](screenshots/1920x1080@1_lore_studio.png)

## Parcours

1. **Source** — un modèle importé, un véhicule FiveM importé, un modèle généré par AI Vehicle
   Creator ou tout élément du projet. « Créer un design » : la source est **verrouillée** et ne
   sera jamais modifiée.
2. **Analyser** — Vehicle Design Analyzer (onglet Analyse).
3. **Marque** — Fictional Brand Library (onglet Marques).
4. **Direction** — Design DNA (onglet Styles) et niveau / contraintes (onglet Presets).
5. **Proposer** — Lore Concept Generator (onglet Propositions) : plusieurs plans, aperçus rendus.
6. **Prévisualiser, comparer, vérifier** — aperçu avant / après, Design Comparison Studio,
   impacts (UV, collisions, LOD, os) affichés avant confirmation.
7. **Confirmer, appliquer** — une variante est créée (ou modifiée) ; tout est annulable.
8. **Ajuster** — Front / Rear / Body Silhouette Studio, identité lumineuse, Vehicle Editor.
9. **Valider et sauvegarder** — revue d'originalité, vérifications par l'utilisateur, provenance,
   rapport de préparation FiveM, Ctrl+S.

Mode **simplifié** (source, marques, presets, analyse, propositions, validation) ou **avancé**
(tous les studios et réglages), en haut du studio.

## Variantes non destructives

- Une variante est une **copie du sous-arbre** de la source, rangée dans un ensemble de variantes
  `lore` (groupe « Lore Friendly · design »). La géométrie importée reste partagée tant qu'elle
  n'est pas modifiée ; une déformation crée une géométrie locale propre à la variante.
- La source est verrouillée ; « Revenir à l'original » l'affiche (les variantes sont masquées).
- **Points de restauration** : copie figée d'une variante ; « Restaurer » crée une **nouvelle**
  variante (rien n'est écrasé).
- Une pièce remplacée (phares, calandre…) est **masquée**, jamais supprimée.
- Les équipements Emergency Studio et les matériaux de livrée sont copiés avec la variante. Les
  signatures lumineuses civiles ne touchent jamais les feux d'urgence (identifiés par leurs
  métadonnées Emergency Studio).
- Annuler / Rétablir (Ctrl+Z / Ctrl+Y) ; appliquer une proposition = une seule étape d'historique.

## Vehicle Design Analyzer

Rapport éditable par sections (général, proportions et silhouette, face avant, arrière, roues,
éléments distinctifs, matériaux). Chaque information porte son statut :

| Statut | Sens |
|---|---|
| Mesure | Mesure géométrique vérifiée (sommets du projet) : dimensions, empattement, voies, porte-à-faux, capot, ligne de toit, volume (maillages fermés), garde au sol… |
| Reconnu | Reconnaissance automatique : nom des pièces (conventions GTA V, français / anglais), règles documentées sur le profil de hauteur (silhouette, type proposé) |
| Hypothèse IA | Résultat d'une analyse cloud des références (AI Vehicle Creator), si l'utilisateur l'a lancée |
| Inconnu | Non observable (dessin des jantes, signature lumineuse absente…) : rien n'est inventé |
| Saisi | Valeur corrigée par l'utilisateur (l'origine est conservée) |

Les composants sont identifiés par leurs **métadonnées**, leur **nom** et leur **position**
mesurée (avant / arrière). Une pièce non reconnue reste « non classée » ; son type se corrige
dans l'onglet Propriétés (sur une variante).

## Fictional Brand Library

- 20 marques de l'univers GTA V (Vapid, Bravado, Declasse, Albany, Benefactor, Obey, Übermacht,
  Karin, Dinka, Annis, Pfister, Grotti, Pegassi, Ocelot, Enus, Gallivanter, Canis, Dundreary,
  Emperor, Maibatsu) : **nom, description rédigée pour l'application, catégories, direction
  stylistique, caractéristiques, palette indicative, identité visuelle autorisée, provenance et
  licence**. Ce sont des **références créatives** : aucun logo, aucun modèle, aucun fichier n'est
  fourni ni téléchargé, et leur utilisation n'est pas présentée comme automatiquement autorisée
  (conditions de Rockstar Games / Take-Two et, sur un serveur, de Cfx.re).
- **Marques originales** : création avec vérification du nom (aucune marque automobile réelle,
  pas de doublon), suggestions de noms générés, enregistrement dans le projet et, au choix, dans
  la bibliothèque utilisateur (`lore/brands.json` dans le dossier de données de l'application).
  Licence par défaut : « Non renseignée ».

## Design DNA Engine

Dix paramètres réglables (0-100) : sportivité, luxe, robustesse, modernité, style rétro,
agressivité visuelle, sobriété, aérodynamisme, caractère utilitaire, orientation tout-terrain.
Profils intégrés : **Sport Premium, Offroad, Utility**, Grand luxe, Rétro, Muscle, Compacte
urbaine, Supercar ; profils personnalisés enregistrables (projet et bibliothèque utilisateur).
Le DNA **guide** les propositions (choix et amplitude des opérations) : il ne promet aucune
modification géométrique à lui seul.

## Lore Concept Generator

Entrées : source, marque, catégorie, direction (DNA, mêlé à celui de la marque), niveau, moteur,
nombre de propositions (1 à 6), contraintes conservées (toit, longueur, voies, garde au sol,
aucune pièce ajoutée).

| Niveau | Contenu |
|---|---|
| Léger | 3-4 opérations : optiques, calandre, détails ; structure conservée |
| Équilibré | 6-8 opérations : nouvelle identité avant / arrière, au moins une modification de silhouette |
| Original | 9-12 opérations : refonte avec au moins trois modifications structurelles |

Chaque proposition est un **plan** d'opérations du catalogue, avec la raison de chaque étape.
**Aperçus** : rendus logiciels de la géométrie transformée (trois quarts, profil, avant,
arrière), calculés en arrière-plan sur une copie de travail — rien n'est écrit dans le projet
tant que la proposition n'est pas appliquée. Les opérations incompatibles avec le véhicule sont
écartées et signalées.

| Moteur | Capacité | État |
|---|---|---|
| Règles Design DNA (local) | Plans de transformation | ✅ fonctionnel, déterministe |
| Claude (Anthropic, cloud) | Plan de transformation (`design_plan`) : seul un **résumé texte** de l'analyse est envoyé, après confirmation (coût non estimé, jamais inventé) ; les plans reçus sont **validés contre le catalogue** (opérations inconnues rejetées, paramètres bornés) | ⚠️ testé contre un serveur simulé uniquement |
| ComfyUI (local) | Image conceptuelle **2D** (`concept_image`) depuis l'aperçu, avec le workflow de l'utilisateur : une illustration, **jamais** un modèle 3D | ⚠️ testé contre un serveur simulé uniquement |

Aucune IA de génération d'images ne modifie le maillage : seules les opérations du catalogue le
font.

## Studios de transformation (opérations réelles)

Toutes les opérations modifient réellement les données du projet : déformation lisse des
sommets dans le repère du véhicule (essieux, habitacle et ligne de caisse mesurés), pièce
paramétrique originale ajoutée, déplacement des roues ou matériau propre à la variante. Aucune
n'est un changement de texture.

| Studio | Opérations |
|---|---|
| **Front Design Studio** | calandre (5 styles), phares (7 formes), pare-chocs avant, prises d'air, écope de capot, lame, protection (plaque, pare-buffle), canards, avancée du bouclier, porte-à-faux avant, hauteur de capot, effilement |
| **Rear Design Studio** | feux arrière (6 formes), pare-chocs arrière, diffuseur, sorties d'échappement (5 configurations), aileron, avancée du bouclier, porte-à-faux arrière, ducktail, effilement |
| **Body Silhouette Studio** | hauteur de pavillon, chute de pavillon, élargissement des ailes, épaules, garde au sol, assiette, voies (roues + ailes), bas de caisse, extensions d'ailes, jonc latéral |
| **Identité lumineuse** | signature avant (barre, deux traits, points), bandeau arrière, couleurs des optiques |

Contraintes : l'empattement est conservé par les opérations de porte-à-faux ; les pivots des
pièces mobiles et des os ne sont pas modifiés (les pièces rigides — optiques, rétroviseurs —
suivent la carrosserie par translation) ; les pièces techniques (collisions, LOD, os) ne sont
pas déformées. Les impacts réellement présents sur le véhicule (UV étirées, collisions et LOD à
régénérer, charnières à vérifier, nouvelles UV, nouveaux matériaux) sont listés **avant**
confirmation.

### Identité lumineuse

| Couche | Ce que fait l'application |
|---|---|
| Rendu visuel | Matériaux **émissifs** (couleur, intensité) : aperçu dans le viewport |
| Géométrie et matériaux | Optiques et bandeaux réels (profils extrudés), matériaux enregistrés dans le `.lsfc` |
| Éclairage GTA V | **Non généré** : shaders et `carcols` à configurer lors de l'export |
| Équipements d'urgence | Gérés par Emergency Studio ; jamais modifiés par les signatures civiles |

## Design Comparison Studio

Modes : **côte à côte** (deux viewports, caméras synchronisées), **séparateur interactif**
(découpe GL en temps réel : A à gauche, B à droite), **superposition** (A translucide, opacité
réglable), **filaire**, **matériaux** (différences de matériaux). A et B : l'original ou
n'importe quelle variante (comparaison de deux variantes). Isolation d'un composant, recadrage,
« Revenir à l'original ».

**Mesurer les différences** : dimensions (longueur, largeur, hauteur, empattement, voies, garde
au sol), recouvrement des silhouettes (profil, face, arrière, dessus), composants déformés
(déplacement maximal), remplacés ou ajoutés. **Déplacements** : sommets déplacés affichés en
couleur dans le viewport.

![Design Comparison Studio](screenshots/1920x1080@1_lore_comparaison.png)

## Design Originality Review

Huit aspects : silhouette, face avant, optiques, calandre, face arrière, logos et inscriptions,
éléments distinctifs, proportions. Pour chacun : état (Modifié / Peu modifié / Inchangé / À
vérifier par vous), **mesures techniques** (recouvrement de silhouettes avec seuils indiqués,
opérations appliquées, pièces remplacées, écarts de dimensions) et **pistes** (opérations
alternatives du catalogue). Les logos ne sont **pas** détectés automatiquement (aucun modèle de
reconnaissance embarqué) : l'utilisateur confirme leur retrait. Aucun pourcentage de légalité,
aucune affirmation de suffisance juridique.

## Asset Provenance Registry

Onglet **Provenance** : chaque ressource (fichier importé, ressource FiveM, génération IA, image
de référence, pièces Lore générées, marque utilisée) avec identifiant, auteur, source, licence,
date d'importation, modifications, restrictions, références et mentions. L'utilisateur complète
auteur, source, licence et restrictions. **Aucune licence n'est inventée** (« Non renseignée »
par défaut) ; les **mentions obligatoires ne peuvent pas être supprimées** ; les fichiers de
licence ou de crédits présents dans une ressource FiveM sont signalés ; aucun contenu protégé
n'est lu ni déchiffré. Les chemins locaux sont abrégés à l'écran (chemin complet en info-bulle).

## Intégration

- **Vehicle Editor** : bouton « Vehicle Editor » (élément affiché sélectionné) ; les variantes
  sont des géométries éditables du projet.
- **AI Vehicle Creator** : un modèle généré peut servir de source ; l'analyse cloud des
  références alimente les « hypothèses IA » ; l'onglet Lore Friendly de la v0.7 ouvre le studio ;
  le choix de marque de la v0.7 est repris comme marque du projet.
- **Livery Studio** : bouton « Livery » (carrosserie de la variante sélectionnée) ; palettes
  indicatives des marques ; les livrées existantes restent attachées aux matériaux copiés.
- **Emergency Studio** : bouton « Emergency » (variantes de service LSPD / EMS sur la variante) ;
  les équipements existants sont conservés.

## Sauvegarde `.lsfc`

Schéma SQLite inchangé (v6) : deux documents versionnés s'ajoutent à la table `documents`.

- `lore` (format 1) : marques et profils DNA du projet, designs (source, marque, catégorie, DNA,
  niveau, contraintes, analyse, propositions et leurs aperçus — blobs `lore-preview-*` —,
  variantes et journal des opérations, points de restauration, comparaisons, revues,
  vérifications, historique). Migration : un projet 0.7 s'ouvre tel quel ; le choix Lore
  Friendly d'AI Vehicle Creator 0.7 devient une marque du projet.
- `provenance` (format 1) : saisies du registre.
- Matériaux : champs `emissive` et `emissive_strength` dans la colonne `extra` existante.

## Limites

- Les déformations sont des champs lisses appliqués aux sommets existants : un maillage très
  pauvre (moins de 60 sommets) se déforme de façon anguleuse ; aucun remaillage automatique.
- La reconnaissance des composants dépend des noms et métadonnées : une carrosserie d'un seul
  tenant est déformée par zones (avant, arrière, toit), pas pièce par pièce.
- Les pièces ajoutées sont paramétriques (originales, simples) et ne sont pas fusionnées à la
  carrosserie.
- Collisions et LOD ne sont pas régénérés ; les pièces ajoutées sont hors hiérarchie d'os GTA V.
- Aperçus des propositions : rendu logiciel simplifié (couleurs unies, pas de textures).
- Moteurs cloud et ComfyUI : testés contre des serveurs simulés uniquement.
- Aucune évaluation de la ressemblance perçue ; aucune garantie juridique ni de compatibilité
  FiveM.
