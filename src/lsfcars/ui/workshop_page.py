"""Pages des ateliers à venir. Elles décrivent le périmètre prévu sans simuler de fonction."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

PLANNED_BADGE = "Prévu — non disponible dans la v0.1.0"


@dataclass(frozen=True)
class WorkshopInfo:
    key: str
    title: str
    summary: str
    planned: tuple[str, ...]


WORKSHOPS: tuple[WorkshopInfo, ...] = (
    WorkshopInfo(
        "liveries",
        "Atelier de livrées",
        "Création et personnalisation des livrées appliquées sur la carrosserie.",
        (
            "Éditeur de calques (couleurs, logos, textes, motifs)",
            "Gabarits UV par véhicule et aperçu en direct dans le viewport",
            "Bibliothèque de livrées Lore Friendly réutilisables",
            "Export des textures au format attendu par FiveM",
        ),
    ),
    WorkshopInfo(
        "emergency",
        "Atelier LSPD / EMS",
        "Configuration des véhicules de police et de secours.",
        (
            "Rampes lumineuses, gyrophares et sirènes positionnables",
            "Accessoires : push-bar, radios, équipements intérieurs",
            "Préréglages LSPD, BCSO, SAHP, EMS, pompiers",
            "Génération des paramètres d'éclairage d'urgence",
        ),
    ),
    WorkshopInfo(
        "ai",
        "Génération IA",
        "Propositions 3D générées à partir d'images de référence.",
        (
            "Adaptateurs interchangeables : IA locale ou services cloud",
            "Clés API stockées hors du dépôt, dans le coffre sécurisé de Windows",
            "File de génération avec suivi et historique",
            "Nettoyage et retopologie avant import dans la scène",
        ),
    ),
    WorkshopInfo(
        "export",
        "Centre d'export FiveM",
        "Optimisation et préparation d'une ressource FiveM prête à l'emploi.",
        (
            "Contrôles : polygones, LOD, matériaux, dimensions",
            "Optimisation automatique des maillages",
            "Génération de fxmanifest.lua et des fichiers de métadonnées",
            "Conversion via Blender en processus auxiliaire lorsque nécessaire",
        ),
    ),
)


class WorkshopPage(QWidget):
    def __init__(self, info: WorkshopInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.info = info
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 32)
        root.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel(info.title)
        title.setObjectName("H1")
        self.badge = QLabel(PLANNED_BADGE)
        self.badge.setObjectName("Badge")
        header.addWidget(title)
        header.addSpacing(12)
        header.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
        root.addLayout(header)

        summary = QLabel(info.summary)
        summary.setObjectName("Muted")
        summary.setWordWrap(True)
        root.addWidget(summary)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        planned_title = QLabel("Fonctions prévues")
        planned_title.setObjectName("H2")
        card_layout.addWidget(planned_title)
        for feature in info.planned:
            label = QLabel(f"•  {feature}")
            label.setWordWrap(True)
            card_layout.addWidget(label)
        root.addWidget(card)

        note = QLabel(
            "Cet atelier n'est pas encore implémenté : aucune action n'est disponible ici pour "
            "le moment. Suivez l'avancement dans le CHANGELOG et sur le dépôt GitHub."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        root.addWidget(note)
        root.addStretch(1)
