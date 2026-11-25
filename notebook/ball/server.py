"""Servidor HTTP que a ESP32 chama.

POST /shake  -> a ESP avisa que foi chacoalhada. O notebook grava a pergunta no
                próprio microfone, processa e devolve o WAV da resposta no corpo
                (a ESP faz o stream para o MAX98357A). Pode levar alguns segundos.
GET  /health -> teste de conectividade.
GET  /history?limit=50 -> últimas perguntas/respostas (base para o app).
"""
import logging
import threading
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .config import Config
from .pipeline import Pipeline


def create_app(pipeline: Pipeline) -> FastAPI:
    app = FastAPI(title="Bola 8 Mágica")
    busy = threading.Lock()

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/shake")
    def shake():  # def (não async): roda em thread, não trava o servidor
        if not busy.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="ocupada")
        try:
            r = pipeline.run()
        finally:
            busy.release()
        return FileResponse(
            r.wav_path,
            media_type="audio/wav",
            headers={
                "X-Source": r.source,
                "X-Question": quote(r.question),
                "X-Answer": quote(r.answer),
            },
        )

    @app.get("/history")
    def history(limit: int = 50):
        return pipeline.store.recent(min(limit, 500))

    return app


def build_pipeline(cfg: Config) -> Pipeline:
    from .audio_in import Recorder
    from .llm import OllamaLLM
    from .store import Store
    from .stt import WhisperSTT
    from .tts import PiperTTS

    return Pipeline(cfg, Store(cfg.db_path), Recorder(cfg), WhisperSTT(cfg), OllamaLLM(cfg), PiperTTS(cfg))


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg = Config()
    pipeline = build_pipeline(cfg)
    logging.info("carregando modelos...")
    pipeline.warm_up()
    logging.info("pronto em http://%s:%d", cfg.host, cfg.port)
    uvicorn.run(create_app(pipeline), host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
