# AI Vehicle Creator — création 3D assistée (locale et cloud)

Module de la version 0.7.0. AI Vehicle Creator part d'images de référence pour aboutir à un
modèle 3D modifiable dans le Vehicle Editor. Le parcours est le suivant :

1. importer les références ;
2. analyser le véhicule ;
3. choisir un moteur local ou cloud ;
4. générer et suivre la progression ;
5. récupérer le modèle, l'afficher, le diagnostiquer et le corriger ;
6. produire les textures ;
7. préparer une adaptation Lore Friendly ;
8. enregistrer, rouvrir et transférer le modèle vers le Vehicle Editor.

> **Un maillage généré n'est pas un véhicule GTA V / FiveM fonctionnel.** La hiérarchie, les
> matériaux, les collisions, les LOD et l'export restent à préparer à la main. Aucun résultat
> n'est présenté comme compatible FiveM, et aucune vérification de l'application ne vaut
> certification des règles de Rockstar Games ou de Cfx.re.

## Moteurs

| Moteur | Type | Méthode | Capacités | État vérifié |
|---|---|---|---|---|
| **LSF Silhouette** | local, intégré | algorithme déterministe (enveloppe visuelle) | image ou multi-vues → 3D, couleurs projetées | **génération réelle** (tests automatisés, test de démarrage de l'exe) |
| **TripoSR** (Stability AI / Tripo AI, MIT) | local, installation séparée | réseau de neurones | une image → 3D, couleurs par sommet | **génération réelle** sur RTX 3060 Ti (voir mesures) ; test réel facultatif |
| **ComfyUI** | local, installation séparée | selon votre workflow | image → 3D, texture (déduites des fichiers produits) | testé contre un **serveur simulé** reproduisant l'API ; aucun ComfyUI réel testé |
| **Meshy** | cloud, clé API | réseau de neurones | image et multi-images (1 à 4) → 3D, textures, PBR | contrat vérifié dans la documentation officielle ; testé contre un **serveur simulé** seulement |
| **Claude (Anthropic)** | cloud, clé API | réseau de neurones | analyse d'images, suggestions Lore Friendly | testé contre un **serveur simulé** seulement |

Fournisseurs étudiés mais **non intégrés** (raison affichée dans l'application) :

- **Stability AI** (Stable Fast 3D, SPAR3D) et **Tripo** : contrat d'API non vérifié, leur
  documentation n'a pas pu être consultée pendant le développement ;
- **Hunyuan3D-2** : sa licence ne s'applique ni dans l'Union européenne, ni au Royaume-Uni, ni en
  Corée du Sud ;
- **TRELLIS** : dépendances compilées pour CUDA, non validées sous Windows.

### Mesures réelles (machine de développement : Ryzen 5 5600X, 32 Go, RTX 3060 Ti 8 Go)

| Moteur | Profil | Entrée | Durée | Résultat |
|---|---|---|---|---|
| TripoSR (PyTorch 2.11, CUDA 12.8) | Équilibré (maillage 256³) | vue trois quarts | 18 s (chargement compris) | 105 204 triangles, pic VRAM 2,4 Go |
| LSF Silhouette | Économique / Équilibré / Haute | profil + avant + dessus | 0,2 s / 1 à 3 s / 1 s | 16 k / 50 k / 120 k triangles ; dimensions retrouvées à ± 3 cm |

TripoSR ne lit qu'**une seule image** ; c'est indiqué dans l'interface et dans l'historique, et
les faces cachées sont estimées par le modèle. Sur les références de démonstration, les
proportions qu'il produit s'écartent du vrai véhicule (largeur exagérée). Le bouton « Recaler
sur les proportions mesurées » corrige l'échelle d'après l'analyse.

## AI Engine Manager

- **Interface commune** des adaptateurs. Chacun déclare son nom, sa version, ses capacités, ses
  formats d'entrée et de sortie, ses ressources, son authentification, ses limites, ses coûts,
  sa licence et son niveau de vérification (réel ou simulé).
- **Détection** du matériel et des moteurs en tâche de fond :
  - GPU via `nvidia-smi` (repli WMI), VRAM, version CUDA ;
  - RAM via `GlobalMemoryStatusEx`, processeur via le registre, disque ;
  - versions de numpy, trimesh, Pillow, PySide6 et Blender.
- **Profils** Économique, Équilibré et Haute qualité, fondés sur le moteur et le matériel. Pour
  TripoSR par exemple, le profil Haute qualité est refusé sous 6 Go de VRAM, et seul
  l'Économique est proposé sur processeur.
- **Auto AI Routing** : chaque moteur est retenu ou écarté avec une raison lisible :
  - indisponible, capacité absente ;
  - profil requis (LSF Silhouette), profil de qualité impossible sur ce matériel ;
  - mode Local / Cloud, plafond de coût.

  Les moteurs retenus sont classés : local privilégié, multi-vues exploitées, vue trois quarts
  adaptée aux réseaux image → 3D. Le **choix manuel** reste toujours possible.
- **File de tâches** : un fil par ressource (GPU local, processeur, réseau), avec progression,
  annulation (le processus TripoSR est arrêté), délai maximal configurable et journal.
  L'interface reste utilisable pendant une génération.
- **Cache** : une même génération (même moteur, mêmes paramètres, mêmes images et retouches) est
  resservie depuis le cache, ce que l'historique signale. Les dossiers temporaires se nettoient
  au-delà de 7 jours ou à la demande.
- **Configuration** (`ai_engines.json`, hors des projets) : mode, confirmation cloud, délai,
  plafond de coût, réglages par moteur. Toute clé glissée dans ce fichier est refusée.

## Clés API et cloud

- Les clés se saisissent dans **Moteurs → onglet du fournisseur**. Elles sont enregistrées dans
  `ai_secrets.json`, chiffré par Windows (DPAPI) : seul votre compte Windows peut le relire.
  Une variable `LSFCARS_<FOURNISSEUR>_API_KEY` est aussi acceptée.
- Aucune clé n'apparaît dans un `.lsfc`, dans le journal ou dans l'historique ; l'interface
  n'en affiche qu'un masque.
- Le **test de connexion** ne fait que des appels gratuits : solde Meshy, liste des modèles
  Anthropic, état de ComfyUI.
- **Aucune image ne quitte le PC sans confirmation explicite**. Les logos annotés sont masqués
  avant l'envoi. Une opération facturée demande d'accepter le coût estimé : grille de crédits
  publiée pour Meshy ; coût « non estimé » pour Anthropic, facturé au jeton.
- Le coût affiché après l'opération est **celui communiqué par le fournisseur** (crédits
  consommés, jetons). Il n'est jamais inventé.
- Requêtes : délais, **reprises contrôlées** (réseau, 429, 5xx, attente exponentielle, respect
  de `Retry-After`), erreurs classées (authentification, crédits, réseau, fournisseur). Le
  journal enregistre méthode, adresse sans paramètres, statut et durée.

## Reference Studio

- Import PNG, JPG, WEBP, BMP ou TIFF (40 Mo au plus). Les images sont conservées intactes dans
  le projet.
- Vues : avant, arrière, profils gauche et droit, trois quarts, dessus, intérieur, détails. La
  vue est proposée d'après le nom du fichier, puis modifiable.
- Réorganisation, rotation par pas de 90°, miroir, recadrage tracé sur l'image, luminosité,
  contraste, saturation. Toutes ces retouches sont non destructives et annulables.
- **Annotations** : logo réel, roue, optique, vitrage, calandre, élément distinctif, note.
- Comparaison de deux références côte à côte ; affichage du détourage.
- **Provenance** de chaque image : source, auteur, licence.
- **Couverture et cohérence** : vues présentes, doublons, résolution faible, et zones qui seront
  **estimées** (flanc opposé, face avant ou arrière, toit, habitacle, soubassement). Les parties
  invisibles ne sont jamais présentées comme reconstruites.

Le détourage local exploite la transparence de l'image, ou à défaut un **fond uni**. Sur une
photo avec décor, il échoue et le signale ; utilisez alors une image détourée.

## Vehicle Vision Analyzer

C'est une analyse **algorithmique locale** fondée sur le détourage :

- rapport longueur / hauteur, profil de toit (capot, milieu, arrière, toit plat) ;
- garde au sol, position et diamètre des roues ;
- couleurs dominantes (k-moyennes), part vitrée, optiques probables ;
- incohérences entre vues (proportions des profils, couleurs).

Le type de véhicule (berline, coupé, SUV, 4x4, pick-up, camion, van, ambulance, moto) est une
proposition classée par score et modifiable. Hélicoptère, bateau et aéronef se choisissent à la
main ou passent par l'analyse cloud.

Les mesures sont marquées **≈ estimées**. Elles découlent d'une longueur connue si vous la
saisissez, sinon d'une longueur typique du type. Une correction de l'utilisateur prend la
source « utilisateur ». L'analyse cloud (Claude), si vous l'activez, forme une section distincte
du rapport.

## Génération 3D

Le parcours est le suivant :

1. références et cohérence ;
2. choix du moteur et du profil ;
3. paramètres (longueur, consigne) ;
4. génération en tâche de fond, avec progression ;
5. validation du fichier produit : maillage lisible, triangles présents, coordonnées finies ;
6. import comme fichier du projet, avec sa provenance ;
7. **recalage automatique** : axe vertical, longueur sur Z, pose au sol, centrage, échelle à la
   longueur estimée. Pour les sorties de réseaux, une analyse en composantes principales et un
   plan d'appui ajusté sur les pneus redressent tangage et roulis ;
8. affichage dans le viewport, puis historique.

L'**ambiguïté avant / arrière** se lève avec le bouton « Retourner 180° ».

LSF Silhouette exploite réellement plusieurs vues : profil, avant ou arrière, dessus. Une vue
absente est remplacée par une section **estimée**, signalée dans le résultat. Les concavités
(passages de roues, vitrages en retrait), l'habitacle et le soubassement ne sont pas
reconstruits. En profil Économique (voxels de 6 cm), les éléments fins comme les rétroviseurs
peuvent disparaître.

## Lore Friendly AI Assistant

- **Marques et noms fictifs originaux**, générés localement et de façon déterministe pour un
  projet. Ils sont filtrés contre une liste de marques automobiles réelles et contre les marques
  de l'univers GTA (Rockstar Games), pour ne pas reprendre l'existant.
- **Trois propositions** fondées sur l'analyse : adaptation légère, équilibrée, originale.
  Chacune couvre la calandre, les optiques, la carrosserie, les détails distinctifs et la
  direction artistique, et le nom reste modifiable. Des suggestions cloud (Claude) peuvent s'y
  ajouter : elles sont filtrées et étiquetées comme telles.
- **Ajustements géométriques réellement applicables** sur confirmation et annulables : longueur
  du capot, hauteur du toit, largeur des voies, garde au sol. Ce sont des déformations lisses
  dans le repère du véhicule.
- **Logos réels** : aucune reconnaissance automatique locale, faute de modèle de détection
  embarqué. On les marque par annotation, et ils sont masqués avant génération, envoi cloud et
  projection de texture. L'analyse cloud peut les lister.
- **Registre de provenance** : références (source, auteur, licence, logos marqués), générations
  (moteur, méthode, licence, date), proposition retenue, licences manquantes, avertissement.
  Il est copiable dans le presse-papiers.

> Remplacer un logo ne suffit pas à garantir le respect des droits de propriété intellectuelle :
> formes, calandres et signatures lumineuses peuvent aussi être protégées.

Depuis la v0.8, la transformation complète d'un véhicule (marques, Design DNA, studios,
comparaison, provenance) se fait dans **Lore Friendly Studio** ; voir
[LORE_FRIENDLY_ENGINE.md](LORE_FRIENDLY_ENGINE.md). Les adaptateurs y gagnent deux capacités
explicites, testées contre des serveurs simulés uniquement : « plan de transformation » (Claude,
résumé texte seulement) et « image conceptuelle 2D » (ComfyUI, workflow dédié — jamais un modèle
3D).

## AI Mesh Assistant

Ses quatre catégories sont affichées séparément.

1. **Diagnostics automatiques**, des mesures exactes :
   - triangles, sommets soudés, parties non connectées, petites pièces ;
   - trous (arêtes de bord), arêtes non manifold ;
   - faces dégénérées ou dupliquées, enroulement incohérent, volume signé, état des UV.
2. **Corrections déterministes** :
   - réorienter les normales, supprimer faces dégénérées et doublons ;
   - fusionner les sommets proches, boucher les petits trous ;
   - lisser (Taubin), simplifier (regroupement de sommets) ;
   - supprimer les petites pièces, symétriser, projeter des UV.
3. **Suggestions** formulées comme des propositions : simplification d'un maillage dense,
   lissage d'une surface à facettes, symétrisation en cas d'asymétrie, retopologie par Blender.
   Ce sont des **règles heuristiques locales**, pas un réseau de neurones.
4. **Validation humaine** : symétrie, suppression de pièces, bouchage d'ouvertures,
   simplification, préparation FiveM. Une confirmation est demandée.

Toutes les opérations passent par l'historique (Ctrl+Z). Elles remplacent la géométrie du
maillage choisi sans toucher au nœud : pivot, hiérarchie et métadonnées d'origine sont conservés.

## AI Texture Creator

| Carte | Origine |
|---|---|
| Couleur de base | **projetée** depuis les références (vue la mieux orientée, test de visibilité par profondeur, flanc opposé supposé symétrique si un seul profil) ou **cuite** depuis les couleurs par sommet |
| Normal map | **dérivée** de la luminance (approximation, pas un relief mesuré) |
| Roughness, Metallic | **générées par règles** (vitrages sombres brillants, préréglage de matériau) |
| Ambient occlusion | **non générée** localement |
| Cartes PBR d'un fournisseur (Meshy) | **fournies par le moteur**, conservées dans `assets/ai/` |

- UV d'atlas (six projections) créées si le modèle n'en a pas ; des recouvrements sont
  possibles dans les creux.
- Variations de teinte de la carrosserie.
- **Appliquer au modèle** crée et affecte un matériau (annulable).
- **Livery Studio** utilise la texture comme base de livrée.

## Historique des générations

Chaque génération réussie, échouée, annulée ou en dépassement de délai est conservée avec :

- références, moteur et version, méthode, paramètres et profil, consigne, date et durée ;
- coût estimé et coût communiqué ;
- statut et erreur, avertissements, fichiers produits, miniature, triangles.

Actions possibles : **réouvrir** (sélection, ou réimport depuis le fichier du projet),
**dupliquer**, **comparer** (miniatures et tableau), **réutiliser les paramètres**,
**supprimer** (avec ou sans le modèle).

## Sauvegarde `.lsfc`

L'état vit dans le document `ai` du projet (format 1, table `documents`). Il contient :

- références avec retouches, annotations et provenance ;
- rapport d'analyse, réglages IA, propositions et choix Lore Friendly ;
- historique ;
- textures produites.

Les images de référence et les miniatures sont des blobs du projet (table `blobs`). Les modèles
générés sont des fichiers du projet (`assets/`, provenance « AI Vehicle Creator »), et les
fichiers annexes vont dans `assets/ai/<génération>/`. Le schéma SQLite reste en **v6** : les
tables `documents` et `blobs` suffisent, et un projet 0.6 s'ouvre sans migration. **Aucune clé
API** n'est enregistrée dans le projet.

## Installer TripoSR (facultatif)

Depuis l'application : **Moteurs → TripoSR → Installer…**. La liste des téléchargements
s'affiche d'abord et une confirmation est demandée. En ligne de commande :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_triposr.ps1
```

Tout va dans `%USERPROFILE%\.lestitcheurfoucars\engines\triposr` (ou dans le dossier défini par
`LSFCARS_ENGINES`), rien dans l'application ni dans les projets. Il faut environ 5 à 6 Go et le
lanceur Python `py`. Le script installe :

- `uv` et Python 3.12 ;
- PyTorch (CUDA 12.8, ou CPU sans GPU NVIDIA) ;
- omegaconf, einops, transformers, huggingface-hub, trimesh, PyMCubes, imageio, Pillow ;
- le code TripoSR (archive GitHub, MIT) et les poids `stabilityai/TripoSR` (Hugging Face, MIT).

L'inférence tourne dans un processus séparé, sans téléchargement implicite (`HF_HUB_OFFLINE=1`).
L'extension `torchmcubes`, qui doit être compilée, est remplacée par PyMCubes, et `rembg` n'est
pas utilisé puisque le détourage est fait par l'application.

## Limites

- TripoSR : une seule image, proportions approximatives, couleurs par sommet seulement, aucune
  texture UV.
- LSF Silhouette : il faut au moins un profil sur fond uni ou détouré. Il ne reconstruit pas les
  concavités, et une vue absente est remplacée par une section estimée.
- Détourage local limité aux fonds unis ou aux images transparentes.
- Analyse locale par règles : le type de véhicule et les mesures sont approximatifs, et les
  véhicules non routiers ne sont pas classés localement.
- Aucune reconnaissance automatique locale des logos.
- Cloud (Meshy, Anthropic) et ComfyUI : protocole vérifié uniquement contre des serveurs simulés.
  Aucune génération cloud réelle n'a été exécutée faute de clé.
- Normal map dérivée, roughness et metallic par règles, aucune ambient occlusion locale.
- Simplification par regroupement de sommets : qualité inférieure à une décimation par
  contraction d'arêtes. La retopologie passe par Blender (Vehicle Editor).
- Aucun modèle généré n'est utilisable en jeu sans préparation FiveM complète.
