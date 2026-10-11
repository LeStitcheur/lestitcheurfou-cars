"""Viewport 3D OpenGL : grille, objets éclairés, sélection et navigation orbitale.

Le rendu passe par les classes OpenGL de Qt (et non PyOpenGL) afin de fonctionner aussi
avec le rendu logiciel Mesa embarqué par Qt (OpenGL 3.0 / GLSL 1.30).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import shiboken6
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMatrix4x4, QMouseEvent, QResizeEvent, QWheelEvent
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLVertexArrayObject,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QLabel, QWidget

from lsfcars.core import diagnostics
from lsfcars.core.logging_setup import get_logger
from lsfcars.scene import mathutils, picking
from lsfcars.scene.camera import OrbitCamera
from lsfcars.scene.mesh import MeshData
from lsfcars.ui.theme import VIEWPORT_BACKGROUND

log = get_logger(__name__)

# Constantes OpenGL (PySide6 ne les expose pas).
GL_LINES = 0x0001
GL_TRIANGLES = 0x0004
GL_UNSIGNED_BYTE = 0x1401
GL_UNSIGNED_INT = 0x1405
GL_FLOAT = 0x1406
GL_DEPTH_TEST = 0x0B71
GL_BLEND = 0x0BE2
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_MULTISAMPLE = 0x809D
GL_DEPTH_BUFFER_BIT = 0x0100
GL_COLOR_BUFFER_BIT = 0x4000
GL_VENDOR = 0x1F00
GL_RENDERER = 0x1F01
GL_VERSION = 0x1F02
GL_SHADING_LANGUAGE_VERSION = 0x8B8C

MIN_GL_VERSION = (3, 0)

# Emplacements fixes des attributs de sommets.
ATTR_POSITION, ATTR_NORMAL, ATTR_COLOR = 0, 1, 2

# Les sources commencent sans directive #version : elle est ajoutée selon le contexte.
MESH_VS = """
in vec3 aPos;
in vec3 aNormal;
in vec4 aColor;
uniform mat4 uModel;
uniform mat4 uView;
uniform mat4 uProj;
uniform mat4 uNormalMat;
out vec3 vNormal;
out vec3 vViewPos;
out vec4 vColor;
void main() {
    vec4 viewPos = uView * uModel * vec4(aPos, 1.0);
    vViewPos = viewPos.xyz;
    vNormal = mat3(uView) * (mat3(uNormalMat) * aNormal);
    vColor = aColor;
    gl_Position = uProj * viewPos;
}
"""

MESH_FS = """
in vec3 vNormal;
in vec3 vViewPos;
in vec4 vColor;
uniform float uHighlight;
out vec4 fragColor;
void main() {
    vec3 n = normalize(vNormal);
    if (!gl_FrontFacing) n = -n;
    vec3 v = normalize(-vViewPos);
    vec3 keyLight = normalize(vec3(0.35, 0.55, 0.75));
    vec3 fillLight = normalize(vec3(-0.6, 0.2, 0.4));
    float diffuse = max(dot(n, keyLight), 0.0);
    float fill = max(dot(n, fillLight), 0.0) * 0.30;
    float spec = pow(max(dot(n, normalize(keyLight + v)), 0.0), 40.0) * 0.25;
    vec3 color = vColor.rgb * (0.22 + 0.78 * diffuse + fill) + vec3(spec);
    vec3 accent = vec3(0.12, 0.56, 1.0);
    float rim = pow(1.0 - max(dot(n, v), 0.0), 2.5);
    color = mix(color, color + accent * (0.9 * rim + 0.12), uHighlight);
    fragColor = vec4(color, vColor.a);
}
"""

LINE_VS = """
in vec3 aPos;
in vec3 aColor;
uniform mat4 uView;
uniform mat4 uProj;
out vec3 vColor;
void main() {
    vColor = aColor;
    gl_Position = uProj * uView * vec4(aPos, 1.0);
}
"""

LINE_FS = """
in vec3 vColor;
out vec4 fragColor;
void main() { fragColor = vec4(vColor, 1.0); }
"""

HINT_TEXT = (
    "Clic gauche : orbite  ·  Clic droit / molette enfoncée : déplacer  ·  Molette : zoom  ·  "
    "F : cadrer  ·  1 / 3 / 7 : vues avant / droite / dessus"
)

STANDARD_VIEWS = {
    "front": (0.0, 0.0),
    "back": (180.0, 0.0),
    "right": (90.0, 0.0),
    "left": (270.0, 0.0),
    "top": (0.0, 89.0),
    "perspective": (35.0, 20.0),
}


def build_grid(half_size: int = 20, step: float = 1.0) -> np.ndarray:
    """Lignes de la grille au sol (plan XZ) : tableau (N, 6) position + couleur."""
    minor, major = (0.17, 0.20, 0.26), (0.26, 0.31, 0.40)
    axis_x, axis_z = (0.85, 0.27, 0.32), (0.18, 0.50, 1.0)
    lines = []
    extent = half_size * step
    for i in range(-half_size, half_size + 1):
        c = i * step
        line_color = major if i % 5 == 0 else minor
        color_x = axis_x if i == 0 else line_color
        color_z = axis_z if i == 0 else line_color
        lines.append((-extent, 0, c, *color_x))  # parallèle à X
        lines.append((extent, 0, c, *color_x))
        lines.append((c, 0, -extent, *color_z))  # parallèle à Z
        lines.append((c, 0, extent, *color_z))
    return np.asarray(lines, dtype=np.float32)


@dataclass
class _GpuMesh:
    vao: QOpenGLVertexArrayObject
    buffers: list[QOpenGLBuffer]
    count: int  # nombre d'indices (triangles) ou de sommets (lignes)

    def destroy(self) -> None:
        """À appeler avec le contexte OpenGL courant."""
        for buffer in self.buffers:
            buffer.destroy()
        self.vao.destroy()


def _qmatrix(m: np.ndarray) -> QMatrix4x4:
    """Matrice numpy 4x4 (vecteurs colonnes) -> QMatrix4x4 (constructeur en ordre ligne)."""
    return QMatrix4x4(*np.asarray(m, dtype=np.float64).reshape(16).tolist())


def _glsl_header(major: int, minor: int) -> str:
    return "#version 330 core\n" if (major, minor) >= (3, 3) else "#version 130\n"


@dataclass
class _ViewObject:
    meshes: list[MeshData]
    matrix: np.ndarray = field(default_factory=mathutils.identity)
    visible: bool = True
    gpu: list[_GpuMesh] | None = None


class Viewport3D(QOpenGLWidget):
    """Widget de rendu 3D. Les objets sont identifiés par une chaîne (id de ``SceneObject``)."""

    object_clicked = Signal(object)  # str | None
    frame_requested = Signal()
    gl_initialized = Signal(bool, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.camera = OrbitCamera()
        self._objects: dict[str, _ViewObject] = {}
        self._pending_delete: list[_GpuMesh] = []
        self._selected: str | None = None
        self._grid_visible = True
        self._fn = None  # QOpenGLFunctions du contexte courant
        self._gl_error: str | None = None
        self._gl_ready = False
        self._mesh_prog: QOpenGLShaderProgram | None = None
        self._line_prog: QOpenGLShaderProgram | None = None
        self._grid: _GpuMesh | None = None
        self._press_pos: QPoint | None = None
        self._last_pos = QPoint()
        self._drag_button = Qt.MouseButton.NoButton
        self._moved = False

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(320, 240)

        self._hint = QLabel(HINT_TEXT, self)
        self._hint.setObjectName("ViewportHint")
        self._hint.move(10, 10)
        self._hint.adjustSize()
        self._error_label = QLabel(self)
        self._error_label.setObjectName("ViewportError")
        self._error_label.setWordWrap(True)
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.hide()

    # --- API publique ------------------------------------------------------
    @property
    def gl_ready(self) -> bool:
        return self._gl_ready

    @property
    def gl_error(self) -> str | None:
        return self._gl_error

    def set_object(self, object_id: str, meshes: list[MeshData]) -> None:
        """Ajoute ou remplace la géométrie d'un objet (envoi GPU différé au prochain rendu)."""
        old = self._objects.get(object_id)
        if old and old.gpu:
            self._pending_delete.extend(old.gpu)
        view = _ViewObject(meshes=meshes)
        if old:
            view.matrix, view.visible = old.matrix, old.visible
        self._objects[object_id] = view
        self.update()

    def set_object_state(self, object_id: str, matrix: np.ndarray, visible: bool) -> None:
        view = self._objects.get(object_id)
        if view:
            view.matrix = np.asarray(matrix, dtype=np.float64)
            view.visible = visible
            self.update()

    def remove_object(self, object_id: str) -> None:
        view = self._objects.pop(object_id, None)
        if view and view.gpu:
            self._pending_delete.extend(view.gpu)
        if self._selected == object_id:
            self._selected = None
        self.update()

    def clear(self) -> None:
        for object_id in list(self._objects):
            self.remove_object(object_id)
        self._selected = None

    def object_ids(self) -> list[str]:
        return list(self._objects)

    def selected(self) -> str | None:
        return self._selected

    def set_selected(self, object_id: str | None) -> None:
        self._selected = object_id
        self.update()

    def set_grid_visible(self, visible: bool) -> None:
        self._grid_visible = visible
        self.update()

    def grid_visible(self) -> bool:
        return self._grid_visible

    def frame_bounds(self, bounds: tuple[np.ndarray, np.ndarray] | None) -> None:
        if bounds is None:
            self.camera.reset()
        else:
            self.camera.frame(*bounds)
        self.update()

    def set_standard_view(self, name: str) -> None:
        self.camera.set_view(*STANDARD_VIEWS[name])
        self.update()

    # --- OpenGL ------------------------------------------------------------
    def initializeGL(self) -> None:  # noqa: N802 (API Qt)
        try:
            ctx = self.context()
            fmt = ctx.format()
            version = (fmt.majorVersion(), fmt.minorVersion())
            fn = ctx.functions()
            self._fn = fn
            info = {
                "Fournisseur": fn.glGetString(GL_VENDOR) or "?",
                "Moteur de rendu": fn.glGetString(GL_RENDERER) or "?",
                "Version": fn.glGetString(GL_VERSION) or "?",
                "GLSL": fn.glGetString(GL_SHADING_LANGUAGE_VERSION) or "?",
                "Contexte": f"{version[0]}.{version[1]}",
            }
            diagnostics.set_gl_info(info)
            log.info("OpenGL : %s — %s", info["Moteur de rendu"], info["Version"])
            if version < MIN_GL_VERSION:
                raise RuntimeError(
                    f"OpenGL {MIN_GL_VERSION[0]}.{MIN_GL_VERSION[1]} requis, "
                    f"contexte obtenu : {version[0]}.{version[1]}"
                )

            header = _glsl_header(*version)
            self._mesh_prog = self._build_program(
                header,
                MESH_VS,
                MESH_FS,
                {"aPos": ATTR_POSITION, "aNormal": ATTR_NORMAL, "aColor": ATTR_COLOR},
            )
            self._line_prog = self._build_program(
                header, LINE_VS, LINE_FS, {"aPos": ATTR_POSITION, "aColor": ATTR_COLOR}
            )
            grid = build_grid()
            self._grid = self._upload(
                [
                    (np.ascontiguousarray(grid[:, :3]), ATTR_POSITION, GL_FLOAT, 3),
                    (np.ascontiguousarray(grid[:, 3:]), ATTR_COLOR, GL_FLOAT, 3),
                ],
                None,
                len(grid),
                self._line_prog,
            )
            fn.glEnable(GL_DEPTH_TEST)
            fn.glEnable(GL_MULTISAMPLE)
            fn.glEnable(GL_BLEND)
            fn.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            self._gl_ready = True
            ctx.aboutToBeDestroyed.connect(self._release_gl)
            self.gl_initialized.emit(True, info["Moteur de rendu"])
        except Exception as exc:  # pilote absent, contexte trop ancien, shaders refusés…
            self._gl_error = (
                "Le rendu 3D n'a pas pu démarrer.\n"
                f"{exc}\n\n"
                "Mettez à jour le pilote graphique ou lancez l'application avec l'option "
                "--software-gl (rendu logiciel)."
            )
            diagnostics.set_gl_info({"État": "échec d'initialisation", "Erreur": str(exc)})
            log.error("Échec de l'initialisation OpenGL : %s", exc)
            self._error_label.setText(self._gl_error)
            self._error_label.show()
            self._layout_overlays()
            self.gl_initialized.emit(False, str(exc))

    def _build_program(
        self, header: str, vs_src: str, fs_src: str, attributes: dict[str, int]
    ) -> QOpenGLShaderProgram:
        program = QOpenGLShaderProgram(self)
        for kind, src in (
            (QOpenGLShader.ShaderTypeBit.Vertex, vs_src),
            (QOpenGLShader.ShaderTypeBit.Fragment, fs_src),
        ):
            if not program.addShaderFromSourceCode(kind, header + src):
                raise RuntimeError(f"Compilation du shader impossible : {program.log()}")
        for name, location in attributes.items():
            program.bindAttributeLocation(name, location)
        if not program.link():
            raise RuntimeError(f"Édition de liens du programme impossible : {program.log()}")
        return program

    def _upload(
        self,
        attributes: list[tuple[np.ndarray, int, int, int]],
        indices: np.ndarray | None,
        count: int,
        program: QOpenGLShaderProgram,
    ) -> _GpuMesh:
        """Crée un VAO : ``attributes`` = (données, emplacement, type GL, composantes)."""
        vao = QOpenGLVertexArrayObject(self)
        vao.create()
        vao.bind()
        program.bind()
        buffers = []
        for data, location, gl_type, size in attributes:
            vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            vbo.create()
            vbo.bind()
            vbo.allocate(data.tobytes(), data.nbytes)
            program.enableAttributeArray(location)
            # Qt normalise les entiers (couleurs uint8 -> 0..1) ; sans effet sur les flottants.
            program.setAttributeBuffer(location, gl_type, 0, size, 0)
            buffers.append(vbo)
        if indices is not None:
            ebo = QOpenGLBuffer(QOpenGLBuffer.Type.IndexBuffer)
            ebo.create()
            ebo.bind()
            ebo.allocate(indices.tobytes(), indices.nbytes)
            buffers.append(ebo)
        vao.release()
        program.release()
        return _GpuMesh(vao, buffers, count)

    def _upload_mesh(self, mesh: MeshData) -> _GpuMesh:
        assert self._mesh_prog is not None
        return self._upload(
            [
                (mesh.positions, ATTR_POSITION, GL_FLOAT, 3),
                (mesh.normals, ATTR_NORMAL, GL_FLOAT, 3),
                (mesh.colors, ATTR_COLOR, GL_UNSIGNED_BYTE, 4),
            ],
            mesh.indices,
            int(mesh.indices.size),
            self._mesh_prog,
        )

    def _release_gl(self) -> None:
        """Libère les ressources GPU avant la destruction du contexte."""
        if not self._gl_ready:
            return
        self.makeCurrent()
        try:
            for gpu in self._pending_delete:
                gpu.destroy()
            self._pending_delete.clear()
            for view in self._objects.values():
                for gpu in view.gpu or []:
                    gpu.destroy()
                view.gpu = None
            if self._grid is not None:
                self._grid.destroy()
                self._grid = None
            for program in (self._mesh_prog, self._line_prog):
                if program is not None:
                    program.removeAllShaders()
        finally:
            self._gl_ready = False
            self.doneCurrent()

    def paintGL(self) -> None:  # noqa: N802
        if not self._gl_ready:
            return
        fn = self._fn
        assert fn is not None and self._mesh_prog is not None and self._line_prog is not None
        for gpu in self._pending_delete:
            gpu.destroy()
        self._pending_delete.clear()

        fn.glClearColor(*VIEWPORT_BACKGROUND, 1.0)
        fn.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        aspect = self.width() / max(self.height(), 1)
        view = _qmatrix(self.camera.view_matrix())
        proj = _qmatrix(self.camera.projection_matrix(aspect))

        if self._grid_visible and self._grid is not None:
            self._line_prog.bind()
            self._line_prog.setUniformValue("uView", view)
            self._line_prog.setUniformValue("uProj", proj)
            self._grid.vao.bind()
            fn.glDrawArrays(GL_LINES, 0, self._grid.count)
            self._grid.vao.release()

        prog = self._mesh_prog
        prog.bind()
        prog.setUniformValue("uView", view)
        prog.setUniformValue("uProj", proj)
        null_offset = shiboken6.VoidPtr(0)
        for object_id, obj in self._objects.items():
            if not obj.visible or not obj.meshes:
                continue
            if obj.gpu is None:
                obj.gpu = [self._upload_mesh(m) for m in obj.meshes]
                prog.bind()
            normal = np.eye(4)
            normal[:3, :3] = mathutils.normal_matrix(obj.matrix)
            prog.setUniformValue("uModel", _qmatrix(obj.matrix))
            prog.setUniformValue("uNormalMat", _qmatrix(normal))
            prog.setUniformValue1f("uHighlight", 1.0 if object_id == self._selected else 0.0)
            for gpu in obj.gpu:
                gpu.vao.bind()
                fn.glDrawElements(GL_TRIANGLES, gpu.count, GL_UNSIGNED_INT, null_offset)
                gpu.vao.release()
        prog.release()

    # --- Superpositions ------------------------------------------------------
    def _layout_overlays(self) -> None:
        if self._error_label.isVisible():
            self._error_label.setFixedWidth(max(min(560, self.width() - 40), 200))
            self._error_label.adjustSize()
            self._error_label.move(
                (self.width() - self._error_label.width()) // 2,
                (self.height() - self._error_label.height()) // 2,
            )
        self._hint.setVisible(self.width() > self._hint.width() + 20)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_overlays()

    # --- Interaction ----------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.setFocus()
        self._press_pos = event.position().toPoint()
        self._last_pos = self._press_pos
        self._drag_button = event.button()
        self._moved = False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._press_pos is None:
            return
        pos = event.position().toPoint()
        delta = pos - self._last_pos
        self._last_pos = pos
        if (pos - self._press_pos).manhattanLength() > 3:
            self._moved = True
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        left = self._drag_button == Qt.MouseButton.LeftButton
        if left and not shift:
            self.camera.orbit(-delta.x() * 0.4, delta.y() * 0.4)
        elif (left and shift) or self._drag_button in (
            Qt.MouseButton.RightButton,
            Qt.MouseButton.MiddleButton,
        ):
            self.camera.pan(delta.x(), delta.y(), self.height())
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_button == Qt.MouseButton.LeftButton and not self._moved:
            pos = event.position()
            self.object_clicked.emit(self.pick(pos.x(), pos.y()))
        self._press_pos = None
        self._drag_button = Qt.MouseButton.NoButton

    def pick(self, x: float, y: float) -> str | None:
        """Identifiant de l'objet visible sous le pixel (x, y), ou ``None``."""
        origin, direction = picking.ray_from_screen(self.camera, x, y, self.width(), self.height())
        candidates = (
            (oid, obj.matrix, obj.meshes) for oid, obj in self._objects.items() if obj.visible
        )
        return picking.pick(origin, direction, candidates)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.camera.zoom(steps)
            self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        views = {
            Qt.Key.Key_1: "front",
            Qt.Key.Key_3: "right",
            Qt.Key.Key_7: "top",
            Qt.Key.Key_5: "perspective",
        }
        key = event.key()
        if key == Qt.Key.Key_F:
            self.frame_requested.emit()
        elif key in views:
            self.set_standard_view(views[key])
        else:
            super().keyPressEvent(event)
