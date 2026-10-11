"""Lecture des ressources GTA V / FiveM (sans Qt, exécutable dans un thread).

Principes :

- lecture seule : aucun fichier source n'est jamais modifié ;
- aucune simulation : un format n'est déclaré pris en charge que s'il est réellement décodé ;
- aucun contournement : les archives chiffrées (AES / NG de l'installation officielle) et les
  ressources protégées (FiveM Asset Escrow) sont détectées puis refusées avec une explication.

Modules : ``rpf`` (archives RPF7), ``rsc`` (ressources RSC7), ``ytd`` (textures), ``yft``
(modèles), ``meta`` (métadonnées XML), ``resource`` (analyse d'une ressource complète),
``structure`` (classification des composants), ``sollumz`` (adaptateur Blender / Sollumz).
"""

from lsfcars.fivem.errors import EncryptedError, FormatError, ProtectedResourceError

__all__ = ["EncryptedError", "FormatError", "ProtectedResourceError"]
