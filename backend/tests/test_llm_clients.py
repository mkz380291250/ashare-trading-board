from app.decision.llm import LocalClaudeClient, DeepSeekClient


class _Proc:
    def __init__(self, out): self.stdout = out; self.returncode = 0


def test_local_claude_invokes_binary_and_returns_stdout():
    calls = {}

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        return _Proc("HELLO\n")

    c = LocalClaudeClient(bin_path="/x/claude", run=fake_run)
    out = c.complete("hi", system="be brief")
    assert out == "HELLO"
    assert calls["cmd"][0] == "/x/claude" and "-p" in calls["cmd"]
    assert "be brief" in calls["cmd"][calls["cmd"].index("-p") + 1]


class _Resp:
    def __init__(self, content): self._c = content
    def json(self): return {"choices": [{"message": {"content": self._c}}]}


def test_deepseek_posts_and_parses():
    seen = {}

    def fake_post(url, **kw):
        seen["url"] = url; seen["json"] = kw["json"]
        return _Resp("WORLD")

    c = DeepSeekClient(api_key="k", base_url="https://api.x.com", model="m", post=fake_post)
    assert c.complete("q", system="s") == "WORLD"
    assert seen["url"].endswith("/chat/completions")
    assert seen["json"]["messages"][0]["role"] == "system"
