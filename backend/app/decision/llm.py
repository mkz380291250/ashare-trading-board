import json
import re
import subprocess
from abc import ABC, abstractmethod

_JSON_RE = re.compile(r"\{[^{}]*\}")


def parse_verdict(text: str) -> dict:
    """Return the LAST JSON object found in text (fenced or bare), else {}."""
    matches = _JSON_RE.findall(text or "")
    for chunk in reversed(matches):
        try:
            obj = json.loads(chunk)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return {}


class LLMClient(ABC):
    @abstractmethod
    def complete(self, prompt: str, system: str | None = None) -> str:
        ...


class LocalClaudeClient(LLMClient):
    """Headless local Claude via `claude -p`."""

    def __init__(self, bin_path: str = "/usr/local/bin/claude",
                 timeout: int = 300, run=subprocess.run):
        self.bin = bin_path
        self.timeout = timeout
        self._run = run

    def complete(self, prompt: str, system: str | None = None) -> str:
        full = prompt if not system else f"{system}\n\n{prompt}"
        r = self._run([self.bin, "-p", full, "--output-format", "text"],
                      capture_output=True, text=True, timeout=self.timeout)
        return (r.stdout or "").strip()


class DeepSeekClient(LLMClient):
    def __init__(self, api_key: str, base_url: str, model: str, post=None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        if post is None:
            import requests
            post = requests.post
        self._post = post

    def complete(self, prompt: str, system: str | None = None) -> str:
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        r = self._post(f"{self.base_url}/chat/completions",
                       headers={"Authorization": f"Bearer {self.api_key}"},
                       json={"model": self.model, "messages": msgs}, timeout=120)
        return r.json()["choices"][0]["message"]["content"].strip()
