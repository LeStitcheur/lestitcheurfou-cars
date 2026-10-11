"""Design system de la suite LeStitcheur, adapté de LeStitcheur Control (``src/design.css``).

Point d'entrée : ``apply_design(app)``. Les valeurs vivent dans ``tokens`` ; les composants
réutilisables dans ``components``, ``sidebar`` et ``topbar``.
"""

from lsfcars.ui.design.qss import apply_design

__all__ = ["apply_design"]
