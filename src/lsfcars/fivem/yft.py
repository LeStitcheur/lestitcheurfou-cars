"""Modèles GTA V : fragments (.yft) et drawables (.ydr), disposition « gen8 ».

Décodage réel (vérifié sur un véhicule d'addon) :

- fragment : drawable principal à ``+0x30``, nom à ``+0x58`` ;
- drawable : groupe de shaders ``+0x10``, squelette ``+0x18``, pointeurs vers les listes de
  modèles par niveau de détail ``+0x50`` (haut), ``+0x58``, ``+0x60``, ``+0x68`` ;
- squelette : os à ``+0x20`` (structures de 0x50 octets), nombre à ``+0x5E`` ;
- modèle : géométries ``+0x08``, correspondance géométrie → shader ``+0x20``, liaison au
  squelette ``+0x28`` (octet 3 = os, octet 1 = maillage skinné) ;
- géométrie : tampon de sommets ``+0x18``, tampon d'indices ``+0x38``, os ``+0x68`` ;
- déclaration de sommets : drapeaux des composants + types (4 bits par composant).

Les véhicules sont généralement un maillage skinné unique dont chaque sommet est rattaché à un
os (portes, capot, roues…). Les triangles sont donc regroupés par os : c'est la base de la
décomposition en composants. Les sommets sont exprimés dans le repère local de leur os pour
conserver les pivots d'origine (charnières de portes, axes de roues).
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

import numpy as np

from lsfcars.fivem.errors import FormatError
from lsfcars.fivem.rsc import Resource, View, joaat
from lsfcars.fivem.ytd import Texture, read_dictionary

# Tailles des types de composants de sommets (rage::grcFvf)
COMPONENT_SIZES = {0: 2, 1: 4, 2: 6, 3: 8, 4: 4, 5: 8, 6: 12, 7: 16, 8: 4, 9: 4, 10: 4, 11: 4, 12: 4, 13: 4}
POSITION, BLEND_WEIGHTS, BLEND_INDICES, NORMAL, COLOUR0 = 0, 1, 2, 3, 4
TEXCOORD0 = 6
LOD_OFFSETS = {"high": 0x50, "medium": 0x58, "low": 0x60, "very_low": 0x68}
LOD_LABELS = {"high": "Haut", "medium": "Moyen", "low": "Bas", "very_low": "Très bas"}

# Noms connus des shaders de véhicules et des paramètres de textures (résolution des hachages)
SHADER_NAMES = [
    "vehicle_paint1", "vehicle_paint1_enveff", "vehicle_paint2", "vehicle_paint2_enveff",
    "vehicle_paint3", "vehicle_paint3_enveff", "vehicle_paint3_lvr", "vehicle_paint4",
    "vehicle_paint4_emissive", "vehicle_paint4_enveff", "vehicle_paint5_enveff", "vehicle_paint6",
    "vehicle_paint6_enveff", "vehicle_paint7", "vehicle_paint7_enveff", "vehicle_paint8",
    "vehicle_paint9", "vehicle_basic", "vehicle_badges", "vehicle_blurredrotor",
    "vehicle_blurredrotor_emissive", "vehicle_cloth", "vehicle_cloth2", "vehicle_cutout",
    "vehicle_dash_emissive", "vehicle_dash_emissive_opaque", "vehicle_decal", "vehicle_decal2",
    "vehicle_detail", "vehicle_detail2", "vehicle_emissive_alpha", "vehicle_emissive_opaque",
    "vehicle_generic", "vehicle_interior", "vehicle_interior2", "vehicle_licenseplate",
    "vehicle_lights", "vehicle_lightsemissive", "vehicle_lightsemissive_siren", "vehicle_mesh",
    "vehicle_mesh2_enveff", "vehicle_mesh_enveff", "vehicle_nosplash", "vehicle_nowater",
    "vehicle_shuts", "vehicle_tire", "vehicle_tire_emissive", "vehicle_track",
    "vehicle_track2", "vehicle_track_ammo", "vehicle_track_emissive", "vehicle_track_cutout",
    "vehicle_vehglass", "vehicle_vehglass_inner", "vehicle_vehglass_crack",
    "default", "emissive", "normal", "normal_spec", "spec", "cutout", "decal", "glass",
    "normal_spec_decal", "emissivenight", "cable",
]  # fmt: skip
SHADER_BY_HASH = {joaat(name): name for name in SHADER_NAMES}
PARAM_NAMES = [
    "DiffuseSampler", "BumpSampler", "SpecSampler", "DetailSampler", "DirtSampler",
    "DamageSampler", "PlateBgSampler", "PlateBgBumpSampler", "TintPaletteSampler",
    "DiffuseSampler2", "DiffuseSampler3", "EnvironmentSampler", "DiffuseExtraSampler",
]  # fmt: skip
PARAM_BY_HASH = {joaat(name): name for name in PARAM_NAMES}

# GTA : Z vers le haut, Y vers l'avant → repère Y vers le haut du studio (rotation -90° sur X)
GTA_TO_Y_UP_EULER = (-90.0, 0.0, 0.0)


@dataclass
class Bone:
    index: int
    name: str
    parent: int
    tag: int
    translation: tuple[float, float, float]
    rotation: tuple[float, float, float, float]  # quaternion x, y, z, w
    scale: tuple[float, float, float]

    def local_matrix(self) -> np.ndarray:
        x, y, z, w = self.rotation
        norm = (x * x + y * y + z * z + w * w) ** 0.5 or 1.0
        x, y, z, w = x / norm, y / norm, z / norm, w / norm
        rotation = np.array(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
            ]
        )
        matrix = np.eye(4)
        matrix[:3, :3] = rotation * np.asarray(self.scale)
        matrix[:3, 3] = self.translation
        return matrix


@dataclass
class Skeleton:
    bones: list[Bone]

    def world_matrices(self) -> list[np.ndarray]:
        worlds: list[np.ndarray] = []
        for bone in self.bones:
            local = bone.local_matrix()
            parent = bone.parent
            worlds.append(worlds[parent] @ local if 0 <= parent < len(worlds) else local)
        return worlds


@dataclass
class ShaderInfo:
    index: int
    name: str
    name_hash: int
    textures: dict[str, str] = field(default_factory=dict)  # paramètre → nom de texture

    @property
    def diffuse(self) -> str | None:
        if "DiffuseSampler" in self.textures:
            return self.textures["DiffuseSampler"]
        return next(iter(self.textures.values()), None)


@dataclass
class Geometry:
    shader_index: int
    positions: np.ndarray  # (N, 3) repère du modèle (GTA)
    indices: np.ndarray  # (M, 3)
    normals: np.ndarray | None
    uvs: np.ndarray | None
    vertex_bones: np.ndarray  # (N,) index d'os du squelette par sommet


@dataclass
class Model:
    bone_index: int
    skinned: bool
    geometries: list[Geometry]


@dataclass
class Drawable:
    name: str
    skeleton: Skeleton | None
    lods: dict[str, list[Model]]
    shaders: list[ShaderInfo]
    textures: list[Texture]  # dictionnaire intégré
    bounds: tuple[tuple[float, ...], tuple[float, ...]] | None
    warnings: list[str] = field(default_factory=list)

    @property
    def high(self) -> list[Model]:
        return self.lods.get("high", [])

    def triangle_count(self, lod: str = "high") -> int:
        return sum(len(g.indices) for m in self.lods.get(lod, []) for g in m.geometries)

    def vertex_count(self, lod: str = "high") -> int:
        return sum(len(g.positions) for m in self.lods.get(lod, []) for g in m.geometries)


@dataclass
class FragmentChild:
    """Enfant physique du fragment portant son propre maillage (roues, pièces détachables)."""

    bone_tag: int
    bone_index: int  # -1 si l'os n'est pas trouvé dans le squelette principal
    drawable: Drawable


@dataclass
class Fragment:
    name: str
    drawable: Drawable
    version: int
    children: list[FragmentChild] = field(default_factory=list)

    def triangle_count(self) -> int:
        return self.drawable.triangle_count() + sum(c.drawable.triangle_count() for c in self.children)


# --- Lecture ------------------------------------------------------------------------


def _read_skeleton(view: View | None) -> Skeleton | None:
    if view is None:
        return None
    count = view.u16(0x5E)
    array = view.ptr(0x20)
    if array is None or count == 0:
        return None
    if count > 2048:
        raise FormatError("Squelette invalide : trop d'os.")
    bones = []
    for index in range(count):
        at = index * 0x50
        rotation = array.floats(at, 4)
        translation = array.floats(at + 0x10, 3)
        scale = array.floats(at + 0x20, 3)
        parent = array.i16(at + 0x32)
        name = array.string(at + 0x38) or f"os_{index}"
        tag = array.u16(at + 0x44)
        bones.append(Bone(index, name, parent, tag, translation, rotation, scale))
    return Skeleton(bones)


def _read_shaders(group: View | None) -> tuple[list[ShaderInfo], list[Texture]]:
    if group is None:
        return [], []
    textures: list[Texture] = []
    dictionary = group.ptr(0x08)
    if dictionary is not None:
        textures = read_dictionary(dictionary)
    shaders: list[ShaderInfo] = []
    for index, shader in enumerate(group.pointer_list(0x10, limit=1024)):
        name_hash = shader.u32(0x08)
        info = ShaderInfo(index, SHADER_BY_HASH.get(name_hash, f"shader_{name_hash:08x}"), name_hash)
        params = shader.ptr(0x00)
        count = shader.u8(0x10)
        if params is not None and 0 < count < 128:
            kinds = [params.u8(p * 16) for p in range(count)]
            hashes_at = 16 * count + sum(16 * kind for kind in kinds)
            for p, kind in enumerate(kinds):
                if kind != 0:
                    continue
                texture = params.ptr(p * 16 + 8)
                name = texture.string(0x28) if texture is not None else ""
                if not name:
                    continue
                try:
                    param = PARAM_BY_HASH.get(params.u32(hashes_at + 4 * p), f"param_{p}")
                except FormatError:
                    param = f"param_{p}"
                info.textures[param] = name
        shaders.append(info)
    return shaders, textures


def _decode_geometry(geometry: View, model_bone: int, skinned: bool) -> Geometry:
    vertex_buffer = geometry.ptr(0x18)
    index_buffer = geometry.ptr(0x38)
    if vertex_buffer is None or index_buffer is None:
        raise FormatError("Géométrie sans tampon de sommets ou d'indices.")
    stride = vertex_buffer.u16(0x08)
    vertex_count = vertex_buffer.u32(0x18)
    data = vertex_buffer.ptr(0x10) or vertex_buffer.ptr(0x20)
    declaration = vertex_buffer.ptr(0x30)
    if data is None or declaration is None or stride == 0:
        raise FormatError("Tampon de sommets incomplet.")
    flags = declaration.u32(0)
    types = declaration.u64(8)
    offsets: dict[int, tuple[int, int]] = {}
    cursor = 0
    for component in range(16):
        if flags & (1 << component):
            kind = (types >> (component * 4)) & 0xF
            offsets[component] = (cursor, kind)
            cursor += COMPONENT_SIZES.get(kind, 0)
    if cursor != stride:
        raise FormatError(f"Déclaration de sommets incohérente (pas {stride}, calculé {cursor}).")
    if vertex_count == 0 or vertex_count > 2_000_000:
        raise FormatError("Nombre de sommets invalide.")
    raw = np.frombuffer(data.raw(0, stride * vertex_count), np.uint8).reshape(vertex_count, stride)

    def floats(component: int, count: int) -> np.ndarray | None:
        if component not in offsets:
            return None
        start, kind = offsets[component]
        if kind in (4, 5, 6, 7):
            width = {4: 1, 5: 2, 6: 3, 7: 4}[kind]
            values = raw[:, start : start + width * 4].copy().view("<f4").reshape(vertex_count, width)
        elif kind in (0, 1, 2, 3):
            width = kind + 1
            values = raw[:, start : start + width * 2].copy().view("<f2").reshape(vertex_count, width)
        else:
            return None
        return values[:, :count].astype(np.float32) if values.shape[1] >= count else None

    positions = floats(POSITION, 3)
    if positions is None:
        raise FormatError("Format de position non pris en charge.")
    normals = floats(NORMAL, 3)
    uvs = floats(TEXCOORD0, 2)

    index_count = index_buffer.u32(0x08)
    indices_view = index_buffer.ptr(0x10)
    if indices_view is None or index_count % 3 or index_count == 0:
        raise FormatError("Tampon d'indices invalide.")
    indices = np.frombuffer(indices_view.raw(0, index_count * 2), "<u2").astype(np.uint32).reshape(-1, 3)
    if int(indices.max()) >= vertex_count:
        raise FormatError("Indice de sommet hors limites.")

    vertex_bones = np.full(vertex_count, model_bone, dtype=np.int32)
    if skinned and BLEND_INDICES in offsets and offsets[BLEND_INDICES][1] in (8, 9):
        start = offsets[BLEND_INDICES][0]
        blend = raw[:, start : start + 4]
        if BLEND_WEIGHTS in offsets and offsets[BLEND_WEIGHTS][1] in (8, 9):
            weight_start = offsets[BLEND_WEIGHTS][0]
            dominant = raw[:, weight_start : weight_start + 4].argmax(axis=1)
        else:
            dominant = np.zeros(vertex_count, dtype=np.int64)
        local = blend[np.arange(vertex_count), dominant].astype(np.int32)
        bone_ids_view = geometry.ptr(0x68)
        bone_ids_count = geometry.u16(0x72)
        if bone_ids_view is not None and bone_ids_count:
            table = np.frombuffer(bone_ids_view.raw(0, bone_ids_count * 2), "<u2").astype(np.int32)
            local = np.where(local < len(table), table[np.minimum(local, len(table) - 1)], local)
        vertex_bones = local
    return Geometry(0, positions, indices, normals, uvs, vertex_bones)


def _read_models(view: View, offset: int, warnings: list[str]) -> list[Model]:
    models: list[Model] = []
    container = view.ptr(offset)  # pointeur vers une liste (pointeur, nombre) de modèles
    if container is None:
        return models
    for model in container.pointer_list(0, limit=4096):
        binding = model.u32(0x28)
        bone_index = (binding >> 24) & 0xFF
        skinned = ((binding >> 8) & 0xFF) > 0
        mapping = model.ptr(0x20)
        geometries = []
        for index, geometry in enumerate(model.pointer_list(0x08, limit=4096)):
            try:
                decoded = _decode_geometry(geometry, bone_index, skinned)
            except FormatError as exc:
                warnings.append(f"Géométrie ignorée : {exc}")
                continue
            if mapping is not None:
                try:
                    decoded.shader_index = mapping.u16(index * 2)
                except FormatError:
                    decoded.shader_index = 0
            geometries.append(decoded)
        models.append(Model(bone_index, skinned, geometries))
    return models


def read_drawable(view: View, name: str = "") -> Drawable:
    warnings: list[str] = []
    shaders, textures = _read_shaders(view.ptr(0x10))
    skeleton = _read_skeleton(view.ptr(0x18))
    lods: dict[str, list[Model]] = {}
    for lod, offset in LOD_OFFSETS.items():
        try:
            models = _read_models(view, offset, warnings)
        except FormatError as exc:
            warnings.append(f"Niveau de détail {LOD_LABELS[lod]} illisible : {exc}")
            continue
        if models:
            lods[lod] = models
    bounds = None
    with contextlib.suppress(FormatError):
        bounds = (view.floats(0x30, 3), view.floats(0x40, 3))
    return Drawable(name, skeleton, lods, shaders, textures, bounds, warnings)


def parse_yft(data: bytes) -> Fragment:
    resource = Resource.from_bytes(data)
    if resource.header.version != 162:
        raise FormatError(
            f"Ce fichier n'est pas un fragment .yft (version RSC7 {resource.header.version}, attendu 162)."
        )
    root = resource.root()
    name = root.string(0x58).removeprefix("pack:/")
    drawable_view = root.ptr(0x30)
    if drawable_view is None:
        raise FormatError("Fragment sans drawable principal.")
    drawable = read_drawable(drawable_view, name)
    if not drawable.high:
        raise FormatError("Aucun modèle de haut niveau de détail dans ce fragment.")
    fragment = Fragment(name, drawable, resource.header.version)
    try:
        fragment.children = _read_children(root, drawable)
    except FormatError as exc:
        drawable.warnings.append(f"Enfants physiques illisibles (roues, pièces) : {exc}")
    return fragment


def _read_children(root: View, drawable: Drawable) -> list[FragmentChild]:
    """Enfants du premier niveau physique : ``+0xF0`` → ``+0x10`` → tableau à ``+0xD0``.

    Chaque enfant porte l'étiquette de son os à ``+0x12`` et son drawable intact à ``+0xA0``.
    """
    group = root.ptr(0xF0)
    lod = group.ptr(0x10) if group is not None else None
    array = lod.ptr(0xD0) if lod is not None else None
    if array is None:
        return []
    count = lod.u8(0x11E)
    by_tag = {b.tag: b.index for b in drawable.skeleton.bones} if drawable.skeleton else {}
    children = []
    for index in range(count):
        child = array.ptr(index * 8)
        if child is None:
            continue
        view = child.ptr(0xA0)
        if view is None:
            continue
        tag = child.u16(0x12)
        child_drawable = read_drawable(view, f"enfant_{index}")
        if child_drawable.high:
            children.append(FragmentChild(tag, by_tag.get(tag, -1), child_drawable))
    return children


def parse_ydr(data: bytes, name: str = "") -> Drawable:
    resource = Resource.from_bytes(data)
    if resource.header.version != 165:
        raise FormatError(
            f"Ce fichier n'est pas un drawable .ydr (version RSC7 {resource.header.version}, attendu 165)."
        )
    drawable = read_drawable(resource.root(), name)
    if not drawable.high:
        raise FormatError("Aucun modèle de haut niveau de détail dans ce drawable.")
    return drawable


# --- Découpage par composant -------------------------------------------------------


@dataclass
class Part:
    """Triangles d'un même os et d'un même shader, exprimés dans le repère local de l'os."""

    bone_index: int  # -1 : non rattaché au squelette
    shader_index: int
    positions: np.ndarray
    indices: np.ndarray
    normals: np.ndarray | None
    uvs: np.ndarray | None


def split_fragment(fragment: Fragment, lod: str = "high") -> list[Part]:
    """Parties du drawable principal et des enfants physiques (repère local de leur os)."""
    parts = split_parts(fragment.drawable, lod)
    for child in fragment.children:
        for part in split_parts(child.drawable, "high"):
            part.bone_index = child.bone_index
            parts.append(part)
    return parts


def split_parts(drawable: Drawable, lod: str = "high") -> list[Part]:
    skeleton = drawable.skeleton
    worlds = skeleton.world_matrices() if skeleton else []
    inverses = [np.linalg.inv(m) for m in worlds]
    parts: list[Part] = []
    for model in drawable.lods.get(lod, []):
        for geometry in model.geometries:
            tri_bones = geometry.vertex_bones[geometry.indices[:, 0]]
            for value in np.unique(tri_bones):
                bone = int(value)
                triangles = geometry.indices[tri_bones == value]
                used, remap = np.unique(triangles, return_inverse=True)
                positions = geometry.positions[used].astype(np.float64)
                normals = geometry.normals[used].astype(np.float64) if geometry.normals is not None else None
                if not 0 <= bone < len(worlds):
                    bone = -1
                elif model.skinned:
                    # Sommets skinnés : repère du modèle → repère local de l'os (pivot conservé)
                    inverse = inverses[bone]
                    positions = positions @ inverse[:3, :3].T + inverse[:3, 3]
                    if normals is not None:
                        normals = normals @ inverse[:3, :3].T
                uvs = geometry.uvs[used].copy() if geometry.uvs is not None else None
                if uvs is not None:
                    uvs[:, 1] = 1.0 - uvs[:, 1]  # convention OpenGL (comme l'import glTF)
                parts.append(
                    Part(
                        bone,
                        geometry.shader_index,
                        positions.astype(np.float32),
                        remap.reshape(-1, 3).astype(np.uint32),
                        normals.astype(np.float32) if normals is not None else None,
                        uvs,
                    )
                )
    return parts
