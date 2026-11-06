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


def _skills() -> dict[str, tuple[int, str]]:
    """{skill: (tokens of its index line in the system prompt, category)}. SKILL.md loads only when used."""
    from tools.skills_tool import find_all_skills
    return {s["name"]: (_tokens(f"- {s['name']}: {s.get('description') or ''}\n"), s.get("category") or "other")
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


def items(kind: str, category: str | None = None) -> list[tuple[str, int, bool]]:
    """(name, tokens, on), most tokens first. An MCP server that is off or not connected counts 0."""
    cfg = core.read_config()
    if kind == "mcp":
        tok = {ts[4:]: n for ts, n in _toolset_tokens().items() if ts.startswith("mcp-")}
        rows = [(name, tok.get(name, 0), str((c or {}).get("enabled", True)).lower() not in ("false", "off"))
                for name, c in (cfg.get("mcp_servers") or {}).items()]
    elif kind == "skills":
        off = _disabled(cfg, kind)
        rows = [(n, t, n not in off) for n, (t, cat) in _skills().items() if category in (None, cat)]
    else:
        off = _disabled(cfg, kind)
        rows = [(n, t, n not in off) for n, t in _toolset_tokens().items() if not n.startswith("mcp-")]
    return sorted(rows, key=lambda r: (-r[1], r[0]))


def total(kind: str) -> int:
    """Tokens the switched-on items of *kind* add to every request."""
    return sum(t for _, t, on in items(kind) if on)


def _write(kind: str, names: list[str], on: bool) -> str | None:
    """Switch every name in one go; an error string, or None."""
    if kind == "mcp":
        return next((err for n in names if (err := core.set_config(("mcp_servers", n, "enabled"), on))), None)
    off = _disabled(core.read_config(), kind)
    return core.set_config(".".join(LIST_PATH[kind]), sorted(off - set(names) if on else off | set(names)))


def _summary(kind: str, changes: dict[str, bool]) -> str:
    """`Off: a, b. On: c. Applies within a minute.`"""
    parts = [f"{label}: {', '.join(f'`{n}`' for n, v in changes.items() if v is state)}"
             for label, state in (("Off", False), ("On", True)) if state in changes.values()]
    return ". ".join(parts) + f". {APPLIES[kind].capitalize()}."


def switch(kind: str, names: list[str], on: bool) -> str:
    known = {n for n, _, _ in items(kind)}
    if names == ["all"]:
        names = sorted(known)
    if unknown := [n for n in names if n not in known]:
        return f"No {KINDS[kind]} named {', '.join(f'`{n}`' for n in unknown)}."
    if kind == "skills" and not on:
        if kept := [n for n in names if n in _essential()]:
            names = [n for n in names if n not in kept]
            if not names:
                return f"`{kept[0]}` is essential to Hermes and stays on."
    return _write(kind, names, on) or _summary(kind, dict.fromkeys(names, on))


def _label(n: str, t: int, on: bool) -> str:
    return f"{'🟢' if on else '⚫'} {n}" + (f"  {k(t)}" if t else "")


def _bulk(rows) -> list[dict]:
    """All on / All off, each shown only when it would change something."""
    return ([{"value": "*on", "label": "All on"}] if any(not on for _, _, on in rows) else []) + \
           ([{"value": "*off", "label": "All off"}] if any(on for _, _, on in rows) else [])


def _head(title: str, rows, note: str) -> str:
    on = [r for r in rows if r[2]]
    return (f"{note}\n" if note else "") + f"{title}: {len(on)} of {len(rows)} on, {k(sum(r[1] for r in on))} tokens"


DONE = {"value": "*done", "label": "Done"}


def _groups(rows) -> list[dict]:
    """One button per skill category, largest first: `creative  8/9  610`."""
    cat = {n: c for n, (_, c) in _skills().items()}
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(cat.get(r[0], "other"), []).append(r)
    order = sorted(groups.items(), key=lambda g: (-sum(r[1] for r in g[1]), g[0]))
    return [{"value": f"#{c}", "label": f"{c}  {sum(r[2] for r in rs)}/{len(rs)}  {k(sum(r[1] for r in rs if r[2]))}"}
            for c, rs in order]


def _list(ctx, kind: str, category: str | None = None, changes: dict[str, bool] | None = None) -> str | None:
    """Buttons stay open: each tap applies at once and the card comes back updated, until Done.
    Top-level Skills shows categories; a category opens its own list."""
    changes = {} if changes is None else changes
    title, note = KINDS[kind] + (f" · {category}" if category else ""), ""
    while True:
        rows = [r for r in items(kind, category) if not (kind == "skills" and r[0] in _essential())]
        if not rows:
            return f"No {title}."
        bulk = _bulk(rows)
        cap = BUTTONS - len(bulk) - 1
        middle = (_groups(rows) if kind == "skills" and not category
                  else [{"value": n, "label": _label(n, t, on)} for n, t, on in rows])[:cap]
        # ponytail: rows past the cap get no button (Hermes shows every choice); `/helm <kind> <name> off` reaches them
        picked = ctx.ask_choice(_head(title, rows, note), middle + bulk + [DONE])
        if picked is None and not changes:  # nothing can ask here (CLI, agent): a table
            table = core.table([[n, k(t) if t else "-", "on" if on else "off"] for n, t, on in rows[:30]],
                               ["name", "tokens", "state"])
            return f"{_head(title, rows, '')}\n{table}"[:1900]
        if picked in (None, "*done"):
            return _summary(kind, changes) if changes else None
        if picked.startswith("#"):
            return _list(ctx, kind, picked[1:], changes)
        names, on = ([n for n, _, _ in rows], picked == "*on") if picked in ("*on", "*off") else \
            ([picked], not dict((n, s) for n, _, s in rows)[picked])
        if err := _write(kind, names, on):
            return err
        changes.update(dict.fromkeys(names, on))
        note = _summary(kind, dict.fromkeys(names, on))


def view(ctx, kind: str, arg: str) -> str | None:
    """No arg: buttons. `<name...> on|off` or `all on|off`: switch by text."""
    parts = arg.split()
    if len(parts) >= 2 and parts[-1] in ("on", "off"):
        return switch(kind, parts[:-1], parts[-1] == "on")
    if parts:
        return f"/helm {kind} <name ...|all> on|off"
    return _list(ctx, kind)


def setup(ctx) -> dict:
    return {kind: (lambda arg, source, _kind=kind: view(ctx, _kind, arg)) for kind in KINDS}
