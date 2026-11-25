"""Pipeline completa: gravar -> transcrever -> filtrar -> responder -> falar."""
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from . import safety as S
from .config import Config
from .safety import Safety
from .store import Store

log = logging.getLogger("ball")


@dataclass
class Result:
    question: str
    answer: str
    source: str          # preset | llm | blocked | not_heard | error
    wav_path: Path
    latency_s: float


class Pipeline:
    """recorder/stt/llm/tts são injetados para poder testar com falsos."""

    def __init__(self, cfg: Config, store: Store, recorder, stt, llm, tts):
        self.cfg, self.store = cfg, store
        self.safety = Safety(store, cfg.max_answer_chars)
        self.recorder, self.stt, self.llm, self.tts = recorder, stt, llm, tts

    def warm_up(self) -> None:
        """Carrega modelos antes da primeira chacoalhada."""
        if hasattr(self.stt, "load"):
            self.stt.load()
        if hasattr(self.tts, "load"):
            self.tts.load()
        for phrase in (S.REDIRECT, S.NOT_HEARD, S.ERROR):
            self.tts.synth(phrase)

    def answer_for(self, question: str) -> tuple[str, str]:
        """Texto da pergunta -> (resposta, origem). Não usa microfone nem STT."""
        if self.safety.is_blocked(question):
            return S.REDIRECT, "blocked"
        preset = self.safety.find_preset(question)
        if preset:
            return preset, "preset"
        try:
            answer = self.safety.sanitize_answer(self.llm.ask(question))
        except Exception:
            log.exception("falha no LLM")
            return S.ERROR, "error"
        if not answer:
            return S.REDIRECT, "blocked"
        return answer, "llm"

    def respond_to_text(self, question: str) -> Result:
        t0 = time.monotonic()
        answer, source = self.answer_for(question)
        return self._finish(t0, question, answer, source)

    def run(self) -> Result:
        """Um ciclo completo, disparado pela chacoalhada."""
        t0 = time.monotonic()
        try:
            audio = self.recorder.record()
            if audio is None:
                return self._finish(t0, "", S.NOT_HEARD, "not_heard")
            question = self.stt.transcribe(audio)
        except Exception:
            log.exception("falha ao gravar/transcrever")
            return self._finish(t0, "", S.ERROR, "error")
        if self.safety.is_hallucination(question):
            return self._finish(t0, question, S.NOT_HEARD, "not_heard")
        answer, source = self.answer_for(question)
        return self._finish(t0, question, answer, source)

    def _finish(self, t0: float, question: str, answer: str, source: str) -> Result:
        wav = self.tts.synth(answer)
        latency = time.monotonic() - t0
        self.store.log(question, answer, source, latency)
        log.info("[%s %.1fs] P: %r | R: %r", source, latency, question, answer)
        return Result(question, answer, source, wav, latency)
