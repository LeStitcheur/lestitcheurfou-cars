"""Design system « Dark Premium — Automotive Creation Studio ».

Point d'entrée : ``apply_design(app)``. Les valeurs vivent dans ``tokens`` (ColorTokens,
TypographyTokens, SpacingTokens, AnimationTokens, AppTheme) ; le style des composants dans
``qss.ComponentStyles`` ; les widgets réutilisables dans ``components``, ``sidebar`` et ``topbar``.
"""

from lsfcars.ui.design.qss import apply_design

__all__ = ["apply_design"]
