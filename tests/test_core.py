from conftest import OWNER, helm, core


def boot(ctx):
    helm.register(ctx)
    return ctx.commands["helm"]


def test_registers_root_and_aliases(ctx):
    boot(ctx)
    assert set(ctx.commands) == {"helm", "pending", "budget"}


def test_owner_gate_fails_closed(ctx):
    run = boot(ctx)
    assert "Only the bot owner" in run("", source={"user_id": "7"}, platform="discord")
    assert "Only the bot owner" in run("", source=None, platform="discord")
    ctx.settings["owner_ids"] = []
    assert "Only the bot owner" in run("", source=OWNER, platform="discord")


def test_local_cli_is_owner(ctx):
    assert "hermes-helm" in boot(ctx)("", source=None, platform="cli")


def test_help_lists_modules(ctx):
    out = boot(ctx)("", source=OWNER, platform="discord")
    for mid in helm.MODULES:
        assert f"`{mid}` (on)" in out


def test_module_switch_writes_setting(ctx):
    run = boot(ctx)
    assert "now off" in run("modules budget off", source=OWNER, platform="discord")
    assert ctx.config["plugins"]["entries"]["hermes-helm"]["settings"]["modules"]["budget"] is False
    assert core.execute("SELECT key FROM audit")[0][0].endswith("modules.budget")
    assert "Usage" in run("modules nope off", source=OWNER, platform="discord")


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
