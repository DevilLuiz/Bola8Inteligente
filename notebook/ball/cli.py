"""Testes locais sem a ESP32.

  python -m ball.cli devices          lista microfones
  python -m ball.cli listen           simula uma chacoalhada (grava, responde, toca)
  python -m ball.cli text "pergunta"  pula microfone e STT
"""
import argparse
import logging
import wave

import numpy as np

from .config import Config
from .server import build_pipeline


def play(path) -> None:
    import sounddevice as sd

    with wave.open(str(path), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        sd.play(data, w.getframerate())
        sd.wait()


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices")
    sub.add_parser("listen")
    t = sub.add_parser("text")
    t.add_argument("question")
    ap.add_argument("--no-play", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.cmd == "devices":
        import sounddevice as sd

        print(sd.query_devices())
        return

    pipeline = build_pipeline(Config())
    result = pipeline.run() if args.cmd == "listen" else pipeline.respond_to_text(args.question)
    print(f"\nPergunta: {result.question}\nResposta: {result.answer}  ({result.source}, {result.latency_s:.1f}s)")
    if not args.no_play:
        play(result.wav_path)


if __name__ == "__main__":
    main()
