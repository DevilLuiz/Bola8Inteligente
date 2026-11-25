import numpy as np

from .config import Config


class WhisperSTT:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._model = None

    def load(self) -> None:
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.cfg.whisper_model,
                device=self.cfg.whisper_device,
                compute_type=self.cfg.whisper_compute,
            )

    def transcribe(self, audio: np.ndarray) -> str:
        self.load()
        segments, _ = self._model.transcribe(
            audio.astype(np.float32),
            language=self.cfg.language,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments).strip()
