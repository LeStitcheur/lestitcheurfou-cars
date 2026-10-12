# Journal des modifications

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/),
versionnement [SemVer](https://semver.org/lang/fr/).

## [Non publié]

## [0.7.0] - 2026-10-12

AI Vehicle Creator : création 3D assistée, hybride locale / cloud, dans le design Dark Premium.

### Modifié

- Les ateliers « Intelligence artificielle » et « Lore Friendly » marqués « Bientôt » deviennent
  **AI Vehicle Creator** (fonctionnel) ; l'entrée « Lore Friendly » ouvre son onglet dédié.
- Le document de projet `ai` (format 1) s'ajoute au `.lsfc` sans changement de schéma (v6) : un
  projet 0.6 s'ouvre tel quel.
- Test de démarrage (`--smoke-test`) : vérifie aussi AI Vehicle Creator (code de sortie 8).

### Ajouté (fonctionnel, testé)

- **AI Engine Manager** : interface commune des adaptateurs (nom, version, capacités, formats,
  ressources, authentification, limites, coûts, licence, niveau de vérification) ; détection du
  matériel (GPU, VRAM, CUDA, RAM, CPU, disque, dépendances) ; profils Économique / Équilibré /
  Haute qualité fondés sur le moteur et le matériel ; **Auto AI Routing** expliqué (moteurs
  retenus et écartés avec leur raison) et choix manuel ; file de tâches par ressource avec
  progression, annulation, délai maximal ; cache des résultats ; nettoyage des temporaires.
- **Moteur local LSF Silhouette** (intégré, algorithme déterministe) : reconstruction multi-vues
  par enveloppe visuelle, surface nets, lissage de Taubin, couleurs projetées ; vues absentes
  remplacées par des sections estimées et signalées.
- **Moteur local TripoSR** (MIT, installation séparée par `scripts/install_triposr.ps1` ou
  « Moteurs → Installer… ») : inférence dans un processus séparé, annulable, sans
  téléchargement implicite. Génération réelle vérifiée sur RTX 3060 Ti (18 s, 105 204
  triangles, 2,4 Go de VRAM).
- **Adaptateurs Meshy** (image et multi-images → 3D, textures, PBR), **Claude / Anthropic**
  (analyse d'images, suggestions Lore Friendly) et **ComfyUI** (workflow API de l'utilisateur,
  nœuds vérifiés) ; contrats des API documentées, **testés contre des serveurs simulés**.
- **Clés API** dans un coffre chiffré par Windows (DPAPI) ou en variable d'environnement, jamais
  dans un projet ni un journal ; test de connexion gratuit ; confirmation avant tout transfert
  cloud et toute opération payante ; reprises contrôlées ; journal des requêtes sans contenu.
- **Reference Studio** : import multiple, vues, ordre, rotation, miroir, recadrage, réglages,
  annotations (dont logos réels), comparaison, détourage, provenance et licence, zones estimées.
- **Vehicle Vision Analyzer** : type proposé (score), proportions, profil de toit, roues, garde au
  sol, couleurs, vitrages, optiques, incohérences entre vues ; rapport éditable, mesures marquées
  approximatives ; section cloud distincte.
- **Génération** : validation du fichier produit, import comme fichier du projet avec
  provenance, recalage automatique (axe vertical, longueur, sol, échelle ; ACP et plan d'appui
  pour les sorties de réseaux), retournement 180°, recalage sur les proportions mesurées.
- **Lore Friendly AI Assistant** : marques et noms fictifs originaux filtrés (marques réelles et
  de l'univers GTA), trois propositions (légère, équilibrée, originale), ajustements
  géométriques applicables, masquage des logos annotés, registre de provenance et avertissement
  juridique (aucune certification Rockstar / Cfx.re).
- **AI Mesh Assistant** : diagnostics exacts, corrections déterministes annulables (normales,
  doublons, fusion, trous, lissage, simplification, petites pièces, symétrie, UV), suggestions
  heuristiques, opérations soumises à validation humaine.
- **AI Texture Creator** : UV d'atlas, couleur de base projetée depuis les références ou cuite
  depuis les couleurs par sommet, normal map dérivée, roughness / metallic par règles, variantes
  de teinte, application au modèle, ouverture dans Livery Studio ; origine de chaque carte
  affichée (aucune AO locale).
- **Historique des générations** : moteur, version, paramètres, consigne, date, durée, coût
  estimé et communiqué, statut, erreurs, fichiers, miniature ; réouvrir, dupliquer, comparer,
  réutiliser les paramètres, supprimer.
- Références de démonstration originales (`samples/references`, rendus du véhicule d'essai).

### Limites connues

- TripoSR n'exploite qu'une image ; proportions approximatives ; couleurs par sommet seulement.
- Aucune génération cloud réelle exécutée (aucune clé) ; ComfyUI réel non testé.
- Stability AI et Tripo non intégrés (contrat non vérifié) ; Hunyuan3D-2 exclu (licence
  inapplicable dans l'UE) ; TRELLIS non validé sous Windows.
- Détourage local limité aux fonds unis ou aux images transparentes ; analyse par règles.
- Aucun modèle généré n'est utilisable en jeu sans préparation FiveM complète.

## [0.6.0] - 2026-10-12

Livery Studio Pro : éditeur de livrées 2D / 3D intégré, dans le design Dark Premium.

### Modifié

- L'atelier « Livrées » marqué « Bientôt » devient le **Livery Studio** (fonctionnel).
- Format de projet `.lsfc` **v6** : tables `images` (calques raster et masques, PNG, décodage
  différé) et `blobs` (logos et polices importés) ; migration automatique v1…v5 → v6.
- Rendu 3D : textures composées en direct (envoi de la seule région modifiée) et mode « livrée
  transparente » posée sur la couleur de peinture du matériau.
- Viewport : gestionnaire de peinture directe et pression des tablettes graphiques.
- Stabilité : les textures OpenGL orphelines (fenêtre détruite) ne provoquent plus de plantage à
  la libération ; caches Qt libérés avant l'arrêt de l'application.

### Ajouté (fonctionnel, testé)

- Page **Livery Studio** : outils, formes, logos, modèles à gauche ; vue 3D, vue UV 2D ou vue
  partagée au centre ; calques, propriétés, couleurs, matériaux, livrées, export à droite ;
  historique, progression, diagnostics, UV en bas ; panneaux redimensionnables et mémorisés.
- **Peinture 3D réelle** : le pinceau est projeté sur le maillage ; les texels dont la position
  3D est dans la sphère du pinceau sont peints, de part et d'autre des coutures UV ; symétrie par
  le plan du véhicule ; pression, taille, opacité, dureté, espacement, gomme.
- **Canvas 2D** : zoom, panoramique, grille, règles, guides magnétiques, UV et coutures,
  sélection rectangulaire, lasso, sélection d'îlot, transformation (déplacement, rotation,
  échelle), alignement, duplication, copier / couper / coller, aperçu réduit pour les 4K.
- **Calques** raster, vectoriels, texte, image, bandes 3D, groupes et masques ; visibilité,
  verrou, opacité, modes Normal / Multiply / Screen / Overlay / Add (+ Obscurcir, Éclaircir),
  fusion vers le bas, pixellisation explicite, éléments communs aux livrées. Rien n'est fusionné à
  l'enregistrement.
- **Outils** : pinceau, gomme, remplissage (couleur, îlot UV, sélection), ligne, rectangle,
  rectangle arrondi, cercle, ellipse, polygone, courbe, dégradé, pipette (2D et 3D), sélection,
  transformation ; raccourcis clavier.
- **Texte** éditable : police, taille, couleur, rotation, alignement, espacement, interligne,
  contour, ombre, opacité ; polices personnelles TTF / OTF intégrées au projet avec leur licence.
- **Logos** : bibliothèque locale (10 emblèmes originaux générés), import PNG / SVG / JPG / WEBP
  avec auteur, source, licence et catégorie ; recoloration, symétrie, proportions ; registre de
  provenance du document.
- **Outils de livrée** : bandes 3D longitudinales, verticales et diagonales, motifs (rayures,
  damier, chevrons, tirets, réfléchissant simulé), zones (flancs, capot, toit, coffre, avant,
  arrière), marquages placés d'après l'orientation réelle du dépliage, symétrie gauche / droite
  calculée en 3D (îlot tourné ou retourné reconnu), textes ajustés à leur îlot.
- **11 modèles** originaux (LSPD, Sheriff, State Police, Highway Patrol, EMS, SAMD, Fire,
  Rescue, Civil, Racing, Custom) et modèles personnels portables ; hauteurs relatives à la
  carrosserie.
- **Couleurs** : carré TSV, RGB, HSV, HEX, opacité, historique, palettes, valeur linéaire ;
  couleur de peinture du matériau distincte de la texture ; fusion sRGB ou linéaire.
- **Inspecteur UV** : îlots, UV absentes, hors limites, triangles dégénérés, chevauchements,
  coutures, densité de texels ; projection boîte et dépliage Blender (Smart UV Project), sur
  confirmation, annulables.
- **Variantes de livrées** : créer, dupliquer, renommer, supprimer, comparer, exporter ;
  association aux variantes d'Emergency Studio (équipements préservés, aperçu des feux).
- **Export** PNG, TIFF, WEBP sans perte, DDS DXT1 / DXT5 / non compressé avec mipmaps,
  1024 / 2048 / 4096 / personnalisé, débordement des îlots, relecture et rapport ; dossier de
  préparation YTD (DDS + manifeste) — aucun fichier .ytd n'est écrit.
- Véhicule d'essai original avec dépliage UV (`samples/vehicule_livree.glb`).
- Test de démarrage étendu au Livery Studio (code de sortie 7).
- Tests : 21 nouveaux tests (20 scénarios obligatoires, cas difficiles, parcours d'acceptation).

### Limites connues

- Aucun fichier YTD produit (pas de convertisseur vérifié) ; compatibilité en jeu non garantie.
- Composition 8 bits sRGB ; la symétrie d'un calque raster existant se fait pendant la peinture.
- Bandes 3D calculées à 2048 px au plus puis mises à l'échelle pour les textures 4K.
- Marquages « réfléchissants » : rendu visuel uniquement.

## [0.5.0] - 2026-10-11

Emergency Vehicle Studio : transformation d'un véhicule civil en variantes de services d'urgence
fictifs (LSPD, BCSO, SAHP, EMS, SAMD, LSFD, Rescue, personnalisé), dans le design Dark Premium.

### Modifié

- L'entrée « Emergency Studio » remplace les ateliers « LSPD » et « EMS » marqués « Bientôt ».
- Format de projet `.lsfc` **v5** : table `documents` (données de studio non géométriques),
  migration automatique v1…v4 → v5.
- `ComponentLibrary` : catégories, composants de départ et dossier paramétrables ; champs
  famille, services, profils compatibles et émetteurs lumineux.
- Viewport : glisser-déposer, gestionnaire de clic prioritaire, superpositions fournies par les
  pages ; points ronds et halos doux dans le rendu des superpositions.
- Panneaux de l'Emergency Studio : listes déroulantes et rangées de boutons qui ne débordent plus.
- OpenGL du bureau demandé explicitement : l'exécutable basculait vers le rendu logiciel Mesa
  malgré un GPU fonctionnel (le rendu logiciel reste disponible par `--software-gl` ou les
  paramètres).

### Ajouté (fonctionnel, testé)

- Page **Emergency Studio** : service / équipements / composants à gauche, viewport au centre,
  propriétés / éclairage / configurations / export à droite, timeline lumineuse / diagnostics /
  historique en bas ; disposition mémorisée ; passage au Vehicle Editor sans perte.
- Variantes non destructives : création, duplication, renommage, suppression restaurable,
  comparaison, matériaux propres à chaque variante, une seule variante visible à la fois.
- Bibliothèque d'équipements : 33 équipements originaux procéduraux (Police, EMS, Fire) avec
  identifiant, catégorie, profils compatibles, dimensions, pivot, émetteurs, provenance et
  licence ; import de modèles personnels.
- Placement : zones par profil de véhicule (toit, calandre, pare-chocs, rétroviseurs, lunette…),
  lancer de rayon sur la carrosserie, clic ou glisser-déposer dans le viewport, alignement sur la
  surface, magnétisme, pas de rotation, paire symétrique, duplication miroir, collisions
  approximatives (boîtes englobantes).
- 12 profils de véhicules (berline, SUV, 4x4, pick-up, van, ambulance, camion, motos, hélicoptère,
  bateau, aéronef) et profils personnalisés ; aucune hypothèse de rampe universelle.
- Lighting Studio : sources (couleur, intensité, portée, angle, visibilité, activation) et groupes
  (avant, arrière, gauche, droite, rampe principale, secondaires, travail). Prévisualisation
  **simulée** dans le viewport, distincte des données GTA V.
- Timeline des motifs : étapes, durées, groupes allumés, presets (alternance, double, triple,
  simultané, progressif, personnalisé), vitesse, lecture / pause, duplication ; évaluation
  déterministe.
- Adaptateurs d'export : données intermédiaires JSON, `carcols.meta` (sirènes, non-ELS) et
  MISS-ELS (XML `vcfroot` + liste des extras) ; ELS classique déclaré indisponible avec
  explication. Chaque adaptateur liste fonctionnalités, limites, dépendances et validations.
- Sirènes : profils et modes liés aux motifs, tonalités originales synthétisées (aperçu Windows),
  chaînes AudioString pour l'export ; aucun son propriétaire.
- Intérieurs Police, EMS / SAMD, Fire / Rescue et presets personnels.
- Livrée : structure de données seulement (Livery Studio prévu).
- Lore Friendly : marques et services fictifs, détection de marques réelles, registre de
  provenance et de licence, sans garantie juridique.
- Diagnostics : nombre de feux (limite de prévisualisation), motifs, mémoire, collisions.
- Test de démarrage étendu à l'Emergency Studio (code de sortie 6 en cas d'échec).
- Tests : 11 nouveaux tests (scénarios obligatoires et parcours d'acceptation dans la fenêtre).

### Limites connues

- Aucune garantie d'utilisation en jeu : pas d'écriture YFT (os de sirène, extras du modèle non
  produits) ; ordre des bits du séquenceur `carcols` supposé (premier pas = bit de poids fort).
- ELS classique non exportable ; les sections « MISC » de MISS-ELS ne sont pas exportées.
- Aperçu sonore limité à Windows (`winsound`).
- Collisions approximatives ; le véhicule d'exemple est orienté +Z (régler les axes).

## [0.4.0] - 2026-10-11

Vehicle Editor Advanced : modification réelle des véhicules (géométrie, pièces, roues, habitacle,
points d'ancrage, matériaux), dans le design Dark Premium.

### Modifié

- La page « Studio 3D » devient le **Vehicle Editor** : outils à gauche (scène, bibliothèque,
  outils de modélisation), viewport au centre, propriétés / géométrie / ancrages / atelier à
  droite, historique / statistiques / compatibilité FiveM en bas ; panneaux rétractables et
  disposition mémorisée ; espaces de travail Vehicle Editor, Bodywork Studio, Wheel Editor,
  Interior Studio.
- La « Bibliothèque » n'est plus un atelier « Bientôt » : elle est fonctionnelle.
- Surbrillance de sélection du rendu 3D en bleu électrique (une teinte rose résiduelle de la v0.2
  subsistait dans le shader).
- Format de projet `.lsfc` **v4** (migration automatique v1 / v2 / v3 → v4).
- Avertissements FiveM centralisés (`editor.compat`) et étendus.

### Ajouté (fonctionnel, testé)

- Modes **Objet**, **Édition** (sommets / arêtes / faces, gizmo avec aperçu, Tab) et **Composant**.
- Édition de maillage (`scene.editmesh`, sans Qt) : transformations, extrusion de région, inset,
  fusion (centre, distance), suppression, séparation, normales (recalcul, inversion,
  orientation cohérente), symétrie avec aperçu, alignement sur un plan, projection UV boîte,
  diagnostic des UV ; biseau via `bmesh.ops.bevel` de Blender en processus annulable.
- Géométrie locale immuable enregistrée dans le projet ; les fichiers importés ne sont jamais
  modifiés.
- Bodywork Studio : panneaux, proportions, 10 pièces originales paramétriques, duplication miroir
  sans échelle négative.
- Component Library locale : 25 composants de départ originaux, import de modèles, presets depuis
  la scène, recherche, filtres, duplication, suppression sans effet sur les projets.
- Replace Component : prévisualisation, alignement des pivots, ajustement des dimensions,
  matériaux, parent et ancrages conservés, os GTA V préservés par défaut, réversible.
- Wheel Editor : identification (os `wheel_*` et noms), profils voiture / SUV / camion / moto /
  spécial, voie, empattement, hauteurs, symétrie, diamètre, largeur, pivots, aperçu de rotation.
- Interior Studio : isolation, carrosserie masquée, caméra intérieure, sièges, configurations
  d'habitacle (civil, police, EMS, commandement).
- Attachment Points : nœuds `anchor` avec type, contraintes, métadonnées, association, axes
  affichés et sélectionnables.
- Matériaux : carte de normales, échelle / décalage UV, 9 presets automobiles originaux, shader
  GTA V suggéré (indicatif).
- Variantes de composants (une seule visible à la fois).
- Historique : transactions, budget mémoire (étapes anciennes oubliées), libération de la
  géométrie inutile, navigation dans l'historique, points de restauration.
- Rapport de compatibilité FiveM (os, pivots, hiérarchie, géométrie, UV, échelles, roues), sans
  promesse de jouabilité.
- Test de démarrage étendu au Vehicle Editor (code de sortie 5 en cas d'échec).
- Tests : 22 nouveaux tests (17 scénarios obligatoires, parcours d'acceptation dans la fenêtre).

### Limites connues

- Inset par mise à l'échelle (pas d'épaisseur constante) ; biseau seulement avec Blender.
- Aucune écriture de formats GTA V : export FiveM à venir ; collisions et LOD non édités.
- Sollumz non testé (non installé sur la machine de développement).

## [0.3.0] - 2026-10-11

Import FiveM / GTA V, décomposition 3D et restauration d'une identité propre « Dark Premium ».

### Modifié

- Abandon complet de l'identité rouge/rose inspirée de LeStitcheur Control : nouvelle direction
  « Dark Premium — Automotive Creation Studio » (palette officielle de 12 couleurs, bleu principal
  `#2563EB`, bleu électrique `#38BDF8`). Design system centralisé (`ColorTokens`,
  `TypographyTokens`, `SpacingTokens`, `AnimationTokens`, `AppTheme`, `ComponentStyles`) ;
  aucune couleur hors des tokens (vérifié par un test), y compris dans le moteur de rendu.
- Polices système Segoe UI ; polices, emblème et script d'import de LeStitcheur Control retirés ;
  carte profil retirée ; bannière du tableau de bord redessinée. Fonctions inchangées.
- La page « Importer un véhicule » devient le **Vehicle Import Studio**.
- Format de projet `.lsfc` **v3** (migration automatique v1/v2 → v3).

### Ajouté (fonctionnel, testé)

- Paquet `fivem/` (sans Qt) :
  - archives RPF7 non chiffrées : parcours, archives imbriquées, extraction ; archives
    chiffrées (AES / NG) détectées et refusées sans déchiffrement ;
  - ressources RSC7 : en-tête, tailles de blocs, décompression, pointeurs ;
  - `.ytd` : dictionnaire, décodage DXT1/3/5, BC4/5/7 et formats non compressés, export PNG/DDS ;
  - `.yft` / `.ydr` : squelette, géométrie, enfants physiques (roues), shaders et textures,
    découpage par os avec pivots d'origine ;
  - métadonnées XML (vehicles, handling, carvariations, carcols, content, setup2…), recherche,
    vérifications croisées, données inconnues conservées ;
  - analyse de ressource (dossier, ZIP, RPF, fichiers) avec statuts Compatible / Partiel /
    Dépendance manquante / Erreur / Non pris en charge, détection de FiveM Asset Escrow ;
  - classification des composants par noms d'os (« Non classée » sinon) ;
  - adaptateur Blender / Sollumz : détection, sondage des opérateurs réellement présents,
    tâches en processus séparé avec journal, délai et annulation ;
  - inventaire des archives d'une installation GTA V (en-têtes seulement).
- Import natif `.yft` / `.ydr` dans les projets (`YftImporter`), textures des `.ytd` voisins.
- Vehicle Import Studio : explorateur de fichiers filtrable, hiérarchie (composants, os,
  ancrages), viewport d'aperçu, modes d'inspection (complet, isolé, éclaté, filaire, matériaux,
  os, ancrages, statistiques ; collisions marquées « non implémenté »), fiches véhicule et
  fichier, lecteur de métadonnées, inspecteur de textures, onglet Blender, onglet Formats,
  diagnostics, journal, progression et annulation ; import dans le projet avec copies et
  manifeste versionné.
- Métadonnées d'origine conservées sur les nœuds (`extra`) et avertissements « Compatibilité
  FiveM » lors des éditions risquées (renommer un os, supprimer, changer la hiérarchie, échelle
  non uniforme).
- Addon de démonstration synthétique (`scripts/generate_demo_addon.py`), embarqué dans
  l'exécutable et vérifié par le test de démarrage.
- 126 tests automatisés (+36) ; test facultatif sur ressource réelle (`LSFCARS_REAL_RESOURCE`).

### Limites connues

- Collisions `.ybn` non décodées ; seul le niveau de détail haut est importé ; matériaux
  simplifiés ; aucune écriture de formats GTA V (export FiveM à venir).
- `.ydr` non validé sur fichier réel ; import via Sollumz non testé (Sollumz non installé).

## [0.2.0] - 2026-10-11

Studio 3D interactif et identité graphique de la suite LeStitcheur.

### Fonctionnel (testé)

- Identité LeStitcheur Control : tokens issus de son code source, DM Sans / Barlow Condensed,
  icônes Lucide, emblème LSF, fenêtre sans cadre, barre de titre, sidebar noire rétractable,
  accents rouge/rose, composants LS* (voir `docs/DESIGN_SYSTEM.md`).
- Tableau de bord « Bienvenue dans ton garage » : bannière, statistiques réelles, projets
  récents avec miniatures ; pages Mes projets, Projets récents, Import, Matériaux,
  Paramètres, Diagnostics.
- Studio 3D : explorateur hiérarchique (recherche, renommage, masquage, verrouillage,
  regroupement, glisser-déposer, menu contextuel), propriétés (objet, provenance,
  transformations, dimensions), éditeur de matériaux (couleur, rugosité, métallicité,
  opacité, texture, affectation, aperçu immédiat), panneau statistiques / progression / journal.
- Viewport : moteur de rendu séparé, modes solide / filaire / matériaux, perspective et
  orthographique, caméra orbitale et libre, 7 vues, sélection simple et multiple, gizmos
  de translation / rotation / échelle (magnétisme Ctrl), fond studio, grille, axes.
- Annuler / rétablir pour toutes les modifications, duplication, suppression confirmée.
- Import GLB, glTF, OBJ, STL, PLY (hiérarchie, matériaux PBR, textures, UV) en arrière-plan
  avec progression ; FBX via Blender en processus auxiliaire (vérifié) ; formats GTA V /
  FiveM reconnus comme « prévus » sans chargement simulé.
- Format .lsfc v2 : provenance (chemin d'origine, SHA-256, importateur), matériaux,
  hiérarchie, caméra, miniature ; migration automatique des projets v0.1 ; enregistrer sous ;
  sauvegarde automatique et récupération après interruption ; originaux jamais modifiés.
- 90 tests automatisés (rendu OpenGL réel, interface, format, import FBX via Blender).

### Prévu (visible comme « Bientôt », non fonctionnel)

- Bibliothèque de composants, Livrées, ateliers LSPD et EMS / SAMD, Configurations,
  Intelligence artificielle, Lore Friendly, Optimisation, Export FiveM, import d'addons FiveM.

## [0.1.0] - 2026-10-11

Première version : fondations de l'application.

### Fonctionnel

- Interface PySide6 en français, thème sombre à accents bleu électrique, navigation par ateliers.
- Gestionnaire de projets : création (nom, type de véhicule, usage, emplacement), ouverture,
  projets récents, projet de démonstration avec véhicule d'exemple.
- Projets enregistrés dans un fichier SQLite `.lsfc` (enregistrement atomique, ouverture en
  lecture seule, versionnement de schéma avec migrations) ; modèles copiés dans `assets/`.
- Viewport 3D OpenGL : grille au sol, axes, éclairage, surbrillance de la sélection,
  sélection par clic. Fonctionne avec le GPU ou en rendu logiciel (`--software-gl`).
- Import de modèles GLB, glTF (avec fichiers externes), OBJ, STL et PLY (couleurs conservées).
- Navigation : orbite, panoramique, zoom, cadrage (F), vues avant / droite / dessus.
- Explorateur d'objets (visibilité, cadrage, retrait) et panneau de propriétés contextuel
  (projet ou objet : nom, position, rotation, échelle uniforme ou non).
- Journal en direct filtrable, fichier de log tournant, rapport de diagnostics copiable.
- 98 tests automatisés (pytest, pytest-qt, rendu OpenGL réel).
- Build `LeStitcheurFouCars.exe` (PyInstaller) avec test de démarrage automatique.
- GitHub Actions : lint, tests Windows (Python 3.12 et 3.13), build de l'exécutable publié
  comme artifact, release automatique sur tag `vX.Y.Z` depuis `main`.

### Prévu (interface réservée, non fonctionnel)

- Ateliers Livrées, LSPD / EMS, Génération IA et Export FiveM.
- Import de véhicules GTA V / FiveM existants, textures et matériaux.

[Non publié]: https://github.com/LeStitcheur/lestitcheurfou-cars/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/LeStitcheur/lestitcheurfou-cars/releases/tag/v0.3.0
[0.2.0]: https://github.com/LeStitcheur/lestitcheurfou-cars/releases/tag/v0.2.0
[0.1.0]: https://github.com/LeStitcheur/lestitcheurfou-cars/releases/tag/v0.1.0
