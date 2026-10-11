"""Erreurs des lecteurs GTA V / FiveM : messages en français, lisibles par l'utilisateur."""

from __future__ import annotations


class FormatError(Exception):
    """Fichier invalide, tronqué ou d'une variante non reconnue."""


class EncryptedError(FormatError):
    """Contenu chiffré : il n'est jamais déchiffré par LeStitcheurFou Cars."""


class ProtectedResourceError(FormatError):
    """Ressource protégée (FiveM Asset Escrow) : lecture impossible, aucun contournement."""
