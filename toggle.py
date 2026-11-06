"""toggle module: MCP servers, skills and toolsets ranked by the tokens they add to every request;
tap one to switch it on or off."""

from __future__ import annotations

import json

from . import core

KINDS = {"mcp": "MCP", "skills": "Skills", "toolsets": "Toolsets"}
LIST_PATH = {"skills": ("skills", "disabled"), "toolsets": ("agent", "disabled_toolsets")}
APPLIES = {"mcp": "applies within a minute", "skills": "applies on /reload-skills or /new",
           "toolsets": "applies from your next message"}
BUTTONS = 24  # Discord: 25 per card, one kept for Hermes' "Other"


def _tokens(text: str) -> int:
    """Hermes' rough rule (agent.model_metadata): ceil(UTF-8 bytes / 4), same as `/context all`."""
    return (len(text.encode("utf-8")) + 3) // 4


def k(tok: int) -> str:
    return f"{tok / 1000:.1f}k" if tok >= 1000 else str(tok)


def _toolset_tokens() -> dict[str, int]:
    """{toolset: tokens of its tool schemas}. MCP servers register as toolset ``mcp-<server>``."""
    from tools.registry import registry
    return {ts: _tokens("".join(json.dumps({"type": "function", "function": registry.get_schema(n) or {}},
                                           ensure_ascii=False) for n in registry.get_tool_names_for_toolset(ts)))
            for ts in registry.get_registered_toolset_names()}


def _skill_tokens() -> dict[str, int]:
    """{skill: tokens of its index line in the system prompt}. SKILL.md itself loads only when used."""
    from tools.skills_tool import find_all_skills
    return {s["name"]: _tokens(f"- {s['name']}: {s.get('description') or ''}\n")
            for s in find_all_skills(skip_disabled=True)}


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


def items(kind: str) -> list[tuple[str, int, bool]]:
    """(name, tokens, on), most tokens first. An MCP server that is off or not connected counts 0."""
    cfg = core.read_config()
    if kind == "mcp":
        tok = {ts[4:]: n for ts, n in _toolset_tokens().items() if ts.startswith("mcp-")}
        rows = [(name, tok.get(name, 0), str((c or {}).get("enabled", True)).lower() not in ("false", "off"))
                for name, c in (cfg.get("mcp_servers") or {}).items()]
    elif kind == "skills":
        off = _disabled(cfg, kind)
        rows = [(n, t, n not in off) for n, t in _skill_tokens().items()]
    else:
        off = _disabled(cfg, kind)
        rows = [(n, t, n not in off) for n, t in _toolset_tokens().items() if not n.startswith("mcp-")]
    return sorted(rows, key=lambda r: (-r[1], r[0]))


def switch(kind: str, name: str, on: bool) -> str:
    known = {n for n, _, _ in items(kind)}
    if name not in known:
        return f"No {KINDS[kind]} named `{name}`."
    if kind == "mcp":
        err = core.set_config(("mcp_servers", name, "enabled"), on)
    else:
        if kind == "skills" and not on and name in _essential():
            return f"`{name}` is essential to Hermes and stays on."
        off = _disabled(core.read_config(), kind)
        err = core.set_config(".".join(LIST_PATH[kind]), sorted(off - {name} if on else off | {name}))
    return err or f"`{name}` {'on' if on else 'off'}, {APPLIES[kind]}."


def view(ctx, kind: str, arg: str) -> str | None:
    """No arg: the ranked list as buttons (a table where nothing can ask). `<name> on|off`: switch."""
    parts = arg.split()
    if len(parts) == 2 and parts[1] in ("on", "off"):
        return switch(kind, parts[0], parts[1] == "on")
    if parts:
        return f"/helm {kind} <name> on|off"
    rows = items(kind)
    if not rows:
        return f"No {KINDS[kind]}."
    on_rows = [r for r in rows if r[2]]
    head = f"{KINDS[kind]}: {len(on_rows)} of {len(rows)} on, {k(sum(r[1] for r in on_rows))} tokens per request"
    pick = [r for r in rows if not (kind == "skills" and r[0] in _essential())]
    shown = pick[:BUTTONS]
    if len(pick) > BUTTONS:
        head += f"\nShowing the {BUTTONS} largest. Type any other name to switch it."
    picked = ctx.ask_choice(head, [{"value": n, "label": f"{'●' if on else '○'} {n}" + (f"  {k(t)}" if t else "")}
                                   for n, t, on in shown] + [{"value": n} for n, _, _ in pick[BUTTONS:]])
    if picked is not None:
        return switch(kind, picked, not dict((n, on) for n, _, on in rows)[picked])
    table = core.table([[n, k(t) if t else "-", "on" if on else "off"] for n, t, on in rows[:30]],
                       ["name", "tokens", "state"])
    return f"{head}\n{table}"[:1900]


def setup(ctx) -> dict:
    return {kind: (lambda arg, source, _kind=kind: view(ctx, _kind, arg)) for kind in KINDS}
