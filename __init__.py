"""hermes-helm: run Hermes from Discord. `/helm <module> ...`, plus `/pending` and `/budget`."""

from __future__ import annotations

import importlib

from . import core

MODULES = ("toggle", "cost", "resume", "budget")
ALIASES = {"pending": ("resume", "pending"), "budget": ("budget", "")}


def _help(subs: dict, ctx) -> str:
    lines = ["**hermes-helm**  `/helm <module> <command>`"]
    for mid in MODULES:
        state = "on" if core.module_on(ctx, mid) else "off"
        cmds = ", ".join(sorted(k for k in subs.get(mid, {}) if k)) or "-"
        lines.append(f"`{mid}` ({state}): {cmds}")
    lines.append("`modules <id> on|off` switches a module.")
    return "\n".join(lines)


def _modules_cmd(ctx, args: str) -> str:
    parts = args.split()
    if len(parts) != 2 or parts[0] not in MODULES or parts[1] not in ("on", "off"):
        return f"Usage: /helm modules <{'|'.join(MODULES)}> on|off"
    err = core.set_config(f"plugins.entries.{core.PLUGIN}.settings.modules.{parts[0]}", parts[1] == "on")
    return err or f"Module `{parts[0]}` is now {parts[1]}."


def _run(ctx, subs: dict, module_id: str, rest: str, source, platform) -> str:
    if not core.is_owner(ctx, source, platform):
        return "Only the bot owner can use /helm. Add your Discord user ID to owner_ids."
    if module_id == "modules":
        return _modules_cmd(ctx, rest)
    if module_id not in subs:
        return _help(subs, ctx)
    if not core.module_on(ctx, module_id):
        return f"Module `{module_id}` is off. Turn it on with `/helm modules {module_id} on`."
    sub, _, arg = rest.strip().partition(" ")
    handlers = subs[module_id]
    handler = handlers.get(sub)
    if handler is None and "" in handlers:
        handler, arg = handlers[""], rest  # default handler sees the whole argument string
    if handler is None:
        return f"`{module_id}` commands: {', '.join(sorted(k for k in handlers if k)) or 'none'}"
    try:
        return handler(arg.strip(), source)
    except Exception as exc:  # reply with the error instead of a silent failure in chat
        return f"`{module_id} {sub}` failed: {exc}"


def register(ctx):
    subs: dict[str, dict[str, core.Handler]] = {}
    for mid in MODULES:
        mod = importlib.import_module(f".{mid}", __name__)
        subs[mid] = mod.setup(ctx) or {}

    def helm(raw_args: str, source=None, platform=None):
        mid, _, rest = (raw_args or "").strip().partition(" ")
        return _run(ctx, subs, mid, rest, source, platform)

    ctx.register_command("helm", helm, description="Control Hermes from chat: skills, MCP, cost, lost turns, budget",
                         args_hint="<module> <command>")
    for name, (mid, sub) in ALIASES.items():
        def alias(raw_args: str, source=None, platform=None, _mid=mid, _sub=sub):
            return _run(ctx, subs, _mid, f"{_sub} {raw_args or ''}".strip(), source, platform)
        ctx.register_command(name, alias, description=f"Shortcut for /helm {mid} {sub}".strip(),
                             args_hint="[args]")
