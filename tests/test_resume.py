import pytest

from conftest import OWNER, helm, core

KEY = "agent:main:discord:dm:1"


@pytest.fixture
def run(ctx, monkeypatch):
    helm.register(ctx)
    monkeypatch.setattr(helm.resume, "_session_key", lambda: KEY)
    monkeypatch.setattr(helm.resume, "_unhold", lambda key: True)
    return lambda args: ctx.commands["helm"](args, source=OWNER, platform="discord")


def turn(ctx, tid, msg="fix the build", **kw):
    ctx.fire("pre_llm_call", turn_id=tid, session_id="s1", user_message=msg, platform="discord", **kw)


def restart(monkeypatch):
    monkeypatch.setattr(helm.resume, "BOOT", "new-boot")


def test_open_turn_from_old_boot_is_lost(ctx, run, monkeypatch):
    turn(ctx, "t1", "first")
    turn(ctx, "t2", "second")
    ctx.fire("on_session_end", turn_id="t2", completed=True)
    assert run("lost") == "No lost turns."  # same boot: t1 is still running
    restart(monkeypatch)
    out = run("lost")
    assert "1. " in out and "first" in out and "second" not in out
    assert core.execute("SELECT status FROM turns WHERE turn_id='t2'") == [("done",)]


def test_replay_injects_and_marks(ctx, run, monkeypatch):
    turn(ctx, "t1", "older")
    turn(ctx, "t2", "newer")
    restart(monkeypatch)
    ctx.choice = "1"
    assert run("lost") == "Replayed 1."  # newest first; tapped "Replay 1"
    assert [c["label"] for c in ctx.asked[0][1]] == ["Replay 1", "Replay 2", "Clear", "Cancel"]
    ctx.choice = None
    assert ctx.posted == [("inject", KEY, "newer")]
    assert "newer" not in run("lost") and "older" in run("lost")
    assert run("lost 9") == "/helm lost <1-1> | clear"


def test_replay_fallback_quotes_text(ctx, run, monkeypatch):
    turn(ctx, "t1", "line one\nline two")
    restart(monkeypatch)
    monkeypatch.setattr(ctx, "inject_message", lambda *a, **k: False)
    out = run("lost 1")
    assert "> line one\n> line two" in out and "allow_gateway_injection" in out
    assert "line one" in run("lost")  # still lost


def test_clear_dismisses(ctx, run, monkeypatch):
    turn(ctx, "t1")
    restart(monkeypatch)
    ctx.choice = "clear"
    assert run("lost") == "Cleared 1."
    ctx.choice = None
    assert run("lost") == "No lost turns."


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
    out = run("lost")
    assert "cut by shutdown" in out and "stopped by me" not in out


def test_long_discord_reply_comes_as_a_file(ctx, run, monkeypatch, tmp_path):
    monkeypatch.setattr(helm.resume, "_cache_dir", lambda: tmp_path)
    long = "\n".join(f"line {i} " + "x" * 90 for i in range(200))  # ~20k chars, past 8 Discord messages
    out = ctx.fire("transform_llm_output", response_text=long, platform="discord", turn_id="a:b/c")[0]
    head, path = out.split("\nMEDIA:")
    assert len(head) < 10_100 and head.endswith("…full reply attached.") and long.startswith(head.split("\n\n…")[0])
    assert path.endswith("helm-reply-a_b_c.txt") and open(path, encoding="utf-8").read() == long
    assert ctx.fire("transform_llm_output", response_text=long, platform="telegram", turn_id="t")[0] is None
    assert ctx.fire("transform_llm_output", response_text="short", platform="discord", turn_id="t")[0] is None


def test_replay_asks_for_discard_when_the_hold_stays(ctx, run, monkeypatch):
    turn(ctx, "t1", "lost one")
    restart(monkeypatch)
    monkeypatch.setattr(helm.resume, "_unhold", lambda key: False)
    assert run("lost 1") == "Replayed 1. Send /discard to let it run."


def test_unhold_outside_a_gateway_is_false():
    assert helm.resume._unhold(KEY) is False  # no live gateway published in tests


def test_unhold_retries_until_the_lost_turn_is_marked(monkeypatch):
    import asyncio, threading, types
    from hermes_cli import plugins
    from gateway import session_authorities, slash_commands_session
    from agent import i18n
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    calls = []

    async def discard(authority, sid):  # the pause lands only after the replay is admitted
        calls.append(sid)
        return "nothing" if len(calls) < 3 else "discarded"

    authority = types.SimpleNamespace(sessions={"s1": 1}, logical_owner=lambda sid: sid)
    runner = types.SimpleNamespace(_gateway_loop=loop, session_store=types.SimpleNamespace(peek_session_id=lambda k: "s1"))
    monkeypatch.setattr(plugins, "_published_gateway_message_injector", [runner], raising=False)
    monkeypatch.setattr(session_authorities, "active_authority", lambda r: authority)
    monkeypatch.setattr(slash_commands_session, "discard_lost_turns", discard)
    monkeypatch.setattr(i18n, "t", lambda key, **kw: "nothing")
    monkeypatch.setattr(helm.resume.time, "sleep", lambda s: None)
    try:
        assert helm.resume._unhold(KEY) is True and len(calls) == 3
    finally:
        loop.call_soon_threadsafe(loop.stop)


def test_stored_text_drops_the_shared_session_prefix(ctx, run, monkeypatch):
    monkeypatch.setattr(helm.resume, "_session_key", lambda: "agent:main:discord:thread:1:1")
    turn(ctx, "t1", "earlier chat\n\n[New message]\n[phuc] write the report")
    turn(ctx, "t2", "[phuc] [draft] title")
    assert [r[0] for r in core.execute("SELECT text FROM turns ORDER BY ts")] == ["write the report", "[draft] title"]
    monkeypatch.setattr(helm.resume, "_session_key", lambda: KEY)  # DM: no prefix to drop
    turn(ctx, "t3", "[draft] title")
    assert core.execute("SELECT text FROM turns WHERE turn_id='t3'") == [("[draft] title",)]
