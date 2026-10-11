# Livery Studio Pro — livrées 2D / 3D

Module de la version 0.6.0. Le **Livery Studio** crée et modifie les livrées d'un véhicule : il
peint directement sur la carrosserie en 3D, édite la texture en 2D, gère des calques éditables,
des textes, des logos, des bandes et plusieurs variantes de livrée, puis exporte les textures.

> La peinture 3D modifie **réellement les pixels de la texture** (aucune superposition écran).
> Le viewport, le canvas 2D et l'export partagent la même composition : la texture exportée est
> celle que l'on voit. Aucune compatibilité en jeu n'est garantie, et aucun fichier `.ytd` n'est
> produit.

## Disposition

| Zone | Contenu |
|---|---|
| Gauche | **Outils** (dessin et options de l'outil actif), **Formes** (bandes 3D, marquages, formes prédéfinies), **Logos**, **Modèles** |
| Centre | Vue 3D, vue UV 2D ou vue partagée (touches 1 / 2 / 3), éclairages d'urgence simulés, retour au Vehicle Editor |
| Droite | **Calques**, **Propriétés**, **Couleurs**, **Matériaux**, **Livrées**, **Export** |
| Bas | **Historique**, **Progression**, **Diagnostics**, **UV** |

Les panneaux sont redimensionnables ; la disposition est mémorisée.

## Document de livrée

- Un document cible un ou plusieurs **matériaux** partageant le même dépliage UV. La texture
  d'origine du matériau sert de fond et n'est jamais modifiée.
- Deux modes : **texture complète** (remplace la texture du matériau, multipliée par sa couleur)
  ou **livrée transparente** posée sur la couleur de peinture (style GTA V « sign »).
- Résolutions 1024, 2048, 4096 ou personnalisée (jusqu'à 8192) ; changement rééchantillonné.
- Le document est versionné (`documents["livery"]`, format 1) et enregistré dans le `.lsfc` v6
  avec ses calques raster, masques, logos et polices. Rien n'est fusionné à l'enregistrement.

## Peinture 3D

Clic gauche sur la carrosserie dans la vue 3D (Alt + glisser : orbite).

1. Le rayon souris est lancé sur les maillages ciblés (triangle et barycentriques).
2. Les triangles proches sont rastérisés dans l'espace UV ; chaque texel dont la **position 3D**
   tombe dans la sphère du pinceau est peint, avec la dureté demandée.
3. Le trait traverse donc les **coutures UV** et touche tous les îlots concernés ; les faces
   opposées (intérieur d'une tôle fine) sont exclues.
4. **Symétrie** : le point est reflété par le plan de symétrie du véhicule (axes du Vehicle
   Editor) puis peint sur l'autre flanc, quel que soit le dépliage (îlot tourné ou retourné).

Réglages : taille (pixels de texture, convertie en mètres d'après la densité de texels), opacité
(sans surcharge aux croisements), dureté, espacement, pression des tablettes (taille et / ou
opacité), gomme, verrouillage de la transparence, peinture du masque.

## Canvas 2D

Zoom (molette), panoramique (Espace ou bouton du milieu), grille, règles, guides magnétiques
(tirer depuis une règle), affichage des UV et des coutures, sélection rectangulaire, lasso,
sélection d'îlot UV (Maj : ajouter, Alt : retirer), transformation des éléments (déplacement,
poignées d'échelle, rotation par pas de 15° avec Maj), alignement (texture, sélection, îlot),
duplication, copier / couper / coller. Au fort dézoom, un aperçu réduit garde les textures 4K
fluides.

## Calques

Types : raster, vectoriel, texte, image (logo), bande 3D, groupe ; masque sur tout calque.
Opérations : ajouter, supprimer, renommer, dupliquer, réordonner (glisser-déposer), masquer,
verrouiller, opacité, modes de fusion (Normal, Multiply, Screen, Overlay, Add, Obscurcir,
Éclaircir), regrouper, dégrouper, fusionner vers le bas, pixelliser (explicite), masque
(ajouter, depuis la sélection, inverser, appliquer, supprimer), élément commun aux livrées.

## Outils

Pinceau, gomme, remplissage (couleur contiguë, îlot UV, sélection), dégradé linéaire ou radial,
ligne, rectangle, rectangle arrondi, cercle, ellipse, polygone, courbe (fermée ou non), texte,
pipette (2D et 3D), sélections, transformation. Raccourcis : V, B, E, G, Maj+G, L, U, Maj+U, O,
Maj+O, P, Maj+P, T, I, M, Maj+M, W ; [ ] taille ; X permuter ; Ctrl+J / E / G / A / D / C / X / V.

## Texte

Contenu multiligne, police (système ou importée TTF / OTF avec licence obligatoire), taille,
couleur, gras, italique, alignement, espacement des caractères, interligne, contour, ombre
(décalage, flou, opacité, couleur), rotation, inversion (lecture au rétroviseur). Le texte reste
éditable après réouverture. Les polices système ne sont pas redistribuées ; vérifiez leur licence
pour diffuser les textures.

## Logos

Bibliothèque locale : 10 emblèmes **originaux générés** (insignes, bouclier, croix de secours
bleue, flamme, ailes, chevrons, damier, éclair…). Import PNG, SVG, JPG, WEBP avec auteur, source,
licence et catégorie ; un logo sans licence est signalé à l'export. Placement au centre ou sur
les deux flancs, taille, rotation, opacité, proportions, miroir, recoloration (alpha conservé).
Le registre de provenance du document liste les logos utilisés. Aucune vérification n'a valeur de
garantie juridique.

## Outils de livrée

- **Bandes 3D** définies dans l'espace du véhicule : longitudinales (hauteur sur les flancs,
  décalage latéral sur le dessus), verticales, diagonales ; motifs uni, rayures, damier,
  chevrons, tirets, réfléchissant (simulé, rendu visuel seulement). Symétriques par construction.
- **Zones** : flancs, gauche, droite, dessus, capot, toit, coffre, avant, arrière.
- **Marquages** : texte placé sur une zone ; position, rotation, retournement et échelle déduits
  du jacobien UV local ; copie symétrique sur l'autre flanc ; texte réduit s'il déborde de son
  îlot.

## Modèles

LSPD, Sheriff, State Police, Highway Patrol, EMS, SAMD, Fire Department, Rescue, Civil, Racing,
Custom : palette, zones, marquages, calques organisés (groupes Bandes, Marquages, Logos), numéro
d'unité. Les hauteurs sont des fractions de la hauteur de carrosserie. Graphismes originaux. La
peinture suggérée du matériau s'applique séparément (bouton dédié). Modèles personnels : fichier
JSON portable (calques, pixels et logos intégrés).

## Couleurs

Carré teinte / saturation / valeur, RGB, HSV, HEX, opacité, couleurs principale et secondaire,
historique, palettes (document et modèles). Composition en **sRGB 8 bits** (comme les éditeurs
courants) ou en lumière **linéaire** (onglet Matériaux). La couleur de peinture de carrosserie
(matériau) est distincte des couleurs intégrées à la texture.

## UV

Inspecteur : îlots, triangles sans UV, hors de [0, 1], dégénérés, îlots superposés (peindre l'un
modifie l'autre), coutures, densité de texels et étirement. Corrections, **toujours après
confirmation** et annulables : projection « boîte » des maillages sans UV ; nouveau dépliage par
Blender (« Smart UV Project », processus séparé, annulable) si Blender est installé.

## Variantes

Créer (vierge ou depuis un modèle), dupliquer, renommer, supprimer, activer, comparer (part des
pixels différents, calques propres, aperçus), exporter séparément. Éléments communs partagés.
**Emergency Studio** : une livrée peut être associée à une variante d'urgence ; le nom et le
numéro d'unité sont synchronisés dans ses données de livrée, les équipements et matériaux ne
sont jamais modifiés, et sélectionner la variante d'urgence active la livrée associée. Le bouton
« Éclairages » affiche les feux simulés de la variante d'urgence.

## Export

| Format | Détails |
|---|---|
| PNG, TIFF (LZW), WEBP | sans perte, transparence ; relu et comparé pixel à pixel |
| DDS DXT5 / DXT1 / non compressé | chaîne de mipmaps (jusqu'à 4 px) ; DXT vérifié par PSNR ≥ 30 dB |
| Préparation YTD | dossier `<projet>_ytd` : DDS `<nom>_sign_N`, `manifest.json`, `LISEZMOI.txt` |

Options : résolution (document, 1024, 2048, 4096, personnalisée), transparence, mipmaps,
débordement des îlots (évite les liserés aux coutures), livrée active ou toutes. Le rapport
signale dimensions non puissances de deux, textures > 4096 px, DXT1 avec transparence, logos ou
polices sans licence. **Aucun fichier `.ytd` n'est écrit** : créez le dictionnaire avec
CodeWalker, OpenIV ou Sollumz. L'export s'exécute en arrière-plan, avec progression et annulation.

## Performances

Calques encodés en PNG et décodés à la demande (livrées inactives libérées), composition par
région modifiée, rendus d'éléments en cache, envoi au GPU de la seule région modifiée, cartes de
surface et zones en cache, historique par tuiles de 128 px.

## Limites

- Aucun fichier YTD produit ; fonctionnement en jeu non garanti.
- Composition 8 bits sRGB (option linéaire pour la fusion seulement).
- Symétrie d'un calque raster déjà peint : non disponible (utilisez la symétrie pendant la
  peinture) ; textes, logos, formes et bandes ont une commande de symétrie.
- Bandes 3D calculées à 2048 px au plus, mises à l'échelle pour les textures 4K.
- Les îlots superposés reçoivent la même peinture (signalé par l'inspecteur UV).
- Pression : tablettes reconnues par Qt (Windows Ink / Wintab selon le pilote).
