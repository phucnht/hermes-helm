"""hermes-helm: run Hermes from chat. `/helm` opens a menu; `/helm <view> [args]` goes straight there."""

from __future__ import annotations

import importlib

from . import core

MODULES = ("toggle", "resume", "budget")
MENU = {"mcp": "MCP", "skills": "Skills", "toolsets": "Toolsets", "lost": "Lost turns", "budget": "Budget"}
USAGE = "/helm [mcp | skills | toolsets | lost | budget | modules]"


def _modules_cmd(args: str) -> str:
    parts = args.split()
    if len(parts) != 2 or parts[0] not in MODULES or parts[1] not in ("on", "off"):
        return f"/helm modules <{'|'.join(MODULES)}> on|off"
    err = core.set_config(f"plugins.entries.{core.PLUGIN}.settings.modules.{parts[0]}", parts[1] == "on")
    return err or f"{parts[0]} {parts[1]}."


def register(ctx):
    views: dict[str, tuple[str, core.Handler]] = {}  # view name -> (module id, handler)
    for mid in MODULES:
        for name, handler in (importlib.import_module(f".{mid}", __name__).setup(ctx) or {}).items():
            views[name] = (mid, handler)

    def run(name: str, arg: str, source):
        mid, handler = views[name]
        if not core.module_on(ctx, mid):
            return f"{mid} is off. `/helm modules {mid} on`"
        try:
            return handler(arg, source)
        except Exception as exc:  # reply with the error instead of failing silently in chat
            return f"/helm {name} failed: {exc}"

    def helm(raw_args: str, source=None, platform=None):
        if not core.is_owner(ctx, source, platform):
            return "Only the owner can use /helm."
        name, _, arg = (raw_args or "").strip().partition(" ")
        name, arg = name.lower(), arg.strip()
        if name == "modules":
            return _modules_cmd(arg)
        if name in views:
            return run(name, arg, source)
        if name:
            return USAGE
        menu = [{"value": v, "label": label} for v, label in MENU.items() if core.module_on(ctx, views[v][0])]
        picked = ctx.ask_choice("hermes-helm", menu + [core.CANCEL])
        if picked == "*cancel":
            return None
        return USAGE if picked is None else run(picked, "", source)

    ctx.register_command("helm", helm, description="Skills, MCP servers, lost turns and spend",
                         args_hint="mcp, skills, toolsets, lost, budget")
