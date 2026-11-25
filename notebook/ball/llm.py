import requests

from .config import Config

SYSTEM_PROMPT = (
    "Você é a Bola Mágica, uma bola de brinquedo mágica, carinhosa e divertida que "
    "conversa com crianças de 5 anos. Responda sempre em português do Brasil, em NO "
    "MÁXIMO 2 frases curtas, usando só palavras muito simples. "
    "Se a pergunta for de sim ou não, responda com sim, não ou talvez, de um jeito "
    "mágico, e explique de forma simples. "
    "Nunca fale de violência, medo, morte, sangue, armas, sexo, drogas ou palavrões. "
    "Se a pergunta não for apropriada para criança, ou se você não souber, diga para "
    "perguntar a um adulto de confiança. "
    "Não use emojis, listas, símbolos nem formatação."
)


class OllamaLLM:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def ask(self, question: str) -> str:
        r = requests.post(
            f"{self.cfg.ollama_url}/api/chat",
            json={
                "model": self.cfg.llm_model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": question},
                ],
                "options": {"temperature": 0.7, "num_predict": 90},
            },
            timeout=self.cfg.llm_timeout_s,
        )
        r.raise_for_status()
        return r.json()["message"]["content"]
