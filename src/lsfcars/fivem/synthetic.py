"""Construction de ressources GTA V synthétiques (tests et addon de démonstration).

Ce module écrit de petits fichiers RSC7 (.ytd, .yft) et RPF7 non chiffrés à partir de données
créées ici, selon les dispositions lues par ``rpf``, ``rsc``, ``ytd`` et ``yft``. Il sert à
vérifier les lecteurs sans aucun fichier propriétaire. Ce n'est pas un exporteur FiveM : les
structures produites ne contiennent que les champs lus par LeStitcheurFou Cars.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from lsfcars.fivem.rpf import ENC_OPEN
from lsfcars.fivem.rsc import block_size, joaat

SYS = 5 << 28
GFX = 6 << 28


def flags_for(size: int) -> int:
    """Drapeaux de bloc couvrant ``size`` octets : une page de 512 × 2^n octets."""
    shift = 0
    while (0x200 << shift) < size:
        shift += 1
    return (1 << 27) | shift


def build_rsc(version: int, system: bytes, graphics: bytes = b"") -> bytes:
    sys_flags = flags_for(len(system))
    gfx_flags = flags_for(len(graphics)) if graphics else 0
    sys_block = system.ljust(block_size(sys_flags), b"\0")
    gfx_block = graphics.ljust(block_size(gfx_flags), b"\0") if graphics else b""
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    payload = compressor.compress(sys_block + gfx_block) + compressor.flush()
    return struct.pack("<4sIII", b"RSC7", version, sys_flags, gfx_flags) + payload


class Block:
    """Tampon d'écriture avec allocation alignée et pointeurs typés."""

    def __init__(self, segment: int) -> None:
        self.segment = segment
        self.data = bytearray()
        self.cursor = 0

    def alloc(self, size: int, align: int = 16) -> int:
        self.cursor = (self.cursor + align - 1) // align * align
        offset = self.cursor
        self.cursor += size
        if self.cursor > len(self.data):
            self.data.extend(b"\0" * (self.cursor - len(self.data)))
        return offset

    def ptr(self, offset: int) -> int:
        return self.segment | offset

    def put(self, offset: int, fmt: str, *values: object) -> None:
        struct.pack_into(fmt, self.data, offset, *values)

    def string(self, text: str) -> int:
        raw = text.encode("utf-8") + b"\0"
        offset = self.alloc(len(raw), 1)
        self.data[offset : offset + len(raw)] = raw
        return offset

    def blob(self, raw: bytes, align: int = 16) -> int:
        offset = self.alloc(len(raw), align)
        self.data[offset : offset + len(raw)] = raw
        return offset

    def payload(self) -> bytes:
        return bytes(self.data[: max(self.cursor, 16)]).ljust(16, b"\0")


# --- Textures ----------------------------------------------------------------------


@dataclass
class TextureSpec:
    name: str
    width: int
    height: int
    format_code: int
    data: bytes
    levels: int = 1
    stride: int = 0


def dxt1_solid(width: int, height: int, rgb565: int) -> bytes:
    """Blocs DXT1 d'une couleur unie (couleur 0, indices nuls)."""
    blocks = max(1, width // 4) * max(1, height // 4)
    return struct.pack("<HHI", rgb565, 0, 0) * blocks


def bgra_gradient(width: int, height: int, alpha: int = 255) -> bytes:
    """Pixels A8R8G8B8 (B, G, R, A en mémoire) : dégradé horizontal rouge."""
    row = bytearray()
    for x in range(width):
        row += bytes((0, 0, int(255 * x / max(width - 1, 1)), alpha))
    return bytes(row) * height


def write_dictionary(system: Block, graphics: Block, textures: list[TextureSpec], at: int) -> None:
    """Écrit un dictionnaire de textures à la position ``at`` du bloc système."""
    array = system.alloc(8 * len(textures), 8)
    system.put(at + 0x30, "<QH", system.ptr(array), len(textures))
    for index, spec in enumerate(textures):
        texture = system.alloc(0x90, 16)
        system.put(array + index * 8, "<Q", system.ptr(texture))
        system.put(texture + 0x28, "<Q", system.ptr(system.string(spec.name)))
        stride = spec.stride or (spec.width * 4 if spec.format_code in (21, 22, 32) else 0)
        system.put(texture + 0x50, "<HHHHI", spec.width, spec.height, 1, stride, spec.format_code)
        system.put(texture + 0x5D, "<B", spec.levels)
        system.put(texture + 0x70, "<Q", graphics.ptr(graphics.blob(spec.data)))


def build_ytd(textures: list[TextureSpec]) -> bytes:
    system, graphics = Block(SYS), Block(GFX)
    system.alloc(0x40)
    write_dictionary(system, graphics, textures, 0)
    return build_rsc(13, system.payload(), graphics.payload())


# --- Modèles -----------------------------------------------------------------------


@dataclass
class BoneSpec:
    name: str
    parent: int
    translation: tuple[float, float, float]
    tag: int = 0


@dataclass
class PartSpec:
    """Boîte attachée à un os (centre relatif à l'os, repère GTA : Z vers le haut)."""

    bone: int
    center: tuple[float, float, float]
    size: tuple[float, float, float]
    shader: int = 0


@dataclass
class ModelSpec:
    name: str
    bones: list[BoneSpec]
    parts: list[PartSpec]
    shaders: list[tuple[str, str]] = field(default_factory=lambda: [("vehicle_paint1", "")])
    embedded: list[TextureSpec] = field(default_factory=list)


def _box(center: np.ndarray, size: tuple[float, float, float]) -> tuple[np.ndarray, np.ndarray]:
    half = np.asarray(size, np.float32) / 2
    corners = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], np.float32)
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    positions: list[np.ndarray] = []
    indices: list[tuple[int, int, int]] = []
    for face in faces:
        base = len(positions)
        positions.extend(center + corners[i] * half for i in face)
        indices.extend([(base, base + 1, base + 2), (base, base + 2, base + 3)])
    return np.asarray(positions, np.float32), np.asarray(indices, np.int64)


def bone_world_translations(bones: list[BoneSpec]) -> list[np.ndarray]:
    worlds: list[np.ndarray] = []
    for bone in bones:
        offset = np.asarray(bone.translation, np.float64)
        worlds.append(worlds[bone.parent] + offset if 0 <= bone.parent < len(worlds) else offset)
    return worlds


def _write_skeleton(system: Block, drawable: int, bones: list[BoneSpec]) -> None:
    skeleton = system.alloc(0x70)
    array = system.alloc(0x50 * len(bones))
    system.put(skeleton + 0x20, "<Q", system.ptr(array))
    system.put(skeleton + 0x5E, "<H", len(bones))
    for index, bone in enumerate(bones):
        at = array + index * 0x50
        system.put(at, "<4f", 0.0, 0.0, 0.0, 1.0)
        system.put(at + 0x10, "<3f", *bone.translation)
        system.put(at + 0x20, "<3f", 1.0, 1.0, 1.0)
        system.put(at + 0x32, "<h", bone.parent)
        system.put(at + 0x38, "<Q", system.ptr(system.string(bone.name)))
        system.put(at + 0x44, "<H", bone.tag or index + 1000)
    system.put(drawable + 0x18, "<Q", system.ptr(skeleton))


def _write_shaders(system: Block, graphics: Block, drawable: int, spec: ModelSpec) -> None:
    group = system.alloc(0x20)
    system.put(drawable + 0x10, "<Q", system.ptr(group))
    if spec.embedded:
        dictionary = system.alloc(0x40)
        write_dictionary(system, graphics, spec.embedded, dictionary)
        system.put(group + 0x08, "<Q", system.ptr(dictionary))
    array = system.alloc(8 * len(spec.shaders), 8)
    system.put(group + 0x10, "<QH", system.ptr(array), len(spec.shaders))
    for index, (shader_name, texture_name) in enumerate(spec.shaders):
        shader = system.alloc(0x30)
        system.put(array + index * 8, "<Q", system.ptr(shader))
        system.put(shader + 0x08, "<I", joaat(shader_name))
        if texture_name:
            params = system.alloc(16 + 4)
            reference = system.alloc(0x40)
            system.put(reference + 0x28, "<Q", system.ptr(system.string(texture_name)))
            system.put(params, "<BBHIQ", 0, 0, 0, 0, system.ptr(reference))
            system.put(params + 16, "<I", joaat("DiffuseSampler"))
            system.put(shader + 0x00, "<Q", system.ptr(params))
            system.put(shader + 0x10, "<B", 1)


STRIDE = 12 + 4 + 4 + 12 + 8  # position, poids, indices d'os, normale, UV
DECLARATION_FLAGS = 0b1001111
DECLARATION_TYPES = 6 | (9 << 4) | (9 << 8) | (6 << 12) | (5 << 24)


def _geometry_data(spec: ModelSpec, parts: list[PartSpec]) -> tuple[bytes, int, bytes]:
    worlds = bone_world_translations(spec.bones)
    rows: list[bytes] = []
    indices: list[np.ndarray] = []
    count = 0
    for part in parts:
        positions, faces = _box(
            np.asarray(part.center, np.float32) + worlds[part.bone].astype(np.float32), part.size
        )
        normals = np.zeros_like(positions)
        for face in faces:
            a, b, c = positions[face]
            normal = np.cross(b - a, c - a)
            normals[face] = normal / (np.linalg.norm(normal) or 1.0)
        packed = bytearray()
        for position, normal in zip(positions, normals, strict=True):
            packed += struct.pack("<3f", *position)
            packed += bytes((255, 0, 0, 0))
            packed += bytes((part.bone, 0, 0, 0))
            packed += struct.pack("<3f", *normal)
            packed += struct.pack("<2f", 0.5, 0.5)
        rows.append(bytes(packed))
        indices.append(faces + count)
        count += len(positions)
    return b"".join(rows), count, np.concatenate(indices).astype("<u2").tobytes()


def build_yft(spec: ModelSpec) -> bytes:
    """Fragment synthétique : un maillage skinné par shader, chaque sommet rattaché à son os."""
    system, graphics = Block(SYS), Block(GFX)
    fragment = system.alloc(0x100)
    drawable = system.alloc(0x100)
    system.put(fragment + 0x30, "<Q", system.ptr(drawable))
    system.put(fragment + 0x58, "<Q", system.ptr(system.string(f"pack:/{spec.name}")))
    _write_skeleton(system, drawable, spec.bones)
    _write_shaders(system, graphics, drawable, spec)

    by_shader: dict[int, list[PartSpec]] = {}
    for part in spec.parts:
        by_shader.setdefault(part.shader, []).append(part)
    models_list = system.alloc(0x10)
    model_array = system.alloc(8, 8)
    model = system.alloc(0x30)
    system.put(drawable + 0x50, "<Q", system.ptr(models_list))
    system.put(models_list, "<QH", system.ptr(model_array), 1)
    system.put(model_array, "<Q", system.ptr(model))
    geometry_array = system.alloc(8 * len(by_shader), 8)
    mapping = system.alloc(2 * len(by_shader), 2)
    system.put(model + 0x08, "<QH", system.ptr(geometry_array), len(by_shader))
    system.put(model + 0x20, "<Q", system.ptr(mapping))
    system.put(model + 0x28, "<I", 1 << 8)  # maillage skinné, os 0
    for index, (shader_index, parts) in enumerate(sorted(by_shader.items())):
        vertex_data, vertex_count, index_data = _geometry_data(spec, parts)
        geometry = system.alloc(0x80)
        vertex_buffer = system.alloc(0x40)
        declaration = system.alloc(0x10)
        index_buffer = system.alloc(0x20)
        system.put(geometry_array + index * 8, "<Q", system.ptr(geometry))
        system.put(mapping + index * 2, "<H", shader_index)
        system.put(geometry + 0x18, "<Q", system.ptr(vertex_buffer))
        system.put(geometry + 0x38, "<Q", system.ptr(index_buffer))
        system.put(geometry + 0x58, "<II", len(index_data) // 2, len(index_data) // 6)
        system.put(geometry + 0x60, "<H", vertex_count)
        system.put(vertex_buffer + 0x08, "<H", STRIDE)
        system.put(vertex_buffer + 0x10, "<Q", graphics.ptr(graphics.blob(vertex_data)))
        system.put(vertex_buffer + 0x18, "<I", vertex_count)
        system.put(vertex_buffer + 0x30, "<Q", system.ptr(declaration))
        system.put(declaration, "<IHBBQ", DECLARATION_FLAGS, STRIDE, 0, 5, DECLARATION_TYPES)
        system.put(index_buffer + 0x08, "<I", len(index_data) // 2)
        system.put(index_buffer + 0x10, "<Q", graphics.ptr(graphics.blob(index_data)))
    return build_rsc(162, system.payload(), graphics.payload())


# --- Archives RPF ---------------------------------------------------------------------


@dataclass
class RpfItem:
    data: bytes
    compress: bool = False
    resource: bool = False


def build_rpf(files: dict[str, RpfItem], encryption: int = ENC_OPEN) -> bytes:
    """Archive RPF7 (chemins « a/b/c.ext »). Les ressources gardent leur en-tête RSC7."""
    tree: dict = {}
    for path, item in files.items():
        node = tree
        parts = path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = item

    entries: list[tuple[str, object]] = [("", tree)]
    layout: list[tuple[int, int]] = [(0, 0)]
    queue = [0]
    while queue:
        index = queue.pop(0)
        node = entries[index][1]
        if not isinstance(node, dict):
            continue
        first = len(entries)
        children = sorted(node.items())
        entries.extend(children)
        layout.extend((0, 0) for _ in children)
        layout[index] = (first, len(children))
        queue.extend(i for i in range(first, first + len(children)) if isinstance(entries[i][1], dict))

    names = bytearray(b"\0")
    name_offsets = []
    for name, _node in entries:
        name_offsets.append(len(names) if name else 0)
        if name:
            names += name.encode("utf-8") + b"\0"
    cursor = (16 + 16 * len(entries) + len(names) + 511) // 512 * 512
    payloads: list[tuple[int, bytes]] = []
    toc = bytearray()
    for index, (_name, node) in enumerate(entries):
        if isinstance(node, dict):
            first, count = layout[index]
            toc += struct.pack("<IIII", name_offsets[index], 0x7FFFFF00, first, count)
            continue
        assert isinstance(node, RpfItem)
        if node.resource:
            raw = node.data
            sys_flags, gfx_flags = struct.unpack_from("<II", raw, 8)
            toc += struct.pack("<H", name_offsets[index])
            toc += len(raw).to_bytes(3, "little")
            toc += ((cursor // 512) | 0x800000).to_bytes(3, "little")
            toc += struct.pack("<II", sys_flags, gfx_flags)
        else:
            if node.compress:
                compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
                raw = compressor.compress(node.data) + compressor.flush()
                stored = len(raw)
            else:
                raw, stored = node.data, 0
            packed = name_offsets[index] | (stored << 16) | ((cursor // 512) << 40)
            toc += struct.pack("<QII", packed, len(node.data), 0)
        payloads.append((cursor, raw))
        cursor = (cursor + len(raw) + 511) // 512 * 512
    output = bytearray(cursor)
    output[:16] = struct.pack("<4sIII", b"7FPR", len(entries), len(names), encryption)
    output[16 : 16 + len(toc)] = toc
    output[16 + len(toc) : 16 + len(toc) + len(names)] = names
    for offset, raw in payloads:
        output[offset : offset + len(raw)] = raw
    return bytes(output)


# --- Véhicule de démonstration -----------------------------------------------------------


def demo_vehicle(name: str = "lsfdemo") -> ModelSpec:
    """Petit véhicule : châssis, carrosserie, portes, capot, coffre, roues, vitre, phare, siège."""
    bones = [
        BoneSpec("chassis", -1, (0.0, 0.0, 0.0)),
        BoneSpec("bodyshell", 0, (0.0, 0.0, 0.0)),
        BoneSpec("door_dside_f", 0, (-0.92, 0.55, 0.45)),
        BoneSpec("door_pside_f", 0, (0.92, 0.55, 0.45)),
        BoneSpec("bonnet", 0, (0.0, 1.05, 0.78)),
        BoneSpec("boot", 0, (0.0, -1.55, 0.8)),
        BoneSpec("wheel_lf", 0, (-0.85, 1.35, 0.32)),
        BoneSpec("wheel_rf", 0, (0.85, 1.35, 0.32)),
        BoneSpec("wheel_lr", 0, (-0.85, -1.3, 0.32)),
        BoneSpec("wheel_rr", 0, (0.85, -1.3, 0.32)),
        BoneSpec("windscreen", 0, (0.0, 0.45, 1.05)),
        BoneSpec("headlight_l", 0, (-0.6, 2.05, 0.62)),
        BoneSpec("seat_dside_f", 0, (-0.4, -0.1, 0.4)),
        BoneSpec("misc_a", 0, (0.0, -2.0, 0.5)),
        BoneSpec("lsf_custom_part", 0, (0.0, 0.0, 1.3)),
    ]
    parts = [
        PartSpec(0, (0.0, 0.0, 0.25), (1.6, 4.0, 0.2), 1),
        PartSpec(1, (0.0, 0.0, 0.62), (1.7, 3.6, 0.55), 0),
        PartSpec(2, (-0.04, -0.45, 0.0), (0.08, 0.9, 0.5), 0),
        PartSpec(3, (0.04, -0.45, 0.0), (0.08, 0.9, 0.5), 0),
        PartSpec(4, (0.0, 0.3, 0.0), (1.5, 0.75, 0.05), 0),
        PartSpec(5, (0.0, 0.0, 0.0), (1.4, 0.5, 0.05), 0),
        PartSpec(10, (0.0, 0.0, 0.0), (1.3, 0.05, 0.4), 2),
        PartSpec(11, (0.0, 0.0, 0.0), (0.3, 0.06, 0.12), 3),
        PartSpec(13, (0.0, 0.0, 0.0), (0.4, 0.1, 0.1), 1),
        PartSpec(14, (0.0, 0.0, 0.0), (0.5, 0.5, 0.05), 1),
    ]
    parts += [PartSpec(bone, (0.0, 0.0, 0.0), (0.22, 0.64, 0.64), 4) for bone in (6, 7, 8, 9)]
    shaders = [
        ("vehicle_paint1", ""),
        ("vehicle_mesh", f"{name}_details"),
        ("vehicle_vehglass", "vehicle_generic_glasswindows2"),
        ("vehicle_lightsemissive", f"{name}_lights"),
        ("vehicle_tire", "vehicle_generic_tyrewallblack"),
    ]
    return ModelSpec(name, bones, parts, shaders)


def demo_textures(name: str = "lsfdemo") -> list[TextureSpec]:
    return [
        TextureSpec(f"{name}_details", 64, 64, 0x31545844, dxt1_solid(64, 64, 0x7BEF)),
        TextureSpec(f"{name}_lights", 16, 16, 21, bgra_gradient(16, 16, alpha=200)),
        TextureSpec(f"{name}_sign_1", 128, 64, 21, bgra_gradient(128, 64)),
    ]


DEMO_METAS = {
    "vehicles.meta": """<?xml version="1.0" encoding="UTF-8"?>
<CVehicleModelInfo__InitDataList>
  <residentTxd>vehshare</residentTxd>
  <InitDatas>
    <Item>
      <modelName>{name}</modelName>
      <txdName>{name}</txdName>
      <handlingId>{handling}</handlingId>
      <gameName>LSFDEMO</gameName>
      <vehicleMakeName>LESTITCHEUR</vehicleMakeName>
      <type>VEHICLE_TYPE_CAR</type>
      <vehicleClass>VC_EMERGENCY</vehicleClass>
      <layout>LAYOUT_STANDARD</layout>
    </Item>
  </InitDatas>
  <txdRelationships>
    <Item><parent>vehicles_poldark_interior</parent><child>{name}</child></Item>
  </txdRelationships>
</CVehicleModelInfo__InitDataList>
""",
    "handling.meta": """<?xml version="1.0" encoding="UTF-8"?>
<CHandlingDataMgr>
  <HandlingData>
    <Item type="CHandlingData">
      <handlingName>{handling}</handlingName>
      <fMass value="1800.000000" />
      <fInitialDriveForce value="0.320000" />
      <nInitialDriveGears value="6" />
      <unknownCustomField value="conservé" />
    </Item>
  </HandlingData>
</CHandlingDataMgr>
""",
    "carvariations.meta": """<?xml version="1.0" encoding="UTF-8"?>
<CVehicleModelInfoVariation>
  <variationData>
    <Item>
      <modelName>{name}</modelName>
      <colors><Item><indices content="char_array">111 111 0 0 0 0</indices></Item></colors>
      <kits><Item>{kit}</Item></kits>
      <lightSettings value="1" />
      <sirenSettings value="0" />
    </Item>
  </variationData>
</CVehicleModelInfoVariation>
""",
    "carcols.meta": """<?xml version="1.0" encoding="UTF-8"?>
<CVehicleModelInfoVarGlobal>
  <Kits>
    <Item><kitName>{kit}</kitName><id value="2950" /><visibleMods /></Item>
  </Kits>
  <Lights />
  <Sirens />
</CVehicleModelInfoVarGlobal>
""",
}

DEMO_MANIFEST = """fx_version 'cerulean'
game 'gta5'

files {
  'data/vehicles.meta',
  'data/handling.meta',
  'data/carvariations.meta',
  'data/carcols.meta',
}

data_file 'HANDLING_FILE' 'data/handling.meta'
data_file 'VEHICLE_METADATA_FILE' 'data/vehicles.meta'
data_file 'CARCOLS_FILE' 'data/carcols.meta'
data_file 'VEHICLE_VARIATION_FILE' 'data/carvariations.meta'
"""


def write_demo_addon(folder: str | Path, name: str = "lsfdemo") -> Path:
    """Écrit une ressource FiveM de démonstration complète (contenu original, librement utilisable)."""
    root = Path(folder)
    (root / "stream").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "fxmanifest.lua").write_text(DEMO_MANIFEST, encoding="utf-8")
    values = {"name": name, "handling": name.upper(), "kit": f"2950_{name}_modkit"}
    for filename, template in DEMO_METAS.items():
        (root / "data" / filename).write_text(template.format(**values), encoding="utf-8")
    (root / "stream" / f"{name}.yft").write_bytes(build_yft(demo_vehicle(name)))
    (root / "stream" / f"{name}.ytd").write_bytes(build_ytd(demo_textures(name)))
    return root
