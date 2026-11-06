import pytest

from conftest import OWNER, helm, core
from helm import toggle


@pytest.fixture
def run(ctx, monkeypatch):
    monkeypatch.setattr(toggle, "_skill_tokens", lambda: {"hermes-agent": 50, "pdf": 40, "web": 30})
    monkeypatch.setattr(toggle, "_toolset_tokens", lambda: {"browser": 900, "terminal": 1500, "mcp-github": 4100})
    ctx.config.update({"mcp_servers": {"github": {"command": "gh"}, "jira": {"enabled": "off"}},
                       "skills": {"disabled": ["web"]}})
    helm.register(ctx)
    return lambda args: ctx.commands["helm"](args, source=OWNER, platform="discord")


def test_list_is_ranked_buttons_and_tap_switches(run, ctx):
    ctx.choice = "github"
    assert "`github` off" in run("mcp")
    question, choices = ctx.asked[0]
    assert question.startswith("MCP: 1 of 2 on, 4.1k tokens")
    assert [c["label"] for c in choices] == ["● github  4.1k", "○ jira"]
    assert ctx.config["mcp_servers"]["github"] == {"command": "gh", "enabled": False}


def test_list_without_buttons_is_a_table(run, ctx):
    out = run("toolsets")
    assert out.index("terminal") < out.index("browser") and "mcp-github" not in out


def test_essential_skill_has_no_button(run, ctx):
    run("skills")
    assert [c["value"] for c in ctx.asked[0][1]] == ["pdf", "web"]
    assert "essential" in run("skills hermes-agent off")


def test_more_than_24_keeps_the_rest_typeable(run, ctx, monkeypatch):
    monkeypatch.setattr(toggle, "_skill_tokens", lambda: {f"s{i:02}": 100 - i for i in range(30)})
    ctx.choice = "s29"
    assert "`s29` off" in run("skills")
    question, choices = ctx.asked[0]
    assert "24 largest" in question and len(choices) == 30 and "label" not in choices[-1]


def test_text_switch(run, ctx):
    assert "within a minute" in run("mcp jira on")
    assert ctx.config["mcp_servers"]["jira"]["enabled"] is True
    assert "/reload-skills" in run("skills pdf off")
    assert ctx.config["skills"]["disabled"] == ["pdf", "web"]
    run("toolsets browser off")
    assert ctx.config["agent"]["disabled_toolsets"] == ["browser"]
    assert "No Toolsets named" in run("toolsets nope off")
    assert run("toolsets browser maybe") == "/helm toolsets <name> on|off"


def test_config_error_is_reported(run, monkeypatch):
    monkeypatch.setattr(core, "set_config", lambda path, value: "config.yaml is managed")
    assert toggle.switch("toolsets", "browser", False) == "config.yaml is managed"


def test_mcp_name_with_dot(run, ctx):
    ctx.config["mcp_servers"] = {"my.server": {}}
    run("mcp my.server off")
    assert ctx.config["mcp_servers"]["my.server"]["enabled"] is False
