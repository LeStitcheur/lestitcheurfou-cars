# Emergency Studio — variantes de véhicules d'urgence

Module de la version 0.5.0. L'**Emergency Studio** transforme un véhicule civil en variantes de
services d'urgence **fictifs** : LSPD, BCSO / Sheriff, SAHP / State Police, EMS, SAMD, LSFD,
Rescue, ou un service personnalisé. Les équipements sont de vrais objets 3D posés sur la
carrosserie. Les feux, les motifs et les sirènes sont des données éditables. Le tout est
enregistré dans le projet `.lsfc`.

> La prévisualisation lumineuse et sonore est une **simulation** dans le logiciel. Les exports
> sont des données préparatoires : aucun n'est garanti utilisable en jeu (ELS ou non-ELS).
> Aucune vérification n'a valeur de garantie juridique ni de certification Rockstar / Cfx.re.

## Disposition

| Zone | Contenu |
|---|---|
| Gauche | **Service** (création et gestion des variantes, profil du véhicule), **Équipements** (bibliothèque), **Composants** (équipements de la variante active) |
| Centre | Viewport 3D : pose par clic ou glisser-déposer, gizmos, aperçu lumineux, collisions, retour au Vehicle Editor |
| Droite | **Propriétés** (équipement sélectionné : zone, magnétisme, rotation, miroir), **Éclairage** (feux et groupes), **Configurations** (intérieur, sirènes, livrée, Lore Friendly), **Export** |
| Bas | **Timeline lumineuse**, **Diagnostics**, **Historique** |

La disposition est mémorisée. Le passage au Vehicle Editor (bouton ou barre latérale) ne perd
rien : les deux pages partagent le même projet et le même historique.

## Variantes

- Une variante est un groupe de la scène (« Variantes d'urgence » sous la racine du modèle).
  Le véhicule de base n'est jamais modifié. Une seule variante est visible à la fois.
- Opérations : créer, activer, renommer, dupliquer (équipements, feux, motifs compris),
  supprimer (restaurable), restaurer, comparer deux variantes.
- Chaque variante a ses équipements, feux, groupes, motifs, sirène, livrée, matériaux
  (surcharges par matériau), paramètres et métadonnées. Les modifications de la base sont
  partagées par toutes les variantes.

## Bibliothèque d'équipements

33 équipements de départ, tous **procéduraux et originaux** (aucun asset tiers) :

| Famille | Exemples |
|---|---|
| Police | rampe lumineuse, mini-rampe, gyrophare, feux de calandre, de pare-chocs, de rétroviseurs, barre de lunette, antenne, radio, console, terminal MDT, cloison, coffre, support |
| EMS | rampe EMS, flashers, antenne, radio, sac médical, brancard, support, rangements, armoire, trousse, défibrillateur |
| Fire | rampe incendie, projecteur de travail, mât d'éclairage, coffre, râtelier, kit de désincarcération, échelle |

Chaque équipement déclare : identifiant, nom, catégorie, famille, services, profils compatibles,
géométrie, matériaux, dimensions, pivot, points d'émission lumineuse, provenance et licence.
**Importer…** ajoute un modèle personnel (GLB, OBJ…) ; la provenance déclarée est conservée.

## Placement

- **Zones** définies par profil de véhicule (toit, calandre, pare-chocs, rétroviseurs, lunette,
  plage arrière, habitacle…) en coordonnées normalisées sur la boîte du véhicule, puis
  projection sur la carrosserie par lancer de rayon.
- **Clic** ou **glisser-déposer** depuis la liste : l'équipement est posé à l'endroit visé et
  aligné sur la surface (normale).
- Magnétisme (pas en mètres), pas de rotation, déplacement vers une autre zone.
- **Paire** : pose gauche + droite ; **Miroir** : duplique la sélection de l'autre côté.
  Un feu unique posé côté droit prend la couleur et le groupe de droite.
- **Collisions** : chevauchements entre équipements par boîtes englobantes (approximatif).
- Les axes du véhicule (Vehicle Editor) déterminent l'avant et la droite.

## Profils de véhicules

Berline, SUV, 4x4, pick-up, van, ambulance, camion, moto routière, moto tout-terrain,
hélicoptère, bateau, aéronef, et profils personnalisés. Chaque profil liste ses zones : une moto
n'a pas de zone « toit », un hélicoptère n'a pas de calandre. Les équipements dont le profil est
incompatible sont signalés.

## Lighting Studio

- Sources : nom, couleur (rouge, bleu, blanc, ambre, vert), intensité, portée, angle,
  visibilité, activation, position locale à l'équipement.
- Groupes : avant, arrière, gauche, droite, rampe principale, secondaires, travail.
- Les feux affichés dans le viewport sont des marqueurs de prévisualisation (points, halos,
  cônes pour la sélection). Ce ne sont pas des données GTA V.
- Limite de prévisualisation : 96 feux (diagnostic au-delà).

## Timeline des motifs

- Un motif est une liste d'étapes (durée en ms, groupes allumés).
- Presets : alternance gauche / droite, double flash, triple flash, simultané, progressif,
  personnalisé ; presets personnels enregistrables.
- Grille éditable (clic = allumer / éteindre un groupe à une étape), ajout / retrait d'étapes,
  durées, vitesse, lecture / pause, duplication.
- Évaluation **déterministe** : l'état à l'instant t ne dépend que du motif, de t et de la
  vitesse.

## Adaptateurs d'export

Chaque adaptateur déclare ses fonctionnalités, ses limites, ses dépendances et ses
validations. Un export impossible est refusé avec la liste précise des raisons.

| Adaptateur | Sortie | État |
|---|---|---|
| Données intermédiaires | `<variante>.lsf-emergency.json` | ✅ (format propre au logiciel) |
| Non-ELS `carcols.meta` | fragment XML `<Sirens>` + rapport texte | ✅ non garanti en jeu |
| MISS-ELS (FiveM) | `<ressource>.xml` (`vcfroot`) + liste des extras | ✅ non garanti en jeu |
| ELS solo (LCPDFR) | — | ❌ refusé : pas de spécification publique vérifiable |

Limites `carcols.meta` : 20 feux au maximum ; motif échantillonné sur 32 pas égaux
(`sequencerBpm = 60000 × 32 / durée du cycle`) ; ordre des bits **supposé** (premier pas = bit de
poids fort) ; rotations non exportées ; le modèle doit contenir les os `siren1`…`sirenN`.

Limites MISS-ELS : 12 extras (un groupe = un extra) ; motifs PRIMARY / SECONDARY / REARREDS ;
une couleur par extra ; sections « miscs » non exportées ; le modèle doit posséder les extras.

Sources consultées : documentation VCF de MISS-ELS
(<https://github.com/matsn0w/MISS-ELS>, `docs/vcf.md`) ; descriptions publiques des éditeurs
de sirènes carcols et des motifs ELS (forum Cfx.re, gta5-mods). Aucun fichier tiers n'a été
copié dans le dépôt.

## Sirènes

- Profil de sirène par variante : modes (feux seuls, feux + tonalité…) liés à un motif.
- Tonalités **originales synthétisées** (wail, yelp, hi-lo, priority, avertisseur) : aperçu par
  **Écouter** (Windows uniquement, `winsound`). Aucun son propriétaire n'est distribué.
- Les chaînes `AudioString` saisies sont reprises dans l'export MISS-ELS. Le son entendu dans le
  logiciel n'est pas celui du jeu.

## Intérieurs, livrée, Lore Friendly

- Intérieurs en un clic : Police (radio, console, MDT, cloison…), EMS / SAMD, Fire / Rescue ;
  l'intérieur courant peut être enregistré comme preset.
- Livrée : **données seulement** (nom, couleurs, identifiant d'unité, indicatif, marquages).
  L'éditeur de livrées (Livery Studio) est prévu.
- Lore Friendly : services et marques fictifs ; détection de noms de marques réelles dans les
  textes de la variante ; registre de provenance et de licence des équipements. Ce contrôle
  n'est pas une garantie juridique.

## Données et format

L'état du studio est le document JSON `emergency` (table `documents` du `.lsfc` v5). Les
équipements sont des nœuds de scène (`extra.emergency_equipment`). Toute opération passe par
l'historique : annuler / rétablir couvre la scène et le document.

## Limites

- Aucune écriture YFT : os de sirène et extras du modèle ne sont pas produits.
- ELS solo non exportable ; « miscs » MISS-ELS non exportés ; ordre des bits `carcols` supposé.
- Aperçu sonore limité à Windows.
- Collisions approximatives (boîtes englobantes).
- Le véhicule d'exemple est orienté +Z : réglez « sens de l'avant » dans le Vehicle Editor.
