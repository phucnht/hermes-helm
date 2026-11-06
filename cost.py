"""cost module: rough tokens each toolset, MCP server and skill adds to every request."""

from __future__ import annotations

import json

from . import core

KINDS = ("mcp", "skill", "toolset")


def _tokens(text: str) -> int:
    """Hermes' rough rule (agent.model_metadata): ceil(UTF-8 bytes / 4), same as `/context all`."""
    return (len(text.encode("utf-8")) + 3) // 4


def _toolset_costs() -> dict[str, int]:
    """{toolset: tokens of its tool schemas}. MCP servers register as toolset ``mcp-<server>``."""
    from tools.registry import registry
    return {ts: _tokens("".join(json.dumps({"type": "function", "function": registry.get_schema(n) or {}},
                                           ensure_ascii=False) for n in registry.get_tool_names_for_toolset(ts)))
            for ts in registry.get_registered_toolset_names()}


def _skill_costs() -> dict[str, int]:
    """{skill: tokens of its index line in the system prompt}, disabled skills included."""
    from tools.skills_tool import find_all_skills
    return {s["name"]: _tokens(f"- {s['name']}: {s.get('description') or ''}\n")
            for s in find_all_skills(skip_disabled=True)}


def _names(value) -> set:
    return {value} if isinstance(value, str) else set(value or [])


def _items() -> list[tuple[str, str, int, bool]]:
    """(kind, name, tokens, on), most expensive first."""
    cfg = core.read_config()
    mcp_cfg = cfg.get("mcp_servers") or {}
    off_toolsets = _names((cfg.get("agent") or {}).get("disabled_toolsets"))
    off_skills = _names((cfg.get("skills") or {}).get("disabled"))
    items = []
    for ts, tok in _toolset_costs().items():
        if ts.startswith("mcp-"):
            items.append(("mcp", ts[4:], tok, (mcp_cfg.get(ts[4:]) or {}).get("enabled", True) is not False))
        else:
            items.append(("toolset", ts, tok, ts not in off_toolsets))
    items += [("skill", n, tok, n not in off_skills) for n, tok in _skill_costs().items()]
    return sorted(items, key=lambda i: (-i[2], i[0], i[1]))


def _k(tok: int) -> str:
    return f"~{tok / 1000:.1f}k" if tok >= 1000 else f"~{tok}"


def setup(ctx) -> dict:
    def show(arg: str, source) -> str:
        if arg and arg not in KINDS:
            return f"Usage: /helm cost [{'|'.join(KINDS)}]"
        items = [i for i in _items() if not arg or i[0] == arg]
        if not items:
            return "Nothing found."
        total = sum(i[2] for i in items if i[3])
        rows = [[k, n, _k(t), "on" if on else "off"] for k, n, t, on in items[:15]]
        return (core.table(rows, ["kind", "name", "tokens", "state"])
                + f"\nTotal on: {_k(total)} tokens per request across {sum(i[3] for i in items)} items."
                + "\nSkills count only their index line; the full SKILL.md loads when used."
                + "\n`/helm cost off` to switch one off.")

    def off(arg: str, source) -> str:
        choices = [{"value": f"{k}:{n}", "label": f"{n} ({k}) {_k(t)}"} for k, n, t, on in _items() if on][:24]
        if not choices:
            return "Nothing is on."
        picked = ctx.ask_choice("Switch which one off?", choices)
        if picked is None:
            return "No choice made."
        from . import toggle
        kind, _, name = str(picked).partition(":")
        return toggle.apply(kind, name, False)

    return {"": show, "off": off}
