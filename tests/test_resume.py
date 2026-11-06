import pytest

from conftest import OWNER, helm, core

KEY = "agent:main:discord:dm:1"


@pytest.fixture
def run(ctx, monkeypatch):
    helm.register(ctx)
    monkeypatch.setattr(helm.resume, "_session_key", lambda: KEY)
    return lambda args: ctx.commands["helm"](args, source=OWNER, platform="discord")


def turn(ctx, tid, msg="fix the build", **kw):
    ctx.fire("pre_llm_call", turn_id=tid, session_id="s1", user_message=msg, platform="discord", **kw)


def restart(monkeypatch):
    monkeypatch.setattr(helm.resume, "BOOT", "new-boot")


def test_open_turn_from_old_boot_is_lost(ctx, run, monkeypatch):
    turn(ctx, "t1", "first")
    turn(ctx, "t2", "second")
    ctx.fire("on_session_end", turn_id="t2", completed=True)
    assert run("resume pending") == "No lost turns."  # same boot: t1 is still running
    restart(monkeypatch)
    out = ctx.commands["pending"]("", source=OWNER, platform="discord")
    assert "1. " in out and "first" in out and "second" not in out and "attachments" in out
    assert core.execute("SELECT status FROM turns WHERE turn_id='t2'") == [("done",)]


def test_replay_injects_and_marks(ctx, run, monkeypatch):
    turn(ctx, "t1", "older")
    turn(ctx, "t2", "newer")
    restart(monkeypatch)
    assert run("resume replay 1") == "Replayed #1."  # newest first
    assert ctx.posted == [("inject", KEY, "newer")]
    assert "newer" not in run("resume pending") and "older" in run("resume pending")
    assert "Usage" in run("resume replay 9")


def test_replay_fallback_quotes_text(ctx, run, monkeypatch):
    turn(ctx, "t1", "line one\nline two")
    restart(monkeypatch)
    monkeypatch.setattr(ctx, "inject_message", lambda *a, **k: False)
    out = run("resume replay 1")
    assert "> line one\n> line two" in out and "allow_gateway_injection" in out
    assert "line one" in run("resume pending")  # still lost


def test_clear_dismisses(ctx, run, monkeypatch):
    turn(ctx, "t1")
    restart(monkeypatch)
    assert run("resume clear") == "Dismissed 1 lost turn(s)."
    assert run("resume pending") == "No lost turns."


def test_skips_subagents_and_empty_and_joins_parts(ctx, run, monkeypatch):
    turn(ctx, "sub", parent_session_id="p1")
    turn(ctx, "empty", "  ")
    turn(ctx, "img", [{"type": "image_url", "image_url": {"url": "x"}}])
    turn(ctx, "parts", [{"type": "text", "text": "look at"}, {"type": "image_url"}, {"type": "text", "text": "this"}])
    assert core.execute("SELECT turn_id, text FROM turns") == [("parts", "look at this")]


def test_prunes_old_rows(ctx, run):
    core.execute("INSERT INTO turns VALUES ('old','b',0,'s','k','discord','x','open')")
    turn(ctx, "t1")
    assert [r[0] for r in core.execute("SELECT turn_id FROM turns")] == ["t1"]


def test_shutdown_interrupt_is_lost_but_user_stop_is_not(ctx, run, monkeypatch):
    turn(ctx, "t1", "cut by shutdown")
    ctx.fire("on_session_end", turn_id="t1", interrupted=True)
    turn(ctx, "t2", "stopped by me")
    ctx.fire("agent_loop_stopped", session_key=KEY, platform="discord", reason="user_stop")
    ctx.fire("on_session_end", turn_id="t2", interrupted=True)
    restart(monkeypatch)
    out = run("resume pending")
    assert "cut by shutdown" in out and "stopped by me" not in out
