"""Analyse d'une ressource de véhicule : dossier FiveM, ZIP, archive RPF ou fichiers isolés.

Chaque fichier reçoit un statut issu d'une validation réelle (décodage effectif) :

- Compatible : lu et décodé entièrement ;
- Partiellement compatible : reconnu, lu en partie (ex. collision : en-tête seulement) ;
- Dépendance manquante : valide, mais un fichier requis est absent ;
- Erreur : invalide, corrompu, chiffré ou protégé ;
- Format non pris en charge : reconnu mais non exploité (audio, scripts…).

Les fichiers d'origine ne sont jamais modifiés. L'analyse est annulable (``cancel``).
"""

from __future__ import annotations

import io
import re
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath

from lsfcars.core.logging_setup import get_logger
from lsfcars.fivem import meta as meta_mod
from lsfcars.fivem.errors import EncryptedError, FormatError, ProtectedResourceError
from lsfcars.fivem.rpf import RpfArchive, encryption_label
from lsfcars.fivem.rsc import read_header
from lsfcars.fivem.yft import LOD_LABELS, Drawable, Fragment, parse_ydr, parse_yft
from lsfcars.fivem.ytd import Texture, TextureDecodeError, alpha_used, decode, parse_ytd, png_bytes

log = get_logger(__name__)

MAX_FILES = 20_000
MAX_IN_MEMORY = 1 << 30
PREVIEW_SIDE = 256


class Status(StrEnum):
    COMPATIBLE = "compatible"
    PARTIAL = "partiel"
    MISSING = "dependance_manquante"
    ERROR = "erreur"
    UNSUPPORTED = "non_pris_en_charge"

    @property
    def label(self) -> str:
        return STATUS_LABELS[self]


STATUS_LABELS = {
    Status.COMPATIBLE: "Compatible",
    Status.PARTIAL: "Partiellement compatible",
    Status.MISSING: "Dépendance manquante",
    Status.ERROR: "Erreur",
    Status.UNSUPPORTED: "Format non pris en charge",
}

# Formats reconnus et ce qui est réellement fait avec eux (affiché dans l'interface)
FORMAT_SUPPORT: dict[str, tuple[str, str]] = {
    ".yft": ("Modèle de véhicule (fragment)", "Décodé : géométrie, os, shaders, roues"),
    ".ydr": (
        "Modèle (drawable)",
        "Décodé (expérimental, non validé sur fichier réel) : géométrie, os, shaders",
    ),
    ".ytd": ("Dictionnaire de textures", "Décodé : DXT1/3/5, BC4/5/7, formats non compressés"),
    ".ybn": ("Collision", "En-tête vérifié uniquement : géométrie de collision non importée"),
    ".meta": ("Métadonnées XML", "Lu : véhicules, handling, variations, carcols, références"),
    ".xml": ("Métadonnées XML", "Lu : content.xml, setup2.xml et autres XML"),
    ".rpf": ("Archive RPF7", "Parcourue si non chiffrée (OPEN) ; chiffrée : refusée"),
    ".zip": ("Archive ZIP", "Parcourue"),
    ".obj": ("Wavefront OBJ", "Importé (trimesh)"),
    ".glb": ("glTF binaire", "Importé (trimesh)"),
    ".gltf": ("glTF", "Importé (trimesh)"),
    ".fbx": ("Autodesk FBX", "Converti par Blender s'il est installé"),
    ".lua": ("Script / manifeste FiveM", "fxmanifest.lua et __resource.lua analysés"),
    ".fxap": ("FiveM Asset Escrow", "Ressource protégée : jamais déchiffrée"),
    ".dds": ("Image DDS", "Aperçu si le format est lisible par Pillow"),
    ".png": ("Image PNG", "Aperçu"),
}
AUDIO = {".awc", ".rel", ".oac", ".nametable"}
GENERIC_MODELS = (".obj", ".glb", ".gltf", ".fbx")  # modèles 3D standard (non FiveM)


class AnalysisCancelled(Exception):
    """L'utilisateur a interrompu l'analyse."""


@dataclass
class ResourceFile:
    path: str  # chemin affiché, relatif à la ressource (séparateurs « / »)
    size: int
    origin: str  # « dossier », « zip », « rpf »
    reader: Callable[[], bytes] = field(repr=False)
    status: Status = Status.UNSUPPORTED
    kind: str = ""
    message: str = ""
    details: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name

    @property
    def extension(self) -> str:
        return PurePosixPath(self.name.lower()).suffix

    @property
    def stem(self) -> str:
        return PurePosixPath(self.name).stem

    def read(self) -> bytes:
        return self.reader()

    def set(self, status: Status, message: str, **details: object) -> None:
        self.status, self.message = status, message
        self.details.update(details)


@dataclass
class TextureSummary:
    name: str
    width: int
    height: int
    format: str
    levels: int
    memory: int
    decoded: bool
    alpha: bool
    reason: str = ""
    preview_png: bytes | None = None
    source: str = ""  # fichier .ytd d'origine


@dataclass
class VehicleModel:
    name: str
    yft: ResourceFile | None = None
    yft_hi: ResourceFile | None = None
    ytds: list[ResourceFile] = field(default_factory=list)
    is_vehicle: bool = False  # déclaré dans vehicles.meta
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def status(self) -> Status:
        return Status.MISSING if self.yft is None else self.yft.status


@dataclass
class ResourceAnalysis:
    source: Path
    source_kind: str
    name: str
    files: list[ResourceFile] = field(default_factory=list)
    models: list[VehicleModel] = field(default_factory=list)
    metadata: list[meta_mod.MetaDocument] = field(default_factory=list)
    textures: list[TextureSummary] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    issues: list[tuple[str, str]] = field(default_factory=list)  # (niveau, message)
    protected: bool = False
    _closers: list[Callable[[], None]] = field(default_factory=list, repr=False)
    _temp: Path | None = field(default=None, repr=False)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    def counts(self) -> dict[Status, int]:
        result = {status: 0 for status in Status}
        for item in self.files:
            result[item.status] += 1
        return result

    @property
    def overall(self) -> Status:
        relevant = [f for f in self.files if f.extension in (".yft", ".ydr", ".ytd", ".meta")]
        if self.protected:
            return Status.ERROR
        if not relevant:
            return Status.ERROR if any(f.status is Status.ERROR for f in self.files) else Status.UNSUPPORTED
        if any(f.status is Status.ERROR for f in relevant):
            return Status.PARTIAL if any(f.status is Status.COMPATIBLE for f in relevant) else Status.ERROR
        if any(f.status is Status.MISSING for f in relevant) or any(m.yft is None for m in self.models):
            return Status.MISSING
        if any(f.status is Status.PARTIAL for f in relevant):
            return Status.PARTIAL
        return Status.COMPATIBLE

    def find(self, path: str) -> ResourceFile | None:
        return next((f for f in self.files if f.path == path), None)

    def model(self, name: str) -> VehicleModel | None:
        return next((m for m in self.models if m.name.lower() == name.lower()), None)

    @property
    def generic_models(self) -> list[ResourceFile]:
        """Modèles 3D standard lisibles (GLB, glTF, OBJ, FBX) : importables comme modèle 3D."""
        return [f for f in self.files if f.extension in GENERIC_MODELS and f.status is Status.COMPATIBLE]

    def local_model_path(self, item: ResourceFile) -> Path:
        """Chemin local d'un modèle standard : fichier d'origine, ou copie extraite d'une archive.

        Pour une archive, les fichiers du même dossier (tampons .bin, textures, .mtl) sont
        extraits à côté du modèle pour que ses références relatives restent valides.
        """
        if self.source_kind == "fichier":
            return self.source
        if self.source_kind == "dossier":
            return self.source / item.path
        folder = item.path.rpartition("/")[0]
        target_root = self.temp_dir() / "modeles"
        for other in self.files:
            if other.path.rpartition("/")[0] == folder:
                target = target_root / other.path
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_bytes(other.read())
        return target_root / item.path

    def temp_dir(self) -> Path:
        if self._temp is None:
            self._temp = Path(tempfile.mkdtemp(prefix="lsfcars-ressource-"))
        return self._temp

    def close(self) -> None:
        """Ferme les archives ouvertes et supprime les fichiers temporaires."""
        for closer in self._closers:
            try:
                closer()
            except Exception:  # noqa: BLE001 (fermeture au mieux)
                log.debug("Fermeture d'une archive impossible", exc_info=True)
        self._closers.clear()
        if self._temp is not None:
            shutil.rmtree(self._temp, ignore_errors=True)
            self._temp = None


# --- Collecte des fichiers --------------------------------------------------------


def _check(cancel: Callable[[], bool] | None) -> None:
    if cancel is not None and cancel():
        raise AnalysisCancelled()


def _add_rpf(analysis: ResourceAnalysis, archive: RpfArchive, prefix: str) -> None:
    for owner, entry, display in archive.walk(prefix):
        item = ResourceFile(display, entry.size, "rpf", lambda o=owner, e=entry: o.read(e))
        if entry.extension == ".rpf" and not entry.is_resource:  # imbriquée illisible
            try:
                owner.open_nested(entry)
            except EncryptedError as exc:
                item.set(Status.ERROR, str(exc))
            except FormatError as exc:
                item.set(Status.ERROR, f"Archive imbriquée illisible : {exc}")
        elif entry.encrypted:
            item.set(Status.ERROR, "Fichier chiffré dans l'archive : il n'est pas déchiffré.")
        analysis.files.append(item)


def _open_rpf_file(analysis: ResourceAnalysis, path: Path, prefix: str) -> None:
    display = prefix.rstrip("/") or path.name
    try:
        archive = RpfArchive.open(path)
    except EncryptedError as exc:
        item = ResourceFile(display, path.stat().st_size, "dossier", path.read_bytes)
        item.set(Status.ERROR, str(exc))
        analysis.files.append(item)
        analysis.issues.append(("erreur", f"{path.name} : archive chiffrée, non lue (aucun déchiffrement)."))
        return
    except FormatError as exc:
        item = ResourceFile(display, path.stat().st_size, "dossier", path.read_bytes)
        item.set(Status.ERROR, f"Archive RPF invalide : {exc}")
        analysis.files.append(item)
        return
    analysis._closers.append(archive.close)
    analysis.issues.append(
        ("info", f"{path.name} : archive RPF7, chiffrement {encryption_label(archive.encryption)}.")
    )
    _add_rpf(analysis, archive, prefix)


def _collect(analysis: ResourceAnalysis, cancel: Callable[[], bool] | None) -> None:
    source = analysis.source
    if analysis.source_kind == "dossier":
        for path in sorted(source.rglob("*")):
            _check(cancel)
            if not path.is_file() or any(part.startswith(".") for part in path.relative_to(source).parts):
                continue
            rel = path.relative_to(source).as_posix()
            if path.suffix.lower() == ".rpf":
                _open_rpf_file(analysis, path, f"{rel}/")
            else:
                analysis.files.append(ResourceFile(rel, path.stat().st_size, "dossier", path.read_bytes))
            if len(analysis.files) > MAX_FILES:
                raise FormatError(f"Ressource trop volumineuse (plus de {MAX_FILES} fichiers).")
    elif analysis.source_kind == "zip":
        try:
            archive = zipfile.ZipFile(source)
        except (zipfile.BadZipFile, OSError) as exc:
            raise FormatError(f"Archive ZIP invalide : {exc}") from exc
        analysis._closers.append(archive.close)
        for info in archive.infolist():
            _check(cancel)
            if info.is_dir():
                continue

            def reader(i: zipfile.ZipInfo = info) -> bytes:
                return archive.read(i)

            if info.flag_bits & 0x1:
                item = ResourceFile(info.filename, info.file_size, "zip", reader)
                item.set(Status.ERROR, "Fichier protégé par mot de passe dans le ZIP : non lu.")
                analysis.files.append(item)
                continue
            if info.filename.lower().endswith(".rpf") and info.file_size <= MAX_IN_MEMORY:
                try:
                    nested = RpfArchive.from_bytes(reader(), PurePosixPath(info.filename).name)
                except (FormatError, zipfile.BadZipFile, OSError) as exc:
                    item = ResourceFile(info.filename, info.file_size, "zip", reader)
                    item.set(Status.ERROR, str(exc))
                    analysis.files.append(item)
                    continue
                _add_rpf(analysis, nested, f"{info.filename}/")
                continue
            analysis.files.append(ResourceFile(info.filename, info.file_size, "zip", reader))
    elif analysis.source_kind == "rpf":
        _open_rpf_file(analysis, source, "")
    else:  # fichier isolé (+ dictionnaires de textures voisins)
        analysis.files.append(ResourceFile(source.name, source.stat().st_size, "dossier", source.read_bytes))
        if source.suffix.lower() in (".yft", ".ydr"):
            from lsfcars.importers.yft_importer import companion_ytds

            for ytd in companion_ytds(source):
                analysis.files.append(ResourceFile(ytd.name, ytd.stat().st_size, "dossier", ytd.read_bytes))


# --- Validation par type ----------------------------------------------------------


def _validate_model(item: ResourceFile) -> Fragment | Drawable | None:
    try:
        data = item.read()
        model = parse_yft(data) if item.extension == ".yft" else parse_ydr(data, item.stem)
    except ProtectedResourceError as exc:
        item.set(Status.ERROR, str(exc), protected=True)
        return None
    except (FormatError, OSError) as exc:
        item.set(Status.ERROR, f"Modèle illisible : {exc}")
        return None
    drawable = model.drawable if isinstance(model, Fragment) else model
    triangles = model.triangle_count() if isinstance(model, Fragment) else drawable.triangle_count()
    bones = len(drawable.skeleton.bones) if drawable.skeleton else 0
    item.set(
        Status.COMPATIBLE,
        f"{triangles:,} triangles, {bones} os".replace(",", " "),
        model_name=model.name or item.stem,
        triangles=triangles,
        vertices=drawable.vertex_count(),
        bones=bones,
        lods=[LOD_LABELS[k] for k in drawable.lods],
        shaders=[s.name for s in drawable.shaders],
        texture_refs=sorted({t for s in drawable.shaders for t in s.textures.values()}),
        embedded_textures=[t.name for t in drawable.textures],
        children=len(model.children) if isinstance(model, Fragment) else 0,
        warnings=list(drawable.warnings),
    )
    return model


def _summarize(texture: Texture, source: str) -> TextureSummary:
    summary = TextureSummary(
        texture.name,
        texture.width,
        texture.height,
        texture.format_name,
        texture.levels,
        texture.memory_bytes,
        False,
        False,
        source=source,
    )
    try:
        image = decode(texture)
    except TextureDecodeError as exc:
        summary.reason = str(exc)
        return summary
    summary.decoded = True
    summary.alpha = alpha_used(image)
    summary.preview_png = png_bytes(image, PREVIEW_SIDE)
    return summary


def _validate_ytd(item: ResourceFile, analysis: ResourceAnalysis, cancel: Callable[[], bool] | None) -> None:
    try:
        textures = parse_ytd(item.read())
    except ProtectedResourceError as exc:
        item.set(Status.ERROR, str(exc), protected=True)
        return
    except (FormatError, OSError) as exc:
        item.set(Status.ERROR, f"Dictionnaire illisible : {exc}")
        return
    decoded = 0
    for texture in textures:
        _check(cancel)
        summary = _summarize(texture, item.path)
        decoded += summary.decoded
        analysis.textures.append(summary)
    item.details["textures"] = [t.name for t in textures]
    if not textures:
        item.set(Status.PARTIAL, "Dictionnaire vide.")
    elif decoded == len(textures):
        item.set(Status.COMPATIBLE, f"{len(textures)} textures décodées")
    elif decoded:
        item.set(Status.PARTIAL, f"{decoded}/{len(textures)} textures décodées")
    else:
        item.set(Status.ERROR, "Aucune texture décodable.")


_FX_DATA_FILE = re.compile(r"data_file\s*\(?\s*['\"]([^'\"]+)['\"]\s*\)?\s*\(?\s*['\"]([^'\"]+)['\"]")
_FX_FILES_BLOCK = re.compile(r"\bfiles\s*\{([^}]*)\}", re.S)
_FX_STRING = re.compile(r"['\"]([^'\"]+)['\"]")
_FX_DEPENDENCY = re.compile(r"\bdependenc(?:y|ies)\s*[\{\(]?([^\n}]*)")


def _validate_manifest(item: ResourceFile, analysis: ResourceAnalysis) -> None:
    try:
        text = item.read().decode("utf-8", errors="replace")
    except OSError as exc:
        item.set(Status.ERROR, f"Lecture impossible : {exc}")
        return
    data_files = _FX_DATA_FILE.findall(text)
    declared = [s for block in _FX_FILES_BLOCK.findall(text) for s in _FX_STRING.findall(block)]
    dependencies = [s for line in _FX_DEPENDENCY.findall(text) for s in _FX_STRING.findall(line)]
    analysis.dependencies.extend(f"data_file {kind} → {path}" for kind, path in data_files)
    analysis.dependencies.extend(f"dépendance : {d}" for d in dependencies)
    base = PurePosixPath(item.path).parent
    known = {f.path.lower() for f in analysis.files}
    missing = []
    for pattern in dict.fromkeys(declared + [p for _kind, p in data_files]):
        full = (base / pattern).as_posix().lower() if str(base) != "." else pattern.lower()
        if "*" in pattern:
            regex = re.compile(re.escape(full).replace(r"\*\*", ".*").replace(r"\*", "[^/]*"))
            if not any(regex.fullmatch(k) for k in known):
                missing.append(pattern)
        elif full not in known:
            missing.append(pattern)
    item.details.update(data_files=data_files, declared=declared, dependencies=dependencies)
    if missing:
        listed = ", ".join(missing[:6])
        item.set(Status.MISSING, f"{len(missing)} fichier(s) déclaré(s) introuvable(s) : {listed}")
        analysis.issues.append(("erreur", f"{item.path} : fichiers déclarés introuvables : {listed}"))
    else:
        item.set(Status.COMPATIBLE, f"{len(data_files)} data_file, {len(declared)} fichier(s) déclaré(s)")


def _validate_generic_model(item: ResourceFile, analysis: ResourceAnalysis) -> None:
    from lsfcars.importers import ModelLoadError, load_model
    from lsfcars.importers.fbx_blender import blender_version

    if item.extension == ".fbx" and blender_version() is None:
        item.set(Status.MISSING, "Dépendance manquante : Blender (conversion FBX).")
        return
    target = analysis.temp_dir() / "validation" / item.path
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_bytes(item.read())
        result = load_model(target)
    except (ModelLoadError, OSError) as exc:
        item.set(Status.ERROR, f"Modèle illisible : {exc}")
        return
    item.set(
        Status.COMPATIBLE,
        f"{result.triangle_count:,} triangles".replace(",", " "),
        triangles=result.triangle_count,
    )


def _validate_image(item: ResourceFile) -> None:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(item.read())) as image:
            image.load()
            preview = png_bytes(image.convert("RGBA"), PREVIEW_SIDE)
            item.set(Status.COMPATIBLE, f"Image {image.width}×{image.height}", preview_png=preview)
    except Exception as exc:  # noqa: BLE001 (Pillow lève des types variés)
        item.set(Status.UNSUPPORTED, f"Image non lisible par l'aperçu : {exc}")


def _validate(item: ResourceFile, analysis: ResourceAnalysis, cancel: Callable[[], bool] | None) -> None:
    ext = item.extension
    item.kind = FORMAT_SUPPORT.get(ext, ("", ""))[0] or ("Audio" if ext in AUDIO else "Fichier")
    if item.status is Status.ERROR and item.message:  # déjà jugé (chiffré, protégé…)
        return
    if ext in (".yft", ".ydr"):
        _validate_model(item)
    elif ext == ".ytd":
        _validate_ytd(item, analysis, cancel)
    elif ext == ".ybn":
        try:
            header = read_header(item.read()[:16])
        except ProtectedResourceError as exc:
            item.set(Status.ERROR, str(exc), protected=True)
        except (FormatError, OSError) as exc:
            item.set(Status.ERROR, f"Collision illisible : {exc}")
        else:
            if header.version == 43:
                item.set(Status.PARTIAL, "Collision reconnue (en-tête valide) ; géométrie non importée.")
            else:
                item.set(Status.ERROR, f"En-tête inattendu pour une collision (version {header.version}).")
    elif ext in (".meta", ".xml"):
        try:
            document = meta_mod.parse_meta(item.read(), item.path)
        except OSError as exc:
            item.set(Status.ERROR, f"Lecture impossible : {exc}")
            return
        analysis.metadata.append(document)
        errors = [i for i in document.issues if i.level == "erreur"]
        if not document.valid:
            item.set(Status.ERROR, errors[0].message if errors else "XML invalide.")
        elif errors:
            item.set(Status.PARTIAL, f"{document.kind_label} — {len(errors)} erreur(s)")
        else:
            item.set(Status.COMPATIBLE, f"{document.kind_label} — {len(document.entries)} entrée(s)")
        item.details["meta_kind"] = document.kind
    elif item.name.lower() in ("fxmanifest.lua", "__resource.lua"):
        item.kind = "Manifeste FiveM"
        _validate_manifest(item, analysis)
    elif ext == ".fxap":
        analysis.protected = True
        item.set(
            Status.ERROR,
            "Ressource protégée par FiveM Asset Escrow : les fichiers chiffrés ne sont pas lisibles "
            "et aucun contournement n'est tenté.",
            protected=True,
        )
    elif ext in (".dds", ".png", ".jpg", ".jpeg"):
        _validate_image(item)
    elif ext in GENERIC_MODELS:
        _validate_generic_model(item, analysis)
    elif ext in AUDIO:
        item.set(Status.UNSUPPORTED, "Audio : reconnu, non utilisé par le studio.")
    elif ext == ".lua":
        item.set(Status.UNSUPPORTED, "Script Lua : non exécuté, non analysé.")
    else:
        item.set(Status.UNSUPPORTED, "Format non utilisé par le studio.")


# --- Analyse complète -------------------------------------------------------------


def source_kind(path: Path) -> str:
    if path.is_dir():
        return "dossier"
    return {".zip": "zip", ".rpf": "rpf"}.get(path.suffix.lower(), "fichier")


def analyze(
    path: str | Path,
    progress: Callable[[float, str], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> ResourceAnalysis:
    """Analyse complète. Lève FormatError (source illisible) ou AnalysisCancelled."""
    path = Path(path)
    if not path.exists():
        raise FormatError(f"Introuvable : {path}")
    report = progress or (lambda _v, _t: None)
    analysis = ResourceAnalysis(path, source_kind(path), path.stem if path.is_file() else path.name)
    try:
        report(0.02, "Inventaire des fichiers")
        _collect(analysis, cancel)
        total = max(len(analysis.files), 1)
        for index, item in enumerate(analysis.files):
            _check(cancel)
            report(0.05 + 0.85 * index / total, f"Analyse de {item.name}")
            try:
                _validate(item, analysis, cancel)
            except AnalysisCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 (un fichier invalide ne doit jamais interrompre)
                log.exception("Analyse de %s", item.path)
                item.set(Status.ERROR, f"Erreur inattendue pendant l'analyse : {exc}")
        report(0.92, "Références et dépendances")
        _resolve(analysis)
        report(1.0, "Analyse terminée")
    except BaseException:
        analysis.close()
        raise
    log.info(
        "Ressource analysée : %s (%d fichiers, statut %s)",
        analysis.name,
        len(analysis.files),
        analysis.overall.label,
    )
    return analysis


def _resolve(analysis: ResourceAnalysis) -> None:
    """Regroupe les modèles, croise les métadonnées et signale les références manquantes."""
    by_name: dict[str, VehicleModel] = {}
    ytds = {f.stem.lower(): f for f in analysis.files if f.extension == ".ytd"}
    for item in analysis.files:
        if item.extension not in (".yft", ".ydr"):
            continue
        stem = item.stem
        base = stem[:-3] if stem.lower().endswith("_hi") else stem
        model = by_name.setdefault(base.lower(), VehicleModel(base))
        if stem.lower().endswith("_hi"):
            model.yft_hi = item
        else:
            model.yft = item
    for model in by_name.values():
        for key in (model.name.lower(), f"{model.name.lower()}+hi"):
            if key in ytds:
                model.ytds.append(ytds[key])
    for entry in (e for d in analysis.metadata for e in d.entries if e.kind == "vehicle"):
        name = entry.fields.get("modelName", "")
        if not name:
            continue
        model = by_name.setdefault(name.lower(), VehicleModel(name))
        model.is_vehicle = True
        model.meta = dict(entry.fields)
        txd = entry.fields.get("txdName", "").lower()
        if txd in ytds and ytds[txd] not in model.ytds:
            model.ytds.append(ytds[txd])
    for model in by_name.values():
        if model.yft_hi is not None and model.yft is None:
            analysis.issues.append(("avertissement", f"{model.name} : variante _hi sans modèle de base."))
        item = model.yft
        if item is None or item.status is not Status.COMPATIBLE:
            continue
        embedded = {t.lower() for t in item.details.get("embedded_textures", [])}
        refs = {t.lower() for t in item.details.get("texture_refs", [])}
        available = embedded | {t.lower() for ytd in model.ytds for t in ytd.details.get("textures", [])}
        missing = sorted(refs - available)
        item.details["missing_textures"] = missing
        if refs and not model.ytds and not embedded and model.is_vehicle:
            item.set(Status.MISSING, f"Dépendance manquante : {model.name}.ytd (textures du véhicule).")
        elif missing:
            item.details.setdefault("warnings", []).append(
                f"{len(missing)} texture(s) absente(s) de la ressource (souvent partagées par le jeu)."
            )
    analysis.models = sorted(by_name.values(), key=lambda m: (not m.is_vehicle, m.name.lower()))
    issues = meta_mod.cross_check(
        analysis.metadata, {m.name for m in analysis.models if m.yft is not None}, set(ytds)
    )
    analysis.issues.extend((issue.level, issue.message) for issue in issues)
    if any(i.level == "erreur" for i in issues):
        for item in analysis.files:
            if item.details.get("meta_kind") == "vehicles" and item.status is Status.COMPATIBLE:
                item.set(Status.MISSING, "Références vers des fichiers absents (voir les diagnostics).")
    if not analysis.models:
        analysis.issues.append(("avertissement", "Aucun modèle .yft / .ydr trouvé dans la ressource."))
    if analysis.protected:
        analysis.issues.insert(
            0, ("erreur", "Ressource protégée par FiveM Asset Escrow : contenu chiffré non lisible.")
        )
    setup = next((d for d in analysis.metadata if d.kind == "setup" and d.root is not None), None)
    if setup is not None:
        device = meta_mod._text(setup.root, "deviceName")
        if device:
            analysis.name = device.removeprefix("dlc_") or analysis.name


# --- Préparation de l'import ------------------------------------------------------


def stage_model(analysis: ResourceAnalysis, model: VehicleModel, folder: Path, high: bool = False) -> Path:
    """Extrait le modèle et ses dictionnaires de textures dans ``folder`` (copies)."""
    source = model.yft_hi if high and model.yft_hi is not None else model.yft
    if source is None:
        raise FormatError(f"Aucun fichier modèle pour {model.name}.")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / source.name
    target.write_bytes(source.read())
    for ytd in model.ytds:
        (folder / ytd.name).write_bytes(ytd.read())
    return target


MANIFEST_VERSION = 1


def build_manifest(
    analysis: ResourceAnalysis, model: VehicleModel, copies: dict[str, str], asset_id: str = ""
) -> dict:
    """Manifeste versionné décrivant la ressource importée (enregistré dans le .lsfc)."""
    yft = model.yft
    details = yft.details if yft else {}
    return {
        "manifest_version": MANIFEST_VERSION,
        "resource": {
            "name": analysis.name,
            "source": str(analysis.source),
            "source_kind": analysis.source_kind,
            "total_size": analysis.total_size,
            "overall_status": analysis.overall.value,
            "protected": analysis.protected,
        },
        "model": {
            "name": model.name,
            "asset_id": asset_id,
            "is_vehicle": model.is_vehicle,
            "meta": model.meta,
            "triangles": details.get("triangles"),
            "bones": details.get("bones"),
            "lods": details.get("lods", []),
            "shaders": details.get("shaders", []),
            "missing_textures": details.get("missing_textures", []),
        },
        "files": [
            {
                "path": f.path,
                "size": f.size,
                "origin": f.origin,
                "status": f.status.value,
                "message": f.message,
                "copy": copies.get(f.path, ""),
            }
            for f in analysis.files
        ],
        "textures": [
            {
                "name": t.name,
                "source": t.source,
                "size": [t.width, t.height],
                "format": t.format,
                "levels": t.levels,
                "memory": t.memory,
                "decoded": t.decoded,
                "alpha": t.alpha,
                "reason": t.reason,
            }
            for t in analysis.textures
        ],
        "metadata": [
            {
                "path": d.path,
                "kind": d.kind,
                "entries": [{"kind": e.kind, "name": e.name, "fields": e.fields} for e in d.entries],
                "issues": [{"level": i.level, "message": i.message} for i in d.issues],
            }
            for d in analysis.metadata
        ],
        "dependencies": list(analysis.dependencies),
        "issues": [{"level": level, "message": message} for level, message in analysis.issues],
    }
