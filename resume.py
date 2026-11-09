"""resume module: remember each user turn; list and replay the ones a restart killed mid-turn.
A Discord reply too long to deliver comes as a file instead of being cut."""

import re
import time
from pathlib import Path
from uuid import uuid4

from . import core

BOOT = uuid4().hex  # this process; an 'open' row from another boot died mid-turn
# 'interrupted' counts too: a graceful gateway shutdown interrupts the turn before the process exits.
# A user /stop is marked 'stopped' by agent_loop_stopped first, so it never shows here.
LOST = "FROM turns WHERE status IN ('open','interrupted') AND boot!=? ORDER BY ts DESC LIMIT 10"
HINT = ("Auto-replay needs `plugins.entries.hermes-helm.allow_gateway_injection: true` in config.yaml "
        "(entry level, not under settings).")


def _session_key() -> str:
    from gateway.session_context import get_session_env
    return get_session_env("HERMES_SESSION_KEY")


def _text(msg) -> str:
    if isinstance(msg, list):
        msg = " ".join(p["text"] for p in msg if isinstance(p, dict) and isinstance(p.get("text"), str))
    return (msg or "").strip() if isinstance(msg, str) else ""


def _own_words(text: str, session_key: str) -> str:
    """What the user typed. In a shared session Hermes adds `[name] ` (and any channel backfill) before it
    reaches the agent, and adds them again to a replay (gateway/run_inbound.py _prefix_inbound_sender_context)."""
    if ":dm:" in (session_key or ""):  # a DM gets no prefix, so a leading `[x] ` is the user's own
        return text
    text = text.rpartition("\n\n[New message]\n")[2]
    return re.sub(r"^\[[^\]\n]+\] ", "", text, count=1)


def _age(ts: float) -> str:
    s = int(time.time() - ts)
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= n:
            return f"{s // n}{unit} ago"
    return f"{s}s ago"


DISCORD_PAGES = 8  # ponytail: mirrors DiscordAdapter.MAX_SPLIT_MESSAGES (hardcoded upstream); read it if it becomes config
HEAD = 10_000  # chars kept inline; with the note it stays well under the cap


def _pages(text: str) -> int:
    from gateway.platforms.base import BasePlatformAdapter
    return len(BasePlatformAdapter.truncate_message(text, 2000))


def _cache_dir() -> Path:
    from gateway.platforms.base import DOCUMENT_CACHE_DIR  # a root Hermes always lets MEDIA: deliver from
    return Path(DOCUMENT_CACHE_DIR)


def long_reply(response_text="", platform="", turn_id="", **kw):
    """Discord drops whatever doesn't fit in 8 messages: send the start, and the whole reply as a file."""
    if platform != "discord" or not isinstance(response_text, str) or _pages(response_text) <= DISCORD_PAGES:
        return None
    path = _cache_dir() / f"helm-reply-{re.sub(r'[^\w-]', '_', turn_id)[-40:] or uuid4().hex}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(response_text, encoding="utf-8")
    head = response_text[:HEAD].rsplit("\n", 1)[0]
    return f"{head}\n\n…full reply attached.\nMEDIA:{path}"


def _lost() -> list[tuple]:
    return core.execute("SELECT turn_id, ts, session_key, platform, text " + LOST, (BOOT,))


def setup(ctx):
    core.execute("CREATE TABLE IF NOT EXISTS turns (turn_id TEXT PRIMARY KEY, boot TEXT, ts REAL, session_id TEXT,"
                 " session_key TEXT, platform TEXT, text TEXT, status TEXT)")

    def pre_llm_call(user_message=None, parent_session_id="", turn_id="", session_id="", platform="", **kw):
        key = _session_key()
        text = _own_words(_text(user_message), key)
        if not text or parent_session_id:
            return None
        now = time.time()
        core.execute("DELETE FROM turns WHERE ts<?", (now - 7 * 86400,))
        core.execute("INSERT OR REPLACE INTO turns VALUES (?,?,?,?,?,?,?, 'open')",
                     (turn_id or uuid4().hex, BOOT, now, session_id, key, platform, text))
        return None

    def on_session_end(turn_id="", completed=False, failed=False, interrupted=False, **kw):
        status = "interrupted" if interrupted else "failed" if failed else "done"
        core.execute("UPDATE turns SET status=? WHERE turn_id=? AND status='open'", (status, turn_id))

    def agent_loop_stopped(session_key="", **kw):
        core.execute("UPDATE turns SET status='stopped' WHERE session_key=? AND status='open'", (session_key,))

    core.hook(ctx, "resume", "pre_llm_call", pre_llm_call)
    core.hook(ctx, "resume", "on_session_end", on_session_end)
    core.hook(ctx, "resume", "agent_loop_stopped", agent_loop_stopped)
    core.hook(ctx, "resume", "transform_llm_output", long_reply)

    def replay(rows, n: int) -> str:
        turn_id, _, key, _, text = rows[n - 1]
        if key and ctx.inject_message(text, session_key=key):
            core.execute("UPDATE turns SET status='replayed' WHERE turn_id=?", (turn_id,))
            return f"Replayed {n}. Send /discard to let it run."  # Hermes holds a chat that lost a turn until /discard
        quoted = "\n".join("> " + line for line in text.splitlines())
        return f"Could not resend {n} by itself. Paste it back:\n{quoted}"[:1700] + "\n" + HINT

    def clear() -> str:
        n = len(core.execute("UPDATE turns SET status='dismissed' WHERE status IN ('open','interrupted') AND boot!=?"
                             " RETURNING 1", (BOOT,)))
        return f"Cleared {n}."

    def view(arg, source):
        """No arg: lost turns, tap one to resend it. `<n>` resends turn n, `clear` dismisses all."""
        rows = _lost()
        if not rows:
            return "No lost turns."
        if arg == "clear":
            return clear()
        if arg:
            return replay(rows, int(arg)) if arg.isdigit() and 1 <= int(arg) <= len(rows) else \
                f"/helm lost <1-{len(rows)}> | clear"
        head = "Lost turns, newest first\n" + "\n".join(
            f"{n}. {_age(ts)}  {text[:70]}" for n, (_, ts, _, _, text) in enumerate(rows, 1))
        picked = ctx.ask_choice(head, [{"value": str(n), "label": f"Replay {n}"} for n in range(1, len(rows) + 1)]
                                + [{"value": "clear", "label": "Clear"}, core.CANCEL])
        if picked == "*cancel":
            return None
        if picked is None:
            return head
        return clear() if picked == "clear" else replay(rows, int(picked))

    return {"lost": view}
