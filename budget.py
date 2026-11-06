"""budget module: record what every LLM call costs, warn near a daily USD limit, stop at it."""

from __future__ import annotations

import datetime
import math
import time

from . import core

LIMIT_PATH = f"plugins.entries.{core.PLUGIN}.settings.budget.daily_usd"
USAGE = "Usage: /budget [status] | /budget set <usd> | /budget off"


def _today(days_ago: int = 0) -> str:
    return (datetime.date.today() - datetime.timedelta(days=days_ago)).isoformat()


def _price(model: str, usage: dict, provider=None, prices=None) -> float | None:
    """USD for one call: Hermes pricing, else the budget.prices table, else None (unknown)."""
    try:
        from agent.usage_pricing import CanonicalUsage, estimate_usage_cost
        buckets = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens")
        cost = estimate_usage_cost(model, CanonicalUsage(**{k: int(usage.get(k) or 0) for k in buckets}),
                                   provider=provider).amount_usd
        if cost is not None:
            return float(cost)
    except Exception:
        pass
    rate = (prices or {}).get(model)
    if rate:
        inp = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        return (inp * float(rate[0]) + (usage.get("output_tokens") or 0) * float(rate[1])) / 1e6
    return None


def setup(ctx):
    core.execute("CREATE TABLE IF NOT EXISTS usage (ts REAL, day TEXT, model TEXT, input INT, output INT, usd REAL)")
    core.execute("CREATE TABLE IF NOT EXISTS budget_warned (day TEXT PRIMARY KEY)")

    def limit() -> float:
        try:
            return float(ctx.get_config("budget.daily_usd") or 0)
        except (TypeError, ValueError):
            return 0.0

    def spent() -> float:
        return core.execute("SELECT COALESCE(SUM(usd), 0) FROM usage WHERE day=?", (_today(),))[0][0]

    def record(model=None, provider=None, usage=None, **_):
        if not usage:  # errors and streamed aux calls carry no usage
            return
        inp = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        usd = _price(model or "", usage, provider, ctx.get_config("budget.prices"))
        core.execute("INSERT INTO usage VALUES (?,?,?,?,?,?)",
                     (time.time(), _today(), model or "?", inp, usage.get("output_tokens") or 0, usd))

    def after_api_request(**kw):
        record(**kw)
        cap, pct = limit(), float(ctx.get_config("budget.warn_pct", default=80) or 80)
        # Warn only from the main turn: it always has a bound session for post_message.
        if cap and spent() >= cap * pct / 100 and core.execute(
                "INSERT OR IGNORE INTO budget_warned VALUES (?) RETURNING day", (_today(),)):
            ctx.post_message(f"⚠️ Budget: ${spent():.2f} of ${cap:.2f} spent today ({pct:g}% warning). "
                             "`/budget` for details.")

    def brake(**_):
        cap = limit()
        if cap and spent() >= cap:
            return {"action": "block", "message": f"Daily budget ${cap:.2f} reached (${spent():.2f} spent). "
                                                  "`/budget set <usd>` to raise it or `/budget off`."}
        return None

    core.hook(ctx, "budget", "post_api_request", after_api_request)
    core.hook(ctx, "budget", "post_auxiliary_call", record)
    core.hook(ctx, "budget", "pre_llm_call", brake)
    core.hook(ctx, "budget", "pre_tool_call", brake)

    def status(arg, source):
        if arg:
            return USAGE
        cap, s = limit(), spent()
        lines = [f"**Budget** today ${s:.2f}" + (f" of ${cap:.2f} ({s / cap * 100:.0f}% used)" if cap else " (no limit)")]
        unpriced = core.execute("SELECT COUNT(*) FROM usage WHERE day=? AND usd IS NULL", (_today(),))[0][0]
        if unpriced:
            lines.append(f"{unpriced} call(s) today have no known price; add them to budget.prices.")
        top = core.execute("SELECT model, COALESCE(SUM(usd), 0), COUNT(*) FROM usage WHERE day=? "
                           "GROUP BY model ORDER BY 2 DESC LIMIT 3", (_today(),))
        if top:
            lines.append("Top models today:\n" + core.table([[m[:40], f"${u:.2f}", n] for m, u, n in top],
                                                            ["model", "usd", "calls"]))
        week = core.execute("SELECT day, COALESCE(SUM(usd), 0), COUNT(*) FROM usage WHERE day>=? "
                            "GROUP BY day ORDER BY day DESC", (_today(6),))
        if week:
            lines.append("Last 7 days:\n" + core.table([[d, f"${u:.2f}", n] for d, u, n in week],
                                                       ["day", "usd", "calls"]))
        return "\n".join(lines)

    def set_limit(arg, source):
        try:
            usd = float(arg)
        except ValueError:
            usd = -1.0
        if not math.isfinite(usd) or usd < 0:
            return "Usage: /budget set <usd>, a number like 5 or 2.50 (0 turns the limit off)."
        err = core.set_config(LIMIT_PATH, usd)
        return err or (f"Daily budget set to ${usd:.2f}." if usd else "Daily budget off.")

    return {"": status, "status": status, "set": set_limit, "off": lambda arg, source: set_limit("0", source)}
