"""Fictional Brand Library : marques automobiles fictives (univers GTA V) et marques originales.

Les marques de l'univers GTA V sont des **références créatives** : seul leur nom est cité, avec
une description stylistique rédigée pour LeStitcheurFou Cars. Aucun logo, aucun modèle et
aucune ressource n'est fourni ou téléchargé, et leur utilisation n'est pas présentée comme
automatiquement autorisée : elle reste soumise aux conditions de Rockstar Games / Take-Two et,
sur un serveur, de Cfx.re. Les marques personnalisées sont créées par l'utilisateur.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

from lsfcars.ai import lore as ai_lore

CATEGORIES = {
    "compact": "Compacte",
    "sedan": "Berline",
    "coupe": "Coupé",
    "sport": "Sportive",
    "super": "Supercar",
    "muscle": "Muscle car",
    "suv": "SUV",
    "offroad": "Tout-terrain",
    "pickup": "Pick-up",
    "van": "Utilitaire / van",
    "luxury": "Luxe",
    "classic": "Classique",
    "service": "Véhicule de service",
    "motorcycle": "Moto",
}
GTA_PROVENANCE = (
    "Marque fictive de l'univers Grand Theft Auto V (Rockstar Games). Nom cité comme référence "
    "créative ; aucun logo, modèle ou fichier n'est fourni ni téléchargé par LeStitcheurFou Cars."
)
GTA_LICENSE = (
    "Aucune licence accordée par LeStitcheurFou Cars. Utilisation soumise aux conditions de "
    "Rockstar Games / Take-Two et, sur un serveur FiveM, à celles de Cfx.re."
)
GTA_IDENTITY = (
    "Nom en texte uniquement. Le logo officiel n'est pas reproduit : créez un emblème original "
    "dans Livery Studio si votre usage le permet."
)
CUSTOM_LICENSE_UNKNOWN = "Non renseignée"


@dataclass
class Brand:
    key: str
    name: str
    description: str
    categories: list[str]
    style: str  # direction stylistique
    traits: list[str]  # caractéristiques générales
    palette: list[str]  # palette indicative (#RRGGBB)
    identity: str  # identité visuelle autorisée
    dna: dict[str, int] = field(default_factory=dict)  # valeurs Design DNA par défaut
    resources: list[str] = field(default_factory=list)  # ressources associées (fichiers du projet)
    origin: str = "custom"  # gta / custom
    provenance: str = ""
    license: str = CUSTOM_LICENSE_UNKNOWN
    author: str = ""

    @property
    def is_gta(self) -> bool:
        return self.origin == "gta"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Brand:
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        brand = cls(**known)
        brand.categories = [c for c in brand.categories if c in CATEGORIES]
        return brand


def _gta(key: str, name: str, description: str, categories, style: str, traits, palette, dna) -> Brand:  # type: ignore[no-untyped-def]
    return Brand(
        key,
        name,
        description,
        list(categories),
        style,
        list(traits),
        list(palette),
        GTA_IDENTITY,
        dict(dna),
        origin="gta",
        provenance=GTA_PROVENANCE,
        license=GTA_LICENSE,
        author="Rockstar Games (univers GTA V)",
    )


# Descriptions rédigées pour LeStitcheurFou Cars (aucune reprise de texte officiel).
GTA_BRANDS: tuple[Brand, ...] = (
    _gta("vapid", "Vapid", "Constructeur américain grand public : véhicules populaires, muscle cars, "
         "pick-up, utilitaires et flottes de service.", ("sedan", "muscle", "pickup", "van", "service"),
         "Américain populaire, volumes francs et calandre large", ["calandre horizontale large",
         "optiques rectangulaires", "pare-chocs massifs"], ["#1F3A68", "#C8CCD2", "#20242B"],
         {"sport": 45, "robust": 65, "utility": 60, "retro": 35, "aggressive": 45}),
    _gta("bravado", "Bravado", "Constructeur américain au caractère affirmé : muscle cars agressives, "
         "SUV et fourgons puissants.", ("muscle", "suv", "van", "service"),
         "Muscle américain agressif", ["capot long", "prises d'air marquées", "face avant agressive"],
         ["#7A1F1F", "#111318", "#B8BCC4"], {"sport": 70, "aggressive": 85, "robust": 60, "retro": 40}),
    _gta("declasse", "Declasse", "Constructeur américain populaire et nostalgique : modèles rétro, "
         "lowriders, muscle classiques et pick-up.", ("classic", "muscle", "pickup", "sedan"),
         "Rétro américain, chromes et lignes longues", ["chromes", "lignes horizontales",
         "porte-à-faux généreux"], ["#2E5E4E", "#E8E2D0", "#9AA3AD"],
         {"retro": 80, "luxury": 35, "sport": 40}),
    _gta("albany", "Albany", "Constructeur américain de prestige classique : grandes berlines, "
         "limousines et SUV statutaires.", ("luxury", "sedan", "suv", "classic"),
         "Luxe américain imposant", ["calandre verticale imposante", "silhouette longue",
         "chromes discrets"], ["#141820", "#C9B37E", "#6B717C"], {"luxury": 80, "sobriety": 55, "retro": 45}),
    _gta("benefactor", "Benefactor", "Constructeur allemand haut de gamme : berlines, coupés et SUV "
         "alliant luxe et performances.", ("luxury", "sedan", "coupe", "suv", "sport"),
         "Premium allemand élégant", ["surfaces tendues", "optiques affinées", "calandre soignée"],
         ["#2B2F36", "#D9DCE1", "#5A6A7E"], {"luxury": 85, "modern": 75, "sobriety": 70, "sport": 55}),
    _gta("obey", "Obey", "Constructeur allemand premium : berlines et coupés sportifs sobres, "
         "souvent à transmission intégrale.", ("sedan", "coupe", "sport", "suv"),
         "Premium sportif sobre", ["calandre basse et large", "signature lumineuse fine",
         "lignes tendues"], ["#3A3F47", "#A9B0BA", "#0F1115"], {"sport": 65, "sobriety": 75, "modern": 75}),
    _gta("ubermacht", "Übermacht", "Constructeur allemand sportif : berlines et coupés dynamiques à la "
         "face avant affirmée.", ("sedan", "coupe", "sport", "suv"), "Sport premium dynamique",
         ["face avant affirmée", "épaules marquées", "jantes larges"], ["#1E3F7A", "#E4E6EA", "#26292F"],
         {"sport": 75, "luxury": 60, "aggressive": 55, "modern": 70}),
    _gta("karin", "Karin", "Constructeur japonais polyvalent : berlines fiables, tout-terrain "
         "robustes et sportives.", ("sedan", "offroad", "suv", "sport", "pickup"),
         "Japonais fiable et polyvalent", ["volumes rationnels", "protections fonctionnelles"],
         ["#B3261E", "#F2F2F2", "#2C2F35"], {"robust": 65, "offroad": 55, "utility": 55, "modern": 55}),
    _gta("dinka", "Dinka", "Constructeur japonais : compactes, sportives accessibles et motos.",
         ("compact", "sport", "motorcycle", "sedan"), "Japonais vif et compact",
         ["optiques étirées", "lignes vives"], ["#E0E3E8", "#1C1F24", "#D2462B"],
         {"sport": 60, "modern": 70, "aero": 55}),
    _gta("annis", "Annis", "Constructeur japonais orienté sport et préparation : coupés et "
         "sportives au tempérament tuning.", ("sport", "coupe", "compact"), "Sport japonais préparé",
         ["aérodynamique visible", "ailerons", "boucliers sculptés"], ["#F2C230", "#15171B", "#C0C4CA"],
         {"sport": 80, "aero": 75, "aggressive": 65}),
    _gta("pfister", "Pfister", "Constructeur allemand de sportives et GT, réputé pour ses coupés aux "
         "lignes arrondies.", ("sport", "coupe", "super"), "GT allemande arrondie",
         ["silhouette fluide", "optiques rondes ou ovales", "arrière ramassé"],
         ["#C9CDD3", "#8A1B1B", "#1A1C20"], {"sport": 80, "aero": 70, "luxury": 55, "retro": 35}),
    _gta("grotti", "Grotti", "Constructeur italien de sportives et de grandes routières élégantes.",
         ("sport", "super", "coupe"), "Sportive italienne élégante", ["courbes sensuelles",
         "capot long", "prises d'air latérales"], ["#B0161B", "#F4E7C5", "#202226"],
         {"sport": 90, "luxury": 70, "aero": 75}),
    _gta("pegassi", "Pegassi", "Constructeur italien de supercars radicales et de motos sportives.",
         ("super", "sport", "motorcycle"), "Supercar radicale et angulaire",
         ["arêtes vives", "silhouette basse", "grandes prises d'air"], ["#9BC53D", "#0D0F12", "#F2A30F"],
         {"sport": 95, "aggressive": 95, "aero": 90, "modern": 80}),
    _gta("ocelot", "Ocelot", "Constructeur britannique de coupés et GT sportives raffinées.",
         ("coupe", "sport", "luxury"), "GT britannique raffinée", ["proportions élancées",
         "calandre ovale", "élégance discrète"], ["#1D4D3A", "#D6C9A8", "#2A2C30"],
         {"luxury": 70, "sport": 70, "retro": 40}),
    _gta("enus", "Enus", "Constructeur britannique d'automobiles de très grand luxe : berlines et "
         "coupés de prestige.", ("luxury", "sedan", "coupe"), "Prestige britannique",
         ["calandre monumentale", "volumes nobles", "porte-à-faux arrière long"],
         ["#0E1A2B", "#D8D3C4", "#8C7A55"], {"luxury": 95, "sobriety": 70, "retro": 45}),
    _gta("gallivanter", "Gallivanter", "Constructeur britannique de tout-terrain de luxe.",
         ("suv", "offroad", "luxury"), "Tout-terrain de luxe", ["toit flottant", "garde au sol élevée",
         "lignes horizontales"], ["#3B4A3F", "#E6E2DA", "#1E2124"],
         {"luxury": 75, "offroad": 65, "robust": 65, "modern": 60}),
    _gta("canis", "Canis", "Constructeur américain de 4x4 et utilitaires robustes.",
         ("offroad", "pickup", "suv", "service"), "Tout-terrain utilitaire", ["passages de roues larges",
         "protections", "formes carrées"], ["#56602F", "#C7B58A", "#232528"],
         {"offroad": 85, "robust": 85, "utility": 70}),
    _gta("dundreary", "Dundreary", "Constructeur britannique : berlines bourgeoises, limousines et SUV.",
         ("luxury", "sedan", "suv"), "Bourgeois britannique", ["calandre droite", "lignes classiques"],
         ["#2F2A3A", "#C8C2B4", "#62666E"], {"luxury": 70, "sobriety": 70, "retro": 50}),
    _gta("emperor", "Emperor", "Constructeur japonais haut de gamme : berlines et SUV confortables.",
         ("luxury", "sedan", "suv"), "Luxe japonais discret", ["surfaces lisses", "optiques fines"],
         ["#E7E8EA", "#3D434C", "#9E8C6C"], {"luxury": 70, "sobriety": 75, "modern": 65}),
    _gta("maibatsu", "Maibatsu", "Constructeur japonais d'utilitaires, de vans et de motos sportives.",
         ("van", "pickup", "motorcycle", "compact"), "Utilitaire japonais", ["volumes simples",
         "lisibilité", "accessoires fonctionnels"], ["#F0F0F0", "#2B5DA8", "#2A2D31"],
         {"utility": 80, "robust": 60, "sobriety": 60}),
)  # fmt: skip


def _norm(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", plain.lower())


def slug(name: str) -> str:
    return _norm(name) or "marque"


class BrandError(ValueError):
    """Marque refusée (nom vide, marque réelle, doublon)."""


def validate_custom_name(name: str, existing: list[Brand]) -> str:
    """Nom d'une marque personnalisée : non vide, ni marque réelle connue, ni doublon."""
    cleaned = " ".join(name.split())
    if not cleaned:
        raise BrandError("Le nom de la marque est vide.")
    words = re.findall(r"[a-zà-ÿ]+", cleaned.lower())
    if any(_norm(w) in ai_lore.REAL_BRANDS for w in words) or _norm(cleaned) in ai_lore.REAL_BRANDS:
        raise BrandError(
            f"« {cleaned} » correspond à une marque automobile réelle : choisissez un nom fictif."
        )
    if any(_norm(b.name) == _norm(cleaned) for b in existing):
        raise BrandError(f"La marque « {cleaned} » existe déjà dans la bibliothèque.")
    return cleaned


class BrandLibrary:
    """Marques GTA V intégrées + marques personnalisées (projet et bibliothèque utilisateur)."""

    def __init__(self, user_file: Path | None = None) -> None:
        self.user_file = user_file
        self.user: list[Brand] = []
        self.project: list[Brand] = []
        self.load_user()

    # --- Persistance de la bibliothèque utilisateur -------------------------------------
    def load_user(self) -> None:
        self.user = []
        if self.user_file is None or not self.user_file.is_file():
            return
        try:
            data = json.loads(self.user_file.read_text(encoding="utf-8"))
            self.user = [Brand.from_dict(b) for b in data.get("brands", []) if isinstance(b, dict)]
        except (OSError, ValueError, TypeError):
            self.user = []

    def save_user(self) -> None:
        if self.user_file is None:
            return
        self.user_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"format": 1, "brands": [b.to_dict() for b in self.user]}
        self.user_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- Consultation ------------------------------------------------------------------
    def all(self) -> list[Brand]:
        seen: set[str] = set()
        result: list[Brand] = []
        for brand in [*self.project, *self.user, *GTA_BRANDS]:
            if brand.key not in seen:
                seen.add(brand.key)
                result.append(brand)
        return result

    def get(self, key: str | None) -> Brand | None:
        return next((b for b in self.all() if b.key == key), None)

    def search(self, text: str = "", category: str | None = None, origin: str | None = None) -> list[Brand]:
        needle = _norm(text)
        result = []
        for brand in self.all():
            if category and category not in brand.categories:
                continue
            if origin and brand.origin != origin:
                continue
            haystack = _norm(" ".join([brand.name, brand.description, brand.style, *brand.traits]))
            if needle and needle not in haystack:
                continue
            result.append(brand)
        return result

    # --- Marques personnalisées ----------------------------------------------------------
    def create(
        self,
        name: str,
        description: str = "",
        categories=(),  # type: ignore[no-untyped-def]
        style: str = "",
        traits=(),  # type: ignore[no-untyped-def]
        palette=(),  # type: ignore[no-untyped-def]
        dna: dict | None = None,
        author: str = "",
        license: str = "",  # noqa: A002 (champ du registre)
        identity: str = "Identité visuelle originale créée par l'utilisateur.",
        save_to_user: bool = False,
    ) -> Brand:
        cleaned = validate_custom_name(name, self.all())
        key = f"custom-{slug(cleaned)}"
        brand = Brand(
            key,
            cleaned,
            description.strip(),
            [c for c in categories if c in CATEGORIES],
            style.strip(),
            [t for t in traits if t],
            [p for p in palette if re.fullmatch(r"#[0-9A-Fa-f]{6}", p or "")],
            identity,
            {k: int(v) for k, v in (dna or {}).items()},
            origin="custom",
            provenance="Marque originale créée dans LeStitcheurFou Cars.",
            license=license.strip() or CUSTOM_LICENSE_UNKNOWN,
            author=author.strip(),
        )
        self.project.append(brand)
        if save_to_user:
            self.user = [b for b in self.user if b.key != key] + [brand]
            self.save_user()
        return brand

    def suggest_names(self, seed: str, count: int = 6) -> list[str]:
        """Noms originaux générés (filtrés : ni marque réelle, ni marque de l'univers GTA)."""
        taken = {_norm(b.name) for b in self.all()}
        return [n for n in ai_lore.brand_names(seed, count + 4) if _norm(n) not in taken][:count]
