import pytest

from conftest import OWNER, helm, core  # noqa: F401
from helm import cost


@pytest.fixture
def run(ctx, monkeypatch):
    monkeypatch.setattr(cost, "_toolset_costs", lambda: {"web": 900, "mcp-github": 3200, "terminal": 1500})
    monkeypatch.setattr(cost, "_skill_costs", lambda: {"pdf": 40, "big-skill": 2000})
    helm.register(ctx)
    return lambda arg="": ctx.commands["helm"](f"cost {arg}".strip(), source=OWNER, platform="discord")


def names(out):
    return [line.split()[1] for line in out.split("```")[1].strip().splitlines()[1:]]


def test_ranks_by_tokens(run):
    out = run()
    assert names(out) == ["github", "big-skill", "terminal", "web", "pdf"]
    assert "mcp      github     ~3.2k   on" in out
    assert "Total on: ~7.6k" in out and "/helm cost off" in out


def test_filter(run):
    assert names(run("skill")) == ["big-skill", "pdf"]
    assert names(run("mcp")) == ["github"]
    assert "Usage" in run("nope")


def test_state_column(ctx, run):
    ctx.config.update({"mcp_servers": {"github": {"enabled": False}}, "skills": {"disabled": ["pdf"]},
                       "agent": {"disabled_toolsets": "web"}})
    rows = {line.split()[1]: line.split()[-1] for line in run().split("```")[1].strip().splitlines()[1:]}
    assert rows == {"github": "off", "big-skill": "on", "terminal": "on", "web": "off", "pdf": "off"}
    assert "Total on: ~3.5k" in run()


def test_off_calls_toggle(ctx, run, monkeypatch):
    calls, seen = [], []
    monkeypatch.setattr(helm.toggle, "apply", lambda kind, name, on: calls.append((kind, name, on)) or "done", raising=False)
    monkeypatch.setattr(ctx, "ask_choice", lambda q, choices: seen.extend(choices) or "mcp:github")
    ctx.config["skills"] = {"disabled": ["pdf"]}
    assert run("off") == "done"
    assert calls == [("mcp", "github", False)]
    assert seen[0] == {"value": "mcp:github", "label": "github (mcp) ~3.2k"}
    assert "skill:pdf" not in [c["value"] for c in seen]


def test_off_no_choice(ctx, run, monkeypatch):
    monkeypatch.setattr(helm.toggle, "apply", lambda *a: pytest.fail("should not toggle"), raising=False)
    ctx.choice = None
    assert run("off") == "No choice made."
