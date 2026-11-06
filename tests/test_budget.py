import pytest

from conftest import OWNER, helm, core
from helm import budget

USAGE = {"input_tokens": 1000, "output_tokens": 500, "prompt_tokens": 1000}


@pytest.fixture
def run(ctx, monkeypatch):
    monkeypatch.setattr(budget, "_price", lambda model, usage, provider=None, prices=None: 1.0)
    helm.register(ctx)
    return lambda args="": ctx.commands["budget"](args, source=OWNER, platform="discord")


def blocks(ctx, hook):
    return [r for r in ctx.fire(hook) if r and r.get("action") == "block"]


def test_usage_recorded_from_both_hooks(ctx, run):
    ctx.fire("post_api_request", model="m1", provider="p", usage=USAGE, session_id="s")
    ctx.fire("post_auxiliary_call", model="m2", usage=USAGE, aux_task="title_generation")
    ctx.fire("post_auxiliary_call", model="m2", usage=None, error="boom")
    rows = core.execute("SELECT model, input, output, usd FROM usage ORDER BY model")
    assert rows == [("m1", 1000, 500, 1.0), ("m2", 1000, 500, 1.0)]


def test_block_when_over_limit(ctx, run):
    ctx.settings["budget"] = {"daily_usd": 2}
    ctx.fire("post_api_request", model="m", usage=USAGE)
    assert not blocks(ctx, "pre_llm_call") and not blocks(ctx, "pre_tool_call")
    ctx.fire("post_api_request", model="m", usage=USAGE)
    for hook in ("pre_llm_call", "pre_tool_call"):
        (b,) = blocks(ctx, hook)
        assert "Daily budget $2.00 reached ($2.00 spent)" in b["message"] and "/budget off" in b["message"]


def test_no_block_without_limit(ctx, run):
    for _ in range(5):
        ctx.fire("post_api_request", model="m", usage=USAGE)
    ctx.settings["budget"] = {"daily_usd": 0}
    assert not blocks(ctx, "pre_llm_call") and not blocks(ctx, "pre_tool_call")


def test_warns_once_at_threshold(ctx, run):
    ctx.settings["budget"] = {"daily_usd": 10, "warn_pct": 20}
    ctx.fire("post_api_request", model="m", usage=USAGE)
    assert ctx.posted == []
    for _ in range(3):
        ctx.fire("post_api_request", model="m", usage=USAGE)
    assert len(ctx.posted) == 1 and ctx.posted[0].startswith("⚠️") and "$2.00 of $10.00" in ctx.posted[0]


def test_set_and_off_write_config(ctx, run):
    settings = lambda: ctx.config["plugins"]["entries"]["hermes-helm"]["settings"]["budget"]["daily_usd"]
    assert "$5.50" in run("set 5.5") and settings() == 5.5
    assert "off" in run("off") and settings() == 0.0


@pytest.mark.parametrize("bad", ["", "abc", "-1", "nan", "inf"])
def test_bad_number_rejected(ctx, run, bad):
    assert "Usage" in run(f"set {bad}")
    assert "plugins" not in ctx.config


def test_status(ctx, run):
    assert "no limit" in run()
    ctx.settings["budget"] = {"daily_usd": 4}
    for model in ("a", "a", "b", "c", "d"):
        ctx.fire("post_api_request", model=model, usage=USAGE)
    out = run("status")
    assert "$5.00 of $4.00 (125% used)" in out
    top = out.split("Top models today:")[1].split("Last 7 days:")[0]
    assert "a " in top and top.count("$1.00") == 2 and "$2.00" in top
    assert budget._today() in out.split("Last 7 days:")[1] and len(out) < 1900
    assert "Usage" in run("5")


def test_price_falls_back_to_table():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    assert budget._price("no-such-model-xyz", usage, "custom", {"no-such-model-xyz": [1, 2]}) == 3.0
    assert budget._price("no-such-model-xyz", usage, "custom") is None
