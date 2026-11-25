"""Piper TTS com cache em disco: respostas repetidas (presets, avisos) saem na hora."""
import hashlib
import threading
import wave
from pathlib import Path

from .config import Config


class PiperTTS:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._voice = None
        self._lock = threading.Lock()
        self._dir = Path(cfg.out_dir) / "tts"

    def load(self) -> None:
        if self._voice is None:
            from piper import PiperVoice

            self._voice = PiperVoice.load(str(self.cfg.piper_model))

    def synth(self, text: str) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha1(f"{self.cfg.piper_model}|{text}".encode()).hexdigest()[:16]
        path = self._dir / f"{key}.wav"
        if path.exists():
            return path
        with self._lock:
            self.load()
            tmp = path.with_suffix(".tmp")
            with wave.open(str(tmp), "wb") as w:
                if hasattr(self._voice, "synthesize_wav"):   # piper-tts >= 1.3
                    self._voice.synthesize_wav(text, w)
                else:                                        # piper-tts 1.2
                    self._voice.synthesize(text, w)
            tmp.replace(path)
        return path
