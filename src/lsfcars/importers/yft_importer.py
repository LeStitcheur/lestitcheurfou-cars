"""Import des modèles GTA V (.yft / .ydr) : décodage natif, sans conversion simulée.

Chaque os du squelette devient un groupe (transformation locale d'origine, donc pivots
conservés) ; les triangles rattachés à un os deviennent des maillages enfants. Le repère GTA
(Z vers le haut) est converti par une rotation sur le nœud racine : les coordonnées des
sommets restent celles du fichier d'origine, ce qui facilite une réexportation fidèle.

Les textures sont cherchées dans le dictionnaire intégré puis dans les .ytd voisins
(``<modèle>.ytd``, ``<modèle>+hi.ytd``). Les textures introuvables sont signalées.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from lsfcars.fivem.errors import FormatError
from lsfcars.fivem.structure import classify
from lsfcars.fivem.yft import (
    GTA_TO_Y_UP_EULER,
    LOD_LABELS,
    Drawable,
    Fragment,
    ShaderInfo,
    parse_ydr,
    parse_yft,
    split_fragment,
    split_parts,
)
from lsfcars.fivem.ytd import Texture, TextureDecodeError, decode, parse_ytd, png_bytes
from lsfcars.importers.base import (
    ImportedMaterial,
    ImportedNode,
    ImportResult,
    ModelLoadError,
    Progress,
    no_progress,
)
from lsfcars.scene.mesh import MeshData
from lsfcars.scene.transform import Transform

TEXTURE_MAX_SIDE = 1024
_MAP_SUFFIXES = ("_n", "_s", "_spec", "_normal", "_nrm", "_bump")


def companion_ytds(path: Path) -> list[Path]:
    """Dictionnaires de textures associés à un modèle (même dossier)."""
    stem = path.stem.removesuffix("_hi")
    names = (f"{stem}.ytd", f"{stem}+hi.ytd", f"{path.stem}.ytd")
    seen: list[Path] = []
    for name in names:
        candidate = path.with_name(name)
        if candidate.is_file() and candidate not in seen:
            seen.append(candidate)
    return seen


def _material_style(shader: ShaderInfo) -> dict:
    name = shader.name
    if "vehglass" in name or name == "glass":
        return {"base_color": (0.16, 0.2, 0.24, 1.0), "roughness": 0.05, "metallic": 0.0, "opacity": 0.35}
    if "tire" in name:
        return {"base_color": (0.07, 0.07, 0.08, 1.0), "roughness": 0.9, "metallic": 0.0, "opacity": 1.0}
    if "light" in name or "emissive" in name:
        return {"base_color": (0.92, 0.92, 0.9, 1.0), "roughness": 0.15, "metallic": 0.0, "opacity": 1.0}
    if "paint" in name:
        return {"base_color": (0.78, 0.8, 0.84, 1.0), "roughness": 0.3, "metallic": 0.55, "opacity": 1.0}
    return {"base_color": (0.6, 0.62, 0.66, 1.0), "roughness": 0.55, "metallic": 0.15, "opacity": 1.0}


def _is_colour_map(name: str) -> bool:
    lowered = name.lower()
    return not any(lowered.endswith(suffix) for suffix in _MAP_SUFFIXES) and "specmap" not in lowered


def build_result(
    model: Fragment | Drawable,
    source: Path,
    fmt: str,
    textures: dict[str, Texture],
    progress: Progress = no_progress,
) -> ImportResult:
    drawable = model.drawable if isinstance(model, Fragment) else model
    name = model.name or source.stem
    parts = split_fragment(model) if isinstance(model, Fragment) else split_parts(drawable)
    if not parts:
        raise ModelLoadError(f"« {source.name} » ne contient aucune géométrie exploitable.")
    result = ImportResult(source, fmt, "Lecteur natif GTA V (LeStitcheurFou Cars)", [], {})
    result.notes.append(
        f"Décodage natif {fmt.upper()} : niveau de détail {LOD_LABELS['high'].lower()}, {len(parts)} pièces"
    )
    other_lods = [LOD_LABELS[k] for k in drawable.lods if k != "high"]
    if other_lods:
        result.notes.append(f"Niveaux de détail présents non importés : {', '.join(other_lods)}")
    result.warnings.extend(drawable.warnings)

    # Matériaux (un par shader utilisé)
    progress(0.35, "Matériaux et textures")
    missing: set[str] = set()
    decoded: dict[str, bytes | None] = {}
    for index in sorted({p.shader_index for p in parts}):
        shader = (
            drawable.shaders[index]
            if index < len(drawable.shaders)
            else ShaderInfo(index, f"shader_{index}", 0)
        )
        material = ImportedMaterial(
            f"shader:{index}", f"{shader.name}.{index:02d}", **_material_style(shader)
        )
        texture_name = shader.diffuse
        if texture_name and "paint" not in shader.name and _is_colour_map(texture_name):
            texture = textures.get(texture_name.lower())
            if texture is not None:
                if texture_name not in decoded:
                    try:
                        decoded[texture_name] = png_bytes(decode(texture), TEXTURE_MAX_SIDE)
                    except TextureDecodeError as exc:
                        decoded[texture_name] = None
                        result.warnings.append(f"Texture « {texture_name} » non décodée : {exc}")
                if decoded[texture_name]:
                    material.texture_png = decoded[texture_name]
                    material.texture_name = texture_name
                    material.base_color = (1.0, 1.0, 1.0, material.base_color[3])
        result.materials[material.key] = material
    for shader in drawable.shaders:
        for texture_name in shader.textures.values():
            if texture_name.lower() not in textures:
                missing.add(texture_name)
    if missing:
        listed = ", ".join(sorted(missing)[:12]) + (" …" if len(missing) > 12 else "")
        result.warnings.append(
            f"{len(missing)} texture(s) introuvable(s) dans la ressource (souvent partagées par "
            f"le jeu, par exemple vehshare) : {listed}"
        )

    # Hiérarchie : racine (conversion de repère), os, pièces
    progress(0.6, "Hiérarchie et pièces")
    root_key = "root"
    result.nodes.append(
        ImportedNode(
            root_key,
            name,
            None,
            Transform(rotation=list(GTA_TO_Y_UP_EULER)),
            extra={"gta": {"role": "root", "coordinate_system": "gta_z_up", "format": fmt}},
        )
    )
    bones = drawable.skeleton.bones if drawable.skeleton else []
    with_geometry = {p.bone_index for p in parts}
    for bone in bones:
        parent = f"bone:{bone.parent}" if 0 <= bone.parent < len(bones) else root_key
        result.nodes.append(
            ImportedNode(
                f"bone:{bone.index}",
                bone.name,
                parent,
                Transform.from_matrix(bone.local_matrix()),
                extra={
                    "gta": {
                        "role": "bone",
                        "bone_index": bone.index,
                        "bone_tag": bone.tag,
                        "parent_index": bone.parent,
                        "translation": list(bone.translation),
                        "rotation_quat": list(bone.rotation),
                        "scale": list(bone.scale),
                        "anchor": bone.index not in with_geometry,
                    },
                    "category": classify(bone.name),
                },
            )
        )
    counts: dict[int, int] = defaultdict(int)
    for part in parts:
        counts[part.bone_index] += 1
    used: dict[str, int] = defaultdict(int)
    for number, part in enumerate(parts):
        bone_name = bones[part.bone_index].name if 0 <= part.bone_index < len(bones) else name
        shader = drawable.shaders[part.shader_index] if part.shader_index < len(drawable.shaders) else None
        shader_name = shader.name if shader else f"shader_{part.shader_index}"
        node_name = bone_name if counts[part.bone_index] == 1 else f"{bone_name} · {shader_name}"
        used[node_name] += 1
        if used[node_name] > 1:  # plusieurs géométries du même os et du même shader
            node_name = f"{node_name} ({used[node_name]})"
        mesh_key = f"part:{number}"
        result.meshes[mesh_key] = MeshData(
            node_name, part.positions, part.indices, part.normals, uvs=part.uvs
        )
        result.nodes.append(
            ImportedNode(
                mesh_key,
                node_name,
                f"bone:{part.bone_index}" if part.bone_index >= 0 else root_key,
                Transform(),
                mesh_key=mesh_key,
                material_key=f"shader:{part.shader_index}",
                extra={
                    "gta": {"role": "geometry", "bone_index": part.bone_index, "shader": shader_name},
                    "category": classify(bone_name, shader_name),
                },
            )
        )
    progress(1.0, "Modèle prêt")
    return result


class YftImporter:
    name = "Lecteur natif GTA V"
    extensions = {".yft": "Modèle de véhicule GTA V (fragment)", ".ydr": "Modèle GTA V (drawable)"}

    def available(self) -> tuple[bool, str]:
        return True, "Décodage natif intégré (format « gen8 »)"

    def load(self, path: Path, progress: Progress = no_progress) -> ImportResult:
        path = Path(path)
        progress(0.05, f"Lecture de {path.name}")
        try:
            data = path.read_bytes()
            model: Fragment | Drawable
            model = parse_yft(data) if path.suffix.lower() == ".yft" else parse_ydr(data, path.stem)
        except FormatError as exc:
            raise ModelLoadError(f"« {path.name} » : {exc}") from exc
        except OSError as exc:
            raise ModelLoadError(f"Lecture de « {path.name} » impossible : {exc}") from exc
        drawable = model.drawable if isinstance(model, Fragment) else model
        textures = {t.name.lower(): t for t in drawable.textures}
        notes = []
        for ytd in companion_ytds(path):
            try:
                for texture in parse_ytd(ytd.read_bytes()):
                    textures.setdefault(texture.name.lower(), texture)
                notes.append(f"Textures lues dans {ytd.name}")
            except (FormatError, OSError) as exc:
                notes.append(f"Dictionnaire {ytd.name} illisible : {exc}")
        result = build_result(model, path, path.suffix.lower().lstrip("."), textures, progress)
        result.notes.extend(notes)
        return result
