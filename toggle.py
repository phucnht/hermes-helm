"""toggle module: switch MCP servers, skills and toolsets on or off from chat."""

from __future__ import annotations

from . import core

KINDS = ("mcp", "skill", "toolset")
LIST_PATH = {"skill": ("skills", "disabled"), "toolset": ("agent", "disabled_toolsets")}
NOTE = {"mcp": "applies within ~1 min (gateway watches config.yaml), or run /reload-mcp now",
        "skill": "applies on /reload-skills or /new",
        "toolset": "applies from your next message"}
LIMIT = 1800  # Discord caps a message at 2000 chars


def _skills() -> list[str]:
    from tools.skills_tool import find_all_skills
    return [s["name"] for s in find_all_skills(skip_disabled=True)]


def _toolsets() -> list[str]:
    from tools.registry import registry
    return list(registry.get_registered_toolset_names())


def _essential() -> set[str]:
    try:
        from agent.skill_utils import ESSENTIAL_SKILLS
        return set(ESSENTIAL_SKILLS)
    except Exception:
        return {"hermes-agent"}


def _disabled(cfg: dict, kind: str) -> set[str]:
    section, key = LIST_PATH[kind]
    value = (cfg.get(section) or {}).get(key) or []
    items = value.split(",") if isinstance(value, str) else value  # tolerate "a, b" written by hand
    return {str(v).strip() for v in items if str(v).strip()}


def _state(kind: str) -> dict[str, bool]:
    cfg = core.read_config()
    if kind == "mcp":
        return {name: str((c or {}).get("enabled", True)).lower() not in ("false", "off")
                for name, c in (cfg.get("mcp_servers") or {}).items()}
    off = _disabled(cfg, kind)
    return {name: name not in off for name in (_skills() if kind == "skill" else _toolsets())}


def _clip(text: str) -> str:
    return text if len(text) <= LIMIT else text[:LIMIT] + "…"


def apply(kind: str, name: str, on: bool) -> str:
    """Switch one MCP server, skill or toolset. Frozen contract: the cost module calls this."""
    if kind not in KINDS:
        return f"Unknown kind `{kind}`; use mcp, skill or toolset."
    known = _state(kind)
    if name not in known:
        return _clip(f"Unknown {kind} `{name}`. Known: {', '.join(sorted(known)) or 'none'}")
    if kind == "mcp":
        err = core.set_config(("mcp_servers", name, "enabled"), on)
    else:
        if kind == "skill" and not on and name in _essential():
            return f"`{name}` is an essential skill and cannot be disabled."
        off = _disabled(core.read_config(), kind)
        off = off - {name} if on else off | {name}
        err = core.set_config(".".join(LIST_PATH[kind]), sorted(off))
    return err or f"{kind} `{name}` is now {'on' if on else 'off'}; {NOTE[kind]}."


def _list(arg: str, source) -> str:
    kind = arg.rstrip("s")  # accept plurals
    if arg and kind not in KINDS:
        return "Usage: /helm toggle list [mcp|skill|toolset]"
    rows = [[k, name, "on" if on else "off"]
            for k in ([kind] if arg else KINDS) for name, on in sorted(_state(k).items())]
    if not rows:
        return "Nothing to toggle."
    header = ["kind", "name", "state"]
    n = len(rows)
    while len(core.table(rows[:n], header)) > LIMIT - 20:
        n -= 1
    return core.table(rows[:n], header) + (f"\n… {len(rows) - n} more" if n < len(rows) else "")


def _switch(kind: str):
    def handler(arg: str, source) -> str:
        parts = arg.split()
        if len(parts) != 2 or parts[1] not in ("on", "off"):
            return f"Usage: /helm toggle {kind} <name> on|off"
        return apply(kind, parts[0], parts[1] == "on")
    return handler


def setup(ctx) -> dict:
    return {"list": _list, **{k: _switch(k) for k in KINDS}}
