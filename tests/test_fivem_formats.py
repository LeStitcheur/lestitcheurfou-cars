"""Lecteurs GTA V / FiveM sur des fichiers synthétiques construits par les tests (aucun fichier tiers)."""

from __future__ import annotations

import io
import struct

import numpy as np
import pytest
from PIL import Image

from lsfcars.fivem.errors import EncryptedError, FormatError, ProtectedResourceError
from lsfcars.fivem.meta import cross_check, parse_meta
from lsfcars.fivem.rpf import ENC_AES, ENC_NG, RpfArchive, probe
from lsfcars.fivem.rsc import Resource, block_size, joaat, read_header
from lsfcars.fivem.structure import UNCLASSIFIED, classify
from lsfcars.fivem.synthetic import (
    DEMO_METAS,
    RpfItem,
    TextureSpec,
    bgra_gradient,
    build_rpf,
    build_rsc,
    build_yft,
    build_ytd,
    demo_textures,
    demo_vehicle,
    dxt1_solid,
    flags_for,
)
from lsfcars.fivem.yft import parse_yft, split_fragment
from lsfcars.fivem.ytd import TextureDecodeError, alpha_used, dds_bytes, decode, parse_ytd
from lsfcars.importers import ModelLoadError, load_model


def test_block_size_and_joaat():
    assert block_size(flags_for(8192)) == 8192
    assert block_size(flags_for(100)) == 512
    assert joaat("adder") == 0xB779A091  # valeur publique bien connue


# --- RPF ---------------------------------------------------------------------------


def _archive() -> bytes:
    inner = build_rpf({"demo.ytd": RpfItem(build_ytd(demo_textures("demo")), resource=True)})
    return build_rpf(
        {
            "common/data/handling.meta": RpfItem(b"<CHandlingDataMgr />" * 20, compress=True),
            "content.xml": RpfItem(b"<CDataFileMgr__ContentsOfDataFileXml />"),
            "x64/vehicles.rpf": RpfItem(inner),
        }
    )


def test_rpf_walk_nested_and_read(tmp_path):
    path = tmp_path / "dlc.rpf"
    path.write_bytes(_archive())
    assert probe(path)[1] == 0x4E45504F
    with RpfArchive.open(path) as archive:
        listing = {display: entry for _a, entry, display in archive.walk()}
        assert set(listing) == {"common/data/handling.meta", "content.xml", "x64/vehicles.rpf/demo.ytd"}
        meta = listing["common/data/handling.meta"]
        assert meta.compressed and archive.read(meta) == b"<CHandlingDataMgr />" * 20
        owner, ytd, _ = next(item for item in archive.walk() if item[2].endswith("demo.ytd"))
        assert ytd.is_resource
        assert [t.name for t in parse_ytd(owner.read(ytd))] == ["demo_details", "demo_lights", "demo_sign_1"]


@pytest.mark.parametrize("encryption", [ENC_AES, ENC_NG])
def test_encrypted_rpf_is_refused_without_decryption(encryption):
    data = build_rpf({"a.meta": RpfItem(b"x")}, encryption=encryption)
    with pytest.raises(EncryptedError, match="ne déchiffre pas"):
        RpfArchive.from_bytes(data)


def test_invalid_rpf_archives():
    with pytest.raises(FormatError, match="signature"):
        RpfArchive.from_bytes(b"PK\x03\x04" + b"\0" * 60)
    with pytest.raises(FormatError):
        RpfArchive.from_bytes(_archive()[:40])
    corrupted = bytearray(_archive())
    struct.pack_into("<I", corrupted, 4, 50_000_000)  # nombre d'entrées absurde
    with pytest.raises(FormatError):
        RpfArchive.from_bytes(bytes(corrupted))


# --- RSC / YTD ---------------------------------------------------------------------


def test_resource_header_errors():
    with pytest.raises(ProtectedResourceError, match="chiffré"):
        read_header(b"\x12\x34" * 16)
    with pytest.raises(FormatError, match="RSC8"):
        read_header(b"RSC8" + b"\0" * 12)
    broken = build_rsc(13, b"\x01" * 64)[:16] + b"pas du deflate"
    with pytest.raises(FormatError, match="décompression"):
        Resource.from_bytes(broken)


def test_ytd_decoding_formats():
    textures = parse_ytd(
        build_ytd(
            [
                TextureSpec("rouge_dxt1", 8, 8, 0x31545844, dxt1_solid(8, 8, 0xF800)),
                TextureSpec("degrade", 4, 2, 21, bgra_gradient(4, 2, alpha=128)),
                TextureSpec("inconnu", 4, 4, 0x58585858, b"\0" * 64),
            ]
        )
    )
    red, gradient, unknown = textures
    image = decode(red)
    assert image.size == (8, 8) and image.getpixel((3, 3))[:3] == (255, 0, 0)
    assert not alpha_used(image) and red.memory_bytes == 32
    pixels = np.asarray(decode(gradient))
    assert pixels[0, -1, 0] == 255 and pixels[0, 0, 0] == 0 and pixels[0, 0, 3] == 128
    assert gradient.has_alpha_channel and alpha_used(decode(gradient))
    assert not unknown.supported
    with pytest.raises(TextureDecodeError, match="non pris en charge"):
        decode(unknown)
    with Image.open(io.BytesIO(dds_bytes(red))) as copy:
        assert copy.size == (8, 8)


def test_ytd_rejects_other_resource_types():
    with pytest.raises(FormatError, match="attendu 13"):
        parse_ytd(build_yft(demo_vehicle()))


# --- YFT ---------------------------------------------------------------------------


def test_yft_geometry_bones_and_parts():
    fragment = parse_yft(build_yft(demo_vehicle("demo")))
    drawable = fragment.drawable
    assert fragment.name == "demo"
    assert [b.name for b in drawable.skeleton.bones][:3] == ["chassis", "bodyshell", "door_dside_f"]
    assert drawable.triangle_count() == 14 * 12
    assert drawable.shaders[0].name == "vehicle_paint1" and drawable.shaders[1].diffuse == "demo_details"
    parts = split_fragment(fragment)
    by_bone = {drawable.skeleton.bones[p.bone_index].name: p for p in parts}
    door = by_bone["door_dside_f"]
    # Sommets exprimés dans le repère de l'os : la porte reste centrée près de son pivot
    assert np.allclose(door.positions.mean(axis=0), [-0.04, -0.45, 0.0], atol=1e-5)
    assert set(by_bone) >= {"wheel_lf", "bonnet", "boot", "windscreen"}


def test_yft_errors_are_readable(tmp_path):
    with pytest.raises(FormatError, match="attendu 162"):
        parse_yft(build_ytd(demo_textures()))
    corrupt = tmp_path / "casse.yft"
    corrupt.write_bytes(build_yft(demo_vehicle())[:200])
    with pytest.raises(ModelLoadError):
        load_model(corrupt)


def test_component_classification_never_invents():
    assert classify("door_dside_f") == "portes"
    assert classify("wheel_lr") == "roues"
    assert classify("bonnet") == "capot" and classify("boot") == "coffre"
    assert classify("windscreen") == "vitres" and classify("headlight_l") == "phares"
    assert classify("seat_dside_f") == "sieges" and classify("dials") == "tableau_de_bord"
    assert classify("lsf_custom_part") == UNCLASSIFIED
    assert classify("", "vehicle_tire") == "roues"


# --- META --------------------------------------------------------------------------


def _metas(**values):
    defaults = {"name": "demo", "handling": "DEMO", "kit": "2950_demo_modkit"}
    defaults.update(values)
    return {name: parse_meta(text.format(**defaults), name) for name, text in DEMO_METAS.items()}


def test_meta_documents_are_structured():
    docs = _metas()
    vehicles = docs["vehicles.meta"]
    assert vehicles.kind == "vehicles" and vehicles.valid
    entry = next(e for e in vehicles.entries if e.kind == "vehicle")
    assert entry.fields["handlingId"] == "DEMO" and entry.fields["txdName"] == "demo"
    assert docs["handling.meta"].entries[0].fields["fMass"] == "1800.000000"
    assert docs["carvariations.meta"].entries[0].fields["kits"] == "2950_demo_modkit"
    assert docs["carcols.meta"].entries[0].name == "2950_demo_modkit"
    # Données inconnues conservées : le texte d'origine et l'arbre complet restent disponibles
    assert "unknownCustomField" in docs["handling.meta"].text
    assert docs["handling.meta"].search("unknownCustomField")
    assert not cross_check(list(docs.values()), {"demo"}, {"demo"})


def test_meta_errors_and_references():
    broken = parse_meta("<CHandlingDataMgr><HandlingData>\n<Item>", "handling.meta")
    assert not broken.valid and "ligne" in broken.issues[0].message
    docs = list(_metas(handling="AUTRE").values())
    docs[1] = parse_meta(DEMO_METAS["handling.meta"].format(handling="DEMO"), "handling.meta")
    messages = [i.message for i in cross_check(docs, set(), set())]
    assert any("aucun fichier demo.yft" in m for m in messages)
    assert any("handlingId « autre »" in m for m in messages)
    unknown = parse_meta("<RootInconnue><a>1</a></RootInconnue>")
    assert unknown.valid and unknown.kind == "inconnu" and unknown.issues[0].level == "info"
