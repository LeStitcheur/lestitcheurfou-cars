"""Moteur de rendu OpenGL basé sur les classes Qt (compatible GL 3.3 core et Mesa GL 3.0).

Le renderer ne connaît ni l'interface ni le graphe de scène : il dessine une liste de
``DrawItem`` décrivant chaque maillage à l'écran.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QMatrix4x4, QOpenGLContext, QVector4D
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QOpenGLVertexArrayObject,
)

from lsfcars.core.logging_setup import get_logger
from lsfcars.render import primitives
from lsfcars.scene import mathutils
from lsfcars.scene.mesh import MeshData
from lsfcars.ui.design import tokens

log = get_logger(__name__)

# Constantes OpenGL (PySide6 ne les expose pas).
GL_POINTS, GL_LINES, GL_TRIANGLES = 0x0000, 0x0001, 0x0004
GL_PROGRAM_POINT_SIZE = 0x8642
GL_POINT_SPRITE = 0x8861  # profil de compatibilité : nécessaire à gl_PointCoord
GL_UNSIGNED_BYTE, GL_UNSIGNED_INT, GL_FLOAT = 0x1401, 0x1405, 0x1406
GL_DEPTH_TEST, GL_BLEND, GL_MULTISAMPLE = 0x0B71, 0x0BE2, 0x809D
GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA = 0x0302, 0x0303
GL_LEQUAL, GL_LESS = 0x0203, 0x0201
GL_DEPTH_BUFFER_BIT, GL_COLOR_BUFFER_BIT = 0x0100, 0x4000
GL_VENDOR, GL_RENDERER, GL_VERSION, GL_SHADING_LANGUAGE_VERSION = 0x1F00, 0x1F01, 0x1F02, 0x8B8C
GL_FALSE, GL_TRUE = 0, 1
GL_SCISSOR_TEST = 0x0C11

MIN_GL_VERSION = (3, 0)
ATTR_POSITION, ATTR_NORMAL, ATTR_COLOR, ATTR_UV = 0, 1, 2, 3

MESH_VS = """
in vec3 aPos; in vec3 aNormal; in vec4 aColor; in vec2 aUV;
uniform mat4 uModel; uniform mat4 uView; uniform mat4 uProj; uniform mat4 uNormalMat;
uniform vec2 uUVScale; uniform vec2 uUVOffset;
out vec3 vNormal; out vec3 vViewPos; out vec4 vColor; out vec2 vUV; out vec3 vWorldNormal;
void main() {
    vec4 viewPos = uView * uModel * vec4(aPos, 1.0);
    vViewPos = viewPos.xyz;
    vWorldNormal = mat3(uNormalMat) * aNormal;
    vNormal = mat3(uView) * vWorldNormal;
    vColor = aColor; vUV = aUV * uUVScale + uUVOffset;
    gl_Position = uProj * viewPos;
}
"""

MESH_FS = """
in vec3 vNormal; in vec3 vViewPos; in vec4 vColor; in vec2 vUV; in vec3 vWorldNormal;
uniform vec4 uBaseColor; uniform float uRough; uniform float uMetal; uniform float uAlpha;
uniform float uUseTexture; uniform sampler2D uTex; uniform float uMode; uniform float uHighlight;
uniform float uTexMode;
uniform float uUseNormal; uniform sampler2D uNormalTex; uniform float uNormalStrength; uniform vec3 uAccent;
uniform vec3 uEmissive;
out vec4 fragColor;
vec3 perturb(vec3 n, vec3 p, vec2 uv) {  // repère tangent par dérivées écran (sans tangentes stockées)
    vec3 dp1 = dFdx(p); vec3 dp2 = dFdy(p); vec2 duv1 = dFdx(uv); vec2 duv2 = dFdy(uv);
    vec3 dp2perp = cross(dp2, n); vec3 dp1perp = cross(n, dp1);
    vec3 t = dp2perp * duv1.x + dp1perp * duv2.x;
    vec3 b = dp2perp * duv1.y + dp1perp * duv2.y;
    float scale = inversesqrt(max(max(dot(t, t), dot(b, b)), 1e-20));
    vec3 m = texture(uNormalTex, uv).xyz * 2.0 - 1.0;
    m.xy *= uNormalStrength;
    return normalize(mat3(t * scale, b * scale, n) * m);
}
void main() {
    if (uMode > 1.5) { fragColor = vec4(uBaseColor.rgb, 1.0); return; }  // gizmo : couleur plate
    vec3 n = normalize(vNormal);
    if (!gl_FrontFacing) n = -n;
    if (uUseNormal > 0.5 && uMode > 0.5) n = perturb(n, vViewPos, vUV);
    vec3 v = normalize(-vViewPos);
    vec3 albedo;
    float alpha = 1.0;
    float rough = 0.62; float metal = 0.0;
    if (uMode < 0.5) {
        albedo = vec3(0.63, 0.65, 0.69);  // mode solide : argile neutre
    } else {
        albedo = uBaseColor.rgb * vColor.rgb;
        if (uUseTexture > 0.5) {
            vec4 tex = texture(uTex, vUV);
            if (uTexMode > 0.5) albedo = mix(albedo, tex.rgb, tex.a);  // livrée posée sur la peinture
            else { albedo *= tex.rgb; alpha = tex.a; }
        }
        alpha *= uBaseColor.a * uAlpha;
        rough = clamp(uRough, 0.04, 1.0); metal = clamp(uMetal, 0.0, 1.0);
    }
    vec3 keyDir = normalize(vec3(0.35, 0.65, 0.68));
    vec3 fillDir = normalize(vec3(-0.65, 0.25, 0.35));
    float diff = max(dot(n, keyDir), 0.0);
    float fill = max(dot(n, fillDir), 0.0) * 0.32;
    float shininess = mix(140.0, 6.0, rough);
    float spec = pow(max(dot(n, normalize(keyDir + v)), 0.0), shininess) * mix(0.9, 0.08, rough);
    vec3 specColor = mix(vec3(0.04), albedo, metal);
    float hemi = 0.5 + 0.5 * normalize(vWorldNormal).y;
    vec3 ambient = mix(vec3(0.07, 0.07, 0.08), vec3(0.20, 0.21, 0.24), hemi);
    vec3 env = mix(vec3(0.05, 0.04, 0.05), vec3(0.55, 0.56, 0.60), hemi) * (1.0 - rough * 0.8);
    vec3 color = albedo * (1.0 - metal) * (ambient + 0.85 * diff + fill)
               + specColor * (spec * 1.6 + env * metal)
               + albedo * metal * 0.25 * (diff + fill);
    float rim = pow(1.0 - max(dot(n, v), 0.0), 3.0);
    color += vec3(0.04, 0.09, 0.16) * rim;  // liseré froid du studio (bleu)
    color = mix(color, color * 0.75 + uAccent * (0.18 + 0.75 * rim), uHighlight * 0.55);
    if (uMode > 0.5) color += uEmissive;  // émission (optiques, signatures lumineuses)
    fragColor = vec4(color, alpha);
}
"""

LINE_VS = """
in vec3 aPos; in vec4 aColor;
uniform mat4 uModel; uniform mat4 uView; uniform mat4 uProj; uniform float uPointSize;
out vec4 vColor; out vec3 vWorld;
void main() {
    vec4 world = uModel * vec4(aPos, 1.0);
    vWorld = world.xyz; vColor = aColor;
    gl_Position = uProj * uView * world;
    gl_PointSize = uPointSize;
}
"""

LINE_FS = """
in vec4 vColor; in vec3 vWorld;
uniform vec4 uColor; uniform vec3 uFadeCenter; uniform float uFadeRadius; uniform float uPointStyle;
out vec4 fragColor;
void main() {
    vec4 c = uColor.a > 0.0 ? uColor : vColor;
    if (uPointStyle > 0.5) {  // points ronds (1) ou halo doux (2)
        vec2 d = gl_PointCoord - vec2(0.5);
        float r2 = dot(d, d);
        if (r2 > 0.25) discard;
        if (uPointStyle > 1.5) c.a *= pow(1.0 - r2 * 4.0, 2.0);
        else c.a *= smoothstep(0.25, 0.18, r2);
    }
    if (uFadeRadius > 0.0) {
        float d = length(vWorld.xz - uFadeCenter.xz);
        c.a *= 1.0 - smoothstep(uFadeRadius * 0.35, uFadeRadius, d);
    }
    fragColor = c;
}
"""

BG_VS = """
in vec3 aPos;
out float vY;
void main() { vY = aPos.y; gl_Position = vec4(aPos.xy, 0.9999, 1.0); }
"""

BG_FS = """
in float vY;
uniform vec3 uTop; uniform vec3 uBottom;
out vec4 fragColor;
void main() { fragColor = vec4(mix(uBottom, uTop, clamp(vY * 0.5 + 0.5, 0.0, 1.0)), 1.0); }
"""


def gl_rgb(color: str) -> tuple[float, float, float]:
    """Couleur hexadécimale des tokens → triplet OpenGL (0..1)."""
    value = color.lstrip("#")
    return tuple(int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


# Toutes les couleurs du rendu proviennent du design system Dark Premium.
BACKGROUND_TOP = gl_rgb(tokens.ColorTokens.BG_SECONDARY)
BACKGROUND_BOTTOM = gl_rgb(tokens.ColorTokens.BG_MAIN)
AXIS_COLORS = {0: gl_rgb(tokens.AXIS_X), 1: gl_rgb(tokens.AXIS_Y), 2: gl_rgb(tokens.AXIS_Z)}
HOVER_COLOR = gl_rgb(tokens.ColorTokens.ELECTRIC)
ACCENT_COLOR = gl_rgb(tokens.ColorTokens.ELECTRIC)  # surbrillance de la sélection (bleu électrique)
SELECTION_EDGE = (*gl_rgb(tokens.ColorTokens.ELECTRIC), 0.95)
WIRE_COLOR = (*gl_rgb(tokens.ColorTokens.TEXT_SECONDARY), 0.85)
GRID_MINOR = (*gl_rgb(tokens.ColorTokens.TEXT_SECONDARY), 0.14)
GRID_MAJOR = (*gl_rgb(tokens.ColorTokens.TEXT_SECONDARY), 0.28)


@dataclass
class DrawItem:
    mesh: MeshData
    model: np.ndarray
    base_color: tuple[float, float, float, float] = (0.72, 0.74, 0.78, 1.0)
    roughness: float = 0.5
    metallic: float = 0.0
    opacity: float = 1.0
    texture: Path | None = None
    selected: bool = False
    normal_texture: Path | None = None
    normal_strength: float = 1.0
    uv_scale: tuple[float, float] = (1.0, 1.0)
    uv_offset: tuple[float, float] = (0.0, 0.0)
    live_texture: object | None = None  # texture composée en direct (Livery Studio)
    emissive: tuple[float, float, float] = (0.0, 0.0, 0.0)  # couleur × intensité
    scissor: tuple[float, float] | None = (
        None  # bande horizontale affichée (fractions de largeur) : comparaison
    )


@dataclass
class Overlay:
    """Superposition en coordonnées monde : points, segments et triangles colorés (N, 7).

    Mode Édition (sommets, arêtes, faces sélectionnées) et repères des points d'ancrage.
    ``xray`` : dessiné par-dessus la géométrie (sans test de profondeur).
    """

    points: np.ndarray | None = None
    lines: np.ndarray | None = None
    triangles: np.ndarray | None = None
    point_size: float = 6.0
    xray: bool = False
    point_style: str = "round"  # square / round / glow


@dataclass
class GizmoDraw:
    mode: str  # translate / rotate / scale
    pivot: np.ndarray
    axes: np.ndarray  # (3, 3) axes monde normalisés
    size: float
    hover: int | None = None


@dataclass
class FrameData:
    view: np.ndarray
    proj: np.ndarray
    view_rotation: np.ndarray  # pour l'indicateur d'axes
    width: int
    height: int
    ratio: float
    items: list[DrawItem] = field(default_factory=list)
    shading: str = "material"  # solid / wireframe / material
    grid: bool = True
    grid_center: np.ndarray = field(default_factory=lambda: np.zeros(3))
    grid_radius: float = 40.0
    gizmo: GizmoDraw | None = None
    overlays: list[Overlay] = field(default_factory=list)


def _qmatrix(m: np.ndarray) -> QMatrix4x4:
    return QMatrix4x4(*np.asarray(m, dtype=np.float64).reshape(16).tolist())


def glsl_header(major: int, minor: int) -> str:
    return "#version 330 core\n" if (major, minor) >= (3, 3) else "#version 130\n"


def build_grid(half_size: int = 40, step: float = 1.0) -> np.ndarray:
    """Lignes de la grille au sol (plan XZ) : (N, 7) position + couleur RGBA."""
    minor, major = GRID_MINOR, GRID_MAJOR
    axis_x, axis_z = (*AXIS_COLORS[0], 0.75), (*AXIS_COLORS[2], 0.75)
    lines = []
    extent = half_size * step
    for i in range(-half_size, half_size + 1):
        c = i * step
        base = major if i % 5 == 0 else minor
        color_x = axis_x if i == 0 else base
        color_z = axis_z if i == 0 else base
        lines += [
            (-extent, 0, c, *color_x),
            (extent, 0, c, *color_x),
            (c, 0, -extent, *color_z),
            (c, 0, extent, *color_z),
        ]
    return np.asarray(lines, dtype=np.float32)


@dataclass
class _Gpu:
    vao: QOpenGLVertexArrayObject
    buffers: list[QOpenGLBuffer]
    count: int
    edge_vao: QOpenGLVertexArrayObject | None = None
    edge_count: int = 0

    def destroy(self) -> None:
        for buffer in self.buffers:
            buffer.destroy()
        self.vao.destroy()
        if self.edge_vao is not None:
            self.edge_vao.destroy()


class Renderer:
    def __init__(self) -> None:
        self.ready = False
        self.info: dict[str, str] = {}
        self.last_frame_ms = 0.0
        self._fn = None
        self._compat = True
        self._mesh_prog: QOpenGLShaderProgram | None = None
        self._line_prog: QOpenGLShaderProgram | None = None
        self._bg_prog: QOpenGLShaderProgram | None = None
        self._meshes: dict[int, tuple[MeshData, _Gpu]] = {}
        self._textures: dict[Path, QOpenGLTexture | None] = {}
        self._live: dict[int, list] = {}  # id(LiveTexture) → [texture, version, taille, objet]
        self._grid: _Gpu | None = None
        self._bg: _Gpu | None = None
        self._axes: _Gpu | None = None
        self._gizmo_meshes = {
            "translate": primitives.TRANSLATE_HANDLE,
            "scale": primitives.SCALE_HANDLE,
            "rotate": primitives.ROTATE_HANDLE,
        }

    # --- Initialisation -----------------------------------------------------
    def initialize(self, context: QOpenGLContext) -> dict[str, str]:
        fmt = context.format()
        version = (fmt.majorVersion(), fmt.minorVersion())
        fn = context.functions()
        self._fn = fn
        self._compat = fmt.profile() != fmt.OpenGLContextProfile.CoreProfile
        self.info = {
            "Fournisseur": fn.glGetString(GL_VENDOR) or "?",
            "Moteur de rendu": fn.glGetString(GL_RENDERER) or "?",
            "Version": fn.glGetString(GL_VERSION) or "?",
            "GLSL": fn.glGetString(GL_SHADING_LANGUAGE_VERSION) or "?",
            "Contexte": f"{version[0]}.{version[1]}",
        }
        if version < MIN_GL_VERSION:
            raise RuntimeError(
                f"OpenGL {MIN_GL_VERSION[0]}.{MIN_GL_VERSION[1]} requis, "
                f"contexte obtenu : {version[0]}.{version[1]}"
            )
        header = glsl_header(*version)
        self._mesh_prog = self._program(
            header,
            MESH_VS,
            MESH_FS,
            {"aPos": ATTR_POSITION, "aNormal": ATTR_NORMAL, "aColor": ATTR_COLOR, "aUV": ATTR_UV},
        )
        self._line_prog = self._program(
            header, LINE_VS, LINE_FS, {"aPos": ATTR_POSITION, "aColor": ATTR_COLOR}
        )
        self._bg_prog = self._program(header, BG_VS, BG_FS, {"aPos": ATTR_POSITION})
        self._grid = self._upload_lines(build_grid())
        quad = np.array([[-1, -1, 0], [3, -1, 0], [-1, 3, 0]], np.float32)
        self._bg = self._upload([(quad, ATTR_POSITION, GL_FLOAT, 3)], None, 3, self._bg_prog)
        axes = np.array(
            [
                [0, 0, 0, *AXIS_COLORS[0], 1],
                [1, 0, 0, *AXIS_COLORS[0], 1],
                [0, 0, 0, *AXIS_COLORS[1], 1],
                [0, 1, 0, *AXIS_COLORS[1], 1],
                [0, 0, 0, *AXIS_COLORS[2], 1],
                [0, 0, 1, *AXIS_COLORS[2], 1],
            ],
            np.float32,
        )
        self._axes = self._upload_lines(axes)
        self.ready = True
        return dict(self.info)

    @staticmethod
    def _program(header: str, vs: str, fs: str, attributes: dict[str, int]) -> QOpenGLShaderProgram:
        program = QOpenGLShaderProgram()
        for kind, src in (
            (QOpenGLShader.ShaderTypeBit.Vertex, vs),
            (QOpenGLShader.ShaderTypeBit.Fragment, fs),
        ):
            if not program.addShaderFromSourceCode(kind, header + src):
                raise RuntimeError(f"Compilation du shader impossible : {program.log()}")
        for name, location in attributes.items():
            program.bindAttributeLocation(name, location)
        if not program.link():
            raise RuntimeError(f"Édition de liens impossible : {program.log()}")
        return program

    @staticmethod
    def _buffer(data: np.ndarray, kind=QOpenGLBuffer.Type.VertexBuffer) -> QOpenGLBuffer:  # type: ignore[no-untyped-def]
        data = np.ascontiguousarray(data)
        buffer = QOpenGLBuffer(kind)
        buffer.create()
        buffer.bind()
        buffer.allocate(data.tobytes(), data.nbytes)
        return buffer

    def _upload(self, attributes, indices, count, program) -> _Gpu:  # type: ignore[no-untyped-def]
        vao = QOpenGLVertexArrayObject()
        vao.create()
        vao.bind()
        program.bind()
        buffers = []
        for data, location, gl_type, size in attributes:
            buffers.append(self._buffer(data))
            program.enableAttributeArray(location)
            program.setAttributeBuffer(location, gl_type, 0, size, 0)
        if indices is not None:
            buffers.append(self._buffer(indices, QOpenGLBuffer.Type.IndexBuffer))
        vao.release()
        program.release()
        return _Gpu(vao, buffers, count)

    def _upload_lines(self, lines: np.ndarray) -> _Gpu:
        return self._upload(
            [(lines[:, :3], ATTR_POSITION, GL_FLOAT, 3), (lines[:, 3:], ATTR_COLOR, GL_FLOAT, 4)],
            None,
            len(lines),
            self._line_prog,
        )

    def _gpu_mesh(self, mesh: MeshData) -> _Gpu:
        cached = self._meshes.get(id(mesh))
        if cached is not None and cached[0] is mesh:
            return cached[1]
        uvs = mesh.uvs if mesh.uvs is not None else np.zeros((mesh.vertex_count, 2), np.float32)
        gpu = self._upload(
            [
                (mesh.positions, ATTR_POSITION, GL_FLOAT, 3),
                (mesh.normals, ATTR_NORMAL, GL_FLOAT, 3),
                (mesh.colors, ATTR_COLOR, GL_UNSIGNED_BYTE, 4),
                (uvs, ATTR_UV, GL_FLOAT, 2),
            ],
            mesh.indices,
            int(mesh.indices.size),
            self._mesh_prog,
        )
        self._meshes[id(mesh)] = (mesh, gpu)
        return gpu

    def _edges(self, mesh: MeshData) -> _Gpu:
        gpu = self._gpu_mesh(mesh)
        if gpu.edge_vao is None:
            edges = mesh.edges()
            vao = QOpenGLVertexArrayObject()
            vao.create()
            vao.bind()
            self._line_prog.bind()
            gpu.buffers[0].bind()  # positions
            self._line_prog.enableAttributeArray(ATTR_POSITION)
            self._line_prog.setAttributeBuffer(ATTR_POSITION, GL_FLOAT, 0, 3, 0)
            gpu.buffers.append(self._buffer(edges, QOpenGLBuffer.Type.IndexBuffer))
            vao.release()
            self._line_prog.release()
            gpu.edge_vao, gpu.edge_count = vao, int(edges.size)
        return gpu

    def _texture(self, path: Path | None) -> QOpenGLTexture | None:
        if path is None:
            return None
        if path not in self._textures:
            image = QImage(str(path))
            if image.isNull():
                log.warning("Texture illisible : %s", path)
                self._textures[path] = None
            else:
                flipped = (
                    image.flipped(Qt.Orientation.Vertical) if hasattr(image, "flipped") else image.mirrored()
                )
                texture = QOpenGLTexture(flipped.convertToFormat(QImage.Format.Format_RGBA8888))
                texture.setMinificationFilter(QOpenGLTexture.Filter.LinearMipMapLinear)
                texture.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
                texture.setWrapMode(QOpenGLTexture.WrapMode.Repeat)
                self._textures[path] = texture
        return self._textures[path]

    def _live_texture(self, live) -> QOpenGLTexture | None:  # type: ignore[no-untyped-def]
        """Texture composée en direct : seule la région modifiée depuis le dernier envoi est transférée."""
        array = live.array
        h, w = array.shape[:2]
        entry = self._live.get(id(live))
        if entry is None or entry[2] != (w, h) or entry[3] is not live:
            if entry is not None:
                entry[0].destroy()
            image = QImage(array.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
            vertical = Qt.Orientation.Vertical
            flipped = image.flipped(vertical) if hasattr(image, "flipped") else image.mirrored()
            texture = QOpenGLTexture(flipped)
            texture.setMinificationFilter(QOpenGLTexture.Filter.LinearMipMapLinear)
            texture.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
            texture.setWrapMode(QOpenGLTexture.WrapMode.Repeat)
            self._live[id(live)] = [texture, live.version, (w, h), live]
            return texture
        texture, version = entry[0], entry[1]
        change = live.changes_since(version)
        if change is not False:
            x0, y0, x1, y1 = (0, 0, w, h) if change is True else change
            region = np.ascontiguousarray(array[y0:y1, x0:x1][::-1])
            texture.bind()
            texture.setData(
                x0,
                h - y1,
                0,
                x1 - x0,
                y1 - y0,
                1,
                QOpenGLTexture.PixelFormat.RGBA,
                QOpenGLTexture.PixelType.UInt8,
                region.tobytes(),
            )
            texture.generateMipMaps()
            texture.release()
            entry[1] = live.version
        return texture

    def collect_garbage(self, live: set[int]) -> None:
        """Libère les maillages qui ne sont plus affichés (contexte courant requis)."""
        for key in [k for k in self._meshes if k not in live]:
            self._meshes.pop(key)[1].destroy()

    def __del__(self) -> None:
        self._abandon_textures()

    def _abandon_textures(self) -> None:
        """Textures non libérées dans leur contexte (fenêtre détruite) : enveloppes détachées.

        Le destructeur C++ de ``QOpenGLTexture`` déréférencerait un contexte déjà détruit ; la
        mémoire vidéo est rendue avec le contexte lui-même.
        """
        textures = [t for t in self._textures.values() if t is not None] + [e[0] for e in self._live.values()]
        self._textures.clear()
        self._live.clear()
        for texture in textures:
            if shiboken6.isValid(texture):
                shiboken6.invalidate(texture)

    def release(self) -> None:
        for _mesh, gpu in self._meshes.values():
            gpu.destroy()
        self._meshes.clear()
        for texture in self._textures.values():
            if texture is not None:
                texture.destroy()
        self._textures.clear()
        for entry in self._live.values():
            entry[0].destroy()
        self._live.clear()
        for gpu in (self._grid, self._bg, self._axes):
            if gpu is not None:
                gpu.destroy()
        self.ready = False

    # --- Rendu --------------------------------------------------------------
    def render(self, frame: FrameData) -> None:
        if not self.ready:
            return
        start = time.perf_counter()
        fn = self._fn
        assert fn is not None and self._mesh_prog and self._line_prog and self._bg_prog
        shown = {id(i.live_texture) for i in frame.items if i.live_texture is not None}
        for key in [k for k in self._live if k not in shown]:  # textures en direct plus affichées
            self._live.pop(key)[0].destroy()
        full = (0, 0, int(frame.width * frame.ratio), int(frame.height * frame.ratio))
        fn.glViewport(*full)
        fn.glClearColor(*BACKGROUND_BOTTOM, 1.0)
        fn.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        fn.glEnable(GL_MULTISAMPLE)

        fn.glDisable(GL_DEPTH_TEST)  # fond studio en dégradé
        self._bg_prog.bind()
        self._bg_prog.setUniformValue("uTop", *BACKGROUND_TOP)
        self._bg_prog.setUniformValue("uBottom", *BACKGROUND_BOTTOM)
        self._draw_arrays(self._bg, GL_TRIANGLES)
        self._bg_prog.release()

        fn.glEnable(GL_DEPTH_TEST)
        fn.glDepthFunc(GL_LESS)
        fn.glEnable(GL_BLEND)
        fn.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        view, proj = _qmatrix(frame.view), _qmatrix(frame.proj)

        if frame.grid and self._grid is not None:
            fn.glDepthMask(GL_FALSE)
            self._line_uniforms(view, proj, np.eye(4), None, frame.grid_center, frame.grid_radius)
            self._draw_arrays(self._grid, GL_LINES)
            fn.glDepthMask(GL_TRUE)

        wire_only = frame.shading == "wireframe"
        if not wire_only:
            opaque = [i for i in frame.items if i.opacity >= 0.999 and i.base_color[3] >= 0.999]
            transparent = [i for i in frame.items if i.opacity < 0.999 or i.base_color[3] < 0.999]
            prog = self._mesh_prog
            prog.bind()
            prog.setUniformValue("uView", view)
            prog.setUniformValue("uProj", proj)
            prog.setUniformValue1i("uTex", 0)
            prog.setUniformValue1f("uMode", 0.0 if frame.shading == "solid" else 1.0)
            for item in opaque:
                self._clip(item, full)
                self._draw_item(item)
            if transparent:
                eye = np.linalg.inv(frame.view)[:3, 3]
                transparent.sort(key=lambda i: -float(np.linalg.norm(i.model[:3, 3] - eye)))
                fn.glDepthMask(GL_FALSE)
                for item in transparent:
                    self._clip(item, full)
                    self._draw_item(item)
                fn.glDepthMask(GL_TRUE)
            fn.glDisable(GL_SCISSOR_TEST)
            prog.release()

        fn.glDepthFunc(GL_LEQUAL)  # arêtes : toutes en filaire, la sélection sinon
        for item in frame.items:
            if wire_only or item.selected:
                self._clip(item, full)
                gpu = self._edges(item.mesh)
                self._line_uniforms(view, proj, item.model, SELECTION_EDGE if item.selected else WIRE_COLOR)
                gpu.edge_vao.bind()
                fn.glDrawElements(GL_LINES, gpu.edge_count, GL_UNSIGNED_INT, shiboken6.VoidPtr(0))
                gpu.edge_vao.release()
        fn.glDisable(GL_SCISSOR_TEST)
        fn.glDepthFunc(GL_LESS)

        for overlay in frame.overlays:
            self._draw_overlay(overlay, view, proj)
        if frame.gizmo is not None:
            self._draw_gizmo(frame.gizmo, view, proj)
        self._draw_axis_indicator(frame, full)
        self.last_frame_ms = (time.perf_counter() - start) * 1000.0

    def _clip(self, item: DrawItem, full: tuple[int, int, int, int]) -> None:
        """Limite le dessin d'un élément à une bande verticale (séparateur de comparaison)."""
        fn = self._fn
        if item.scissor is None:
            fn.glDisable(GL_SCISSOR_TEST)
            return
        width, height = full[2], full[3]
        x0 = int(round(max(0.0, min(1.0, item.scissor[0])) * width))
        x1 = int(round(max(0.0, min(1.0, item.scissor[1])) * width))
        fn.glEnable(GL_SCISSOR_TEST)
        fn.glScissor(x0, 0, max(x1 - x0, 0), height)

    def _draw_overlay(self, overlay: Overlay, view: QMatrix4x4, proj: QMatrix4x4) -> None:
        """Superposition dynamique : tampons créés pour l'image puis libérés."""
        fn = self._fn
        if overlay.xray:
            fn.glDisable(GL_DEPTH_TEST)
        else:
            fn.glDepthFunc(GL_LEQUAL)
        fn.glDepthMask(GL_FALSE)
        fn.glEnable(GL_PROGRAM_POINT_SIZE)
        if self._compat:
            fn.glEnable(GL_POINT_SPRITE)
        for data, mode in (
            (overlay.triangles, GL_TRIANGLES),
            (overlay.lines, GL_LINES),
            (overlay.points, GL_POINTS),
        ):
            if data is None or not len(data):
                continue
            gpu = self._upload_lines(np.ascontiguousarray(data, np.float32))
            self._line_uniforms(view, proj, np.eye(4), None)
            self._line_prog.setUniformValue1f("uPointSize", float(overlay.point_size))
            style = {"round": 1.0, "glow": 2.0}.get(overlay.point_style, 0.0) if mode == GL_POINTS else 0.0
            self._line_prog.setUniformValue1f("uPointStyle", style)
            self._draw_arrays(gpu, mode)
            gpu.destroy()
        self._line_prog.setUniformValue1f("uPointSize", 1.0)
        self._line_prog.setUniformValue1f("uPointStyle", 0.0)
        fn.glDepthMask(GL_TRUE)
        fn.glDepthFunc(GL_LESS)
        fn.glEnable(GL_DEPTH_TEST)

    def _draw_arrays(self, gpu: _Gpu | None, mode: int) -> None:
        if gpu is not None:
            gpu.vao.bind()
            self._fn.glDrawArrays(mode, 0, gpu.count)
            gpu.vao.release()

    def _line_uniforms(
        self,
        view: QMatrix4x4,
        proj: QMatrix4x4,
        model: np.ndarray,
        color: tuple | None,
        fade_center: np.ndarray | None = None,
        fade_radius: float = 0.0,
    ) -> None:
        prog = self._line_prog
        prog.bind()
        prog.setUniformValue("uView", view)
        prog.setUniformValue("uProj", proj)
        prog.setUniformValue("uModel", _qmatrix(model))
        prog.setUniformValue("uColor", QVector4D(*(color or (0.0, 0.0, 0.0, 0.0))))
        center = fade_center if fade_center is not None else np.zeros(3)
        prog.setUniformValue("uFadeCenter", float(center[0]), float(center[1]), float(center[2]))
        prog.setUniformValue1f("uFadeRadius", float(fade_radius))

    def _draw_item(self, item: DrawItem) -> None:
        prog = self._mesh_prog
        gpu = self._gpu_mesh(item.mesh)
        prog.bind()  # un premier envoi GPU libère le programme : on le réactive
        normal = np.eye(4)
        normal[:3, :3] = mathutils.normal_matrix(item.model)
        prog.setUniformValue("uModel", _qmatrix(item.model))
        prog.setUniformValue("uNormalMat", _qmatrix(normal))
        prog.setUniformValue("uBaseColor", QVector4D(*item.base_color))
        prog.setUniformValue1f("uRough", float(item.roughness))
        prog.setUniformValue1f("uMetal", float(item.metallic))
        prog.setUniformValue1f("uAlpha", float(item.opacity))
        prog.setUniformValue1f("uHighlight", 1.0 if item.selected else 0.0)
        prog.setUniformValue("uAccent", *ACCENT_COLOR)
        prog.setUniformValue("uEmissive", *(float(c) for c in item.emissive))
        prog.setUniformValue("uUVScale", float(item.uv_scale[0]), float(item.uv_scale[1]))
        prog.setUniformValue("uUVOffset", float(item.uv_offset[0]), float(item.uv_offset[1]))
        live = item.live_texture
        texture = self._live_texture(live) if live is not None else self._texture(item.texture)
        prog.setUniformValue1f("uUseTexture", 1.0 if texture is not None else 0.0)
        decal = live is not None and getattr(live, "mode", "texture") == "decal"
        prog.setUniformValue1f("uTexMode", 1.0 if decal else 0.0)
        if texture is not None:
            texture.bind(0)
        normal = self._texture(item.normal_texture)
        prog.setUniformValue1i("uNormalTex", 1)
        prog.setUniformValue1f("uUseNormal", 1.0 if normal is not None else 0.0)
        prog.setUniformValue1f("uNormalStrength", float(item.normal_strength))
        if normal is not None:
            normal.bind(1)
        gpu.vao.bind()
        self._fn.glDrawElements(GL_TRIANGLES, gpu.count, GL_UNSIGNED_INT, shiboken6.VoidPtr(0))
        gpu.vao.release()
        if normal is not None:
            normal.release(1)
        if texture is not None:
            texture.release()

    def _draw_gizmo(self, gizmo: GizmoDraw, view: QMatrix4x4, proj: QMatrix4x4) -> None:
        fn = self._fn
        fn.glDisable(GL_DEPTH_TEST)
        prog = self._mesh_prog
        prog.bind()
        prog.setUniformValue("uView", view)
        prog.setUniformValue("uProj", proj)
        prog.setUniformValue1f("uMode", 2.0)
        handle = self._gizmo_meshes[gizmo.mode]
        for index in range(3):
            axis = gizmo.axes[index]
            side = gizmo.axes[(index + 1) % 3]
            basis = np.eye(4)  # repère dont +Y suit l'axe demandé
            basis[:3, 0] = side
            basis[:3, 1] = axis
            basis[:3, 2] = np.cross(side, axis)
            model = mathutils.translation(gizmo.pivot) @ basis @ mathutils.scaling((gizmo.size,) * 3)
            color = HOVER_COLOR if gizmo.hover == index else AXIS_COLORS[index]
            self._draw_item(DrawItem(handle, model, (*color, 1.0)))
        prog.release()
        fn.glEnable(GL_DEPTH_TEST)

    def _draw_axis_indicator(self, frame: FrameData, full: tuple[int, int, int, int]) -> None:
        if self._axes is None:
            return
        size = int(70 * frame.ratio)
        fn = self._fn
        fn.glViewport(int(12 * frame.ratio), int(12 * frame.ratio), size, size)
        fn.glDisable(GL_DEPTH_TEST)
        rotation = np.eye(4)
        rotation[:3, :3] = frame.view_rotation
        ortho = np.diag([1 / 1.3, 1 / 1.3, -0.3, 1.0])
        self._line_uniforms(_qmatrix(rotation), _qmatrix(ortho), np.eye(4), None)
        self._draw_arrays(self._axes, GL_LINES)
        fn.glEnable(GL_DEPTH_TEST)
        fn.glViewport(*full)
