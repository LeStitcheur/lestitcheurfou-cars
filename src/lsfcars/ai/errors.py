"""Erreurs du module IA : chacune porte un message destiné à l'utilisateur (en français)."""

from __future__ import annotations


class AIError(RuntimeError):
    """Erreur prévue d'une opération IA (affichée comme notification, jamais un plantage)."""


class EngineUnavailable(AIError):
    """Le moteur n'est pas installé, pas configuré ou ne prend pas en charge l'opération."""


class ConsentRequired(AIError):
    """Transfert cloud ou opération payante sans confirmation explicite de l'utilisateur."""


class JobCancelled(AIError):
    """Tâche annulée par l'utilisateur."""


class JobTimeout(AIError):
    """Délai maximal dépassé."""


class NetworkError(AIError):
    """Erreur réseau (connexion, DNS, délai) : peut être retentée."""


class AuthError(AIError):
    """Clé API absente, invalide ou refusée."""


class QuotaError(AIError):
    """Crédits insuffisants ou limite de requêtes atteinte."""


class ProviderError(AIError):
    """Réponse d'erreur du fournisseur ou du moteur."""


class InvalidOutput(AIError):
    """Le moteur a répondu, mais le résultat n'est pas un fichier exploitable."""
