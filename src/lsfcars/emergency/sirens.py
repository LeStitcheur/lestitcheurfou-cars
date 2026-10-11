"""Sirènes : tonalités **originales** synthétisées et aperçu sonore.

Aucun son tiers n'est distribué : les tonalités intégrées (wail, yelp, deux tons, priorité,
avertisseur) sont générées par calcul. Un son personnel peut être associé à un mode, avec sa
licence déclarée par l'utilisateur. Un son joué dans l'application **n'est pas** utilisable tel
quel dans GTA V : FiveM attend des banques audio (« AudioString » / « SoundSet ») préparées
séparément ; ces noms ne sont que des métadonnées d'export.
"""

from __future__ import annotations

import io
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

from lsfcars.emergency.model import SIREN_TONES

SAMPLE_RATE = 22050
TONE_LICENSE = "Original, synthétisé par LeStitcheurFou Cars : libre d'utilisation"


def _sweep(duration: float, low: float, high: float, period: float) -> np.ndarray:
    t = np.arange(int(duration * SAMPLE_RATE)) / SAMPLE_RATE
    modulation = 0.5 - 0.5 * np.cos(2 * np.pi * (t % period) / period)
    frequency = low + (high - low) * modulation
    phase = 2 * np.pi * np.cumsum(frequency) / SAMPLE_RATE
    return np.sin(phase) + 0.25 * np.sin(2 * phase) + 0.12 * np.sin(3 * phase)


def _two_tone(duration: float, first: float, second: float, period: float) -> np.ndarray:
    t = np.arange(int(duration * SAMPLE_RATE)) / SAMPLE_RATE
    frequency = np.where((t % (2 * period)) < period, first, second)
    phase = 2 * np.pi * np.cumsum(frequency) / SAMPLE_RATE
    return np.sign(np.sin(phase)) * 0.35 + 0.65 * np.sin(phase)


def tone_samples(tone: str, duration: float = 2.0) -> np.ndarray:
    """Échantillons (-1…1) d'une tonalité intégrée ; déterministe."""
    if tone == "none":
        return np.zeros(int(0.1 * SAMPLE_RATE))
    generators = {
        "wail": lambda: _sweep(duration, 620.0, 1350.0, 3.0),
        "yelp": lambda: _sweep(duration, 650.0, 1450.0, 0.32),
        "hilo": lambda: _two_tone(duration, 960.0, 770.0, 0.5),
        "priority": lambda: _two_tone(duration, 1100.0, 800.0, 0.12),
        "horn": lambda: _two_tone(max(duration * 0.4, 0.3), 380.0, 380.0, 1.0),
    }
    if tone not in generators:
        raise ValueError(f"Tonalité inconnue : {tone}")
    signal = generators[tone]()
    fade = max(min(len(signal) // 10, int(0.02 * SAMPLE_RATE)), 1)
    envelope = np.ones(len(signal))
    envelope[:fade] = np.linspace(0, 1, fade)
    envelope[-fade:] = np.linspace(1, 0, fade)
    signal = signal * envelope
    return signal / max(float(np.max(np.abs(signal))), 1e-9) * 0.6


def tone_wav(tone: str, duration: float = 2.0) -> bytes:
    """WAV PCM 16 bits mono d'une tonalité intégrée."""
    samples = (tone_samples(tone, duration) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(samples.tobytes())
    return buffer.getvalue()


def playback_available() -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "Aperçu sonore disponible sous Windows seulement (module winsound)."
    return True, "Aperçu via le lecteur audio de Windows"


class SirenPlayer:
    """Aperçu sonore non bloquant (Windows) ; un seul son à la fois."""

    def __init__(self) -> None:
        self._folder = Path(tempfile.mkdtemp(prefix="lsfcars-sirens-"))
        self.playing: str | None = None

    def play(self, tone: str, custom_file: str | Path | None = None, loop: bool = False) -> bool:
        available, _reason = playback_available()
        if not available:
            return False
        import winsound

        if custom_file is not None:
            path = Path(custom_file)
            if path.suffix.lower() != ".wav" or not path.is_file():
                raise ValueError("Seuls les fichiers WAV existants peuvent être prévisualisés.")
        else:
            if tone not in SIREN_TONES:
                raise ValueError(f"Tonalité inconnue : {tone}")
            path = self._folder / f"{tone}.wav"
            if not path.exists():
                path.write_bytes(tone_wav(tone, 3.0))
        flags = winsound.SND_FILENAME | winsound.SND_ASYNC
        if loop:
            flags |= winsound.SND_LOOP
        winsound.PlaySound(str(path), flags)
        self.playing = tone
        return True

    def stop(self) -> None:
        if sys.platform == "win32":
            import winsound

            winsound.PlaySound(None, 0)
        self.playing = None
