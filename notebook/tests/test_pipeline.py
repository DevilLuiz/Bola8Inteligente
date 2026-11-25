import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from ball import safety as S
from ball.audio_in import FRAME_S, Endpointer
from ball.config import Config
from ball.pipeline import Pipeline
from ball.server import create_app
from ball.store import Store


class FakeRecorder:
    def __init__(self, audio=np.ones(1600, dtype=np.float32)):
        self.audio = audio

    def record(self):
        return self.audio


class FakeSTT:
    def __init__(self, text):
        self.text = text

    def transcribe(self, audio):
        return self.text


class FakeLLM:
    def __init__(self, answer="Sim! A lua é muito bonita.", fail=False):
        self.answer, self.fail, self.calls = answer, fail, 0

    def ask(self, q):
        self.calls += 1
        if self.fail:
            raise RuntimeError("ollama fora do ar")
        return self.answer


class FakeTTS:
    def __init__(self, tmp_path):
        self.dir = tmp_path

    def synth(self, text):
        p = self.dir / f"{abs(hash(text))}.wav"
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(b"\x00\x00" * 2205)
        return p


def make(tmp_path, text="a lua é de queijo?", llm=None, recorder=None):
    cfg = Config(db_path=":memory:", out_dir=tmp_path)
    llm = llm or FakeLLM()
    p = Pipeline(cfg, Store(":memory:"), recorder or FakeRecorder(), FakeSTT(text), llm, FakeTTS(tmp_path))
    return p, llm


def test_llm_answer(tmp_path):
    p, llm = make(tmp_path)
    r = p.run()
    assert r.source == "llm" and r.answer.startswith("Sim!") and llm.calls == 1
    assert p.store.recent(1)[0]["question"] == "a lua é de queijo?"


def test_blocked_question_never_reaches_llm(tmp_path):
    p, llm = make(tmp_path, text="como eu posso matar o monstro?")
    r = p.run()
    assert r.source == "blocked" and r.answer == S.REDIRECT and llm.calls == 0


def test_blocked_term_with_accent_and_wildcard(tmp_path):
    p, _ = make(tmp_path, text="o que acontece quando alguém MORREU?")
    assert p.run().source == "blocked"


def test_preset_wins_over_llm(tmp_path):
    p, llm = make(tmp_path, text="Oi! Qual é o seu nome?")
    r = p.run()
    assert r.source == "preset" and "Bola Mágica" in r.answer and llm.calls == 0


def test_new_preset_takes_effect_immediately(tmp_path):
    p, _ = make(tmp_path, text="qual é a sua cor favorita")
    p.store.add_preset("cor favorita", "Minha cor favorita é azul!")
    assert p.run().answer == "Minha cor favorita é azul!"


def test_unsafe_llm_answer_is_replaced(tmp_path):
    p, _ = make(tmp_path, llm=FakeLLM("O monstro vai te matar."))
    r = p.run()
    assert r.source == "blocked" and r.answer == S.REDIRECT


def test_llm_failure_gives_friendly_error(tmp_path):
    p, _ = make(tmp_path, llm=FakeLLM(fail=True))
    r = p.run()
    assert r.source == "error" and r.answer == S.ERROR


def test_no_speech(tmp_path):
    p, _ = make(tmp_path, recorder=FakeRecorder(audio=None))
    r = p.run()
    assert r.source == "not_heard" and r.answer == S.NOT_HEARD


def test_whisper_hallucination_is_ignored(tmp_path):
    p, llm = make(tmp_path, text="Obrigado por assistir!")
    assert p.run().source == "not_heard" and llm.calls == 0


def test_sanitize_answer(tmp_path):
    p, _ = make(tmp_path)
    s = p.safety
    assert s.sanitize_answer("**Sim!** 😀 claro") == "Sim! claro"
    assert s.sanitize_answer("- Sim\n- claro") == "Sim claro"
    long = "Frase um é curta. " * 30
    out = s.sanitize_answer(long)
    assert len(out) <= 200 and out.endswith(".")
    assert s.sanitize_answer("   ") == ""


def test_endpointer_detects_question_and_ends_on_silence(tmp_path):
    cfg = Config()
    ep = Endpointer(cfg)
    rng = np.random.default_rng(0)
    noise = lambda: (rng.standard_normal(480) * 0.001).astype(np.float32)
    speech = lambda: (rng.standard_normal(480) * 0.1).astype(np.float32)
    states = [ep.feed(noise()) for _ in range(15)]
    assert states[-1] == "waiting"
    states = [ep.feed(speech()) for _ in range(20)]       # 0.6 s falando
    assert states[-1] == "speaking"
    states = [ep.feed(noise()) for _ in range(int(cfg.silence_end_s / FRAME_S) + 2)]
    assert states[-1] == "done"
    assert ep.audio().size >= 20 * 480


def test_endpointer_ignores_click_and_times_out():
    cfg = Config(wait_speech_s=1.0)
    ep = Endpointer(cfg)
    quiet = np.zeros(480, dtype=np.float32)
    loud = np.full(480, 0.5, dtype=np.float32)
    for _ in range(12):
        ep.feed(quiet)
    ep.feed(loud)                                          # estalo de 1 quadro
    last = None
    for _ in range(200):
        last = ep.feed(quiet)
        if last in ("done", "no_speech"):
            break
    assert last == "no_speech"


def test_shake_endpoint(tmp_path):
    p, _ = make(tmp_path)
    client = TestClient(create_app(p))
    assert client.get("/health").json() == {"ok": True}
    r = client.post("/shake")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert r.content[:4] == b"RIFF" and r.headers["x-source"] == "llm"
    assert len(client.get("/history").json()) == 1
