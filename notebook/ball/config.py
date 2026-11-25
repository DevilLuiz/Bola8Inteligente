"""Configuração central. Tudo pode ser sobrescrito por variável de ambiente BALL_*."""
import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(f"BALL_{name}", default)


@dataclass
class Config:
    # --- Dados ---
    db_path: Path = field(default_factory=lambda: Path(_env("DB_PATH", "data/ball.db")))
    out_dir: Path = field(default_factory=lambda: Path(_env("OUT_DIR", "data/audio")))

    # --- Gravação (microfone do notebook) ---
    sample_rate: int = int(_env("SAMPLE_RATE", "16000"))
    mic_device: str | None = os.environ.get("BALL_MIC_DEVICE")  # índice ou nome; None = padrão
    wait_speech_s: float = float(_env("WAIT_SPEECH_S", "6"))    # espera a criança começar a falar
    silence_end_s: float = float(_env("SILENCE_END_S", "1.0"))  # silêncio que encerra a pergunta
    max_record_s: float = float(_env("MAX_RECORD_S", "8"))
    speech_margin: float = float(_env("SPEECH_MARGIN", "3.0"))  # limiar = ruído de fundo * margem
    min_rms: float = float(_env("MIN_RMS", "0.01"))             # piso do limiar (0..1)

    # --- STT (faster-whisper) ---
    whisper_model: str = _env("WHISPER_MODEL", "small")
    whisper_device: str = _env("WHISPER_DEVICE", "auto")
    whisper_compute: str = _env("WHISPER_COMPUTE", "int8")
    language: str = _env("LANGUAGE", "pt")

    # --- LLM (Ollama) ---
    ollama_url: str = _env("OLLAMA_URL", "http://localhost:11434")
    llm_model: str = _env("LLM_MODEL", "llama3.2:3b")
    llm_timeout_s: float = float(_env("LLM_TIMEOUT_S", "30"))
    max_answer_chars: int = int(_env("MAX_ANSWER_CHARS", "200"))

    # --- TTS (Piper) ---
    piper_model: str = _env("PIPER_MODEL", "models/pt_BR-faber-medium.onnx")

    # --- Servidor (a ESP32 chama aqui) ---
    host: str = _env("HOST", "0.0.0.0")
    port: int = int(_env("PORT", "8000"))
