"""Panneaux du Livery Studio : outils, formes et marquages, logos, modèles, calques, propriétés,
matériaux, livrées (variantes), export, progression, diagnostics, UV.

Chaque panneau lit l'état dans ``page.studio`` et agit par ``page.run`` (erreurs prévues →
notifications). Aucune couleur littérale : les couleurs de dessin viennent du panneau couleur.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from lsfcars.livery import bands, export, render2d
from lsfcars.livery import templates as tpl
from lsfcars.livery.logos import CATEGORIES as LOGO_CATEGORIES
from lsfcars.livery.model import BLEND_MODES, BLEND_SPACES, LAYER_KINDS, MODES, STANDARD_SIZES, to_hex
from lsfcars.livery.raster import BrushSettings
from lsfcars.ui.design import tokens
from lsfcars.ui.design.components import LSInput, LSProgress, LSSelect, eyebrow, label, tooltip
from lsfcars.ui.design.icons import icon
from lsfcars.ui.editor.panels import Page, button, spin
from lsfcars.ui.livery.canvas import TOOLS
from lsfcars.ui.livery.colors import Swatch

ID_ROLE = Qt.ItemDataRole.UserRole


def check(text: str, value: bool = False, tip: str = "") -> QCheckBox:
    box = QCheckBox(text)
    box.setChecked(value)
    if tip:
        tooltip(box, tip)
    return box


def int_spin(value: int, minimum: int, maximum: int, suffix: str = "") -> QSpinBox:
    box = QSpinBox()
    box.setRange(minimum, maximum)
    box.setValue(value)
    if suffix:
        box.setSuffix(suffix)
    return box


def form() -> QFormLayout:
    layout = QFormLayout()
    layout.setHorizontalSpacing(8)
    layout.setVerticalSpacing(6)
    layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
    return layout


def thumbnail(array, size: int = 96) -> QPixmap:  # type: ignore[no-untyped-def]
    image = render2d.qimage_from_rgba(array)
    return QPixmap.fromImage(
        image.scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
    )


def clear_items(widget) -> None:  # type: ignore[no-untyped-def]
    """Vide une liste ou un arbre en rendant chaque élément à Python (destruction unique).

    ``clear()`` détruirait les éléments côté C++ alors que leurs enveloppes Python restent rattachées
    au parent : elles seraient libérées une seconde fois par le ramasse-miettes.
    """
    if isinstance(widget, QTreeWidget):
        while widget.topLevelItemCount():
            widget.takeTopLevelItem(0)
    else:
        while widget.count():
            widget.takeItem(0)


def secondary_brush() -> QBrush:
    return QBrush(QColor(tokens.ColorTokens.TEXT_SECONDARY))


# --- Outils ------------------------------------------------------------------------------------


class ToolsPanel(Page):
    """Grille d'outils et propriétés contextuelles de l'outil actif."""

    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        tools = self.section(
            "Outils de dessin", "Raccourcis entre parenthèses ; Espace + glisser : panoramique."
        )
        grid = QGridLayout()
        grid.setSpacing(4)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QToolButton] = {}
        for index, (key, text, icon_name, shortcut) in enumerate(TOOLS):
            widget = QToolButton()
            widget.setCheckable(True)
            widget.setIcon(icon(icon_name, tokens.ColorTokens.TEXT_SECONDARY, tokens.ColorTokens.ELECTRIC))
            widget.setIconSize(QSize(18, 18))
            widget.setFixedSize(38, 34)
            tooltip(widget, text, shortcut)
            widget.clicked.connect(lambda _c=False, k=key: page.set_tool(k))
            self.group.addButton(widget)
            self.buttons[key] = widget
            grid.addWidget(widget, index // 5, index % 5)
        tools.body.addLayout(grid)
        self.tool_name = tools.add(eyebrow(""))
        self.stack = QStackedWidget()
        self.layout_.addWidget(self.stack)
        self.pages: dict[str, int] = {}
        self._build_brush()
        self._build_fill()
        self._build_gradient()
        self._build_shapes()
        self._build_text()
        self._build_selection()
        self._build_move()
        self._build_info()
        self.finish()

    def _page(self, keys: tuple[str, ...]) -> QVBoxLayout:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)
        index = self.stack.addWidget(widget)
        for key in keys:
            self.pages[key] = index
        return layout

    def _build_brush(self) -> None:
        layout = self._page(("brush", "eraser"))
        grid = form()
        self.size = spin(24, 1, 1024, 1, 0, " px")
        self.opacity = int_spin(100, 1, 100, " %")
        self.hardness = int_spin(80, 0, 100, " %")
        self.spacing = int_spin(15, 1, 200, " %")
        grid.addRow("Taille", self.size)
        grid.addRow("Opacité", self.opacity)
        grid.addRow("Dureté", self.hardness)
        grid.addRow("Espacement", self.spacing)
        layout.addLayout(grid)
        self.pressure_size = check(
            "Pression → taille", True, "Tablette compatible : la pression module la taille"
        )
        self.pressure_opacity = check("Pression → opacité", False)
        self.symmetry = check(
            "Symétrie gauche / droite",
            False,
            "Calculée en 3D par le plan de symétrie du véhicule (respecte l'orientation réelle des UV)",
        )
        self.lock_alpha = check(
            "Verrouiller la transparence", False, "Peindre seulement les pixels déjà peints"
        )
        self.target = LSSelect([("Calque", "layer"), ("Masque du calque", "mask")])
        for widget in (self.pressure_size, self.pressure_opacity, self.symmetry, self.lock_alpha):
            layout.addWidget(widget)
        row = QHBoxLayout()
        row.addWidget(label("Cible", "muted"))
        row.addWidget(self.target, 1)
        layout.addLayout(row)
        layout.addWidget(
            label(
                "Peinture 3D : peignez directement sur la carrosserie dans la vue 3D "
                "(Alt + glisser : orbite). "
                "Les pixels de la texture sont réellement modifiés, de part et d'autre des coutures UV.",
                "faint",
                wrap=True,
            )
        )

    def _build_fill(self) -> None:
        layout = self._page(("fill",))
        grid = form()
        self.fill_mode = LSSelect(
            [
                ("Zone de couleur contiguë", "color"),
                ("Îlot UV sous le curseur", "island"),
                ("Sélection", "selection"),
            ]
        )
        self.tolerance = int_spin(32, 0, 255)
        self.fill_opacity = int_spin(100, 1, 100, " %")
        grid.addRow("Mode", self.fill_mode)
        grid.addRow("Tolérance", self.tolerance)
        grid.addRow("Opacité", self.fill_opacity)
        layout.addLayout(grid)

    def _build_gradient(self) -> None:
        layout = self._page(("gradient",))
        grid = form()
        self.gradient_kind = LSSelect([("Linéaire", "linear"), ("Radial", "radial")])
        self.gradient_opacity = int_spin(100, 1, 100, " %")
        grid.addRow("Type", self.gradient_kind)
        grid.addRow("Opacité", self.gradient_opacity)
        layout.addLayout(grid)
        layout.addWidget(
            label(
                "Glissez de la couleur principale vers la secondaire (limité à la sélection).",
                "faint",
                wrap=True,
            )
        )

    def _build_shapes(self) -> None:
        layout = self._page(("line", "rect", "rounded_rect", "circle", "ellipse", "polygon", "curve"))
        self.shape_fill = check("Remplir (couleur principale)", True)
        self.shape_stroke = check("Contour (couleur secondaire)", False)
        self.shape_closed = check("Courbe fermée", False)
        grid = form()
        self.stroke_width = spin(6, 0.5, 200, 0.5, 1, " px")
        self.radius = spin(24, 0, 1000, 1, 0, " px")
        grid.addRow("Épaisseur", self.stroke_width)
        grid.addRow("Arrondi", self.radius)
        for widget in (self.shape_fill, self.shape_stroke, self.shape_closed):
            layout.addWidget(widget)
        layout.addLayout(grid)
        layout.addWidget(
            label("Les formes restent vectorielles et éditables (calque vectoriel).", "faint", wrap=True)
        )

    def _build_text(self) -> None:
        layout = self._page(("text",))
        grid = form()
        self.font = QFontComboBox()
        self.font.setCurrentFont(QFont(render2d.default_family()))
        self.text_size = spin(96, 4, 2000, 1, 0, " px")
        grid.addRow("Police", self.font)
        grid.addRow("Taille", self.text_size)
        layout.addLayout(grid)
        self.text_bold = check("Gras", True)
        layout.addWidget(self.text_bold)
        layout.addWidget(label("Cliquez sur la texture pour poser un texte éditable.", "faint", wrap=True))

    def _build_selection(self) -> None:
        layout = self._page(("select", "lasso", "island"))
        layout.addWidget(
            label(
                "Maj : ajouter · Alt : retirer. La sélection limite peinture, remplissage et dégradé.",
                "faint",
                wrap=True,
            )
        )
        grid = QGridLayout()
        grid.setSpacing(4)
        actions = [
            ("Tout", "layout-grid", self.page.select_all, "Tout sélectionner (Ctrl+A)"),
            ("Aucune", "x", self.page.clear_selection, "Désélectionner (Ctrl+D)"),
            ("Copier", "copy", self.page.copy, "Copier (Ctrl+C)"),
            ("Couper", "trash-2", self.page.cut, "Couper (Ctrl+X)"),
            ("Coller", "copy-plus", self.page.paste, "Coller en nouveau calque (Ctrl+V)"),
            (
                "→ Masque",
                "lsf-mask",
                self.page.mask_from_selection,
                "Masque du calque actif depuis la sélection",
            ),
        ]
        for index, (text, icon_name, slot, tip) in enumerate(actions):
            grid.addWidget(button(text, icon_name, slot, tip), index // 2, index % 2)
        layout.addLayout(grid)

    def _build_move(self) -> None:
        layout = self._page(("move",))
        layout.addWidget(
            label(
                "Cliquez un élément (texte, logo, forme) ; carrés : échelle, rond : rotation "
                "(Maj : pas de 15°).",
                "faint",
                wrap=True,
            )
        )
        self.align_ref = LSSelect([("Texture", "canvas"), ("Sélection", "selection"), ("Îlot UV", "island")])
        row = QHBoxLayout()
        row.addWidget(label("Aligner sur", "muted"))
        row.addWidget(self.align_ref, 1)
        layout.addLayout(row)
        grid = QGridLayout()
        grid.setSpacing(4)
        aligns = [
            ("Gauche", "left"),
            ("Centre H", "hcenter"),
            ("Droite", "right"),
            ("Haut", "top"),
            ("Centre V", "vcenter"),
            ("Bas", "bottom"),
        ]
        for index, (text, mode) in enumerate(aligns):
            widget = button(text, None, lambda m=mode: self.page.align(m, self.align_ref.currentData()))
            grid.addWidget(widget, index // 3, index % 3)
        layout.addLayout(grid)
        row = QHBoxLayout()
        for text, tip, slot in (
            ("−15°", "Rotation", lambda: self.page.transform_current(rotation=-15)),
            ("+15°", "Rotation", lambda: self.page.transform_current(rotation=15)),
            ("−10 %", "Échelle", lambda: self.page.transform_current(scale=0.9)),
            ("+10 %", "Échelle", lambda: self.page.transform_current(scale=1.1)),
        ):
            row.addWidget(button(text, None, slot, tip))
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(button("Dupliquer", "copy-plus", self.page.duplicate_layer, "Dupliquer (Ctrl+J)"))
        row.addWidget(button("Symétrie", "lsf-mirror", self.page.mirror_layer, "Copie sur l'autre flanc"))
        layout.addLayout(row)

    def _build_info(self) -> None:
        layout = self._page(("pipette",))
        layout.addWidget(
            label(
                "Cliquez sur la texture (ou la carrosserie en 3D) pour prélever la couleur visible.",
                "faint",
                wrap=True,
            )
        )

    def set_tool(self, key: str) -> None:
        if key in self.buttons:
            self.buttons[key].setChecked(True)
        self.tool_name.setText(next((t[1] for t in TOOLS if t[0] == key), "").upper())
        self.stack.setCurrentIndex(self.pages.get(key, self.pages["pipette"]))

    def brush_settings(self, eraser: bool = False) -> BrushSettings:
        return BrushSettings(
            size=self.size.value(),
            opacity=self.opacity.value() / 100,
            hardness=self.hardness.value() / 100,
            spacing=self.spacing.value() / 100,
            pressure_size=self.pressure_size.isChecked(),
            pressure_opacity=self.pressure_opacity.isChecked(),
            eraser=eraser,
        )


# --- Formes et marquages (outils de livrée) --------------------------------------------------


class MarkingsPanel(Page):
    """Bandes 3D, marquages de zone, formes prédéfinies."""

    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        band = self.section(
            "Bandes 3D",
            "Définies dans l'espace du véhicule : elles suivent la carrosserie et restent symétriques.",
        )
        grid = form()
        self.zone = LSSelect([(v, k) for k, v in bands.ZONES.items()])
        self.zone.select_data("sides")
        self.orientation = LSSelect([(v, k) for k, v in bands.ORIENTATIONS.items()])
        self.pattern = LSSelect([(v, k) for k, v in bands.PATTERNS.items()])
        self.side = LSSelect([("Deux côtés", "both"), ("Gauche", "left"), ("Droite", "right")])
        self.width = spin(0.12, 0.005, 5.0, 0.01, 3, " m")
        self.height = spin(0.55, -1.0, 5.0, 0.01, 2, " m")
        self.lon = spin(0.0, -10.0, 10.0, 0.05, 2, " m")
        self.lateral = spin(0.0, -3.0, 3.0, 0.01, 2, " m")
        self.angle = spin(30, -89, 89, 1, 0, "°")
        self.period = spin(0.3, 0.01, 5.0, 0.01, 2, " m")
        for text, widget in (
            ("Zone", self.zone),
            ("Orientation", self.orientation),
            ("Motif", self.pattern),
            ("Côtés", self.side),
            ("Largeur", self.width),
            ("Hauteur (centre)", self.height),
            ("Longitudinal", self.lon),
            ("Décalage latéral", self.lateral),
            ("Angle (diagonale)", self.angle),
            ("Période du motif", self.period),
        ):
            grid.addRow(text, widget)
        band.body.addLayout(grid)
        band.add(label("Couleurs : principale et secondaire du panneau Couleurs.", "faint", wrap=True))
        band.row(button("Ajouter la bande", "lsf-band", self.add_band, variant="primary"), stretch=True)

        marking = self.section("Marquages", "Texte placé sur une zone, orienté d'après le dépliage réel.")
        self.text = LSInput("POLICE, AMBULANCE, numéro d'unité…")
        marking.add(self.text)
        grid = form()
        zones = ("sides", "left", "right", "hood", "roof", "trunk", "front", "rear")
        self.text_zone = LSSelect([(bands.ZONES[k], k) for k in zones])
        self.text_size = spin(0.15, 0.01, 2.0, 0.01, 2, " m")
        self.text_lon = spin(0.1, -10.0, 10.0, 0.05, 2, " m")
        self.text_height = spin(0.66, 0.0, 5.0, 0.01, 2, " m")
        self.both_sides = check("Les deux flancs (symétrie 3D)", True)
        self.mirrored = check("Inversé (lecture au rétroviseur)", False)
        grid.addRow("Zone", self.text_zone)
        grid.addRow("Hauteur des lettres", self.text_size)
        grid.addRow("Longitudinal", self.text_lon)
        grid.addRow("Hauteur du centre", self.text_height)
        marking.body.addLayout(grid)
        marking.add(self.both_sides)
        marking.add(self.mirrored)
        marking.row(
            button("Ajouter le marquage", "lsf-text", self.add_marking, variant="primary"),
            button("Numéro d'unité", None, self.add_unit, "Numéro de la livrée active sur le toit"),
        )

        shapes = self.section("Formes prédéfinies", "Insérées au centre de la vue 2D, couleur principale.")
        grid = QGridLayout()
        grid.setSpacing(4)
        presets = [
            ("Rectangle", "square", "rect"),
            ("Arrondi", "lsf-rounded", "rounded_rect"),
            ("Cercle", "lsf-circle", "circle"),
            ("Ellipse", "lsf-ellipse", "ellipse"),
            ("Chevron", "lsf-polygon", "chevron"),
            ("Étoile", "lsf-polygon", "star"),
            ("Flèche", "lsf-polygon", "arrow"),
            ("Triangle", "lsf-polygon", "triangle"),
            ("Bandeau", "lsf-band", "banner"),
        ]
        for index, (text, icon_name, key) in enumerate(presets):
            grid.addWidget(
                button(text, icon_name, lambda k=key: self.page.insert_preset(k)), index // 3, index % 3
            )
        shapes.body.addLayout(grid)
        self.finish()

    def add_band(self) -> str | None:
        studio = self.page.studio
        if studio is None:
            return None
        params = {
            "zone": self.zone.currentData(),
            "orientation": self.orientation.currentData(),
            "pattern": self.pattern.currentData(),
            "side": self.side.currentData(),
            "width": self.width.value(),
            "center_height": self.height.value(),
            "center_lon": self.lon.value(),
            "lateral_offset": self.lateral.value(),
            "angle": self.angle.value(),
            "period": self.period.value(),
            "color": self.page.colors.color(),
            "color2": self.page.colors.secondary(),
        }
        name = f"Bande {bands.PATTERNS[params['pattern']].lower()}"
        return self.page.run("Bande 3D", lambda: studio.add_band(name, **params))

    def add_marking(self, text: str | None = None) -> list[str] | None:
        studio = self.page.studio
        text = (text if text is not None else self.text.text()).strip()
        if studio is None or not text:
            return None
        style = {"color": self.page.colors.color(), "bold": True, "mirrored": self.mirrored.isChecked()}
        return self.page.run(
            "Marquage",
            lambda: studio.add_text_on_zone(
                text,
                self.text_zone.currentData(),
                self.text_size.value(),
                self.text_lon.value(),
                self.text_height.value(),
                self.both_sides.isChecked(),
                **style,
            ),
        )

    def add_unit(self) -> list[str] | None:
        studio = self.page.studio
        doc = studio.document() if studio is not None else None
        variant = doc.active_variant if doc else None
        if variant is None:
            return None
        unit = variant.metadata.get("unit") or "12"
        color = self.page.colors.color()
        return self.page.run(
            "Numéro d'unité",
            lambda: studio.add_text_on_zone(unit, "roof", 0.45, 0.0, 0.0, False, color=color, bold=True),
        )


# --- Logos -------------------------------------------------------------------------------------


class LogoImportDialog(QDialog):
    def __init__(self, path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Importer un logo")
        layout = QVBoxLayout(self)
        layout.addWidget(label(f"Fichier : {Path(path).name}", "muted"))
        layout.addWidget(
            label(
                "Renseignez la provenance et la licence : n'importez que des logos dont vous "
                "détenez les droits.",
                "faint",
                wrap=True,
            )
        )
        grid = form()
        self.name = LSInput("Nom")
        self.name.setText(Path(path).stem)
        self.category = LSSelect([(v, k) for k, v in LOGO_CATEGORIES.items()])
        self.category.select_data("personal")
        self.author = LSInput("Auteur")
        self.source = LSInput("Source (site, fichier…)")
        self.license = LSInput("Licence (ex. CC BY 4.0, création personnelle…)")
        for text, widget in (
            ("Nom", self.name),
            ("Catégorie", self.category),
            ("Auteur", self.author),
            ("Source", self.source),
            ("Licence", self.license),
        ):
            grid.addRow(text, widget)
        layout.addLayout(grid)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class LogosPanel(Page):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        library = self.section(
            "Bibliothèque de logos", "Emblèmes originaux intégrés et logos importés (PNG, SVG, JPG, WEBP)."
        )
        self.search = LSInput("Rechercher un logo…")
        self.search.textChanged.connect(lambda _t: self.refresh())
        self.category = LSSelect(
            [("Toutes les catégories", "")] + [(v, k) for k, v in LOGO_CATEGORIES.items()]
        )
        self.category.activated.connect(lambda: self.refresh())
        library.add(self.search)
        library.add(self.category)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(64, 64))
        self.list.setGridSize(QSize(92, 96))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setWordWrap(True)
        self.list.setMinimumHeight(230)
        self.list.currentItemChanged.connect(lambda *_: self._show_info())
        self.list.itemDoubleClicked.connect(lambda _i: self.add_center())
        library.add(self.list)
        self.info = library.add(label("", "faint", wrap=True))
        placement = self.section("Placement")
        grid = form()
        self.size_m = spin(0.3, 0.02, 3.0, 0.01, 2, " m")
        self.lon = spin(0.75, -10.0, 10.0, 0.05, 2, " m")
        self.height = spin(0.6, 0.0, 5.0, 0.01, 2, " m")
        self.tint = check(
            "Recolorer (couleur principale)", False, "Remplace la couleur en conservant la transparence"
        )
        grid.addRow("Taille", self.size_m)
        grid.addRow("Longitudinal", self.lon)
        grid.addRow("Hauteur", self.height)
        placement.body.addLayout(grid)
        placement.add(self.tint)
        placement.row(
            button("Au centre de la vue", "plus", self.add_center),
            button(
                "Sur les flancs",
                "lsf-mirror",
                self.add_sides,
                "Deux flancs, orientation UV réelle",
                "primary",
            ),
        )
        manage = self.section("Gestion")
        manage.row(
            button(
                "Importer…", "upload", self.import_dialog, "PNG, SVG, JPG, WEBP — auteur, source et licence"
            ),
            button("", "trash-2", self.remove, "Retirer de la bibliothèque (logos importés)", "danger"),
        )
        self.finish()

    def current_logo(self) -> str | None:
        item = self.list.currentItem()
        return item.data(ID_ROLE) if item is not None else None

    def select_logo(self, logo_id: str) -> bool:
        for row in range(self.list.count()):
            if self.list.item(row).data(ID_ROLE) == logo_id:
                self.list.setCurrentRow(row)
                return True
        return False

    def refresh(self) -> None:
        library = self.page.logos
        current = self.current_logo()
        clear_items(self.list)
        if library is None:
            self.info.setText("Chargement de la bibliothèque…")
            return
        for entry in library.entries(self.category.currentData() or None, self.search.text()):
            item = QListWidgetItem(entry.name)
            item.setData(ID_ROLE, entry.id)
            item.setToolTip(f"{entry.name}\n{LOGO_CATEGORIES.get(entry.category, entry.category)}")
            try:
                image = render2d.source_image(f"thumb-{entry.id}", library.data(entry.id), 64, 64)
                if image is not None:
                    item.setIcon(QIcon(QPixmap.fromImage(image)))
            except Exception:  # noqa: BLE001 (vignette illisible : le logo reste listé)
                pass
            self.list.addItem(item)
        if current:
            self.select_logo(current)
        self._show_info()

    def _show_info(self) -> None:
        library, logo_id = self.page.logos, self.current_logo()
        entry = library.get(logo_id) if library and logo_id else None
        if entry is None:
            self.info.setText("Sélectionnez un logo.")
            return
        license_text = entry.license or "non renseignée (vérifiez vos droits)"
        self.info.setText(
            f"{entry.name} — {LOGO_CATEGORIES.get(entry.category, entry.category)}\n"
            f"Auteur : {entry.author or '—'} · Source : {entry.source or '—'}\nLicence : {license_text}"
        )

    def add_center(self) -> str | None:
        studio, logo_id = self.page.studio, self.current_logo()
        if studio is None or logo_id is None:
            return None
        x, y = self.page.view_center()
        doc = studio.document()
        width = (doc.width if doc else 1024) * 0.12
        params = {"tint": self.page.colors.color(), "tint_enabled": True} if self.tint.isChecked() else {}
        return self.page.run("Logo", lambda: studio.add_logo(logo_id, x, y, width, **params))

    def add_sides(self) -> list[str] | None:
        studio, logo_id = self.page.studio, self.current_logo()
        if studio is None or logo_id is None:
            return None
        tint = self.page.colors.color() if self.tint.isChecked() else None
        size, lon, height = self.size_m.value(), self.lon.value(), self.height.value()
        return self.page.run(
            "Logo", lambda: studio.add_logo_on_zone(logo_id, "sides", size, lon, height, True, tint)
        )

    def import_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Importer un logo", "", "Logos (*.png *.svg *.jpg *.jpeg *.webp)"
        )
        if not path:
            return
        dialog = LogoImportDialog(path, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.import_logo(
            path,
            dialog.name.text(),
            dialog.category.currentData(),
            dialog.author.text(),
            dialog.source.text(),
            dialog.license.text(),
        )

    def import_logo(
        self,
        path: str,
        name: str = "",
        category: str = "personal",
        author: str = "",
        source: str = "",
        license_text: str = "",
    ) -> str | None:
        library = self.page.logos
        if library is None:
            return None
        entry = self.page.run(
            "Import de logo", lambda: library.import_file(path, name, category, author, source, license_text)
        )
        if entry is None:
            return None
        if not entry.license:
            self.page.controller.notify.emit(
                "Logo", "Licence non renseignée : le logo sera signalé à l'export.", "warning"
            )
        self.refresh()
        self.select_logo(entry.id)
        return entry.id

    def remove(self) -> None:
        library, logo_id = self.page.logos, self.current_logo()
        if library is None or logo_id is None:
            return
        if not library.remove(logo_id):
            self.page.controller.notify.emit(
                "Logo", "Les emblèmes intégrés ne peuvent pas être retirés.", "info"
            )
        self.refresh()


# --- Modèles -----------------------------------------------------------------------------------


class TemplatesPanel(Page):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        builtin = self.section("Modèles de livrées", "Graphismes originaux : calques organisés et éditables.")
        self.list = QListWidget()
        self.list.setMinimumHeight(200)
        for template in tpl.BUILTIN_TEMPLATES:
            item = QListWidgetItem(f"{tpl.CATEGORIES[template.key]} — {template.name.split('—')[-1].strip()}")
            item.setData(ID_ROLE, template.key)
            item.setToolTip(template.description)
            self.list.addItem(item)
        self.list.currentItemChanged.connect(lambda *_: self._show())
        builtin.add(self.list)
        self.description = builtin.add(label("", "faint", wrap=True))
        self.palette_row = QHBoxLayout()
        self.palette_row.setSpacing(4)
        builtin.body.addLayout(self.palette_row)
        self.unit = LSInput("Numéro d'unité (ex. 1-ADAM-12)")
        builtin.add(self.unit)
        builtin.row(
            button(
                "Appliquer",
                "layers",
                self.apply,
                "Ajoute les calques du modèle à la livrée active",
                "primary",
            ),
            button("Nouvelle livrée", "plus", self.new_variant, "Crée une livrée à partir du modèle"),
        )
        self.paint_info = builtin.add(label("", "faint", wrap=True))
        builtin.row(
            button(
                "Appliquer la peinture suggérée",
                "palette",
                self.apply_paint,
                "Couleur de peinture du matériau ciblé (distincte de la texture)",
            ),
            stretch=True,
        )
        personal = self.section(
            "Modèles personnels", "Fichiers portables : calques, pixels et logos intégrés."
        )
        self.user_list = QListWidget()
        self.user_list.setMaximumHeight(110)
        personal.add(self.user_list)
        personal.row(
            button("Enregistrer la livrée…", "save", self.save_template),
            button("Appliquer", "import", self.apply_user),
        )
        self.finish()
        self.list.setCurrentRow(0)

    def current(self) -> str | None:
        item = self.list.currentItem()
        return item.data(ID_ROLE) if item is not None else None

    def select(self, key: str) -> None:
        for row in range(self.list.count()):
            if self.list.item(row).data(ID_ROLE) == key:
                self.list.setCurrentRow(row)

    def _show(self) -> None:
        template = tpl.TEMPLATES_BY_KEY.get(self.current() or "")
        while self.palette_row.count():
            item = self.palette_row.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if template is None:
            return
        zones = ", ".join(bands.ZONES[z] for z in template.zones)
        self.description.setText(template.description + (f"\nZones : {zones}" if zones else ""))
        for color in template.palette:
            swatch = Swatch(color)
            swatch.set_color(color)
            swatch.clicked.connect(lambda c: self.page.colors.set_color(c, record=True))
            self.palette_row.addWidget(swatch)
        self.palette_row.addStretch(1)
        self.paint_info.setText(
            f"Peinture de carrosserie suggérée : {template.paint} (matériau, hors texture)."
        )

    def apply(self) -> list[str] | None:
        studio, key = self.page.studio, self.current()
        if studio is None or key is None:
            return None
        unit = self.unit.text().strip()
        return self.page.run("Modèle", lambda: studio.apply_template(key, unit=unit))

    def new_variant(self) -> str | None:
        studio, key = self.page.studio, self.current()
        if studio is None or key is None:
            return None
        unit = self.unit.text().strip()
        return self.page.run("Nouvelle livrée", lambda: studio.create_variant(tpl.CATEGORIES[key], key, unit))

    def apply_paint(self) -> None:
        template = tpl.TEMPLATES_BY_KEY.get(self.current() or "")
        if template is not None:
            self.page.apply_paint_color(template.paint)

    def refresh(self) -> None:
        clear_items(self.user_list)
        for path in tpl.list_user_templates():
            item = QListWidgetItem(path.stem)
            item.setData(ID_ROLE, str(path))
            self.user_list.addItem(item)

    def save_template(self, path: str | None = None) -> str | None:
        studio = self.page.studio
        if studio is None:
            return None
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Enregistrer comme modèle", str(tpl.user_templates_dir() / "modele.json"), "*.json"
            )
        if not path:
            return None
        saved = self.page.run("Modèle personnel", lambda: studio.save_template(path, Path(path).stem))
        self.refresh()
        return str(saved) if saved else None

    def apply_user(self) -> None:
        studio, item = self.page.studio, self.user_list.currentItem()
        if studio is not None and item is not None:
            self.page.run("Modèle personnel", lambda: studio.apply_user_template(item.data(ID_ROLE)))


# --- Calques ------------------------------------------------------------------------------------


class LayerTree(QTreeWidget):
    restructured = Signal()

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().dropEvent(event)
        self.restructured.emit()


class LayersPanel(QWidget):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        self._updating = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)
        self.variant_label = eyebrow("")
        layout.addWidget(self.variant_label)
        row = QHBoxLayout()
        self.blend = LSSelect([(v, k) for k, v in BLEND_MODES.items()])
        self.blend.activated.connect(
            lambda: self._set(blend=self.blend.currentData(), label="Mode de fusion")
        )
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.valueChanged.connect(self._opacity_preview)
        self.opacity.sliderReleased.connect(lambda: self.page.commit_edit("Opacité du calque"))
        self.opacity_label = label("100 %", "muted")
        row.addWidget(self.blend, 1)
        row.addWidget(self.opacity, 1)
        row.addWidget(self.opacity_label)
        layout.addLayout(row)
        self.tree = LayerTree()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.currentItemChanged.connect(lambda *_: self._current_changed())
        self.tree.restructured.connect(self._restructured)
        layout.addWidget(self.tree, 1)
        grid = QGridLayout()
        grid.setSpacing(4)
        actions = [
            ("Calque", "plus", lambda: page.add_layer("raster"), "Nouveau calque raster"),
            ("Groupe", "group", lambda: page.add_layer("group"), "Nouveau groupe"),
            ("Dupliquer", "copy-plus", page.duplicate_layer, "Dupliquer (Ctrl+J)"),
            ("", "trash-2", page.remove_layer, "Supprimer le calque (Suppr)"),
            ("Monter", None, lambda: page.move_layer(1), "Monter le calque"),
            ("Baisser", None, lambda: page.move_layer(-1), "Descendre le calque"),
            ("Grouper", "group", page.group_selected, "Grouper la sélection (Ctrl+G)"),
            ("Dégrouper", "ungroup", page.ungroup, "Dégrouper"),
            ("Fusionner", "layers", page.merge_down, "Fusionner vers le bas (Ctrl+E)"),
            ("Pixelliser", None, page.rasterize_layer, "Convertir en calque raster (action explicite)"),
            ("Masque", "lsf-mask", page.add_mask, "Ajouter un masque (blanc = visible)"),
            ("Inverser", None, page.invert_mask, "Inverser le masque"),
            ("Appliquer", None, page.apply_mask, "Appliquer le masque (définitif, annulable)"),
            ("Sans masque", "x", page.delete_mask, "Supprimer le masque"),
        ]
        for index, (text, icon_name, slot, tip) in enumerate(actions):
            widget = button(text, icon_name, slot, tip, "danger" if icon_name == "trash-2" else "secondary")
            grid.addWidget(widget, index // 3, index % 3)
        layout.addLayout(grid)
        self.shared = check(
            "Commun à toutes les livrées", False, "Élément partagé par les livrées (sous leurs calques)"
        )
        self.shared.clicked.connect(lambda checked: self.page.set_shared(checked))
        self.mask_paint = check(
            "Peindre le masque", False, "Le pinceau et la gomme agissent sur le masque du calque"
        )
        self.mask_paint.clicked.connect(
            lambda checked: self.page.tools.target.select_data("mask" if checked else "layer")
        )
        layout.addWidget(self.shared)
        layout.addWidget(self.mask_paint)

    def _set(self, label: str = "Calque", **fields) -> None:  # type: ignore[no-untyped-def]
        layer = self.page.current_layer()
        if layer is not None and self.page.studio is not None and not self._updating:
            self.page.run(label, lambda: self.page.studio.set_layer(layer.id, label, **fields))

    def _opacity_preview(self, value: int) -> None:
        self.opacity_label.setText(f"{value} %")
        if self._updating:
            return
        layer = self.page.current_layer()
        if layer is None or self.page.studio is None:
            return
        layer_id = layer.id

        def mutate(doc) -> None:  # type: ignore[no-untyped-def]
            found = doc.find(layer_id)
            if found is not None:
                found[0].opacity = value / 100

        self.page.studio.preview(mutate)
        self.page.texture_changed()
        if not self.opacity.isSliderDown():
            self.page.schedule_commit("Opacité du calque")

    def _item(self, layer, parent) -> QTreeWidgetItem:  # type: ignore[no-untyped-def]
        item = QTreeWidgetItem(parent)
        suffix = []
        if layer.locked:
            suffix.append("verrouillé")
        if layer.mask:
            suffix.append("masque" + ("" if layer.mask_enabled else " désactivé"))
        if layer.blend != "normal":
            suffix.append(BLEND_MODES[layer.blend].split(" ")[0])
        if layer.opacity < 1:
            suffix.append(f"{layer.opacity:.0%}")
        item.setText(0, layer.name + (f"  · {', '.join(suffix)}" if suffix else ""))
        item.setToolTip(0, f"{LAYER_KINDS[layer.kind]} — opacité {layer.opacity:.0%}")
        item.setData(0, ID_ROLE, layer.id)
        item.setCheckState(0, Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked)
        icon_name = {
            "raster": "lsf-brush",
            "vector": "shapes",
            "text": "lsf-text",
            "image": "image",
            "band": "lsf-band",
            "group": "folder",
        }[layer.kind]
        item.setIcon(0, icon(icon_name, tokens.ColorTokens.TEXT_SECONDARY))
        flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
        flags |= Qt.ItemFlag.ItemIsDragEnabled
        if layer.kind == "group":
            flags |= Qt.ItemFlag.ItemIsDropEnabled
        item.setFlags(flags)
        for child in reversed(layer.children):  # haut de pile en premier
            self._item(child, item)
        item.setExpanded(True)
        return item

    def refresh(self) -> None:
        studio = self.page.studio
        doc = studio.document() if studio is not None else None
        variant = doc.active_variant if doc else None
        current = self.page.current_layer_id
        self._updating = True
        self.tree.blockSignals(True)  # aucun signal pendant la reconstruction (éléments détruits)
        clear_items(self.tree)
        if variant is not None:
            self.variant_label.setText(f"LIVRÉE · {variant.name.upper()}")
            for layer in reversed(variant.layers):
                self._item(layer, self.tree)
            if variant.use_shared and doc.shared_layers:
                shared = QTreeWidgetItem(self.tree)
                shared.setText(0, "Éléments communs (toutes les livrées)")
                shared.setFlags(Qt.ItemFlag.ItemIsEnabled)
                shared.setForeground(0, secondary_brush())
                for layer in reversed(doc.shared_layers):
                    self._item(layer, shared)
                shared.setExpanded(True)
        else:
            self.variant_label.setText("AUCUN DOCUMENT")
        self._select(current)
        self.tree.blockSignals(False)
        self._updating = False
        self._current_changed()

    def _select(self, layer_id: str | None) -> None:
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if layer_id and item.data(0, ID_ROLE) == layer_id:
                self.tree.setCurrentItem(item)
                return
            iterator += 1

    def select_layer(self, layer_id: str) -> None:
        self.page.current_layer_id = layer_id
        self._select(layer_id)

    def selected_ids(self) -> list[str]:
        return [i.data(0, ID_ROLE) for i in self.tree.selectedItems() if i.data(0, ID_ROLE)]

    def _current_changed(self) -> None:
        item = self.tree.currentItem()
        layer_id = item.data(0, ID_ROLE) if item is not None else None
        if layer_id and not self._updating:
            self.page.current_layer_id = layer_id
        layer = self.page.current_layer()
        previous, self._updating = self._updating, True
        self.blend.setEnabled(layer is not None)
        self.opacity.setEnabled(layer is not None)
        if layer is not None:
            self.blend.select_data(layer.blend)
            self.opacity.setValue(int(round(layer.opacity * 100)))
            doc = self.page.studio.document()
            self.shared.setChecked(
                any(item.id == layer.id for top in doc.shared_layers for item in top.walk())
            )
        self._updating = previous
        if not self.page.refreshing and not previous:
            self.page.properties.refresh()
            self.page.canvas.update()

    def _item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._updating:
            return
        layer_id = item.data(0, ID_ROLE)
        if not layer_id or self.page.studio is None:
            return
        visible = item.checkState(0) == Qt.CheckState.Checked
        layer = (
            self.page.current_layer()
            if self.page.current_layer_id == layer_id
            else self.page.layer_by_id(layer_id)
        )
        if layer is not None and layer.visible != visible:
            self.page.run(
                "Visibilité", lambda: self.page.studio.set_layer(layer_id, "Visibilité", visible=visible)
            )

    def structure(self) -> list:
        """Arborescence (haut de pile en premier) : [(id, [enfants…]), …] pour la livrée active."""

        def walk(parent: QTreeWidgetItem) -> list:
            result = []
            for index in range(parent.childCount()):
                child = parent.child(index)
                layer_id = child.data(0, ID_ROLE)
                if layer_id:
                    result.append((layer_id, walk(child)))
            return result

        top = self.tree.invisibleRootItem()
        items = []
        for index in range(top.childCount()):
            child = top.child(index)
            if child.data(0, ID_ROLE):
                items.append((child.data(0, ID_ROLE), walk(child)))
        return items

    def _restructured(self) -> None:
        self.page.apply_structure(self.structure())


# --- Propriétés --------------------------------------------------------------------------------


class PropertiesPanel(Page):
    """Propriétés contextuelles du calque sélectionné (texte, logo, forme, bande, raster)."""

    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        self._updating = False
        self.title = eyebrow("")
        self.layout_.addWidget(self.title)
        common = self.section("Calque")
        self.name = LSInput("Nom du calque")
        self.name.editingFinished.connect(self._rename)
        common.add(self.name)
        self.locked = check("Verrouillé", False)
        self.locked.clicked.connect(lambda c: self._set_layer(locked=c))
        self.mask_enabled = check("Masque actif", True)
        self.mask_enabled.clicked.connect(lambda c: self._set_layer(mask_enabled=c))
        common.row(self.locked, self.mask_enabled, stretch=True)
        self.stack = QStackedWidget()
        self.layout_.addWidget(self.stack)
        self.pages: dict[str, int] = {}
        self._build_empty()
        self._build_text()
        self._build_image()
        self._build_vector()
        self._build_band()
        self._build_raster()
        self.finish()

    def _page(self, kind: str) -> QVBoxLayout:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.pages[kind] = self.stack.addWidget(widget)
        return layout

    def _build_empty(self) -> None:
        self._page("none").addWidget(label("Sélectionnez un calque.", "faint"))

    def _placement_controls(self, layout: QVBoxLayout, prefix: str) -> None:
        layout.addWidget(eyebrow("Placement sur la carrosserie"))
        grid = form()
        zone = LSSelect(
            [(bands.ZONES[k], k) for k in ("left", "right", "hood", "roof", "trunk", "front", "rear")]
        )
        lon = spin(0.1, -10, 10, 0.05, 2, " m")
        height = spin(0.66, 0, 5, 0.01, 2, " m")
        size = spin(0.15, 0.01, 3, 0.01, 2, " m")
        grid.addRow("Zone", zone)
        grid.addRow("Longitudinal", lon)
        grid.addRow("Hauteur", height)
        grid.addRow("Taille", size)
        layout.addLayout(grid)
        setattr(self, f"{prefix}_zone", zone)
        setattr(self, f"{prefix}_lon", lon)
        setattr(self, f"{prefix}_height", height)
        setattr(self, f"{prefix}_size", size)
        row = QHBoxLayout()
        row.addWidget(
            button(
                "Placer",
                "move",
                lambda: self.place(prefix),
                "Position, rotation et retournement d'après le dépliage",
            )
        )
        row.addWidget(button("Symétrie", "lsf-mirror", self.page.mirror_layer, "Copie sur l'autre flanc"))
        layout.addLayout(row)

    def _build_text(self) -> None:
        layout = self._page("text")
        layout.addWidget(eyebrow("Texte"))
        self.text = QPlainTextEdit()
        self.text.setMaximumHeight(70)
        self.text.textChanged.connect(lambda: self._edit("text", self.text.toPlainText(), "Texte"))
        layout.addWidget(self.text)
        grid = form()
        self.font = QFontComboBox()
        self.font.currentFontChanged.connect(lambda f: self._edit("font_family", f.family(), "Police"))
        self.size = spin(64, 1, 4000, 1, 1, " px")
        self.size.valueChanged.connect(lambda v: self._edit("size", v, "Taille du texte"))
        self.align = LSSelect([("Centré", "center"), ("Gauche", "left"), ("Droite", "right")])
        self.align.activated.connect(
            lambda: self._edit("align", self.align.currentData(), "Alignement", now=True)
        )
        self.letter = spin(0, -50, 200, 0.5, 1, " px")
        self.letter.valueChanged.connect(
            lambda v: self._edit("letter_spacing", v, "Espacement des caractères")
        )
        self.line = spin(1.0, 0.5, 4.0, 0.05, 2)
        self.line.valueChanged.connect(lambda v: self._edit("line_spacing", v, "Interligne"))
        self.text_rotation = spin(0, -360, 360, 1, 1, "°")
        self.text_rotation.valueChanged.connect(lambda v: self._edit("rotation", v, "Rotation"))
        self.outline = spin(0, 0, 100, 0.5, 1, " px")
        self.outline.valueChanged.connect(lambda v: self._edit("outline_width", v, "Contour"))
        for text, widget in (
            ("Police", self.font),
            ("Taille", self.size),
            ("Alignement", self.align),
            ("Espacement", self.letter),
            ("Interligne", self.line),
            ("Rotation", self.text_rotation),
            ("Contour", self.outline),
        ):
            grid.addRow(text, widget)
        layout.addLayout(grid)
        row = QHBoxLayout()
        self.bold = check("Gras")
        self.bold.clicked.connect(lambda c: self._edit("bold", c, "Gras", now=True))
        self.italic = check("Italique")
        self.italic.clicked.connect(lambda c: self._edit("italic", c, "Italique", now=True))
        self.flip_h = check("Inversé")
        self.flip_h.clicked.connect(lambda c: self._edit("flip_h", c, "Inversion", now=True))
        for widget in (self.bold, self.italic, self.flip_h):
            row.addWidget(widget)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(
            button(
                "Couleur", "palette", lambda: self._color("color", "Couleur du texte"), "Couleur principale"
            )
        )
        row.addWidget(
            button(
                "Contour",
                "palette",
                lambda: self._color("outline_color", "Couleur du contour"),
                "Couleur principale",
            )
        )
        layout.addLayout(row)
        layout.addWidget(eyebrow("Ombre"))
        self.shadow = check("Ombre portée")
        self.shadow.clicked.connect(lambda c: self._shadow(enabled=c))
        layout.addWidget(self.shadow)
        grid = form()
        self.shadow_dx = spin(6, -200, 200, 1, 0, " px")
        self.shadow_dy = spin(6, -200, 200, 1, 0, " px")
        self.shadow_blur = int_spin(4, 0, 64, " px")
        self.shadow_opacity = int_spin(60, 0, 100, " %")
        for text, widget, key in (
            ("Décalage X", self.shadow_dx, "dx"),
            ("Décalage Y", self.shadow_dy, "dy"),
            ("Flou", self.shadow_blur, "blur"),
            ("Opacité", self.shadow_opacity, "opacity"),
        ):
            grid.addRow(text, widget)
            widget.valueChanged.connect(
                lambda v, k=key: self._shadow(**{k: v / 100 if k == "opacity" else v})
            )
        layout.addLayout(grid)
        layout.addWidget(
            button("Couleur de l'ombre", "palette", lambda: self._shadow(color=self.page.colors.color()))
        )
        self._placement_controls(layout, "text_place")

    def _build_image(self) -> None:
        layout = self._page("image")
        layout.addWidget(eyebrow("Logo / image"))
        self.provenance = label("", "faint", wrap=True)
        layout.addWidget(self.provenance)
        grid = form()
        self.img_width = spin(256, 1, 8192, 1, 0, " px")
        self.img_width.valueChanged.connect(lambda v: self._size("width", v))
        self.img_height = spin(256, 1, 8192, 1, 0, " px")
        self.img_height.valueChanged.connect(lambda v: self._size("height", v))
        self.img_rotation = spin(0, -360, 360, 1, 1, "°")
        self.img_rotation.valueChanged.connect(lambda v: self._edit("rotation", v, "Rotation"))
        grid.addRow("Largeur", self.img_width)
        grid.addRow("Hauteur", self.img_height)
        grid.addRow("Rotation", self.img_rotation)
        layout.addLayout(grid)
        row = QHBoxLayout()
        self.keep_ratio = check("Proportions", True)
        self.keep_ratio.clicked.connect(lambda c: self._edit("keep_ratio", c, "Proportions", now=True))
        self.img_flip_h = check("Miroir H")
        self.img_flip_h.clicked.connect(lambda c: self._edit("flip_h", c, "Miroir", now=True))
        self.img_flip_v = check("Miroir V")
        self.img_flip_v.clicked.connect(lambda c: self._edit("flip_v", c, "Miroir", now=True))
        for widget in (self.keep_ratio, self.img_flip_h, self.img_flip_v):
            row.addWidget(widget)
        layout.addLayout(row)
        self.tint = check("Recolorer", False, "Remplace la couleur en conservant la transparence")
        self.tint.clicked.connect(lambda c: self._edit("tint_enabled", c, "Recoloration", now=True))
        layout.addWidget(self.tint)
        layout.addWidget(
            button("Couleur de recoloration", "palette", lambda: self._color("tint", "Recoloration"))
        )
        self._placement_controls(layout, "image_place")

    def _build_vector(self) -> None:
        layout = self._page("vector")
        layout.addWidget(eyebrow("Forme vectorielle"))
        grid = form()
        self.stroke_width = spin(0, 0, 500, 0.5, 1, " px")
        self.stroke_width.valueChanged.connect(
            lambda v: self._edit("stroke_width", v, "Épaisseur du contour")
        )
        self.vec_radius = spin(16, 0, 2000, 1, 0, " px")
        self.vec_radius.valueChanged.connect(lambda v: self._edit("radius", v, "Arrondi"))
        self.vec_rotation = spin(0, -360, 360, 1, 1, "°")
        self.vec_rotation.valueChanged.connect(lambda v: self._edit("rotation", v, "Rotation"))
        grid.addRow("Contour", self.stroke_width)
        grid.addRow("Arrondi", self.vec_radius)
        grid.addRow("Rotation", self.vec_rotation)
        layout.addLayout(grid)
        grid = QGridLayout()
        grid.setSpacing(4)
        grid.addWidget(
            button(
                "Remplissage", "palette", lambda: self._fill(self.page.colors.color()), "Couleur principale"
            ),
            0,
            0,
        )
        grid.addWidget(button("Sans remplissage", "x", lambda: self._fill(None)), 0, 1)
        grid.addWidget(
            button("Contour", "palette", lambda: self._color("stroke", "Couleur du contour")), 1, 0
        )
        grid.addWidget(
            button("Dégradé", "lsf-gradient", self._gradient_fill, "Principale → secondaire, sur la largeur"),
            1,
            1,
        )
        layout.addLayout(grid)

    def _build_band(self) -> None:
        layout = self._page("band")
        layout.addWidget(eyebrow("Bande 3D"))
        grid = form()
        self.band_zone = LSSelect([(v, k) for k, v in bands.ZONES.items()])
        self.band_zone.activated.connect(
            lambda: self._edit("zone", self.band_zone.currentData(), "Zone", now=True)
        )
        self.band_orientation = LSSelect([(v, k) for k, v in bands.ORIENTATIONS.items()])
        self.band_orientation.activated.connect(
            lambda: self._edit("orientation", self.band_orientation.currentData(), "Orientation", now=True)
        )
        self.band_pattern = LSSelect([(v, k) for k, v in bands.PATTERNS.items()])
        self.band_pattern.activated.connect(
            lambda: self._edit("pattern", self.band_pattern.currentData(), "Motif", now=True)
        )
        self.band_side = LSSelect([("Deux côtés", "both"), ("Gauche", "left"), ("Droite", "right")])
        self.band_side.activated.connect(
            lambda: self._edit("side", self.band_side.currentData(), "Côtés", now=True)
        )
        self.band_width = spin(0.12, 0.005, 5, 0.01, 3, " m")
        self.band_height = spin(0.55, -1, 5, 0.01, 2, " m")
        self.band_lon = spin(0, -10, 10, 0.05, 2, " m")
        self.band_lateral = spin(0, -3, 3, 0.01, 2, " m")
        self.band_angle = spin(30, -89, 89, 1, 0, "°")
        self.band_period = spin(0.3, 0.01, 5, 0.01, 2, " m")
        for widget, key in (
            (self.band_width, "width"),
            (self.band_height, "center_height"),
            (self.band_lon, "center_lon"),
            (self.band_lateral, "lateral_offset"),
            (self.band_angle, "angle"),
            (self.band_period, "period"),
        ):
            widget.valueChanged.connect(lambda v, k=key: self._edit(k, v, "Bande 3D"))
        for text, widget in (
            ("Zone", self.band_zone),
            ("Orientation", self.band_orientation),
            ("Motif", self.band_pattern),
            ("Côtés", self.band_side),
            ("Largeur", self.band_width),
            ("Hauteur", self.band_height),
            ("Longitudinal", self.band_lon),
            ("Latéral", self.band_lateral),
            ("Angle", self.band_angle),
            ("Période", self.band_period),
        ):
            grid.addRow(text, widget)
        layout.addLayout(grid)
        row = QHBoxLayout()
        row.addWidget(button("Couleur 1", "palette", lambda: self._color("color", "Couleur")))
        row.addWidget(
            button(
                "Couleur 2",
                "palette",
                lambda: self._color("color2", "Couleur", secondary=True),
                "Couleur secondaire",
            )
        )
        layout.addLayout(row)
        layout.addWidget(
            label(
                "Motif « réfléchissant » : rendu visuel seulement, aucune rétroréflexion en jeu.",
                "faint",
                wrap=True,
            )
        )

    def _build_raster(self) -> None:
        layout = self._page("raster")
        layout.addWidget(eyebrow("Calque raster"))
        self.raster_info = label("", "faint", wrap=True)
        layout.addWidget(self.raster_info)
        layout.addWidget(
            label(
                "Peignez avec le pinceau (2D ou directement en 3D), la gomme, le remplissage ou le dégradé.",
                "faint",
                wrap=True,
            )
        )

    # --- Rafraîchissement -------------------------------------------------------------------
    def refresh(self) -> None:
        layer = self.page.current_layer()
        self._updating = True
        try:
            if layer is None:
                self.title.setText("PROPRIÉTÉS")
                self.stack.setCurrentIndex(self.pages["none"])
                return
            self.title.setText(LAYER_KINDS[layer.kind].upper())
            self.name.setText(layer.name)
            self.locked.setChecked(layer.locked)
            self.mask_enabled.setEnabled(bool(layer.mask))
            self.mask_enabled.setChecked(layer.mask_enabled)
            self.stack.setCurrentIndex(self.pages.get(layer.kind, self.pages["none"]))
            getattr(self, f"_refresh_{layer.kind}", lambda _l: None)(layer)
        finally:
            self._updating = False

    def _refresh_text(self, layer) -> None:  # type: ignore[no-untyped-def]
        p = layer.params
        if self.text.toPlainText() != p.get("text", ""):
            self.text.setPlainText(p.get("text", ""))
        self.font.setCurrentFont(QFont(p.get("font_family") or render2d.default_family()))
        self.size.setValue(float(p.get("size", 64)))
        self.align.select_data(p.get("align", "center"))
        self.letter.setValue(float(p.get("letter_spacing", 0)))
        self.line.setValue(float(p.get("line_spacing", 1.0)))
        self.text_rotation.setValue(float(p.get("rotation", 0)))
        self.outline.setValue(float(p.get("outline_width", 0)))
        self.bold.setChecked(bool(p.get("bold")))
        self.italic.setChecked(bool(p.get("italic")))
        self.flip_h.setChecked(bool(p.get("flip_h")))
        shadow = p.get("shadow") or {}
        self.shadow.setChecked(bool(shadow.get("enabled")))
        self.shadow_dx.setValue(float(shadow.get("dx", 6)))
        self.shadow_dy.setValue(float(shadow.get("dy", 6)))
        self.shadow_blur.setValue(int(shadow.get("blur", 4)))
        self.shadow_opacity.setValue(int(float(shadow.get("opacity", 0.6)) * 100))

    def _refresh_image(self, layer) -> None:  # type: ignore[no-untyped-def]
        p = layer.params
        self.img_width.setValue(float(p.get("width", 256)))
        self.img_height.setValue(float(p.get("height", 256)))
        self.img_rotation.setValue(float(p.get("rotation", 0)))
        self.keep_ratio.setChecked(bool(p.get("keep_ratio", True)))
        self.img_flip_h.setChecked(bool(p.get("flip_h")))
        self.img_flip_v.setChecked(bool(p.get("flip_v")))
        self.tint.setChecked(bool(p.get("tint_enabled")))
        doc = self.page.studio.document()
        entry = next((e for e in doc.provenance if e.get("blob") == p.get("blob")), None)
        if entry:
            self.provenance.setText(
                f"{entry.get('name')} — auteur : {entry.get('author') or '—'}\n"
                f"Licence : {entry.get('license') or 'non renseignée'}"
            )
        else:
            self.provenance.setText("Image collée ou importée.")

    def _refresh_vector(self, layer) -> None:  # type: ignore[no-untyped-def]
        p = layer.params
        self.stroke_width.setValue(float(p.get("stroke_width", 0)))
        self.vec_radius.setValue(float(p.get("radius", 16)))
        self.vec_rotation.setValue(float(p.get("rotation", 0)))

    def _refresh_band(self, layer) -> None:  # type: ignore[no-untyped-def]
        p = layer.params
        self.band_zone.select_data(p.get("zone", "sides"))
        self.band_orientation.select_data(p.get("orientation", "longitudinal"))
        self.band_pattern.select_data(p.get("pattern", "solid"))
        self.band_side.select_data(p.get("side", "both"))
        self.band_width.setValue(float(p.get("width", 0.12)))
        self.band_height.setValue(float(p.get("center_height", 0.55)))
        self.band_lon.setValue(float(p.get("center_lon", 0.0)))
        self.band_lateral.setValue(float(p.get("lateral_offset", 0.0)))
        self.band_angle.setValue(float(p.get("angle", 30)))
        self.band_period.setValue(float(p.get("period", 0.3)))

    def _refresh_raster(self, layer) -> None:  # type: ignore[no-untyped-def]
        doc = self.page.studio.document()
        self.raster_info.setText(f"{doc.width} × {doc.height} px" + (" · masque" if layer.mask else ""))

    # --- Édition --------------------------------------------------------------------------------
    def _edit(self, key: str, value, label_text: str, now: bool = False) -> None:  # type: ignore[no-untyped-def]
        if not self._updating:
            self.page.edit_param(key, value, label_text, now)

    def _color(self, key: str, label_text: str, secondary: bool = False) -> None:
        color = self.page.colors.secondary() if secondary else self.page.colors.color()
        self._edit(key, color, label_text, now=True)

    def _shadow(self, **changes) -> None:  # type: ignore[no-untyped-def]
        layer = self.page.current_layer()
        if self._updating or layer is None:
            return
        default = {
            "enabled": False,
            "dx": 6,
            "dy": 6,
            "blur": 4,
            "opacity": 0.6,
            "color": self.page.colors.secondary(),
        }
        shadow = dict(layer.params.get("shadow") or default)
        shadow.update(changes)
        self.page.edit_param("shadow", shadow, "Ombre", now="enabled" in changes or "color" in changes)

    def _size(self, key: str, value: float) -> None:
        layer = self.page.current_layer()
        if self._updating or layer is None:
            return
        p = layer.params
        if p.get("keep_ratio", True):
            ratio = float(p.get("height", 1)) / max(float(p.get("width", 1)), 1e-6)
            width = value if key == "width" else value / max(ratio, 1e-6)
            self.page.edit_params({"width": width, "height": width * ratio}, "Taille du logo")
            self._updating = True
            if key == "width":
                self.img_height.setValue(width * ratio)
            else:
                self.img_width.setValue(width)
            self._updating = False
        else:
            self.page.edit_param(key, value, "Taille du logo")

    def _fill(self, color: str | None) -> None:
        if not self._updating:
            self.page.edit_params({"fill": color, "gradient": None}, "Remplissage", now=True)

    def _gradient_fill(self) -> None:
        layer = self.page.current_layer()
        if layer is None or layer.kind != "vector":
            return
        bounds = render2d.element_bounds(layer)
        gradient = {
            "kind": "linear",
            "c0": self.page.colors.color(),
            "c1": self.page.colors.secondary(),
            "p0": [bounds.left(), bounds.center().y()],
            "p1": [bounds.right(), bounds.center().y()],
        }
        self.page.edit_params({"gradient": gradient}, "Dégradé", now=True)

    def _rename(self) -> None:
        layer = self.page.current_layer()
        name = self.name.text().strip()
        if layer is not None and name and name != layer.name:
            self.page.run("Renommage", lambda: self.page.studio.set_layer(layer.id, "Renommage", name=name))

    def _set_layer(self, **fields) -> None:  # type: ignore[no-untyped-def]
        layer = self.page.current_layer()
        if layer is not None and not self._updating:
            self.page.run(
                "Calque", lambda: self.page.studio.set_layer(layer.id, "Propriétés du calque", **fields)
            )

    def place(self, prefix: str) -> None:
        layer = self.page.current_layer()
        if layer is None:
            return
        zone = getattr(self, f"{prefix}_zone").currentData()
        side = "right" if zone == "right" else "left"
        lon = getattr(self, f"{prefix}_lon").value()
        height = getattr(self, f"{prefix}_height").value()
        size = getattr(self, f"{prefix}_size").value()
        self.page.run(
            "Placement", lambda: self.page.studio.place_on_zone(layer.id, zone, lon, height, side, size)
        )


# --- Matériaux ---------------------------------------------------------------------------------


class MaterialsPanel(Page):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        targets = self.section(
            "Matériaux ciblés", "Maillages recevant la texture de livrée (même dépliage UV)."
        )
        self.targets = QListWidget()
        self.targets.setMaximumHeight(130)
        targets.add(self.targets)
        targets.row(button("Appliquer les cibles", "check", self.apply_targets), stretch=True)
        texture = self.section("Texture de livrée")
        grid = form()
        self.mode = LSSelect([(v, k) for k, v in MODES.items()])
        self.mode.activated.connect(lambda: self._set_doc(mode=self.mode.currentData()))
        self.blend_space = LSSelect([(v, k) for k, v in BLEND_SPACES.items()])
        self.blend_space.activated.connect(lambda: self._set_doc(blend_space=self.blend_space.currentData()))
        self.texture_name = LSInput("Nom de la texture exportée")
        self.texture_name.editingFinished.connect(
            lambda: self._set_doc(texture_name=self.texture_name.text().strip() or None)
        )
        grid.addRow("Mode", self.mode)
        grid.addRow("Fusion", self.blend_space)
        grid.addRow("Nom", self.texture_name)
        texture.body.addLayout(grid)
        self.resolution = LSSelect([(f"{s} × {s}", s) for s in STANDARD_SIZES] + [("Personnalisée", 0)])
        self.custom_w = int_spin(2048, 16, 8192, " px")
        self.custom_h = int_spin(2048, 16, 8192, " px")
        texture.row(label("Résolution", "muted"), self.resolution)
        texture.row(
            self.custom_w,
            self.custom_h,
            button("Changer", "scale-3d", self.apply_resolution, "Rééchantillonne les calques"),
        )
        self.base_info = texture.add(label("", "faint", wrap=True))
        self.base_visible = check("Afficher la texture d'origine sous les calques", True)
        self.base_visible.clicked.connect(
            lambda c: self.page.run("Livrée", lambda: self.page.studio.set_variant(base_visible=c))
        )
        texture.add(self.base_visible)
        paint = self.section(
            "Peinture de carrosserie",
            "Couleur du matériau (vernis) : distincte des couleurs intégrées à la texture de livrée.",
        )
        self.paint_swatch = Swatch("", 30)
        paint.row(
            self.paint_swatch,
            button("Utiliser la couleur principale", "palette", self.apply_paint),
            stretch=True,
        )
        self.finish()

    def refresh(self) -> None:
        studio = self.page.studio
        doc = studio.document() if studio is not None else None
        clear_items(self.targets)
        if studio is None:
            return
        for candidate in studio.candidate_materials():
            uv = "UV" if candidate["with_uv"] else "sans UV"
            texture = " · texture" if candidate["texture"] else ""
            item = QListWidgetItem(f"{candidate['name']} — {candidate['meshes']} maillage(s), {uv}{texture}")
            item.setData(ID_ROLE, candidate["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = doc is not None and candidate["id"] in doc.targets
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.targets.addItem(item)
        if doc is None:
            return
        self.mode.select_data(doc.mode)
        self.blend_space.select_data(doc.blend_space)
        self.texture_name.setText(doc.texture_name)
        square = doc.width == doc.height and doc.width in STANDARD_SIZES
        self.resolution.setCurrentIndex(max(self.resolution.findData(doc.width if square else 0), 0))
        self.custom_w.setValue(doc.width)
        self.custom_h.setValue(doc.height)
        base = doc.base_texture or "aucune (fond blanc en mode texture, transparent en mode livrée)"
        self.base_info.setText(f"Texture d'origine : {base} — jamais modifiée.")
        variant = doc.active_variant
        self.base_visible.setChecked(variant.base_visible if variant else True)
        material = studio.scene.materials.get(doc.targets[0]) if doc.targets else None
        if material is not None:
            r, g, b, _a = (c * 255 for c in material.base_color)
            self.paint_swatch.set_color(to_hex(r, g, b))

    def checked_targets(self) -> list[str]:
        return [
            self.targets.item(i).data(ID_ROLE)
            for i in range(self.targets.count())
            if self.targets.item(i).checkState() == Qt.CheckState.Checked
        ]

    def apply_targets(self) -> None:
        targets = self.checked_targets()
        if not targets:
            self.page.controller.notify.emit("Matériaux", "Cochez au moins un matériau.", "info")
            return
        self._set_doc(targets=targets)

    def _set_doc(self, **fields) -> None:  # type: ignore[no-untyped-def]
        if self.page.studio is not None and self.page.studio.document() is not None:
            self.page.run("Document de livrée", lambda: self.page.studio.set_document(**fields))

    def apply_resolution(self) -> None:
        size = self.resolution.currentData()
        width, height = (size, size) if size else (self.custom_w.value(), self.custom_h.value())
        self.page.run("Résolution", lambda: self.page.studio.resize_document(width, height))

    def apply_paint(self) -> None:
        self.page.apply_paint_color(self.page.colors.color())


# --- Livrées (variantes) ----------------------------------------------------------------------


class VariantsPanel(Page):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        manage = self.section(
            "Livrées du véhicule", "Chaque livrée a ses calques ; les éléments communs sont partagés."
        )
        self.list = QListWidget()
        self.list.setMinimumHeight(140)
        self.list.itemClicked.connect(self._activate)
        manage.add(self.list)
        self.name = LSInput("Nom (ex. LSPD Patrol)")
        manage.add(self.name)
        self.template = LSSelect(
            [("Vierge", "")] + [(tpl.CATEGORIES[t.key], t.key) for t in tpl.BUILTIN_TEMPLATES]
        )
        self.unit = LSInput("Numéro d'unité")
        manage.row(self.template, self.unit)
        manage.row(
            button("Nouvelle", "plus", self.create, variant="primary"),
            button("Dupliquer", "copy-plus", self.duplicate),
            button("Renommer", "pencil", self.rename),
            button("", "trash-2", self.delete, "Supprimer la livrée", "danger"),
        )
        options = self.section("Livrée active")
        self.use_shared = check("Utiliser les éléments communs", True)
        self.use_shared.clicked.connect(
            lambda c: self.page.run("Livrée", lambda: self.page.studio.set_variant(use_shared=c))
        )
        options.add(self.use_shared)
        self.unit_active = LSInput("Numéro d'unité de la livrée active")
        self.unit_active.editingFinished.connect(self._set_unit)
        options.add(self.unit_active)
        emergency = self.section(
            "Emergency Studio", "Association à une variante d'urgence : équipements et matériaux préservés."
        )
        self.emergency = LSSelect()
        emergency.add(self.emergency)
        emergency.row(
            button("Associer", "siren", self.link), button("Dissocier", "x", lambda: self.link(None))
        )
        self.emergency_info = emergency.add(label("", "faint", wrap=True))
        compare = self.section("Comparer")
        self.compare_with = LSSelect()
        compare.row(self.compare_with, button("Comparer", "scan", self.compare))
        row = QHBoxLayout()
        self.preview_a, self.preview_b = QLabel(), QLabel()
        for widget in (self.preview_a, self.preview_b):
            widget.setFixedSize(120, 120)
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(widget)
        row.addStretch(1)
        compare.body.addLayout(row)
        self.comparison = compare.add(label("", "faint", wrap=True))
        self.finish()

    def _activate(self, item: QListWidgetItem) -> None:
        variant_id = item.data(ID_ROLE)
        self.page.run("Livrée", lambda: self.page.studio.activate_variant(variant_id))

    def refresh(self) -> None:
        studio = self.page.studio
        doc = studio.document() if studio is not None else None
        clear_items(self.list)
        self.compare_with.clear()
        self.emergency.clear()
        if doc is None:
            return
        for variant in doc.variants:
            linked = " · urgence" if variant.emergency_variant else ""
            item = QListWidgetItem(("● " if variant.id == doc.active else "○ ") + variant.name + linked)
            item.setData(ID_ROLE, variant.id)
            self.list.addItem(item)
            if variant.id != doc.active:
                self.compare_with.addItem(variant.name, variant.id)
        active = doc.active_variant
        if active is not None:
            self.use_shared.setChecked(active.use_shared)
            self.unit_active.setText(active.metadata.get("unit", ""))
        self.emergency.addItem("Aucune", "")
        emergency = studio.emergency_variants()
        for item in emergency:
            self.emergency.addItem(f"{item['name']} ({item['service']})", item["id"])
        if active is not None and active.emergency_variant:
            self.emergency.select_data(active.emergency_variant)
            name = next((e["name"] for e in emergency if e["id"] == active.emergency_variant), "?")
            self.emergency_info.setText(
                f"Associée à « {name} » : sélectionner cette variante dans Emergency Studio active la livrée."
            )
        else:
            self.emergency_info.setText("Aucune association.")

    def _active(self) -> str | None:
        doc = self.page.studio.document() if self.page.studio else None
        return doc.active if doc else None

    def create(self) -> str | None:
        studio = self.page.studio
        if studio is None:
            return None
        template = self.template.currentData() or None
        name = self.name.text().strip() or (self.template.currentText() if template else "Livrée")
        unit = self.unit.text().strip()
        return self.page.run("Nouvelle livrée", lambda: studio.create_variant(name, template, unit))

    def duplicate(self) -> str | None:
        active = self._active()
        if active is None:
            return None
        name = self.name.text().strip() or None
        return self.page.run("Livrée", lambda: self.page.studio.duplicate_variant(active, name))

    def rename(self) -> None:
        active, name = self._active(), self.name.text().strip()
        if active and name:
            self.page.run("Livrée", lambda: self.page.studio.rename_variant(active, name))

    def delete(self) -> None:
        active = self._active()
        if active:
            self.page.run("Livrée", lambda: self.page.studio.delete_variant(active))

    def _set_unit(self) -> None:
        if self._active():
            unit = self.unit_active.text().strip()
            self.page.run("Livrée", lambda: self.page.studio.set_variant(metadata={"unit": unit}))

    def link(self, emergency_id: str | None = "") -> None:
        active = self._active()
        if active is None:
            return
        target = self.emergency.currentData() if emergency_id == "" else emergency_id
        self.page.run("Association", lambda: self.page.studio.link_emergency(active, target or None))

    def compare(self) -> dict | None:
        active, other = self._active(), self.compare_with.currentData()
        if not active or not other:
            return None
        result = self.page.run("Comparaison", lambda: self.page.studio.compare_variants(active, other, 120))
        if result is None:
            return None
        self.preview_a.setPixmap(thumbnail(result["preview_a"], 120))
        self.preview_b.setPixmap(thumbnail(result["preview_b"], 120))
        a, b = result["layers"]
        text = f"{result['changed_ratio']:.1%} des pixels diffèrent · calques {a} / {b}"
        if result["only_a"]:
            text += "\nPropres à la livrée active : " + ", ".join(result["only_a"][:6])
        if result["only_b"]:
            text += "\nPropres à l'autre : " + ", ".join(result["only_b"][:6])
        self.comparison.setText(text)
        return result


# --- Export -------------------------------------------------------------------------------------


class ExportPanel(Page):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        options = self.section(
            "Export des textures", "Le fichier exporté est la texture visible dans le viewport."
        )
        grid = form()
        self.format = LSSelect([(v[0], k) for k, v in export.FORMATS.items()])
        sizes = (
            [("Taille du document", 0)]
            + [(f"{s} × {s}", s) for s in STANDARD_SIZES]
            + [("Personnalisée", -1)]
        )
        self.size = LSSelect(sizes)
        self.custom = int_spin(2048, 16, 8192, " px")
        self.padding = int_spin(8, 0, 64, " px")
        self.scope = LSSelect([("Livrée active", "active"), ("Toutes les livrées", "all")])
        grid.addRow("Format", self.format)
        grid.addRow("Résolution", self.size)
        grid.addRow("Personnalisée", self.custom)
        grid.addRow("Débordement des îlots", self.padding)
        grid.addRow("Livrées", self.scope)
        options.body.addLayout(grid)
        self.alpha = check("Transparence", True)
        self.mipmaps = check("Mipmaps (DDS)", True)
        options.row(self.alpha, self.mipmaps, stretch=True)
        options.row(
            button("Exporter…", "download", self.export_dialog, variant="primary"),
            button(
                "Préparer YTD…",
                "package",
                self.ytd_dialog,
                "Dossier DDS + manifeste pour un outil de conversion",
            ),
        )
        options.add(
            label(
                "Aucun fichier .ytd n'est écrit : le dictionnaire se crée avec CodeWalker, OpenIV "
                "ou Sollumz.",
                "faint",
                wrap=True,
            )
        )
        report = self.section("Aperçu et rapport")
        self.preview = QLabel()
        self.preview.setFixedSize(160, 160)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        report.add(self.preview)
        self.report = QListWidget()
        self.report.setMinimumHeight(110)
        report.add(self.report)
        self.finish()

    def options(self) -> export.ExportOptions:
        size = self.size.currentData()
        if size == -1:
            size = self.custom.value()
        return export.ExportOptions(
            fmt=self.format.currentData(),
            width=size or None,
            height=size or None,
            alpha=self.alpha.isChecked(),
            mipmaps=self.mipmaps.isChecked(),
            padding=self.padding.value(),
        )

    def refresh(self) -> None:
        studio = self.page.studio
        if studio is not None and studio.compositor.result is not None and self.isVisible():
            self.preview.setPixmap(thumbnail(studio.compositor.result, 160))

    def export_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Dossier d'export")
        if folder:
            self.page.export_async(folder, self.options(), self.scope.currentData())

    def ytd_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Dossier de préparation YTD")
        if folder:
            self.page.export_async(folder, self.options(), "ytd")

    def show_reports(self, reports: list) -> None:
        clear_items(self.report)
        for report in reports:
            self.report.addItem(("✔ " if report.verified else "⚠ ") + report.summary())
            for warning in report.warnings:
                self.report.addItem("   ⚠ " + warning)
            for note in report.notes:
                self.report.addItem("   ℹ " + note)


# --- Progression, diagnostics, UV ---------------------------------------------------------------


class ProgressPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        self.title = label("Aucune tâche en cours.", "muted")
        self.bar = LSProgress()
        self.cancel_button = button("Annuler", "x", self.cancel)
        self.cancel_button.setEnabled(False)
        self.on_cancel = None
        for widget in (self.title, self.bar, self.cancel_button):
            layout.addWidget(widget)
        layout.addStretch(1)

    def start(self, title: str, on_cancel=None) -> None:  # type: ignore[no-untyped-def]
        self.title.setText(title)
        self.bar.reset("Démarrage…")
        self.on_cancel = on_cancel
        self.cancel_button.setEnabled(on_cancel is not None)

    def update_progress(self, value: float, text: str) -> None:
        self.bar.set_progress(value, text)

    def finish(self, message: str) -> None:
        self.bar.set_progress(1.0, message)
        self.cancel_button.setEnabled(False)
        self.on_cancel = None

    def cancel(self) -> None:
        if self.on_cancel is not None:
            self.on_cancel()


class DiagnosticsPanel(QWidget):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        row = QHBoxLayout()
        self.summary = label("", "muted")
        row.addWidget(self.summary, 1)
        row.addWidget(button("Analyser", "refresh-cw", self.refresh))
        layout.addLayout(row)
        self.list = QListWidget()
        layout.addWidget(self.list, 1)

    def refresh(self) -> list[tuple[str, str]]:
        clear_items(self.list)
        studio = self.page.studio
        if studio is None:
            return []
        items = self.page.run("Diagnostics", studio.diagnostics) or []
        icons = {"info": "info", "warning": "triangle-alert", "error": "circle-x"}
        colors = {
            "info": tokens.ColorTokens.TEXT_SECONDARY,
            "warning": tokens.ColorTokens.WARNING,
            "error": tokens.ColorTokens.ERROR,
        }
        for level, text in items:
            self.list.addItem(
                QListWidgetItem(icon(icons.get(level, "info"), colors.get(level, colors["info"])), text)
            )
        warnings = sum(1 for level, _t in items if level != "info")
        self.summary.setText(f"{warnings} avertissement(s)")
        return items


class UVPanel(QWidget):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        left = QVBoxLayout()
        self.report = label("", "muted", wrap=True)
        left.addWidget(self.report)
        self.warnings = QListWidget()
        left.addWidget(self.warnings, 1)
        layout.addLayout(left, 2)
        right = QVBoxLayout()
        self.show_uv = check("Afficher les UV", True)
        self.show_uv.clicked.connect(lambda c: self._canvas("show_uv", c))
        self.show_seams = check("Coutures", False)
        self.show_seams.clicked.connect(lambda c: self._canvas("show_seams", c))
        self.show_grid = check("Grille", False)
        self.show_grid.clicked.connect(lambda c: self._canvas("show_grid", c))
        self.show_rulers = check("Règles", True)
        self.show_rulers.clicked.connect(lambda c: self._canvas("show_rulers", c))
        for widget in (self.show_uv, self.show_seams, self.show_grid, self.show_rulers):
            right.addWidget(widget)
        self.project_button = button(
            "Projection UV (boîte)…",
            "cuboid",
            lambda: self.page.project_uvs(True),
            "Maillages sans UV : projection automatique, après confirmation",
        )
        right.addWidget(self.project_button)
        from lsfcars.editor.blender_ops import unwrap_available

        available, reason = unwrap_available()
        self.unwrap_button = button(
            "Dépliage Blender…", "sparkles", lambda: self.page.unwrap_with_blender(True), reason
        )
        self.unwrap_button.setEnabled(available)
        right.addWidget(self.unwrap_button)
        right.addWidget(button("Effacer les guides", "x", self.clear_guides))
        right.addStretch(1)
        layout.addLayout(right, 1)

    def _canvas(self, attribute: str, value: bool) -> None:
        setattr(self.page.canvas, attribute, value)
        self.page.canvas.update()

    def clear_guides(self) -> None:
        self.page.canvas.guides.clear()
        self.page.canvas.update()

    def refresh(self) -> None:
        clear_items(self.warnings)
        studio = self.page.studio
        if studio is None or studio.document() is None:
            missing = studio.nodes_without_uv() if studio is not None else []
            suffix = f" {len(missing)} maillage(s) sans UV." if missing else ""
            self.report.setText("Aucun document de livrée." + suffix)
            self.project_button.setEnabled(bool(missing))
            return
        report = self.page.run("UV", studio.uv_report)
        if report is None:
            return
        self.report.setText(
            f"{report.triangles} triangles · {report.islands} îlots · "
            f"{report.seam_edges} arêtes de couture · "
            f"{report.coverage_ratio:.0%} de la texture utilisée · {report.texel_density:.0f} px/m"
        )
        for text in report.warnings() or ["Aucun problème détecté."]:
            self.warnings.addItem(text)
        self.project_button.setEnabled(bool(studio.nodes_without_uv()))
