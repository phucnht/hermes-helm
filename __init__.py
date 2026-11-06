"""hermes-helm: run Hermes from Discord. `/helm <module> ...`, plus `/pending` and `/budget`."""

from __future__ import annotations

import importlib

from . import core

MODULES = ("toggle", "cost", "resume", "budget")
ALIASES = {"pending": ("resume", "pending"), "budget": ("budget", "")}
ALIAS_HINT = {"pending": "empty lists lost turns. Resend one with /helm resume replay <n>",
              "budget": "empty shows spend; set <usd> | off"}

# What each module does and its commands, as typed into the args box after /helm.
HELP = {
    "toggle": ("Switch things on or off", [
        ("toggle list", "every MCP server, skill and toolset, on or off"),
        ("toggle mcp <name> on|off", "for example `toggle mcp github off`"),
        ("toggle skill <name> on|off", "applies on /reload-skills or /new"),
        ("toggle toolset <name> on|off", "applies from your next message")]),
    "cost": ("See what fills every request", [
        ("cost", "rank MCP servers, skills and toolsets by tokens per request"),
        ("cost off", "buttons for the biggest ones; tap to switch one off")]),
    "resume": ("Get back turns a restart killed", [
        ("resume pending", "list them (same as /pending)"),
        ("resume replay <n>", "send turn n again"),
        ("resume clear", "dismiss the list")]),
    "budget": ("Cap daily spend", [
        ("budget", "today's spend against the limit (same as /budget)"),
        ("budget set <usd>", "for example `budget set 5`; new turns stop at the limit"),
        ("budget off", "remove the limit")]),
}


def _section(ctx, mid: str) -> list[str]:
    title, cmds = HELP[mid]
    off = "" if core.module_on(ctx, mid) else f" (off: `/helm modules {mid} on`)"
    return [f"**{title}**{off}"] + [f"`{cmd}`: {what}" for cmd, what in cmds]


def _help(subs: dict, ctx) -> str:
    lines = ["**hermes-helm** runs this Hermes from chat. Type `/helm`, then one of these in the `args` box. "
             "Start with `cost` to see what each request carries.", ""]
    for mid in MODULES:
        lines += _section(ctx, mid) + [""]
    lines.append("`modules <toggle|cost|resume|budget> on|off`: turn a whole section on or off")
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
        return "\n".join(_section(ctx, module_id))
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
                         args_hint="empty for help, or: cost | toggle list | budget set 5 | resume pending")
    for name, (mid, sub) in ALIASES.items():
        def alias(raw_args: str, source=None, platform=None, _mid=mid, _sub=sub):
            return _run(ctx, subs, _mid, f"{_sub} {raw_args or ''}".strip(), source, platform)
        ctx.register_command(name, alias, description=f"Shortcut for /helm {mid} {sub}".strip(),
                             args_hint=ALIAS_HINT[name])
