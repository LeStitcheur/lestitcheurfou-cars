"""Configuration OpenGL, à appeler avant la création de ``QApplication``."""

from __future__ import annotations

import os

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QSurfaceFormat

GL_MAJOR, GL_MINOR = 3, 3


def software_gl_requested() -> bool:
    return os.environ.get("LSFCARS_SOFTWARE_GL", "").strip().lower() in ("1", "true", "oui")


def configure_opengl(software: bool = False) -> None:
    """Demande un contexte OpenGL 3.3 core ; ``software`` force le rendu Mesa embarqué."""
    if software or software_gl_requested():
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    fmt.setVersion(GL_MAJOR, GL_MINOR)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)
