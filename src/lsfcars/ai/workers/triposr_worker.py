"""Processus auxiliaire TripoSR (exécuté par le Python du moteur, jamais par l'application).

Usage : python triposr_worker.py --src <dossier TripoSR> --weights <dossier des poids>
        --input <image RGBA détourée> --output <fichier .glb> [--mc-resolution 256]
        [--chunk-size 8192] [--device cuda|cpu] [--foreground-ratio 0.85]

Communique par lignes JSON sur la sortie standard :
  {"progress": 0.4, "text": "..."}   {"done": "<chemin>", "stats": {...}}   {"error": "..."}

Le dépôt TripoSR (MIT) n'est pas modifié : ``torchmcubes`` (extension à compiler) est remplacé
par PyMCubes et ``rembg`` n'est pas importé. Avec ``--u2net <modèle.onnx>``, le fond est retiré
par le réseau U²-Net (Apache-2.0, modèle distribué par le projet rembg) exécuté avec
onnxruntime, selon le même prétraitement que rembg.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
import types


def emit(**payload) -> None:  # type: ignore[no-untyped-def]
    print(json.dumps(payload), flush=True)


def install_stubs() -> None:
    try:
        import torchmcubes  # noqa: F401
    except ImportError:
        import mcubes
        import numpy as np
        import torch

        module = types.ModuleType("torchmcubes")

        def marching_cubes(volume, threshold):  # type: ignore[no-untyped-def]
            values = volume.detach().cpu().numpy().astype(np.float64)
            vertices, faces = mcubes.marching_cubes(values, float(threshold))
            # torchmcubes renvoie les coordonnées dans l'ordre inverse des indices (x = dernier axe)
            vertices = np.ascontiguousarray(vertices[:, ::-1])
            return torch.from_numpy(vertices.astype(np.float32)), torch.from_numpy(faces.astype(np.int64))

        module.marching_cubes = marching_cubes
        sys.modules["torchmcubes"] = module
    try:
        import rembg  # noqa: F401
    except ImportError:
        stub = types.ModuleType("rembg")

        def unavailable(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("rembg absent : le détourage est fourni par LeStitcheurFou Cars.")

        stub.remove = unavailable
        stub.new_session = lambda *_a, **_k: None
        sys.modules["rembg"] = stub


def u2net_alpha(image, model_path: str):  # type: ignore[no-untyped-def]
    """Masque de premier plan (0-255) par U²-Net : prétraitement identique à rembg (320², ImageNet)."""
    import numpy as np
    import onnxruntime as ort
    from PIL import Image

    providers = [
        p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in ort.get_available_providers()
    ]
    session = ort.InferenceSession(model_path, providers=providers)
    rgb = image.convert("RGB")
    small = np.asarray(rgb.resize((320, 320), Image.Resampling.LANCZOS)).astype(np.float32)
    small /= max(float(small.max()), 1e-6)
    mean, std = np.array([0.485, 0.456, 0.406]), np.array([0.229, 0.224, 0.225])
    tensor = ((small - mean) / std).transpose(2, 0, 1)[None].astype(np.float32)
    prediction = session.run(None, {session.get_inputs()[0].name: tensor})[0][0, 0]
    low, high = float(prediction.min()), float(prediction.max())
    prediction = (prediction - low) / max(high - low, 1e-6)
    mask = Image.fromarray((prediction * 255).astype(np.uint8)).resize(rgb.size, Image.Resampling.LANCZOS)
    return mask


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True)
    parser.add_argument("--weights", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--mc-resolution", type=int, default=256)
    parser.add_argument("--chunk-size", type=int, default=8192)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--foreground-ratio", type=float, default=0.85)
    parser.add_argument("--u2net", default="", help="modèle U²-Net (.onnx) : détourage neuronal de l'image")
    args = parser.parse_args()
    start = time.monotonic()
    try:
        sys.path.insert(0, args.src)
        emit(progress=0.02, text="Chargement de PyTorch")
        install_stubs()
        import numpy as np
        import torch
        from PIL import Image

        device = args.device
        if device.startswith("cuda") and not torch.cuda.is_available():
            emit(progress=0.03, text="CUDA indisponible : calcul sur le processeur (lent)")
            device = "cpu"
        from tsr.system import TSR
        from tsr.utils import resize_foreground

        emit(progress=0.08, text="Chargement du modèle TripoSR")
        model = TSR.from_pretrained(args.weights, config_name="config.yaml", weight_name="model.ckpt")
        model.renderer.set_chunk_size(args.chunk_size)
        model.to(device)
        emit(progress=0.35, text="Préparation de l'image")
        image = Image.open(args.input).convert("RGBA")
        if args.u2net:
            emit(progress=0.38, text="Détourage neuronal (U²-Net)")
            mask = u2net_alpha(image, args.u2net)
            coverage = float((np.asarray(mask) >= 128).mean())
            if coverage < 0.01 or coverage > 0.97:
                raise RuntimeError(
                    f"Détourage U²-Net : aucun sujet distinct du fond (couverture {coverage:.0%}). "
                    "Cadrez le véhicule entier sur l'image ou fournissez un PNG détouré."
                )
            image.putalpha(mask)
            image.save(args.input.replace(".png", "_u2net.png"))  # contrôle visuel du détourage
        image = resize_foreground(image, args.foreground_ratio)
        array = np.asarray(image).astype(np.float32) / 255.0
        rgb = array[:, :, :3] * array[:, :, 3:4] + (1 - array[:, :, 3:4]) * 0.5
        image = Image.fromarray((rgb * 255.0).astype(np.uint8))
        emit(progress=0.45, text=f"Inférence ({device})")
        with torch.no_grad():
            scene_codes = model([image], device=device)
        emit(progress=0.7, text=f"Extraction du maillage (résolution {args.mc_resolution})")
        mesh = model.extract_mesh(scene_codes, True, resolution=args.mc_resolution)[0]
        mesh.export(args.output)
        stats = {
            "vertices": int(len(mesh.vertices)),
            "faces": int(len(mesh.faces)),
            "device": device,
            "gpu": torch.cuda.get_device_name(0) if device.startswith("cuda") else "",
            "torch": torch.__version__,
            "seconds": round(time.monotonic() - start, 2),
            "peak_vram_mb": int(torch.cuda.max_memory_allocated() / 2**20)
            if device.startswith("cuda")
            else 0,
        }
        emit(progress=1.0, text="Maillage écrit")
        emit(done=args.output, stats=stats)
        return 0
    except Exception as exc:  # noqa: BLE001 (toute erreur est remontée à l'application)
        emit(error=f"{type(exc).__name__}: {exc}", trace=traceback.format_exc()[-2000:])
        return 1


if __name__ == "__main__":
    sys.exit(main())
