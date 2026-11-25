"""Filtros de entrada/saída e respostas pré-programadas."""
import re

from .store import Store
from .textutil import normalize

REDIRECT = "Essa pergunta é para um adulto. Pergunta para a mamãe ou para o papai!"
NOT_HEARD = "Não ouvi direito. Chacoalha de novo e pergunta mais alto!"
ERROR = "Ops, minha mágica falhou. Chacoalha e tenta de novo!"

# Whisper "alucina" estas frases quando só há ruído/silêncio.
_HALLUCINATIONS = {
    "obrigado", "obrigada", "obrigado por assistir", "tchau", "legendas pela comunidade amara org",
}

_EMOJI = re.compile("[\U00010000-\U0010ffff\u2600-\u27bf\ufe0f]")
_MD = re.compile(r"[*_#`>~|]")
_LIST_MARK = re.compile(r"^\s*(?:[-•]|\d+[.)])\s+", re.MULTILINE)


class Safety:
    def __init__(self, store: Store, max_chars: int = 200):
        self.store = store
        self.max_chars = max_chars

    def _blocked_regex(self) -> re.Pattern | None:
        parts = []
        for t in self.store.blocked_terms():
            t = normalize(t.rstrip("*")) + ("*" if t.endswith("*") else "")
            if not t:
                continue
            if t.endswith("*"):
                parts.append(rf"\b{re.escape(t[:-1])}\w*")
            else:
                parts.append(rf"\b{re.escape(t)}\b")
        return re.compile("|".join(parts)) if parts else None

    def is_blocked(self, text: str) -> bool:
        rx = self._blocked_regex()
        return bool(rx and rx.search(normalize(text)))

    def is_hallucination(self, text: str) -> bool:
        n = normalize(text)
        return not n or n in _HALLUCINATIONS

    def find_preset(self, question: str) -> str | None:
        q = normalize(question)
        for pattern, answer in self.store.presets():
            p = normalize(pattern)
            if p and p in q:
                return answer
        return None

    def sanitize_answer(self, answer: str) -> str:
        """Limpa formatação, limita tamanho e bloqueia se tiver termo proibido.
        Retorna '' se a resposta não puder ser usada."""
        a = _EMOJI.sub("", answer)
        a = _LIST_MARK.sub("", a)
        a = _MD.sub("", a)
        a = re.sub(r"\s+", " ", a).strip()
        if not a:
            return ""
        if len(a) > self.max_chars:
            cut = a[: self.max_chars]
            end = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
            if end >= 20:
                a = cut[: end + 1]
            else:
                a = cut[: cut.rfind(" ")].rstrip(",;:") + "."
        if self.is_blocked(a):
            return ""
        return a
