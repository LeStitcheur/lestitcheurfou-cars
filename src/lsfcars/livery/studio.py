"""Livery Studio : opérations sur le document de livrée, toutes inscrites dans l'historique.

Une opération = une étape d'historique (``SetDocument`` + commandes d'images). Les pixels
peints restent dans des calques raster séparés ; textes, logos, formes et bandes restent des
calques paramétriques éditables. La texture composée est publiée dans
``session.live_textures`` : tous les viewports du projet affichent la livrée en temps réel, et
l'export utilise exactement la même composition.

Aucune dépendance Qt Widgets (QtGui pour le rendu du texte et des logos).
"""

from __future__ import annotations

import base64
import copy
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from lsfcars.core.logging_setup import get_logger
from lsfcars.livery import bands, export, raster, render2d
from lsfcars.livery import templates as tpl
from lsfcars.livery.compositor import Compositor, Rect, union
from lsfcars.livery.logos import LogoError, LogoLibrary, blob_key
from lsfcars.livery.model import (
    DEFAULT_SIZE,
    DOC_KEY,
    MAX_SIZE,
    VECTOR_SHAPES,
    Layer,
    LiveryDocument,
    LiveryVariant,
    clone_layer,
    hex_color,
    new_id,
    rgba,
    to_hex,
)
from lsfcars.livery.surface import Hit, LiverySurface
from lsfcars.scene.commands import AddBlob, Command, CompositeCommand, PatchImage, SetDocument, SetImage
from lsfcars.scene.images import ImageBuffer, encode_png

log = get_logger(__name__)

BODY_HINTS = ("carross", "body", "paint", "caisse", "livery", "livree", "sign", "peinture")


class LiveryError(Exception):
    """Erreur présentable à l'utilisateur."""


@dataclass
class LiveTexture:
    """Texture composée publiée aux viewports (mises à jour partielles suivies par version)."""

    array: np.ndarray
    mode: str = "texture"
    version: int = 1
    history: list[tuple[int, Rect | None]] = field(default_factory=list)  # (version, région ; None = tout)

    def publish(self, region: Rect | None) -> None:
        self.version += 1
        self.history.append((self.version, region))
        del self.history[:-32]

    def changes_since(self, version: int) -> Rect | bool:
        """Région modifiée depuis ``version`` ; ``True`` = tout renvoyer, ``False`` = rien."""
        if version == self.version:
            return False
        newer = [r for v, r in self.history if v > version]
        if not self.history or self.history[0][0] > version + 1 or any(r is None for r in newer):
            return True
        region = None
        for r in newer:
            region = union(region, r)
        return region if region is not None else False


@dataclass
class StrokeState:
    engine: raster.StrokeEngine
    layer_id: str
    symmetry: bool
    mode: str  # "2d" / "3d"
    label: str
    last_point: np.ndarray | None = None


def _slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")
    return value or "livree"


class LiveryStudio:
    def __init__(self, session, logos: LogoLibrary | None = None) -> None:  # type: ignore[no-untyped-def]
        self.session = session
        self.scene = session.scene
        self.logos = logos
        self.compositor = Compositor(self.scene, getattr(session.project, "project_dir", None))
        self.live: LiveTexture | None = None
        self.selection: np.ndarray | None = None  # masque de sélection (H, W) uint8, non enregistré
        self.clipboard: dict | None = None
        self._surface: tuple[tuple, LiverySurface] | None = None
        self._stroke: StrokeState | None = None
        self._pending: list[Rect] = []
        self._edit_before: dict | None = None
        if not hasattr(session, "live_textures"):
            session.live_textures = {}
        session.stack.subscribe(self._on_command)

    # --- Document ------------------------------------------------------------------------------
    def document(self) -> LiveryDocument | None:
        return LiveryDocument.from_dict(self.scene.documents.get(DOC_KEY))

    def require(self) -> LiveryDocument:
        doc = self.document()
        if doc is None:
            raise LiveryError("Créez d'abord un document de livrée.")
        return doc

    def variant(self, doc: LiveryDocument, variant_id: str | None = None) -> LiveryVariant:
        variant = doc.variant(variant_id)
        if variant is None:
            raise LiveryError("Aucune variante de livrée active.")
        return variant

    def _push(self, label: str, doc: LiveryDocument | None, commands: list[Command] | None = None) -> None:
        before = copy.deepcopy(self.scene.documents.get(DOC_KEY))
        after = doc.to_dict() if doc is not None else None
        steps = list(commands or []) + [SetDocument(DOC_KEY, before, after, label)]
        self.session.stack.push(CompositeCommand(steps, label))

    def _image_command(self, key: str, buffer: ImageBuffer | None, label: str) -> SetImage:
        return SetImage(key, self.scene.images.get(key), buffer, label)

    def _transaction(self, label: str, action):  # type: ignore[no-untyped-def]
        stack = self.session.stack
        nested = stack.in_transaction
        if not nested:
            stack.begin(label)
        try:
            result = action()
        except Exception:
            if not nested:
                stack.rollback()
            raise
        if not nested:
            stack.commit()
        return result

    # --- Édition interactive (glisser, curseurs) : aperçu puis une seule étape d'historique --------
    def begin_edit(self) -> None:
        if self._edit_before is None:
            self._edit_before = copy.deepcopy(self.scene.documents.get(DOC_KEY))

    def preview(self, mutate) -> None:  # type: ignore[no-untyped-def]
        """Applique ``mutate(doc)`` sans historique (aperçu en direct) ; ``commit_edit`` l'inscrit."""
        self.begin_edit()
        doc = self.require()
        mutate(doc)
        self.scene.documents[DOC_KEY] = doc.to_dict()
        self.refresh()

    def commit_edit(self, label: str = "Modification") -> bool:
        before, self._edit_before = self._edit_before, None
        if before is None:
            return False
        after = copy.deepcopy(self.scene.documents.get(DOC_KEY))
        if before == after:
            return False
        self.session.stack.push(SetDocument(DOC_KEY, before, after, label), execute=False)
        return True

    def cancel_edit(self) -> None:
        before, self._edit_before = self._edit_before, None
        if before is not None:
            self.scene.documents[DOC_KEY] = before
            self.refresh()

    @property
    def editing(self) -> bool:
        return self._edit_before is not None

    # --- Cibles et création -------------------------------------------------------------------
    def candidate_materials(self) -> list[dict]:
        """Matériaux candidats (UV présentes, texture, nom évoquant la carrosserie)."""
        result = []
        for material in self.scene.materials.values():
            nodes = [n for n in self.scene.mesh_nodes() if n.material_id == material.id]
            if not nodes:
                continue
            meshes = [self.session.geometry_for(n) for n in nodes]
            with_uv = sum(1 for m in meshes if m is not None and m.uvs is not None)
            triangles = sum(m.triangle_count for m in meshes if m is not None)
            name = material.name.lower()
            score = (with_uv > 0) * 4 + bool(material.texture) * 2 + any(h in name for h in BODY_HINTS) * 3
            result.append(
                {
                    "id": material.id,
                    "name": material.name,
                    "meshes": len(nodes),
                    "with_uv": with_uv,
                    "triangles": triangles,
                    "texture": material.texture,
                    "score": score + min(triangles / 100000, 1.0),
                }
            )
        return sorted(result, key=lambda c: -c["score"])

    def create_document(
        self,
        material_ids: list[str] | None = None,
        size: int | None = None,
        mode: str | None = None,
        name: str = "Livrée 1",
        template: str | None = None,
        unit: str = "",
    ) -> LiveryDocument:
        if self.document() is not None:
            raise LiveryError("Ce projet possède déjà un document de livrée.")
        candidates = self.candidate_materials()
        if not candidates:
            raise LiveryError("Aucun maillage dans le projet : importez d'abord un véhicule.")
        targets = list(material_ids or [candidates[0]["id"]])
        chosen = [c for c in candidates if c["id"] in targets]
        if not any(c["with_uv"] for c in chosen):
            missing = ", ".join(c["name"] for c in chosen) or "matériau"
            raise LiveryError(
                f"UV absentes sur « {missing} » : impossible de peindre une texture. Utilisez "
                "« Projection UV » (sur confirmation) ou un dépliage avec Blender."
            )
        base = self.scene.materials[targets[0]].texture
        width = height = size or DEFAULT_SIZE
        if base and size is None:
            try:
                with Image.open(self.session.project.project_dir / base) as image:
                    w, h = image.size
                width = min(max(16, 2 ** round(math.log2(max(w, 16)))), 4096)
                height = min(max(16, 2 ** round(math.log2(max(h, 16)))), 4096)
            except OSError:
                base = None
        doc = LiveryDocument(
            width=width,
            height=height,
            targets=targets,
            mode=mode or ("texture" if base else "decal"),
            base_texture=base,
            texture_name=f"{_slug(self.session.project.name)}_sign_1",
        )
        variant = LiveryVariant(name)
        variant.metadata["unit"] = unit
        doc.variants.append(variant)
        doc.active = variant.id
        key = new_id("img-")
        variant.layers.append(Layer("raster", "Peinture", image=key))

        def action() -> None:
            self._push(
                "Nouveau document de livrée",
                doc,
                [self._image_command(key, ImageBuffer.blank(width, height), "Calque")],
            )
            if template:
                self.apply_template(template, variant.id, unit)

        self._transaction("Nouveau document de livrée", action)
        return self.require()

    def delete_document(self) -> None:
        self._push("Suppression du document de livrée", None)
        self._unpublish()

    def set_document(self, **fields) -> None:  # type: ignore[no-untyped-def]
        """Mode, nom de texture, espace de fusion, cibles."""
        doc = self.require()
        for key in ("mode", "texture_name", "blend_space"):
            if fields.get(key) is not None:
                setattr(doc, key, fields[key])
        if fields.get("targets"):
            doc.targets = list(fields["targets"])
        doc.__post_init__()
        self._push("Propriétés du document de livrée", doc)

    def resize_document(self, width: int, height: int) -> None:
        """Change la résolution : les calques raster et masques sont rééchantillonnés."""
        doc = self.require()
        width, height = max(16, min(MAX_SIZE, int(width))), max(16, min(MAX_SIZE, int(height)))
        commands: list[Command] = []
        for key in doc.image_keys():
            image = self.scene.images.get(key)
            if image is None:
                continue
            mode = "L" if image.channels == 1 else "RGBA"
            resized = Image.fromarray(image.array, mode).resize((width, height), Image.LANCZOS)
            commands.append(self._image_command(key, ImageBuffer(np.array(resized, np.uint8)), "Résolution"))
        sx, sy = width / doc.width, height / doc.height
        for layer in [*doc.shared_layers, *(item for v in doc.variants for item in v.layers)]:
            for item in layer.walk():
                _scale_params(item, sx, sy)
        doc.width, doc.height = width, height
        self.selection = None
        self._push(f"Résolution {width}×{height}", doc, commands)

    # --- Surface 3D ----------------------------------------------------------------------------
    def frame(self) -> dict:
        from lsfcars.editor.operations import VehicleEditor

        axes = VehicleEditor(self.session).axes
        up = np.zeros(3)
        up[axes.up_axis] = 1.0
        forward = np.zeros(3)
        forward[axes.longitudinal_axis] = axes.forward_sign
        return {
            "up": up,
            "forward": forward,
            "right": np.cross(forward, up),
            "lateral_axis": axes.lateral_axis,
            "mirror_origin": axes.mirror_origin,
        }

    def surface(self, doc: LiveryDocument | None = None) -> LiverySurface:
        """Surface ciblée (recalculée seulement si la géométrie, les cibles ou les axes changent)."""
        doc = doc or self.require()
        frame = self.frame()
        nodes = []
        for node in self.scene.mesh_nodes():
            if node.material_id in doc.targets:
                world = self.scene.world_matrix(node.id)
                visible = self.scene.effective_visible(node.id)
                nodes.append((node.id, node.asset_id, node.mesh_key, visible, world.round(5).tobytes()))
        uv_transforms = [
            (m.uv_scale, m.uv_offset)
            for m in (self.scene.materials.get(t) for t in doc.targets)
            if m is not None
        ]
        signature = (
            tuple(doc.targets),
            doc.width,
            doc.height,
            tuple(nodes),
            str(uv_transforms),
            tuple(np.round(np.concatenate([frame["up"], frame["forward"]]), 4)),
            frame["mirror_origin"],
        )
        if self._surface is None or self._surface[0] != signature:
            surface = LiverySurface.from_session(self.session, doc.targets, doc.width, doc.height, frame)
            self._surface = (signature, surface)
            self.compositor.surface = surface
            self.compositor.forget()
        return self._surface[1]

    # --- Composition et texture publiée ----------------------------------------------------------
    def refresh(self, rects: list[Rect] | None = None) -> Rect | None:
        """Met à jour la texture composée (région touchée seulement) et la publie aux viewports."""
        doc = self.document()
        if doc is None:
            self._unpublish()
            return None
        variant = doc.active_variant
        if any(layer.kind == "band" for layer in self._all_layers(doc, variant)):
            self.surface(doc)
        pending, self._pending = self._pending, []
        region = self.compositor.update(doc, variant, (rects or []) + pending)
        result = self.compositor.result
        assert result is not None
        if self.live is None or self.live.array is not result:
            self.live = LiveTexture(result, doc.mode)
            self.live.publish(None)
        elif region is not None:
            self.live.publish(region)
        self.live.mode = doc.mode
        targets = set(doc.targets)
        for key in list(self.session.live_textures):
            if key not in targets:
                self.session.live_textures.pop(key)
        for target in targets:
            self.session.live_textures[target] = self.live
        return region

    def _unpublish(self) -> None:
        self.session.live_textures.clear()
        self.live = None
        self.compositor.reset()

    def _all_layers(self, doc: LiveryDocument, variant: LiveryVariant | None) -> list[Layer]:
        layers = [item for layer in doc.shared_layers for item in layer.walk()]
        if variant is not None:
            layers += list(variant.walk())
        return layers

    def composite(self, variant_id: str | None = None) -> np.ndarray:
        """Composition complète (pleine résolution) d'une variante : identique au viewport."""
        doc = self.require()
        variant = self.variant(doc, variant_id)
        if variant.id == doc.active:
            self.refresh()
            assert self.compositor.result is not None
            return self.compositor.result.copy()
        if any(layer.kind == "band" for layer in self._all_layers(doc, variant)):
            self.surface(doc)
        return self.compositor.render_full(doc, variant)

    def _on_command(self, command: Command, action: str) -> None:
        for item in _leaves(command):
            if isinstance(item, PatchImage):
                self._pending.append(item.rect())

    # --- Variantes -------------------------------------------------------------------------------
    def create_variant(
        self, name: str, template: str | None = None, unit: str = "", emergency_variant: str | None = None
    ) -> str:
        doc = self.require()
        variant = LiveryVariant(name.strip() or f"Livrée {len(doc.variants) + 1}")
        variant.metadata["unit"] = unit
        variant.emergency_variant = emergency_variant
        key = new_id("img-")
        variant.layers.append(Layer("raster", "Peinture", image=key))
        doc.variants.append(variant)
        doc.active = variant.id

        def action() -> None:
            self._push(
                "Nouvelle livrée",
                doc,
                [self._image_command(key, ImageBuffer.blank(doc.width, doc.height), "Calque")],
            )
            if template:
                self.apply_template(template, variant.id, unit)

        self._transaction(f"Nouvelle livrée « {variant.name} »", action)
        self._release_inactive()
        return variant.id

    def duplicate_variant(self, variant_id: str, name: str | None = None) -> str:
        doc = self.require()
        source = self.variant(doc, variant_id)
        mapping: dict[str, str] = {}
        clone = LiveryVariant.from_dict(source.to_dict())
        clone.id = new_id("V")
        clone.name = name or f"{source.name} (copie)"
        clone.emergency_variant = None
        clone.layers = [clone_layer(layer, mapping) for layer in source.layers]
        doc.variants.append(clone)
        doc.active = clone.id
        self._push(f"Duplication de « {source.name} »", doc, self._copy_images(mapping))
        return clone.id

    def _copy_images(self, mapping: dict[str, str]) -> list[Command]:
        commands: list[Command] = []
        for old, new in mapping.items():
            image = self.scene.images.get(old)
            if image is not None:
                commands.append(SetImage(new, None, image.copy(), "Copie d'image"))
        return commands

    def rename_variant(self, variant_id: str, name: str) -> None:
        doc = self.require()
        variant = self.variant(doc, variant_id)
        if not name.strip():
            raise LiveryError("Le nom de la livrée ne peut pas être vide.")
        variant.name = name.strip()
        self._push("Renommage de la livrée", doc)

    def delete_variant(self, variant_id: str) -> None:
        doc = self.require()
        variant = self.variant(doc, variant_id)
        if len(doc.variants) <= 1:
            raise LiveryError("Le document doit conserver au moins une livrée.")
        doc.variants = [v for v in doc.variants if v.id != variant.id]
        if doc.active == variant.id:
            doc.active = doc.variants[0].id
        self._push(f"Suppression de « {variant.name} »", doc)  # pixels conservés par l'historique

    def activate_variant(self, variant_id: str) -> None:
        doc = self.require()
        self.variant(doc, variant_id)
        if doc.active == variant_id:
            return
        doc.active = variant_id
        self._push("Livrée active", doc)
        self._release_inactive()

    def set_variant(self, variant_id: str | None = None, **fields) -> None:  # type: ignore[no-untyped-def]
        doc = self.require()
        variant = self.variant(doc, variant_id)
        for key in ("base_visible", "use_shared", "template"):
            if key in fields and fields[key] is not None:
                setattr(variant, key, fields[key])
        if fields.get("metadata"):
            variant.metadata.update(fields["metadata"])
        self._push("Propriétés de la livrée", doc)

    def compare_variants(self, a: str, b: str, preview: int = 256) -> dict:
        """Différence entre deux livrées : part des pixels différents, calques propres, aperçus."""
        doc = self.require()
        va, vb = self.variant(doc, a), self.variant(doc, b)
        ca, cb = self.composite(a), self.composite(b)
        changed = np.abs(ca.astype(np.int16) - cb.astype(np.int16)).max(axis=-1) > 8
        names_a = {layer.name for layer in va.walk()}
        names_b = {layer.name for layer in vb.walk()}

        def thumb(array: np.ndarray) -> np.ndarray:
            return np.array(Image.fromarray(array, "RGBA").resize((preview, preview), Image.BILINEAR))

        return {
            "changed_ratio": float(changed.mean()),
            "only_a": sorted(names_a - names_b),
            "only_b": sorted(names_b - names_a),
            "layers": (sum(1 for _ in va.walk()), sum(1 for _ in vb.walk())),
            "preview_a": thumb(ca),
            "preview_b": thumb(cb),
        }

    def _release_inactive(self) -> int:
        """Libère la mémoire des calques des livrées inactives (réencodés, rechargés à la demande)."""
        doc = self.document()
        if doc is None:
            return 0
        active = doc.active_variant
        keep = active.image_keys() if active else set()
        keep |= {k for layer in doc.shared_layers for k in layer.image_keys()}
        released = 0
        for key in doc.image_keys() - keep:
            image = self.scene.images.get(key)
            if image is not None and image.release():
                released += 1
        return released

    # --- Calques -------------------------------------------------------------------------------
    def _stack_for(self, doc: LiveryDocument, parent: str | None, shared: bool) -> list[Layer]:
        if parent:
            found = doc.find(parent)
            if found is None or found[0].kind != "group":
                raise LiveryError("Groupe introuvable.")
            return found[0].children
        return doc.shared_layers if shared else self.variant(doc).layers

    def add_layer(
        self,
        kind: str,
        name: str | None = None,
        params: dict | None = None,
        parent: str | None = None,
        index: int | None = None,
        shared: bool = False,
        image: ImageBuffer | None = None,
        label: str | None = None,
        extra: list[Command] | None = None,
    ) -> str:
        doc = self.require()
        layer = Layer(kind, name or _default_name(kind, params), params=dict(params or {}))
        commands: list[Command] = list(extra or [])
        if kind == "raster":
            layer.image = new_id("img-")
            buffer = image or ImageBuffer.blank(doc.width, doc.height)
            commands.append(self._image_command(layer.image, buffer, "Calque"))
        stack = self._stack_for(doc, parent, shared)
        stack.insert(len(stack) if index is None else max(0, min(index, len(stack))), layer)
        self._push(label or f"Nouveau calque : {layer.name}", doc, commands)
        return layer.id

    def layer(self, layer_id: str, doc: LiveryDocument | None = None) -> Layer:
        doc = doc or self.require()
        found = doc.find(layer_id)
        if found is None:
            raise LiveryError("Calque introuvable.")
        return found[0]

    def remove_layer(self, layer_id: str) -> None:
        doc = self.require()
        found = doc.find(layer_id)
        if found is None:
            raise LiveryError("Calque introuvable.")
        layer, stack = found
        stack.remove(layer)
        self._push(f"Suppression du calque « {layer.name} »", doc)

    def set_layer(self, layer_id: str, label: str | None = None, **fields) -> None:  # type: ignore[no-untyped-def]
        """Nom, visibilité, verrou, opacité, mode de fusion, activation du masque."""
        doc = self.require()
        layer = self.layer(layer_id, doc)
        for key in ("name", "visible", "locked", "opacity", "blend", "mask_enabled"):
            if key in fields and fields[key] is not None:
                setattr(layer, key, fields[key])
        layer.__post_init__()
        self._push(label or "Propriétés du calque", doc)

    def update_params(self, layer_id: str, label: str | None = None, **params) -> None:  # type: ignore[no-untyped-def]
        doc = self.require()
        layer = self.layer(layer_id, doc)
        if layer.locked:
            raise LiveryError(f"Le calque « {layer.name} » est verrouillé.")
        layer.params.update(copy.deepcopy(params))
        self._push(label or "Modification du calque", doc)

    def duplicate_layer(self, layer_id: str) -> str:
        doc = self.require()
        found = doc.find(layer_id)
        if found is None:
            raise LiveryError("Calque introuvable.")
        layer, stack = found
        mapping: dict[str, str] = {}
        clone = clone_layer(layer, mapping)
        clone.name = f"{layer.name} (copie)"
        stack.insert(stack.index(layer) + 1, clone)
        self._push(f"Duplication du calque « {layer.name} »", doc, self._copy_images(mapping))
        return clone.id

    def move_layer(
        self,
        layer_id: str,
        offset: int = 0,
        parent: str | None = None,
        index: int | None = None,
        reparent: bool = False,
    ) -> None:
        """Monte / descend un calque (``offset``) ou le déplace dans un groupe (``reparent``)."""
        doc = self.require()
        found = doc.find(layer_id)
        if found is None:
            raise LiveryError("Calque introuvable.")
        layer, stack = found
        if reparent:
            if parent and parent in {item.id for item in layer.walk()}:
                raise LiveryError("Un groupe ne peut pas être placé dans lui-même.")
            shared = stack is doc.shared_layers
            stack.remove(layer)
            target = self._stack_for(doc, parent, shared)
            target.insert(len(target) if index is None else max(0, min(index, len(target))), layer)
        else:
            position = stack.index(layer)
            new_position = max(0, min(len(stack) - 1, position + offset))
            if new_position == position:
                return
            stack.insert(new_position, stack.pop(position))
        self._push("Ordre des calques", doc)

    def restructure(self, structure: list) -> None:
        """Réordonne la livrée active d'après une arborescence [(id, [enfants…]), …], haut de pile d'abord."""
        doc = self.require()
        variant = self.variant(doc)
        layers = {layer.id: layer for layer in variant.walk()}

        def build(items: list) -> list[Layer]:
            result = []
            for layer_id, children in reversed(items):  # liste du bas vers le haut
                layer = layers.pop(layer_id, None)
                if layer is None:
                    continue
                layer.children = build(children) if layer.kind == "group" else []
                result.append(layer)
            return result

        rebuilt = build(structure)
        rebuilt[:0] = [
            layer for layer in variant.layers if layer.id in layers
        ]  # non cités : conservés en bas
        variant.layers = rebuilt
        self._push("Ordre des calques", doc)

    def group_layers(self, layer_ids: list[str], name: str = "Groupe") -> str:
        doc = self.require()
        found = [f for f in (doc.find(i) for i in layer_ids) if f is not None]
        if not found:
            raise LiveryError("Sélectionnez au moins un calque à regrouper.")
        stack = found[0][1]
        if any(f[1] is not stack for f in found):
            raise LiveryError("Les calques à regrouper doivent être au même niveau.")
        layers = sorted((f[0] for f in found), key=stack.index)
        position = stack.index(layers[0])
        for layer in layers:
            stack.remove(layer)
        group = Layer("group", name, children=layers)
        stack.insert(position, group)
        self._push(f"Groupe « {name} »", doc)
        return group.id

    def ungroup(self, group_id: str) -> None:
        doc = self.require()
        found = doc.find(group_id)
        if found is None or found[0].kind != "group":
            raise LiveryError("Groupe introuvable.")
        group, stack = found
        position = stack.index(group)
        stack[position : position + 1] = group.children
        self._push("Dégroupement", doc)

    def set_shared(self, layer_id: str, shared: bool) -> None:
        """Rend un calque commun à toutes les livrées (ou propre à la livrée active)."""
        doc = self.require()
        found = doc.find(layer_id)
        if found is None:
            raise LiveryError("Calque introuvable.")
        layer, stack = found
        if (stack is doc.shared_layers) == shared:
            return
        stack.remove(layer)
        (doc.shared_layers if shared else self.variant(doc).layers).append(layer)
        self._push("Élément commun" if shared else "Élément propre à la livrée", doc)

    def rasterize(self, layer: Layer, doc: LiveryDocument) -> np.ndarray:
        """Pixels (pleine taille) d'un calque seul, opacité et masque exclus."""
        out = np.zeros((doc.height, doc.width, 4), np.uint8)
        if layer.kind == "raster":
            image = self.scene.images.get(layer.image or "")
            return image.array.copy() if image is not None else out
        if layer.kind == "group":
            solo = Layer.from_dict({**layer.to_dict(), "opacity": 1.0, "mask": None})
            variant = LiveryVariant("tmp", layers=[solo], base_visible=False, use_shared=False)
            return self.compositor.render_full(LiveryDocument(doc.width, doc.height, mode="decal"), variant)
        if layer.kind == "band":
            self.surface(doc)
        crop = self.compositor.crop(layer, doc)
        if crop is not None:
            x0, y0, data = crop
            out[y0 : y0 + data.shape[0], x0 : x0 + data.shape[1]] = data
        return out

    def rasterize_layer(self, layer_id: str) -> None:
        """Convertit un calque paramétrique en calque raster (action explicite, annulable)."""
        doc = self.require()
        layer = self.layer(layer_id, doc)
        if layer.kind == "raster":
            return
        pixels = self.rasterize(layer, doc)
        key = new_id("img-")
        layer.kind, layer.image, layer.params, layer.children = "raster", key, {}, []
        command = self._image_command(key, ImageBuffer(pixels), "Pixels")
        self._push(f"Pixellisation de « {layer.name} »", doc, [command])

    def merge_down(self, layer_id: str) -> str:
        """Fusionne un calque avec celui du dessous en un calque raster (opacité, fusion et masque inclus)."""
        doc = self.require()
        found = doc.find(layer_id)
        if found is None:
            raise LiveryError("Calque introuvable.")
        layer, stack = found
        position = stack.index(layer)
        if position == 0:
            raise LiveryError("Aucun calque en dessous pour fusionner.")
        below = stack[position - 1]
        if "band" in (layer.kind, below.kind):
            self.surface(doc)
        pair = LiveryVariant("tmp", layers=[below, layer], base_visible=False, use_shared=False)
        tmp_doc = LiveryDocument(doc.width, doc.height, mode="decal", blend_space=doc.blend_space)
        pixels = self.compositor.render_full(tmp_doc, pair)
        key = new_id("img-")
        merged = Layer("raster", below.name, image=key)
        stack[position - 1 : position + 1] = [merged]
        command = self._image_command(key, ImageBuffer(pixels), "Fusion")
        self._push(f"Fusion de « {layer.name} » vers le bas", doc, [command])
        return merged.id

    # --- Masques -----------------------------------------------------------------------------------
    def add_mask(self, layer_id: str, from_selection: bool = False) -> None:
        doc = self.require()
        layer = self.layer(layer_id, doc)
        if layer.mask:
            raise LiveryError("Ce calque a déjà un masque.")
        if from_selection and self.selection is not None:
            data = self.selection.copy()
        else:
            data = np.full((doc.height, doc.width), 255, np.uint8)
        layer.mask = new_id("img-")
        layer.mask_enabled = True
        self._push("Masque de calque", doc, [self._image_command(layer.mask, ImageBuffer(data), "Masque")])

    def invert_mask(self, layer_id: str) -> None:
        doc = self.require()
        layer = self.layer(layer_id, doc)
        mask = self.scene.images.get(layer.mask or "")
        if mask is None or layer.mask is None:
            raise LiveryError("Ce calque n'a pas de masque.")
        command = self._image_command(layer.mask, ImageBuffer(255 - mask.array), "Masque")
        self._push("Inversion du masque", doc, [command])

    def apply_mask(self, layer_id: str) -> None:
        """Applique définitivement le masque (le calque devient raster)."""
        doc = self.require()
        layer = self.layer(layer_id, doc)
        mask = self.scene.images.get(layer.mask or "")
        if mask is None:
            raise LiveryError("Ce calque n'a pas de masque.")
        pixels = self.rasterize(layer, doc)
        pixels[..., 3] = (pixels[..., 3].astype(np.uint16) * mask.array // 255).astype(np.uint8)
        key = new_id("img-")
        layer.kind, layer.image, layer.params, layer.children = "raster", key, {}, []
        layer.mask = None
        command = self._image_command(key, ImageBuffer(pixels), "Masque appliqué")
        self._push("Application du masque", doc, [command])

    def delete_mask(self, layer_id: str) -> None:
        doc = self.require()
        layer = self.layer(layer_id, doc)
        layer.mask = None
        self._push("Suppression du masque", doc)

    # --- Peinture ---------------------------------------------------------------------------------
    def _paint_target(self, layer_id: str, target: str) -> tuple[Layer, str, ImageBuffer]:
        doc = self.require()
        layer = self.layer(layer_id, doc)
        if layer.locked:
            raise LiveryError(f"Le calque « {layer.name} » est verrouillé.")
        if not layer.visible:
            raise LiveryError(f"Le calque « {layer.name} » est masqué : affichez-le pour peindre.")
        key = layer.mask if target == "mask" else layer.image
        if target == "mask" and not key:
            raise LiveryError("Ce calque n'a pas de masque.")
        if target != "mask" and layer.kind != "raster":
            raise LiveryError(
                f"« {layer.name} » est un {layer.label.lower()} : peignez sur un calque raster "
                "(ou pixellisez-le)."
            )
        image = self.scene.images.get(key or "")
        if image is None or key is None:
            raise LiveryError("Pixels du calque absents.")
        return layer, key, image

    def begin_stroke(
        self,
        layer_id: str,
        color: str,
        settings: raster.BrushSettings,
        target: str = "layer",
        symmetry: bool = False,
        mode: str = "2d",
        lock_alpha: bool = False,
    ) -> None:
        if self._stroke is not None:
            self.end_stroke()
        layer, key, image = self._paint_target(layer_id, target)
        engine = raster.StrokeEngine(image, key, rgba(color), settings, self.selection, lock_alpha)
        label = "Gomme" if settings.eraser else ("Peinture 3D" if mode == "3d" else "Pinceau")
        self._stroke = StrokeState(engine, layer.id, symmetry, mode, label)

    @property
    def stroking(self) -> bool:
        return self._stroke is not None

    def stroke_2d(self, x: float, y: float, pressure: float = 1.0) -> Rect | None:
        stroke = self._stroke
        if stroke is None:
            return None
        stroke.engine.stroke_to(x, y, pressure)
        if stroke.symmetry:
            mirrored = self.surface().mirror_pixel(x, y)
            if mirrored is not None:
                stroke.engine.dab(mirrored[0].x, mirrored[0].y, pressure)
        return self._live_update(stroke.engine)

    def brush_radius_m(self, size_px: float) -> float:
        """Rayon 3D (mètres) équivalent à un diamètre en pixels de texture (densité moyenne)."""
        density = self.surface().texel_density()
        return (size_px / 2.0) / density if density > 0 else 0.05

    def stroke_3d(self, origin, direction, pressure: float = 1.0) -> Hit | None:  # type: ignore[no-untyped-def]
        """Peinture directe sur la carrosserie : rayon → point 3D → texels dans la sphère du pinceau."""
        stroke = self._stroke
        if stroke is None:
            return None
        surface = self.surface()
        hit = surface.raycast(origin, direction)
        if hit is None:
            return None
        settings = stroke.engine.settings
        scale = pressure if settings.pressure_size else 1.0
        radius = self.brush_radius_m(settings.size) * max(scale, 0.05)
        points = [hit.point]
        if stroke.last_point is not None:  # espacement régulier entre deux positions de la souris
            step = max(radius * 2 * settings.spacing, 1e-4)
            distance = float(np.linalg.norm(hit.point - stroke.last_point))
            count = min(int(distance / step), 200)
            if count:
                points = [
                    stroke.last_point + (hit.point - stroke.last_point) * (i / count)
                    for i in range(1, count + 1)
                ]
        stroke.last_point = hit.point
        for point in points:
            targets = [(point, hit.normal)]
            if stroke.symmetry:
                targets.append((surface.mirror_point(point), surface.mirror_vector(hit.normal)))
            for target, normal in targets:
                for x0, y0, alpha in surface.brush_patches(target, radius, settings.hardness, normal):
                    if settings.pressure_opacity:
                        alpha = alpha * max(0.0, min(1.0, pressure))
                    stroke.engine.apply(x0, y0, alpha)
        self._live_update(stroke.engine)
        return hit

    def _live_update(self, engine: raster.StrokeEngine) -> Rect | None:
        dirty = engine.take_dirty()
        if dirty is None:
            return None
        return self.refresh([dirty])

    def end_stroke(self) -> int:
        stroke, self._stroke = self._stroke, None
        if stroke is None:
            return 0
        commands = stroke.engine.commands(stroke.label)
        if commands:
            self.session.stack.push(CompositeCommand(list(commands), stroke.label), execute=False)
        return len(commands)

    def cancel_stroke(self) -> None:
        stroke, self._stroke = self._stroke, None
        if stroke is not None:
            stroke.engine.cancel()
            self.refresh([(0, 0, stroke.engine.width, stroke.engine.height)])

    def _patch(self, key: str, image: ImageBuffer, rect: Rect, new: np.ndarray, label: str) -> None:
        x0, y0, x1, y1 = rect
        before = image.array[y0:y1, x0:x1].copy()
        self.session.stack.push(PatchImage(key, x0, y0, before, new, label))

    def fill(
        self,
        layer_id: str,
        x: float,
        y: float,
        color: str,
        tolerance: int = 32,
        mode: str = "color",
        opacity: float = 1.0,
        target: str = "layer",
    ) -> Rect | None:
        """Remplissage : zone de couleur contiguë (aspect composé), îlot UV sous le curseur ou sélection."""
        doc = self.require()
        _layer, key, image = self._paint_target(layer_id, target)
        xi, yi = int(x), int(y)
        if not (0 <= xi < doc.width and 0 <= yi < doc.height):
            return None
        if mode == "island":
            region = self.surface(doc).island_mask(x, y)
            if region is None:
                raise LiveryError("Aucun îlot UV sous le curseur.")
        elif mode == "selection":
            if self.selection is None:
                raise LiveryError("Aucune sélection active.")
            region = self.selection > 0
        else:
            source = (
                self.composite() if image.channels == 4 else np.repeat(image.array[..., None], 4, axis=-1)
            )
            region = raster.connected_region(raster.similar_mask(source, xi, yi, tolerance), xi, yi)
        if self.selection is not None and mode != "selection":
            region = region & (self.selection > 0)
        ys, xs = np.nonzero(region)
        if not len(xs):
            return None
        rect = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        sub = image.array[rect[1] : rect[3], rect[0] : rect[2]].copy()
        local = region[rect[1] : rect[3], rect[0] : rect[2]]
        r, g, b, a = rgba(color)
        if image.channels == 1:
            value = np.uint8(round(r * 0.2126 + g * 0.7152 + b * 0.0722))
            sub = np.where(local, value, sub).astype(np.uint8)
        else:
            raster.paint_over(
                sub, np.asarray((r, g, b), np.float32), local.astype(np.float32) * opacity * a / 255.0
            )
        self._patch(key, image, rect, sub, "Remplissage")
        self.refresh([rect])
        return rect

    def gradient(
        self,
        layer_id: str,
        p0: tuple[float, float],
        p1: tuple[float, float],
        c0: str,
        c1: str,
        kind: str = "linear",
        opacity: float = 1.0,
    ) -> Rect | None:
        doc = self.require()
        _layer, key, image = self._paint_target(layer_id, "layer")
        rect = (0, 0, doc.width, doc.height)
        mask = (self.selection > 0) if self.selection is not None else None
        if mask is not None:
            bounds = self.selection_bounds()
            if bounds is None:
                return None
            rect = bounds
        grad = raster.gradient(doc.width, doc.height, p0, p1, rgba(c0), rgba(c1), kind, rect)
        sub = image.array[rect[1] : rect[3], rect[0] : rect[2]].copy()
        coverage = grad[..., 3].astype(np.float32) / 255.0 * opacity
        if mask is not None:
            coverage *= mask[rect[1] : rect[3], rect[0] : rect[2]]
        raster.paint_over(sub, grad[..., :3].astype(np.float32), coverage)
        self._patch(key, image, rect, sub, "Dégradé")
        self.refresh([rect])
        return rect

    def pick_color(self, x: float, y: float) -> str:
        doc = self.require()
        self.refresh()
        result = self.compositor.result
        assert result is not None
        xi, yi = int(min(max(x, 0), doc.width - 1)), int(min(max(y, 0), doc.height - 1))
        r, g, b, a = (int(v) for v in result[yi, xi])
        return to_hex(r, g, b, a)

    # --- Sélection -----------------------------------------------------------------------------
    def _selection_base(self, doc: LiveryDocument, op: str) -> np.ndarray:
        if op == "replace" or self.selection is None or self.selection.shape != (doc.height, doc.width):
            return np.zeros((doc.height, doc.width), np.uint8)
        return self.selection

    def _combine(self, base: np.ndarray, shape: np.ndarray, op: str) -> None:
        if op == "subtract":
            base[shape > 0] = 0
        else:
            np.maximum(base, shape, out=base)
        self.selection = base if base.any() else None

    def select_rect(self, x0: float, y0: float, x1: float, y1: float, op: str = "replace") -> None:
        doc = self.require()
        base = self._selection_base(doc, op)
        shape = np.zeros_like(base)
        ax, bx = sorted((max(int(round(x0)), 0), max(int(round(x1)), 0)))
        ay, by = sorted((max(int(round(y0)), 0), max(int(round(y1)), 0)))
        shape[ay:by, ax:bx] = 255
        self._combine(base, shape, op)

    def select_polygon(self, points: list[tuple[float, float]], op: str = "replace") -> None:
        """Sélection libre (lasso) : polygone rempli."""
        doc = self.require()
        if len(points) < 3:
            return
        mask = Image.new("L", (doc.width, doc.height), 0)
        ImageDraw.Draw(mask).polygon([(float(x), float(y)) for x, y in points], fill=255)
        self._combine(self._selection_base(doc, op), np.array(mask, np.uint8), op)

    def select_island(self, x: float, y: float, op: str = "replace") -> None:
        doc = self.require()
        island = self.surface(doc).island_mask(x, y)
        if island is None:
            raise LiveryError("Aucun îlot UV sous le curseur.")
        self._combine(self._selection_base(doc, op), island.astype(np.uint8) * 255, op)

    def select_all(self) -> None:
        doc = self.require()
        self.selection = np.full((doc.height, doc.width), 255, np.uint8)

    def clear_selection(self) -> None:
        self.selection = None

    def selection_bounds(self) -> Rect | None:
        if self.selection is None:
            return None
        ys, xs = np.nonzero(self.selection)
        if not len(xs):
            return None
        return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)

    # --- Presse-papiers ------------------------------------------------------------------------
    def copy(self, layer_id: str | None = None) -> bool:
        """Copie la sélection (d'un calque ou de la composition) ou un calque paramétrique entier."""
        doc = self.require()
        layer = self.layer(layer_id, doc) if layer_id else None
        if layer is not None and layer.kind != "raster" and self.selection is None:
            mapping: dict[str, str] = {}
            clone = clone_layer(layer, mapping)
            images = {
                new: self.scene.images[old].copy() for old, new in mapping.items() if old in self.scene.images
            }
            self.clipboard = {"layer": clone.to_dict(), "images": images}
            return True
        rect = self.selection_bounds() or (0, 0, doc.width, doc.height)
        source = self.rasterize(layer, doc) if layer is not None else self.composite()
        pixels = source[rect[1] : rect[3], rect[0] : rect[2]].copy()
        if self.selection is not None:
            sel = self.selection[rect[1] : rect[3], rect[0] : rect[2]].astype(np.uint16)
            pixels[..., 3] = (pixels[..., 3] * sel // 255).astype(np.uint8)
        self.clipboard = {"pixels": pixels, "rect": rect}
        return True

    def cut(self, layer_id: str) -> bool:
        if self.selection is None:
            raise LiveryError("Couper nécessite une sélection.")
        _layer, key, image = self._paint_target(layer_id, "layer")
        self.copy(layer_id)
        rect = self.selection_bounds()
        if rect is None:
            return False
        sub = image.array[rect[1] : rect[3], rect[0] : rect[2]].copy()
        keep = 255 - self.selection[rect[1] : rect[3], rect[0] : rect[2]].astype(np.uint16)
        sub[..., 3] = (sub[..., 3] * keep // 255).astype(np.uint8)
        self._patch(key, image, rect, sub, "Couper")
        self.refresh([rect])
        return True

    def paste(self) -> str | None:
        """Colle en nouveau calque : pixels → calque image transformable, calque → copie éditable."""
        doc = self.require()
        clip = self.clipboard
        if not clip:
            return None
        if "layer" in clip:
            mapping: dict[str, str] = {}
            layer = clone_layer(Layer.from_dict(clip["layer"]), mapping)
            layer.name = f"{layer.name} (collé)"
            commands: list[Command] = [
                SetImage(new, None, clip["images"][old].copy(), "Coller")
                for old, new in mapping.items()
                if old in clip["images"]
            ]
            self.variant(doc).layers.append(layer)
            self._push("Coller", doc, commands)
            return layer.id
        pixels, rect = clip["pixels"], clip["rect"]
        data = encode_png(pixels)
        key = blob_key(data)
        params = {
            "blob": key,
            "x": (rect[0] + rect[2]) / 2,
            "y": (rect[1] + rect[3]) / 2,
            "width": float(pixels.shape[1]),
            "height": float(pixels.shape[0]),
            "source": "clipboard",
        }
        return self.add_layer("image", "Collage", params, extra=[AddBlob(key, data)], label="Coller")

    # --- Éléments : formes, textes, logos, bandes ----------------------------------------------
    def add_shape(
        self,
        shape: str,
        points: list[tuple[float, float]],
        fill: str | None = "#2563EB",
        stroke: str | None = None,
        stroke_width: float = 0.0,
        **extra,  # type: ignore[no-untyped-def]
    ) -> str:
        if shape not in VECTOR_SHAPES:
            raise LiveryError(f"Forme inconnue : {shape}")
        params = {
            "shape": shape,
            "points": [[float(x), float(y)] for x, y in points],
            "fill": fill,
            "stroke": stroke,
            "stroke_width": float(stroke_width),
            **extra,
        }
        return self.add_layer("vector", params=params)

    def add_text(
        self, text: str, x: float, y: float, size: float = 96.0, color: str = "#F3F6FC", **style
    ) -> str:  # type: ignore[no-untyped-def]
        if not text.strip():
            raise LiveryError("Le texte est vide.")
        params = {
            "text": text,
            "x": float(x),
            "y": float(y),
            "size": float(size),
            "color": hex_color(color),
            "align": "center",
            "font_family": style.pop("font_family", None) or render2d.default_family(),
            **style,
        }
        return self.add_layer("text", params=params)

    def _logo_blob(self, logo_id: str) -> tuple[str, bytes, dict]:
        if self.logos is None:
            raise LiveryError("Bibliothèque de logos indisponible.")
        entry = self.logos.get(logo_id)
        if entry is None:
            raise LiveryError(f"Logo inconnu : {logo_id}")
        try:
            data = self.logos.data(logo_id)
        except LogoError as exc:
            raise LiveryError(str(exc)) from exc
        return blob_key(data), data, entry.provenance()

    def _register_logo(self, doc: LiveryDocument, logo_id: str) -> tuple[dict, list[Command]]:
        key, data, provenance = self._logo_blob(logo_id)
        w, h = render2d.source_size(data)
        if not any(p.get("logo_id") == logo_id for p in doc.provenance):
            doc.provenance.append(provenance | {"blob": key})
        params = {
            "blob": key,
            "logo_id": logo_id,
            "width": 256.0,
            "height": 256.0 * h / max(w, 1),
            "keep_ratio": True,
        }
        return params | {"_name": provenance["name"]}, [AddBlob(key, data)]

    def add_logo(self, logo_id: str, x: float, y: float, width: float = 256.0, **params) -> str:  # type: ignore[no-untyped-def]
        doc = self.require()
        base, commands = self._register_logo(doc, logo_id)
        name = base.pop("_name")
        ratio = base["height"] / base["width"]
        base.update(x=float(x), y=float(y), width=float(width), height=float(width) * ratio, **params)
        layer = Layer("image", name, params=base)
        self.variant(doc).layers.append(layer)
        self._push(f"Logo « {name} »", doc, commands)
        return layer.id

    def add_band(self, name: str = "Bande", **params) -> str:  # type: ignore[no-untyped-def]
        defaults = {
            "zone": "sides",
            "orientation": "longitudinal",
            "center_height": 0.55,
            "width": 0.12,
            "color": "#2563EB",
            "color2": "#F3F6FC",
            "pattern": "solid",
            "period": 0.3,
            "side": "both",
        }
        if not self.surface().triangle_count:
            raise LiveryError("Aucune surface UV ciblée : impossible de calculer une bande 3D.")
        return self.add_layer("band", name, {**defaults, **params})

    def transform_layer(
        self,
        layer_id: str,
        dx: float = 0.0,
        dy: float = 0.0,
        rotation: float = 0.0,
        scale: float = 1.0,
        label: str = "Transformation",
    ) -> None:
        doc = self.require()
        layer = self.layer(layer_id, doc)
        if layer.locked:
            raise LiveryError(f"Le calque « {layer.name} » est verrouillé.")
        if layer.kind in ("raster", "band"):
            raise LiveryError("Transformez un texte, un logo, une forme ou un groupe d'éléments.")
        transform_params(layer, dx, dy, rotation, scale)
        if dx or dy:
            layer.params.pop("anchor", None)
        self._push(label, doc)

    def align_layers(self, layer_ids: list[str], mode: str, reference: str = "canvas") -> None:
        """Aligne des éléments sur la texture, la sélection ou l'îlot UV qui les contient."""
        doc = self.require()
        canvas = (0, 0, doc.width, doc.height)
        if reference == "selection" and self.selection_bounds() is None:
            raise LiveryError("Aucune sélection active.")
        for layer_id in layer_ids:
            layer = self.layer(layer_id, doc)
            if layer.kind not in ("text", "image", "vector"):
                continue
            bounds = render2d.element_bounds(layer, self.scene.blobs)
            ref = canvas
            if reference == "selection":
                ref = self.selection_bounds() or canvas
            elif reference == "island":
                found = self.surface(doc).island_mask(bounds.center().x(), bounds.center().y())
                if found is not None:
                    ys, xs = np.nonzero(found)
                    ref = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
            dx = dy = 0.0
            if mode == "left":
                dx = ref[0] - bounds.left()
            elif mode == "right":
                dx = ref[2] - bounds.right()
            elif mode in ("center", "hcenter"):
                dx = (ref[0] + ref[2]) / 2 - bounds.center().x()
            if mode == "top":
                dy = ref[1] - bounds.top()
            elif mode == "bottom":
                dy = ref[3] - bounds.bottom()
            elif mode in ("center", "vcenter"):
                dy = (ref[1] + ref[3]) / 2 - bounds.center().y()
            transform_params(layer, dx, dy, 0.0, 1.0)
        self._push("Alignement", doc)

    # --- Placement 3D et symétrie -----------------------------------------------------------------
    def _anchor_point(
        self, zone: str, lon: float, height: float, side: str
    ) -> tuple[np.ndarray, np.ndarray] | None:
        """Point de départ (hors carrosserie) et direction de visée pour une zone du véhicule."""
        surface = self.surface()
        frame = surface.frame
        bmin, bmax = surface.bounds
        center = (bmin + bmax) / 2
        up, fwd, right = (np.asarray(frame[k], np.float64) for k in ("up", "forward", "right"))
        low = float(np.dot(center, up)) - float(bands.vehicle_coords(surface, center[None])["height"][0])
        reach = float(np.linalg.norm(bmax - bmin)) + 1.0
        at_height = center + fwd * lon + up * (low + height - float(np.dot(center, up)))
        if zone in ("sides", "left", "right"):
            sign = -1.0 if (zone == "left" or (zone == "sides" and side == "left")) else 1.0
            return at_height + right * sign * reach, right * sign
        if zone in ("roof", "hood", "trunk", "top"):
            found = bands.zone_center(surface, zone) if zone != "top" else None
            base = found[0] if found is not None else center
            return base + fwd * lon + up * reach, up
        if zone in ("front", "rear"):
            sign = 1.0 if zone == "front" else -1.0
            return at_height - fwd * lon + fwd * sign * reach, fwd * sign
        return None

    def _resolve(
        self, params: dict, zone: str, lon: float, height: float, side: str, size_m: float | None, kind: str
    ) -> bool | None:
        """Calcule position, rotation, retournement et taille d'un élément posé sur une zone."""
        surface = self.surface()
        anchor = self._anchor_point(zone, lon, height, side)
        if anchor is None:
            return None
        start, normal = anchor
        hit = surface.raycast(start, -normal)
        target = hit.point if hit is not None else start - normal * 1.0
        placement = surface.placement(target, normal)
        if placement is None:
            return None
        mirrored = bool(params.pop("mirrored", False))  # lecture au rétroviseur (capot d'ambulance)
        params.update(x=placement.x, y=placement.y, rotation=placement.rotation)
        params["flip_v"] = bool(placement.flip)
        params["flip_h"] = mirrored
        params["scale_y"] = placement.stretch
        if size_m:
            if kind == "text":
                params["size"] = size_m * placement.px_per_m
            else:
                ratio = float(params.get("height", 1.0)) / max(float(params.get("width", 1.0)), 1e-6)
                params["width"] = size_m * placement.px_per_m
                params["height"] = params["width"] * ratio
        if kind == "text" and placement.tri >= 0:
            self._fit_to_island(params, placement.tri)
        params["anchor"] = {
            "zone": zone,
            "lon": lon,
            "height": height,
            "side": side,
            "point": [float(v) for v in target],
        }
        return True

    def _fit_to_island(self, params: dict, tri: int, margin: float = 0.9) -> None:
        """Réduit un texte trop grand pour son îlot UV (il déborderait hors de la pièce)."""
        x0, y0, x1, y1 = self.surface().island_bounds(tri)
        bounds = render2d.element_bounds(Layer("text", "ajustement", params=params), self.scene.blobs)
        if bounds.isEmpty():
            return
        ratio = min((x1 - x0) * margin / bounds.width(), (y1 - y0) * margin / bounds.height(), 1.0)
        if ratio < 1.0:
            params["size"] = float(params.get("size", 64.0)) * ratio

    def place_on_zone(
        self,
        layer_id: str,
        zone: str,
        lon: float = 0.0,
        height: float = 0.6,
        side: str = "left",
        size_m: float | None = None,
    ) -> None:
        """Place un texte ou un logo sur une zone de la carrosserie (orientation du dépliage respectée)."""
        doc = self.require()
        layer = self.layer(layer_id, doc)
        if layer.kind not in ("text", "image"):
            raise LiveryError("Seuls les textes et les logos se placent sur une zone.")
        if self._resolve(layer.params, zone, lon, height, side, size_m, layer.kind) is None:
            raise LiveryError(f"Zone « {bands.ZONES.get(zone, zone)} » introuvable sur la surface ciblée.")
        self._push(f"Placement : {bands.ZONES.get(zone, zone).lower()}", doc)

    def add_text_on_zone(
        self,
        text: str,
        zone: str,
        size_m: float = 0.15,
        lon: float = 0.0,
        height: float = 0.6,
        mirror_sides: bool = True,
        **style,
    ) -> list[str]:  # type: ignore[no-untyped-def]
        """Marquage placé sur une zone ; sur les flancs, une copie symétrique est créée de l'autre côté."""
        doc = self.require()
        created = self._zone_layers(doc, "text", text, zone, size_m, lon, height, mirror_sides, style)
        self._push(f"Marquage « {text} »", doc, created[1])
        return created[0]

    def add_logo_on_zone(
        self,
        logo_id: str,
        zone: str,
        size_m: float = 0.3,
        lon: float = 0.0,
        height: float = 0.6,
        mirror_sides: bool = True,
        tint: str | None = None,
    ) -> list[str]:
        doc = self.require()
        style = {"tint": tint} if tint else {}
        created = self._zone_layers(doc, "image", logo_id, zone, size_m, lon, height, mirror_sides, style)
        self._push("Logo sur la carrosserie", doc, created[1])
        return created[0]

    def _zone_layers(
        self,
        doc: LiveryDocument,
        kind: str,
        content: str,
        zone: str,
        size_m: float,
        lon: float,
        height: float,
        mirror_sides: bool,
        style: dict,
        stack: list[Layer] | None = None,
        name: str | None = None,
    ) -> tuple[list[str], list[Command]]:
        sides = ["left", "right"] if (zone == "sides" and mirror_sides) else [None]
        stack = stack if stack is not None else self.variant(doc).layers
        created: list[str] = []
        commands: list[Command] = []
        for side in sides:
            if kind == "text":
                params = {
                    "text": content,
                    "size": 64.0,
                    "color": "#F3F6FC",
                    "align": "center",
                    "font_family": render2d.default_family(),
                    **copy.deepcopy(style),
                }
                label = name or content.replace("\n", " ")
            else:
                params, extra = self._register_logo(doc, content)
                label = name or params.pop("_name")
                params.pop("_name", None)
                if style.get("tint"):
                    params.update(tint=style["tint"], tint_enabled=True)
                commands += extra
            target_zone = zone if side is None else side
            if self._resolve(params, target_zone, lon, height, side or "left", size_m, kind) is None:
                continue
            suffix = f" ({'gauche' if side == 'left' else 'droite'})" if side else ""
            layer = Layer(kind, label + suffix, params=params)
            stack.append(layer)
            created.append(layer.id)
        if not created:
            raise LiveryError(f"Zone « {bands.ZONES.get(zone, zone)} » introuvable sur la surface ciblée.")
        return created, commands

    def mirror_layer(self, layer_id: str) -> str:
        """Copie symétrique (côté opposé du véhicule) d'un texte, logo, forme ou bande.

        La position, la rotation et le retournement sont recalculés d'après l'orientation réelle
        du dépliage UV de chaque côté (aucun simple retournement horizontal de l'image).
        """
        doc = self.require()
        found = doc.find(layer_id)
        if found is None:
            raise LiveryError("Calque introuvable.")
        layer, stack = found
        surface = self.surface(doc)
        mapping: dict[str, str] = {}
        clone = clone_layer(layer, mapping)
        clone.name = _mirror_name(layer.name)
        params = clone.params
        if layer.kind in ("text", "image"):
            x, y = float(params.get("x", 0)), float(params.get("y", 0))
            mirrored = surface.mirror_pixel(x, y)
            source = surface.surface_at(x, y)
            if mirrored is None or source is None:
                raise LiveryError("Aucune surface correspondante de l'autre côté du véhicule.")
            placement, point = mirrored
            src = surface.placement(source[0], source[1])
            relative = float(params.get("rotation", 0.0)) - (src.rotation if src else 0.0)
            params["x"], params["y"] = placement.x, placement.y
            params["rotation"] = placement.rotation + relative
            params["flip_v"] = (
                bool(params.get("flip_v", False)) ^ bool(src.flip if src else False) ^ placement.flip
            )
            if src and src.px_per_m > 0:
                ratio = placement.px_per_m / src.px_per_m
                if layer.kind == "text":
                    params["size"] = float(params.get("size", 64)) * ratio
                else:
                    params["width"] = float(params.get("width", 256)) * ratio
                    params["height"] = float(params.get("height", 256)) * ratio
            if isinstance(params.get("anchor"), dict):
                params["anchor"]["point"] = [float(v) for v in point]
                params["anchor"]["side"] = "right" if params["anchor"].get("side") == "left" else "left"
        elif layer.kind == "vector":
            new_points = []
            for px, py in params.get("points") or []:
                mirrored = surface.mirror_pixel(float(px), float(py))
                if mirrored is None:
                    raise LiveryError("Une partie de la forme n'a pas de correspondance de l'autre côté.")
                new_points.append([mirrored[0].x, mirrored[0].y])
            params["points"] = new_points
        elif layer.kind == "band":
            side = params.get("side", "both")
            if side == "both":
                raise LiveryError("Cette bande couvre déjà les deux côtés (symétrique par construction).")
            params["side"] = "right" if side == "left" else "left"
        else:
            raise LiveryError("Symétrie d'un calque raster : activez la symétrie pendant la peinture.")
        stack.insert(stack.index(layer) + 1, clone)
        self._push(f"Symétrie de « {layer.name} »", doc, self._copy_images(mapping))
        return clone.id

    # --- Modèles --------------------------------------------------------------------------------
    def apply_template(self, key: str, variant_id: str | None = None, unit: str = "") -> list[str]:
        """Applique un modèle : groupes Bandes, Marquages, Logos (calques éditables)."""
        template = tpl.TEMPLATES_BY_KEY.get(key)
        if template is None:
            raise LiveryError(f"Modèle inconnu : {key}")
        doc = self.require()
        variant = self.variant(doc, variant_id)
        doc.active = variant.id
        unit = unit or variant.metadata.get("unit") or "12"
        surface = self.surface(doc)
        if template.elements and not surface.triangle_count:
            raise LiveryError("Aucune surface UV ciblée : le modèle ne peut pas être placé.")
        body_height = bands.vehicle_coords(surface, surface.centroids[:1])["total_height"] or 1.0
        groups = {name: Layer("group", name) for name in ("Bandes", "Marquages", "Logos")}
        commands: list[Command] = []
        for element in template.elements:
            if element["type"] == "band":
                params = {
                    "zone": "sides",
                    "orientation": "longitudinal",
                    "width": 0.12,
                    "center_height": 0.55,
                    "pattern": "solid",
                    "period": 0.3,
                    "side": "both",
                    "color2": "#F3F6FC",
                    **element["params"],
                }
                if "center_frac" in params:  # hauteur relative : adaptée à la carrosserie
                    params["center_height"] = params.pop("center_frac") * body_height
                groups["Bandes"].children.append(Layer("band", element["name"], params=params))
                continue
            if element["type"] == "text":
                content, kind, group = element["text"].replace("{unit}", unit), "text", groups["Marquages"]
                style = copy.deepcopy(element.get("style") or {})
            else:
                content, kind, group = element["logo"], "image", groups["Logos"]
                style = {"tint": element["tint"]} if element.get("tint") else {}
            try:
                _ids, extra = self._zone_layers(
                    doc,
                    kind,
                    content,
                    element["zone"],
                    element["size_m"],
                    element["lon"],
                    element["height"] * body_height,  # fraction de la hauteur de carrosserie
                    True,
                    style,
                    group.children,
                    element["name"],
                )
            except LiveryError as exc:
                log.info("Modèle %s : élément « %s » ignoré (%s)", key, element["name"], exc)
                continue
            commands += extra
        if doc.mode == "texture" and template.key != "custom":
            # teinte de carrosserie : en mode texture, la peinture suggérée multiplie la texture d'origine
            # (joints conservés) ; en mode livrée transparente, elle relève du matériau.
            tint = Layer(
                "band",
                "Teinte de carrosserie",
                blend="multiply",
                params={
                    "zone": "body",
                    "orientation": "longitudinal",
                    "width": 50.0,
                    "center_height": 0.0,
                    "lateral_offset": 0.0,
                    "pattern": "solid",
                    "side": "both",
                    "color": template.paint,
                },
            )
            groups["Bandes"].children.insert(0, tint)
        created = [g for g in groups.values() if g.children]
        variant.layers.extend(created)
        variant.template = key
        doc.palettes[f"Modèle {template.name}"] = list(template.palette)
        variant.metadata.setdefault("unit", unit)
        variant.metadata["suggested_paint"] = template.paint
        self._push(f"Modèle « {template.name} »", doc, commands)
        return [g.id for g in created]

    def save_template(self, path: str | Path, name: str, variant_id: str | None = None) -> Path:
        """Enregistre la livrée comme modèle personnel portable (calques, pixels, logos intégrés)."""
        doc = self.require()
        variant = self.variant(doc, variant_id)
        images = {k: self.scene.images[k].png() for k in variant.image_keys() if k in self.scene.images}
        used = {layer.params.get("blob") for layer in variant.walk()} | {
            layer.params.get("font_blob") for layer in variant.walk()
        }
        blobs = {k: v for k, v in self.scene.blobs.items() if k in used}
        palette = next(iter(doc.palettes.values()), [])
        path = tpl.save_user_template(
            Path(path), name, [layer.to_dict() for layer in variant.layers], images, palette
        )
        if blobs:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["blobs"] = {k: base64.b64encode(v).decode("ascii") for k, v in blobs.items()}
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def apply_user_template(self, path: str | Path, variant_id: str | None = None) -> list[str]:
        data = tpl.load_user_template(Path(path))
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        blobs = {k: base64.b64decode(v) for k, v in (raw.get("blobs") or {}).items()}
        doc = self.require()
        variant = self.variant(doc, variant_id)
        mapping: dict[str, str] = {}
        layers = [clone_layer(Layer.from_dict(d), mapping) for d in data.get("layers") or []]
        commands: list[Command] = [AddBlob(k, v) for k, v in blobs.items()]
        for old, new in mapping.items():
            png = data["images"].get(old)
            if png is None:
                continue
            buffer = ImageBuffer(png=png)
            if (buffer.width, buffer.height) != (doc.width, doc.height):
                mode = "L" if buffer.channels == 1 else "RGBA"
                resized = Image.fromarray(buffer.array, mode).resize((doc.width, doc.height), Image.LANCZOS)
                buffer = ImageBuffer(np.array(resized, np.uint8))
            commands.append(SetImage(new, None, buffer, "Modèle"))
        variant.layers.extend(layers)
        if data.get("palette"):
            doc.palettes[f"Modèle {data.get('name', 'personnel')}"] = data["palette"]
        self._push(f"Modèle personnel « {data.get('name', '')} »", doc, commands)
        return [layer.id for layer in layers]

    # --- Couleurs et polices ------------------------------------------------------------------
    def record_color(self, color: str) -> None:
        """Historique des couleurs utilisées (hors annulation : simple confort)."""
        doc = self.document()
        if doc is None:
            return
        color = hex_color(color)
        doc.color_history = [color, *[c for c in doc.color_history if c != color]][:24]
        self.scene.documents[DOC_KEY] = doc.to_dict()
        self.session.mark_meta_dirty()

    def save_palette(self, name: str, colors: list[str]) -> None:
        doc = self.require()
        doc.palettes[name.strip() or "Palette"] = [hex_color(c) for c in colors]
        self._push("Palette enregistrée", doc)

    def delete_palette(self, name: str) -> None:
        doc = self.require()
        doc.palettes.pop(name, None)
        self._push("Palette supprimée", doc)

    def import_font(self, path: str | Path, license_text: str, author: str = "", source: str = "") -> str:
        """Police personnelle (TTF / OTF) intégrée au projet, avec sa licence déclarée."""
        path = Path(path)
        if path.suffix.lower() not in (".ttf", ".otf"):
            raise LiveryError("Formats de police acceptés : TTF, OTF.")
        if not license_text.strip():
            raise LiveryError(
                "Indiquez la licence de la police : elle conditionne la diffusion des textures."
            )
        data = path.read_bytes()
        key = blob_key(data)
        family = render2d.register_font(key, data)
        if family is None:
            raise LiveryError("Police illisible.")
        doc = self.require()
        if not any(f.get("blob") == key for f in doc.fonts):
            doc.fonts.append(
                {
                    "family": family,
                    "blob": key,
                    "file": path.name,
                    "license": license_text.strip(),
                    "author": author.strip(),
                    "source": source.strip() or path.name,
                }
            )
        self._push(f"Police « {family} »", doc, [AddBlob(key, data)])
        return family

    def font_blob(self, family: str) -> str | None:
        doc = self.document()
        return next((f["blob"] for f in doc.fonts if f.get("family") == family), None) if doc else None

    # --- UV ---------------------------------------------------------------------------------------
    def uv_report(self):  # type: ignore[no-untyped-def]
        return self.surface().uv_report()

    def nodes_without_uv(self, material_ids: list[str] | None = None) -> list[str]:
        doc = self.document()
        if material_ids:
            wanted = set(material_ids)
        elif doc is not None:
            wanted = set(doc.targets)
        else:
            wanted = {c["id"] for c in self.candidate_materials()[:1]}
        result = []
        for node in self.scene.mesh_nodes():
            mesh = self.session.geometry_for(node)
            if node.material_id in wanted and mesh is not None and mesh.uvs is None:
                result.append(node.id)
        return result

    def project_missing_uvs(self, node_ids: list[str]) -> int:
        """Projection UV « boîte » des maillages sans UV (à appeler après confirmation de l'utilisateur)."""
        from lsfcars.editor.operations import VehicleEditor
        from lsfcars.scene import editmesh

        editor = VehicleEditor(self.session)

        def action() -> None:
            for node_id in node_ids:
                editor.edit(node_id, lambda m: editmesh.box_project_uv(m), "Projection UV")

        self._transaction("Projection UV", action)
        self._surface = None
        return len(node_ids)

    # --- Export -----------------------------------------------------------------------------------
    def export(
        self, path: str | Path, options: export.ExportOptions, variant_id: str | None = None
    ) -> export.ExportReport:
        doc = self.require()
        array = self.composite(variant_id)
        coverage = self.surface(doc).maps().coverage if options.padding and doc.mode == "texture" else None
        report = export.export_texture(array, path, options, coverage)
        self.check_provenance(doc, report)
        return report

    def export_all(self, folder: str | Path, options: export.ExportOptions) -> list[export.ExportReport]:
        doc = self.require()
        return [
            self.export(Path(folder) / f"{doc.texture_name}_{_slug(variant.name)}", options, variant.id)
            for variant in doc.variants
        ]

    def prepare_ytd(self, folder: str | Path, options: export.ExportOptions, dictionary: str | None = None):  # type: ignore[no-untyped-def]
        doc = self.require()
        base = re.sub(r"_sign_\d+$", "", doc.texture_name)
        textures = {
            f"{base}_sign_{index}": self.composite(v.id) for index, v in enumerate(doc.variants, start=1)
        }
        coverage = self.surface(doc).maps().coverage if options.padding and doc.mode == "texture" else None
        return export.prepare_ytd(
            folder, dictionary or _slug(self.session.project.name), textures, options, coverage
        )

    def check_provenance(self, doc: LiveryDocument, report: export.ExportReport) -> None:
        for entry in doc.provenance:
            if not entry.get("license"):
                report.warnings.append(
                    f"Logo « {entry.get('name')} » sans licence renseignée : vérifiez vos droits."
                )
        for font in doc.fonts:
            if not font.get("license"):
                report.warnings.append(f"Police « {font.get('family')} » sans licence renseignée.")

    # --- Emergency Studio ------------------------------------------------------------------------
    def emergency_variants(self) -> list[dict]:
        data = self.scene.documents.get("emergency") or {}
        return [
            {"id": v.get("id"), "name": v.get("name"), "service": v.get("service")}
            for v in data.get("variants") or []
        ]

    def active_emergency_variant(self) -> str | None:
        return (self.scene.documents.get("emergency") or {}).get("active")

    def link_emergency(self, variant_id: str, emergency_id: str | None) -> None:
        """Associe une livrée à une variante d'urgence et synchronise ses données de livrée (nom, unité)."""
        doc = self.require()
        variant = self.variant(doc, variant_id)
        variant.emergency_variant = emergency_id

        def action() -> None:
            self._push("Livrée associée", doc)
            if emergency_id:
                self._sync_emergency(variant, emergency_id)

        self._transaction("Livrée associée", action)

    def _sync_emergency(self, variant: LiveryVariant, emergency_id: str) -> None:
        from lsfcars.emergency.studio import EmergencyStudio

        studio = EmergencyStudio(self.session)
        target = studio.state().variant(emergency_id)
        if target is None:
            raise LiveryError("Variante d'urgence introuvable.")
        livery = dict(vars(target.livery))
        livery.update(
            livery_name=variant.name, unit_id=variant.metadata.get("unit") or livery.get("unit_id", "")
        )
        studio.update_variant(emergency_id, livery=livery)  # données seulement : équipements intacts

    def follow_emergency(self, emergency_id: str | None) -> str | None:
        """Active la livrée associée à la variante d'urgence sélectionnée (si elle existe)."""
        doc = self.document()
        if doc is None or not emergency_id:
            return None
        variant = next((v for v in doc.variants if v.emergency_variant == emergency_id), None)
        if variant is None:
            return None
        if variant.id != doc.active:
            self.activate_variant(variant.id)
        return variant.id

    # --- Diagnostics ------------------------------------------------------------------------------
    def diagnostics(self) -> list[tuple[str, str]]:
        """(niveau, message) : UV, matériaux partagés, textures manquantes, mémoire, licences."""
        doc = self.document()
        if doc is None:
            return [("info", "Aucun document de livrée.")]
        items: list[tuple[str, str]] = []
        surface = self.surface(doc)
        report = surface.uv_report()
        items.append(
            (
                "info",
                f"{surface.triangle_count} triangles ciblés, {report.islands} îlot(s) UV, "
                f"{report.coverage_ratio:.0%} de la texture utilisée, {report.texel_density:.0f} px/m.",
            )
        )
        items += [("warning", w) for w in report.warnings()]
        for material_id in doc.targets:
            material = self.scene.materials.get(material_id)
            if material is None:
                items.append(("error", "Matériau ciblé introuvable."))
                continue
            users = [n.name for n in self.scene.mesh_nodes() if n.material_id == material_id]
            if len(users) > 1:
                items.append(
                    (
                        "info",
                        f"Matériau « {material.name} » partagé par {len(users)} maillages : la livrée "
                        "s'applique à tous (" + ", ".join(users[:6]) + ").",
                    )
                )
            if material.texture and not (self.session.project.project_dir / material.texture).is_file():
                items.append(("warning", f"Texture d'origine manquante : {material.texture}"))
        textures = {m.texture for m in (self.scene.materials.get(t) for t in doc.targets) if m and m.texture}
        if len(textures) > 1:
            items.append(
                (
                    "warning",
                    "Les matériaux ciblés utilisent plusieurs textures d'origine : seule la première sert "
                    "de fond ; ciblez des matériaux partageant le même dépliage.",
                )
            )
        decoded = sum(img.nbytes() for img in self.scene.images.values() if img.decoded)
        items.append(
            (
                "info",
                f"Mémoire des calques décodés : {decoded / 1e6:.1f} Mo ; dernière composition "
                f"{self.compositor.last_ms:.0f} ms.",
            )
        )
        items += [("warning", w) for w in dict.fromkeys(self.compositor.warnings)]
        for entry in doc.provenance:
            if not entry.get("license"):
                items.append(("warning", f"Logo « {entry.get('name')} » : licence non renseignée."))
        return items


# --- Fonctions utilitaires ---------------------------------------------------------------------


def _leaves(command: Command):  # type: ignore[no-untyped-def]
    if isinstance(command, CompositeCommand):
        for item in command.commands:
            yield from _leaves(item)
    else:
        yield command


def _default_name(kind: str, params: dict | None) -> str:
    params = params or {}
    if kind == "text":
        return str(params.get("text", "Texte")).replace("\n", " ")[:32] or "Texte"
    if kind == "vector":
        return VECTOR_SHAPES.get(params.get("shape", ""), "Forme")
    return {"raster": "Calque", "image": "Image", "band": "Bande", "group": "Groupe"}.get(kind, "Calque")


def _mirror_name(name: str) -> str:
    if "(gauche)" in name:
        return name.replace("(gauche)", "(droite)")
    if "(droite)" in name:
        return name.replace("(droite)", "(gauche)")
    return f"{name} (symétrie)"


def transform_params(layer: Layer, dx: float, dy: float, rotation: float, scale: float) -> None:
    params = layer.params
    if layer.kind == "vector":
        points = np.asarray(params.get("points") or [], np.float64)
        if len(points):
            center = (points.min(axis=0) + points.max(axis=0)) / 2
            params["points"] = ((points - center) * scale + center + [dx, dy]).round(3).tolist()
        params["rotation"] = float(params.get("rotation", 0.0)) + rotation
        if params.get("shape") == "rounded_rect":
            params["radius"] = float(params.get("radius", 16.0)) * scale
        if params.get("stroke_width"):
            params["stroke_width"] = float(params["stroke_width"]) * scale
    elif layer.kind in ("text", "image"):
        params["x"] = float(params.get("x", 0.0)) + dx
        params["y"] = float(params.get("y", 0.0)) + dy
        params["rotation"] = float(params.get("rotation", 0.0)) + rotation
        if layer.kind == "text":
            params["size"] = max(1.0, float(params.get("size", 64.0)) * scale)
        else:
            params["width"] = max(1.0, float(params.get("width", 256.0)) * scale)
            params["height"] = max(1.0, float(params.get("height", 256.0)) * scale)
    for child in layer.children:
        transform_params(child, dx, dy, rotation, scale)


def _scale_params(layer: Layer, sx: float, sy: float) -> None:
    params = layer.params
    if layer.kind == "vector" and params.get("points"):
        params["points"] = [[x * sx, y * sy] for x, y in params["points"]]
    elif layer.kind in ("text", "image"):
        params["x"] = float(params.get("x", 0)) * sx
        params["y"] = float(params.get("y", 0)) * sy
        if layer.kind == "text":
            params["size"] = float(params.get("size", 64)) * sy
        else:
            params["width"] = float(params.get("width", 256)) * sx
            params["height"] = float(params.get("height", 256)) * sy
