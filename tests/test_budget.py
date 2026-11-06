import pytest

from conftest import OWNER, helm, core
from helm import budget

USAGE = {"input_tokens": 1000, "output_tokens": 500, "prompt_tokens": 1000}


@pytest.fixture
def run(ctx, monkeypatch):
    monkeypatch.setattr(budget, "_price", lambda model, usage, provider=None, prices=None: 1.0)
    helm.register(ctx)
    return lambda args="": ctx.commands["helm"](f"budget {args}", source=OWNER, platform="discord")


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
        assert b["message"] == "Daily budget $2.00 reached. `/helm budget` to raise it."


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
    assert ctx.posted == ["⚠️ $2.00 of $10.00 spent today. `/helm budget`"]


def test_text_sets_and_removes_limit(ctx, run):
    settings = lambda: ctx.config["plugins"]["entries"]["hermes-helm"]["settings"]["budget"]["daily_usd"]
    assert run("5.5") == "Daily limit $5.5." and settings() == 5.5
    assert run("$7") == "Daily limit $7." and settings() == 7.0
    assert run("off") == "No daily limit." and settings() == 0.0


@pytest.mark.parametrize("bad", ["abc", "-1", "nan", "inf"])
def test_bad_number_rejected(ctx, run, bad):
    assert run(bad) == "/helm budget <usd> | off"
    assert "plugins" not in ctx.config


def test_view_shows_spend_and_preset_buttons(ctx, run):
    ctx.settings["budget"] = {"daily_usd": 5}
    for model in ("a", "b"):
        ctx.fire("post_api_request", model=model, usage=USAGE)
    ctx.choice = "20"
    assert run() == "Daily limit $20."
    question, choices = ctx.asked[0]
    assert question.startswith("$2.00 of $5.00 today") and budget._today()[5:] in question
    assert [c["label"] for c in choices] == ["$1", "$20", "No limit"]  # the current $5 is not offered
    ctx.choice = None
    assert run().startswith("$2.00 of $5.00 today")  # no buttons: plain text


def test_price_falls_back_to_table():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    assert budget._price("no-such-model-xyz", usage, "custom", {"no-such-model-xyz": [1, 2]}) == 3.0
    assert budget._price("no-such-model-xyz", usage, "custom") is None


def test_price_table_overrides_hermes():
    # openai-codex is subscription-included, so Hermes prices it at $0; the table must still apply
    usage = {"input_tokens": 1_000_000, "output_tokens": 0}
    assert budget._price("gpt-5.4", usage, "openai-codex", {"gpt-5.4": [2, 8]}) == 2.0
