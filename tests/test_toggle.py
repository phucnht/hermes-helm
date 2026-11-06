import pytest

from conftest import OWNER, helm, core
from helm import toggle

SKILLS = {"hermes-agent": (50, "core"), "pdf": (40, "docs"), "ocr": (35, "docs"), "web": (30, "research")}


@pytest.fixture
def run(ctx, monkeypatch):
    monkeypatch.setattr(toggle, "_skills", lambda: SKILLS)
    monkeypatch.setattr(toggle, "_toolset_tokens", lambda: {"browser": 900, "terminal": 1500, "mcp-github": 4100})
    ctx.config.update({"mcp_servers": {"github": {"command": "gh"}, "jira": {"enabled": "off"}},
                       "skills": {"disabled": ["web"]}})
    helm.register(ctx)
    return lambda args: ctx.commands["helm"](args, source=OWNER, platform="discord")


def labels(ctx, n=0):
    return [c.get("label") for c in ctx.asked[n][1] if "label" in c]


def test_list_stays_open_until_done(run, ctx):
    ctx.choice = ["github", "jira", "*done"]
    assert run("mcp") == "Off: `github`. On: `jira`. Applies within a minute."
    assert ctx.asked[0][0] == "MCP: 1 of 2 on, 4.1k tokens"
    assert labels(ctx) == ["● github  4.1k", "○ jira", "All on", "All off", "Done"]
    assert ctx.asked[1][0].startswith("Off: `github`. Applies within a minute.\nMCP: 0 of 2 on")
    assert labels(ctx, 2) == ["○ github  4.1k", "● jira", "All on", "All off", "Done"]
    assert labels(ctx, 1) == ["○ github  4.1k", "○ jira", "All on", "Done"]  # all off: only All on (fake keeps tokens)
    assert ctx.config["mcp_servers"] == {"github": {"command": "gh", "enabled": False}, "jira": {"enabled": True}}


def test_all_off_and_done_without_changes(run, ctx):
    ctx.choice = ["*off", "*done"]
    assert run("toolsets") == "Off: `terminal`, `browser`. Applies from your next message."
    assert ctx.config["agent"]["disabled_toolsets"] == ["browser", "terminal"]
    ctx.choice = ["*done"]
    assert run("toolsets") is None


def test_skills_open_by_category(run, ctx):
    ctx.choice = ["#docs", "*off", "*done"]
    assert run("skills") == "Off: `pdf`, `ocr`. Applies on /reload-skills or /new."
    assert labels(ctx) == ["docs  2/2  75", "research  0/1  0", "All on", "All off", "Done"]  # no core group
    assert ctx.asked[1][0] == "Skills · docs: 2 of 2 on, 75 tokens"
    assert ctx.config["skills"]["disabled"] == ["ocr", "pdf", "web"]


def test_skills_all_on_keeps_essential_out_of_the_list(run, ctx):
    ctx.choice = ["*on", "*done"]
    run("skills")
    assert "hermes-agent" not in str(ctx.asked[0][1])
    assert ctx.config["skills"]["disabled"] == []


def test_every_choice_is_a_button_within_the_cap(run, ctx, monkeypatch):
    monkeypatch.setattr(toggle, "_toolset_tokens", lambda: {f"t{i:02}": 100 - i for i in range(30)})
    ctx.choice = ["*done"]
    run("toolsets")
    assert len(ctx.asked[0][1]) == 24 and labels(ctx)[-1] == "Done"  # Hermes adds Other as the 25th
    assert run("toolsets t29 off") == "Off: `t29`. Applies from your next message."


def test_no_buttons_gives_a_table(run, ctx):
    out = run("toolsets")
    assert out.startswith("Toolsets: 2 of 2 on") and out.index("terminal") < out.index("browser")


def test_text_switch_many_and_all(run, ctx):
    assert run("skills pdf web off") == "Off: `pdf`, `web`. Applies on /reload-skills or /new."
    assert ctx.config["skills"]["disabled"] == ["pdf", "web"]
    run("skills all off")
    assert ctx.config["skills"]["disabled"] == ["ocr", "pdf", "web"]  # hermes-agent stays on
    assert "essential" in run("skills hermes-agent off")
    assert run("mcp jira on").startswith("On: `jira`")
    assert run("toolsets nope off") == "No Toolsets named `nope`."
    assert run("toolsets browser maybe") == "/helm toolsets <name ...|all> on|off"


def test_config_error_is_reported(run, ctx, monkeypatch):
    monkeypatch.setattr(core, "set_config", lambda path, value: "config.yaml is managed")
    assert toggle.switch("toolsets", ["browser"], False) == "config.yaml is managed"
    ctx.choice = ["browser"]
    assert run("toolsets") == "config.yaml is managed"


def test_mcp_name_with_dot(run, ctx):
    ctx.config["mcp_servers"] = {"my.server": {}}
    run("mcp my.server off")
    assert ctx.config["mcp_servers"]["my.server"]["enabled"] is False
