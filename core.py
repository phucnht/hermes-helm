"""Shared helpers for every hermes-helm module: owner gate, settings, storage, config writes."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Callable

PLUGIN = "hermes-helm"
LOCAL_PLATFORMS = {"", "cli", "tui", "desktop", "local"}

# A module handler gets the text after its subcommand and the caller's source; returns the reply.
Handler = Callable[[str, Any], str]

_db: sqlite3.Connection | None = None
_db_lock = threading.Lock()


def user_id(source: Any) -> str:
    if source is None:
        return ""
    value = source.get("user_id") if isinstance(source, dict) else getattr(source, "user_id", None)
    return str(value or "")


def is_owner(ctx, source: Any, platform: str | None) -> bool:
    """Local surfaces are the owner by definition; on a messaging platform the caller must be in
    ``owner_ids``. Unknown caller or empty list fails closed."""
    if (platform or "") in LOCAL_PLATFORMS and source is None:
        return True
    owners = {str(o) for o in (ctx.get_config("owner_ids", default=[]) or [])}
    uid = user_id(source)
    return bool(uid) and uid in owners


def module_on(ctx, module_id: str) -> bool:
    return ctx.get_config(f"modules.{module_id}", default=True) is not False


def db() -> sqlite3.Connection:
    """One shared connection to the plugin's SQLite file. Modules create their own tables."""
    global _db
    with _db_lock:
        if _db is None:
            from plugins.plugin_storage import plugin_db
            _db = plugin_db(PLUGIN, "helm.db")
            _db.execute("CREATE TABLE IF NOT EXISTS audit (ts REAL, key TEXT, old TEXT, new TEXT)")
            _db.commit()
        return _db


def hook(ctx, module_id: str, name: str, fn: Callable) -> None:
    """Register a hook that goes quiet while its module is switched off, and never raises."""
    def guarded(*args, **kwargs):
        if not module_on(ctx, module_id):
            return None
        try:
            return fn(*args, **kwargs)
        except Exception:  # a broken module must not break the agent turn
            import logging
            logging.getLogger(PLUGIN).exception("%s %s hook failed", module_id, name)
            return None
    ctx.register_hook(name, guarded)


def execute(sql: str, params: tuple = ()) -> list[tuple]:
    conn = db()
    with _db_lock:
        rows = conn.execute(sql, params).fetchall()
        conn.commit()
        return rows


def read_config() -> dict:
    from hermes_cli.config import load_config_readonly
    return load_config_readonly() or {}


def set_config(path: str | tuple, value: Any) -> str | None:
    """The only writer of config.yaml. ``path`` is dotted, or a tuple when a key may contain a dot
    (an MCP server name). Returns an error string, or None on success."""
    from hermes_cli import config as hc
    if hc.is_managed():
        return "config.yaml is managed by your package manager; change it there."
    cfg = hc.load_config()
    keys = list(path) if isinstance(path, tuple) else path.split(".")
    path = ".".join(keys)
    node = cfg
    for key in keys[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = node[key] = {}
        node = child
    old = node.get(keys[-1])
    node[keys[-1]] = value
    hc.save_config(cfg, merge_existing=True)
    execute("INSERT INTO audit VALUES (?,?,?,?)",
            (time.time(), path, json.dumps(old, default=str), json.dumps(value, default=str)))
    return None


CANCEL = {"value": "*cancel", "label": "Cancel"}


def table(rows: list[list[Any]], header: list[str]) -> str:
    """Monospace table for Discord (code block keeps columns aligned)."""
    cells = [header] + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(header))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in cells]
    return "```\n" + "\n".join(lines) + "\n```"
