from conftest import OWNER, helm, core


def boot(ctx):
    helm.register(ctx)
    return ctx.commands["helm"]


def test_registers_one_command(ctx):
    boot(ctx)
    assert set(ctx.commands) == {"helm"}


def test_owner_gate_fails_closed(ctx):
    run = boot(ctx)
    assert "Only the owner" in run("", source={"user_id": "7"}, platform="discord")
    assert "Only the owner" in run("", source=None, platform="discord")
    ctx.settings["owner_ids"] = []
    assert "Only the owner" in run("", source=OWNER, platform="discord")


def test_local_cli_is_owner(ctx):
    assert boot(ctx)("", source=None, platform="cli") == helm.USAGE  # owner; nothing to tap, so text


def test_menu_opens_the_tapped_view(ctx, monkeypatch):
    from helm import toggle
    monkeypatch.setattr(toggle, "total", lambda kind: {"mcp": 4100, "skills": 810}.get(kind, 0))
    run = boot(ctx)
    ctx.choice = ["budget", None]
    assert run("", source=OWNER, platform="discord").endswith("today")
    assert [c["label"] for c in ctx.asked[0][1]] == ["MCP  4.1k", "Skills  810", "Toolsets", "Lost turns", "Budget",
                                                     "Cancel"]
    assert ctx.asked[1][0].startswith("$0.00 today")


def test_menu_hides_off_modules_and_unknown_view_shows_usage(ctx):
    run = boot(ctx)
    ctx.settings["modules"] = {"toggle": False}
    run("", source=OWNER, platform="discord")
    assert [c["value"] for c in ctx.asked[0][1]] == ["lost", "budget", "*cancel"]
    ctx.choice = "*cancel"
    assert run("", source=OWNER, platform="discord") is None
    assert run("nope", source=OWNER, platform="discord") == helm.USAGE


def test_arg_hints_fit_discord_option_description(ctx):
    boot(ctx)  # Discord shows "Arguments: <hint>" in a 100-char field
    assert all(len("Arguments: " + h) <= 100 for h in ctx.hints.values())


def test_module_switch_writes_setting(ctx):
    run = boot(ctx)
    assert run("modules budget off", source=OWNER, platform="discord") == "budget off."
    assert ctx.config["plugins"]["entries"]["hermes-helm"]["settings"]["modules"]["budget"] is False
    assert core.execute("SELECT key FROM audit")[0][0].endswith("modules.budget")
    assert run("modules nope off", source=OWNER, platform="discord").startswith("/helm modules")


def test_off_module_refuses_and_hooks_go_quiet(ctx):
    calls = []
    core.hook(ctx, "budget", "pre_llm_call", lambda **kw: calls.append(1) or "x")
    ctx.settings["modules"] = {"budget": False}
    assert ctx.fire("pre_llm_call") == [None] and not calls
    assert "is off" in boot(ctx)("budget", source=OWNER, platform="discord")


def test_hook_errors_are_swallowed(ctx):
    core.hook(ctx, "cost", "post_api_request", lambda **kw: 1 / 0)
    assert ctx.fire("post_api_request") == [None]


def test_table_aligns():
    assert core.table([["a", 1], ["bbb", 22]], ["name", "n"]) == "```\nname  n\na     1\nbbb   22\n```"
