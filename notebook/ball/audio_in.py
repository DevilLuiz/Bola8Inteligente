"""Gravação pelo microfone do notebook, com detecção de fim de fala por energia."""
from collections import deque

import numpy as np

from .config import Config

FRAME_S = 0.03
CALIBRATION_FRAMES = 10   # ~0.3 s para medir o ruído de fundo
PREROLL_FRAMES = 10       # guarda ~0.3 s antes do início da fala
MIN_VOICED_S = 0.3        # ignora estalos mais curtos que isso


def rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(frame, dtype=np.float64)))) if len(frame) else 0.0


class Endpointer:
    """Máquina de estados alimentada quadro a quadro (testável sem microfone)."""

    def __init__(self, cfg: Config, frame_s: float = FRAME_S):
        self.cfg = cfg
        self.frame_s = frame_s
        self.frames: list[np.ndarray] = []
        self._preroll: deque = deque(maxlen=PREROLL_FRAMES)
        self._calib: list[float] = []
        self.threshold = cfg.min_rms
        self.elapsed = 0.0
        self.started = False
        self.voiced_s = 0.0
        self.silence_s = 0.0
        self.speech_s = 0.0

    def feed(self, frame: np.ndarray) -> str:
        """Retorna 'calibrating' | 'waiting' | 'speaking' | 'done' | 'no_speech'."""
        self.elapsed += self.frame_s
        level = rms(frame)

        if len(self._calib) < CALIBRATION_FRAMES:
            self._calib.append(level)
            if len(self._calib) == CALIBRATION_FRAMES:
                noise = float(np.mean(self._calib))
                self.threshold = max(self.cfg.min_rms, noise * self.cfg.speech_margin)
            self._preroll.append(frame)
            return "calibrating"

        loud = level > self.threshold

        if not self.started:
            self._preroll.append(frame)
            if loud:
                self.started = True
                self.frames = list(self._preroll)
                self.voiced_s = self.frame_s
                self.silence_s = 0.0
                self.speech_s = self.frame_s
                return "speaking"
            if self.elapsed > self.cfg.wait_speech_s:
                return "no_speech"
            return "waiting"

        self.frames.append(frame)
        self.speech_s += self.frame_s
        if loud:
            self.voiced_s += self.frame_s
            self.silence_s = 0.0
        else:
            self.silence_s += self.frame_s

        if self.speech_s >= self.cfg.max_record_s:
            return "done"
        if self.silence_s >= self.cfg.silence_end_s:
            if self.voiced_s >= MIN_VOICED_S:
                return "done"
            # só um estalo: volta a esperar a fala de verdade
            self.started = False
            self.frames = []
            self._preroll.clear()
            return "waiting"
        return "speaking"

    def audio(self) -> np.ndarray:
        return np.concatenate(self.frames) if self.frames else np.zeros(0, dtype=np.float32)


class Recorder:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def record(self) -> np.ndarray | None:
        """Bloqueia até a criança terminar de falar. None se ninguém falou."""
        import sounddevice as sd

        sr = self.cfg.sample_rate
        frame_len = int(sr * FRAME_S)
        ep = Endpointer(self.cfg)
        device = self.cfg.mic_device
        if device is not None and device.isdigit():
            device = int(device)
        with sd.InputStream(samplerate=sr, channels=1, dtype="float32",
                            blocksize=frame_len, device=device) as stream:
            while True:
                data, _ = stream.read(frame_len)
                state = ep.feed(data[:, 0].copy())
                if state == "done":
                    return ep.audio()
                if state == "no_speech":
                    return None
