import pytest
from app.decision.llm import LocalClaudeClient, DeepSeekClient, UsageLimitError


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


def test_local_claude_defaults_to_sonnet_5():
    calls = {}

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        return _Proc("HELLO\n")

    c = LocalClaudeClient(bin_path="/x/claude", run=fake_run)
    c.complete("hi")
    assert "--model" in calls["cmd"]
    assert calls["cmd"][calls["cmd"].index("--model") + 1] == "claude-sonnet-5"


def test_local_claude_model_overridable():
    calls = {}

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        return _Proc("HELLO\n")

    c = LocalClaudeClient(bin_path="/x/claude", model="claude-haiku-4-5-20251001", run=fake_run)
    c.complete("hi")
    assert calls["cmd"][calls["cmd"].index("--model") + 1] == "claude-haiku-4-5-20251001"


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


def test_local_claude_retries_when_binary_missing():
    # claude CLI 自动更新的几秒窗口内二进制不存在(2026-07-03 事故):应重试而非立崩
    calls = {"n": 0}
    naps = []

    def flaky_run(cmd, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise FileNotFoundError(cmd[0])
        return _Proc("OK\n")

    c = LocalClaudeClient(bin_path="/x/claude", run=flaky_run, sleep=naps.append)
    assert c.complete("hi") == "OK"
    assert calls["n"] == 3
    assert len(naps) == 2                      # 两次失败各睡一次


def test_local_claude_gives_up_after_max_retries():
    def always_missing(cmd, **kw):
        raise FileNotFoundError(cmd[0])

    c = LocalClaudeClient(bin_path="/x/claude", run=always_missing, sleep=lambda s: None)
    with pytest.raises(FileNotFoundError):
        c.complete("hi")


def test_local_claude_raises_on_usage_limit_message():
    # 2026-07-06 事故:账号限额时 claude -p 只回这句提示,曾被当成正常发言
    # 写进决策(8只全 HOLD/置信度0),必须识别为错误
    def limited_run(cmd, **kw):
        return _Proc("You've hit your session limit · resets 4:50pm (UTC)\n")

    c = LocalClaudeClient(bin_path="/x/claude", run=limited_run)
    with pytest.raises(UsageLimitError):
        c.complete("hi")


def test_local_claude_raises_on_weekly_usage_limit_variant():
    def limited_run(cmd, **kw):
        return _Proc("You've hit your usage limit · resets Oct 4\n")

    c = LocalClaudeClient(bin_path="/x/claude", run=limited_run)
    with pytest.raises(UsageLimitError):
        c.complete("hi")


def test_local_claude_long_analysis_mentioning_limit_is_not_error():
    # 分析师正文里偶然提到 limit 字样不该误杀:限额提示必然是短输出
    text = "深入分析:" + "该股基本面稳健。" * 100 + " hit your session limit 只是引用。"
    c = LocalClaudeClient(bin_path="/x/claude", run=lambda cmd, **kw: _Proc(text))
    assert c.complete("hi") == text.strip()
