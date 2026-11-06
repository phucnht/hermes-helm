import pytest

from conftest import OWNER, helm, core
from helm import toggle


@pytest.fixture
def run(ctx, monkeypatch):
    monkeypatch.setattr(toggle, "_skills", lambda: ["hermes-agent", "pdf", "web"])
    monkeypatch.setattr(toggle, "_toolsets", lambda: ["browser", "terminal"])
    ctx.config.update({"mcp_servers": {"github": {"command": "gh"}, "jira": {"enabled": "off"}},
                       "skills": {"disabled": ["web"]}})
    helm.register(ctx)
    return lambda args: ctx.commands["helm"](args, source=OWNER, platform="discord")


def test_list_shows_state(run):
    rows = {tuple(line.split()) for line in run("toggle list").splitlines()}
    assert {("mcp", "github", "on"), ("mcp", "jira", "off"), ("skill", "web", "off"),
            ("skill", "pdf", "on"), ("toolset", "terminal", "on")} <= rows
    assert "github" not in run("toggle list skills") and "Usage" in run("toggle list nope")


def test_list_truncates(run, monkeypatch):
    monkeypatch.setattr(toggle, "_skills", lambda: [f"skill-{i:03}" for i in range(300)])
    out = run("toggle list skill")
    assert len(out) < 1900 and "more" in out.splitlines()[-1]


def test_mcp_on_off(run, ctx):
    assert "/reload-mcp" in run("toggle mcp github off")
    assert ctx.config["mcp_servers"]["github"] == {"command": "gh", "enabled": False}
    run("toggle mcp jira on")
    assert ctx.config["mcp_servers"]["jira"]["enabled"] is True
    assert "Known: github, jira" in run("toggle mcp nope off")


def test_skill_on_off(run, ctx):
    assert "/reload-skills" in run("toggle skill pdf off")
    assert ctx.config["skills"]["disabled"] == ["pdf", "web"]
    run("toggle skill web on")
    assert ctx.config["skills"]["disabled"] == ["pdf"]
    assert "Unknown skill" in run("toggle skill nope off")
    assert "essential" in run("toggle skill hermes-agent off")
    assert ctx.config["skills"]["disabled"] == ["pdf"]


def test_toolset_on_off(run, ctx):
    assert "next message" in run("toggle toolset browser off")
    assert ctx.config["agent"]["disabled_toolsets"] == ["browser"]
    run("toggle toolset browser on")
    assert ctx.config["agent"]["disabled_toolsets"] == []
    assert "Unknown toolset" in run("toggle toolset nope off")
    assert "Usage" in run("toggle toolset browser maybe")


def test_apply_reports_config_error(run, monkeypatch):
    monkeypatch.setattr(core, "set_config", lambda path, value: "config.yaml is managed")
    assert toggle.apply("toolset", "browser", False) == "config.yaml is managed"
    assert "Unknown kind" in toggle.apply("tool", "browser", False)
