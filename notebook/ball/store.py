"""SQLite: histórico, respostas pré-programadas e termos bloqueados.

O app de configuração (fase futura) só precisa ler/escrever estas tabelas;
a pipeline relê o banco a cada pergunta, então mudanças valem na hora.
"""
import sqlite3
import threading
import time
from pathlib import Path

from .textutil import normalize

SCHEMA = """
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    source TEXT NOT NULL,          -- preset | llm | blocked | not_heard | error
    latency_s REAL
);
CREATE TABLE IF NOT EXISTS presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,         -- frase normalizada; casa se estiver contida na pergunta
    answer TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS blocked_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL UNIQUE      -- normalizado; sufixo * = qualquer terminação
);
"""

DEFAULT_BLOCKED = [
    "morr*", "mort*", "matar", "matei", "assassin*", "sangue", "sangr*",
    "arma", "armas", "revolver", "faca", "suicid*", "sexo", "sexual", "pelad*",
    "drog*", "maconha", "cocaina", "porra", "merda", "caralho", "puta",
    "buceta", "foder", "foda*",
]

DEFAULT_PRESETS = [
    ("qual e o seu nome", "Eu sou a Bola Mágica! E você, como se chama?"),
    ("quem e voce", "Eu sou a Bola Mágica! Eu respondo as suas perguntas."),
]


class Store:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            if self._db.execute("SELECT COUNT(*) FROM blocked_terms").fetchone()[0] == 0:
                self._db.executemany(
                    "INSERT OR IGNORE INTO blocked_terms(term) VALUES (?)",
                    [(t,) for t in DEFAULT_BLOCKED],
                )
            if self._db.execute("SELECT COUNT(*) FROM presets").fetchone()[0] == 0:
                self._db.executemany(
                    "INSERT INTO presets(pattern, answer) VALUES (?, ?)", DEFAULT_PRESETS
                )
            self._db.commit()

    # --- leitura ---
    def blocked_terms(self) -> list[str]:
        with self._lock:
            return [r["term"] for r in self._db.execute("SELECT term FROM blocked_terms")]

    def presets(self) -> list[tuple[str, str]]:
        with self._lock:
            rows = self._db.execute("SELECT pattern, answer FROM presets WHERE enabled = 1")
            return [(r["pattern"], r["answer"]) for r in rows]

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM interactions ORDER BY id DESC LIMIT ?", (limit,)
            )
            return [dict(r) for r in rows]

    # --- escrita ---
    def add_blocked(self, term: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO blocked_terms(term) VALUES (?)", (normalize(term),)
            )
            self._db.commit()

    def add_preset(self, pattern: str, answer: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO presets(pattern, answer) VALUES (?, ?)",
                (normalize(pattern), answer),
            )
            self._db.commit()

    def log(self, question: str, answer: str, source: str, latency_s: float | None = None) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO interactions(ts, question, answer, source, latency_s) "
                "VALUES (?, ?, ?, ?, ?)",
                (time.time(), question, answer, source, latency_s),
            )
            self._db.commit()
