"""Servidor da Bola 8 Mágica (roda no notebook).

Endpoints:
  GET /perguntar         -> a ESP chama após a chacoalhada. O notebook escuta a
                            pergunta, gera a resposta, sintetiza e devolve o WAV.
                            A conexão fica aberta durante todo o processo.
  GET /fala.wav          -> arquivo de teste (fala16.wav)
  GET /tts?texto=Ola     -> só o Piper, para teste

Rodar:
  BALL_WHISPER_DEVICE=cpu BALL_WHISPER_COMPUTE=int8 \
  uvicorn servidor:app --host 0.0.0.0 --port 8000
"""

import logging
import subprocess
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

log = logging.getLogger("bola")
_pipeline = None  # pipeline do pacote ball, carregado uma vez na subida


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Carrega o Whisper etc. na subida, para a 1ª chacoalhada não demorar.
    global _pipeline
    try:
        from ball.config import Config
        from ball.server import build_pipeline

        _pipeline = build_pipeline(Config())
        log.warning("Pipeline ball carregado.")
    except Exception:
        log.exception("Não consegui carregar o pipeline ball; /perguntar vai falhar")
    yield


app = FastAPI(lifespan=lifespan)

PASTA = Path(__file__).parent
ARQUIVO_TESTE = PASTA / "fala16.wav"
PIPER_MODELO = PASTA / "models" / "pt_BR-faber-medium.onnx"
MAX_TEXTO = 300

# Só uma pergunta por vez (um microfone, uma bola).
_trava = threading.Lock()


def resposta_wav(dados: bytes) -> Response:
    # Response com bytes já define Content-Length, que a ESP32 exige.
    return Response(content=dados, media_type="audio/wav")


def sintetizar(texto: str) -> bytes:
    texto = texto.strip()[:MAX_TEXTO]
    if not texto:
        raise HTTPException(400, "texto vazio")
    if not PIPER_MODELO.exists():
        raise HTTPException(501, "modelo do Piper não encontrado")
    with tempfile.TemporaryDirectory() as tmp:
        saida = Path(tmp) / "saida.wav"
        try:
            subprocess.run(
                ["piper", "--model", str(PIPER_MODELO), "--output_file", str(saida)],
                input=texto.encode("utf-8"),
                check=True,
                capture_output=True,
                timeout=30,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            raise HTTPException(500, f"Piper falhou: {e}")
        return saida.read_bytes()


def executar_pipeline() -> bytes:
    """Escuta -> transcreve -> responde -> devolve o WAV da resposta.

    Faz o mesmo que `python -m ball.cli listen`, mas devolve o WAV em vez de
    tocar no notebook.
    """
    if _pipeline is None:
        raise HTTPException(503, "pipeline ball não carregou; veja o log do servidor")
    try:
        r = _pipeline.run()
    except Exception as e:
        log.exception("pipeline falhou")
        raise HTTPException(500, f"pipeline falhou: {e}")
    print(f"\nPergunta: {r.question}\nResposta: {r.answer}  ({r.source}, {r.latency_s:.1f}s)", flush=True)
    return Path(r.wav_path).read_bytes()


@app.get("/perguntar")
def perguntar():
    if not _trava.acquire(blocking=False):
        raise HTTPException(429, "já estou ouvindo outra pergunta")
    try:
        return resposta_wav(executar_pipeline())
    finally:
        _trava.release()


@app.get("/fala.wav")
def fala():
    if not ARQUIVO_TESTE.exists():
        raise HTTPException(404, f"Coloque {ARQUIVO_TESTE.name} ao lado deste arquivo")
    return resposta_wav(ARQUIVO_TESTE.read_bytes())


@app.get("/tts")
def tts(texto: str):
    return resposta_wav(sintetizar(texto))
