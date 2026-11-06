# hermes-helm

Run your Hermes Agent from Discord. You can switch skills, MCP servers and toolsets on or off, see how many tokens each one adds to every request, get back the turns a gateway restart killed, and stop the agent when it hits a daily spend limit.

Hermes can do most of this already, but only in the CLI, the desktop app or `config.yaml`. In Discord, `/tools`, `/toolsets`, `/skills` and `/plugins` are CLI-only. If your agent runs 24/7 on a server and you talk to it from your phone, you have to SSH in to change any of it. hermes-helm puts those controls in chat.

Only the bot owner can use it.

## Commands

| Command | What it does |
|---|---|
| `/helm` | Lists the modules and whether each is on |
| `/helm toggle list [mcp\|skill\|toolset]` | Lists every MCP server, skill and toolset with its on/off state |
| `/helm toggle mcp <name> on\|off` | Turns an MCP server on or off. The gateway reconnects within about a minute, or run `/reload-mcp` |
| `/helm toggle skill <name> on\|off` | Turns a skill on or off. Applies after `/reload-skills` or `/new` |
| `/helm toggle toolset <name> on\|off` | Turns a toolset on or off. Applies from your next message |
| `/helm cost [mcp\|skill\|toolset]` | Ranks what each item adds to every request, in tokens (same estimate rule as `/context all`) |
| `/helm cost off` | Shows buttons for the most expensive items. Tap one to switch it off |
| `/pending` | Lists turns that died mid-run because the gateway stopped or crashed |
| `/helm resume replay <n>` | Sends a lost turn again |
| `/helm resume clear` | Dismisses the lost-turn list |
| `/budget` | Shows today's spend against your limit, the top models and the last 7 days |
| `/budget set <usd>` / `/budget off` | Sets or removes the daily limit |
| `/helm modules <module> on\|off` | Turns a whole module (`toggle`, `cost`, `resume`, `budget`) on or off |

## Install

```bash
hermes plugins install phucnht/hermes-helm
hermes plugins enable hermes-helm
```

Add your Discord user ID to `config.yaml`, then restart the gateway:

```yaml
plugins:
  entries:
    hermes-helm:
      allow_gateway_injection: true   # optional: lets /helm resume replay resend a turn by itself
      settings:
        owner_ids: ["123456789012345678"]
        budget: {daily_usd: 5, warn_pct: 80}
```

In Discord, turn on Developer Mode, then right-click your name and choose Copy User ID. With `owner_ids` empty, nobody can use `/helm` from chat. The CLI and desktop app always can.

## How each module works

**toggle** writes the same `config.yaml` keys that `hermes mcp`, `hermes skills config` and `hermes tools` write: `mcp_servers.<name>.enabled`, `skills.disabled` and `agent.disabled_toolsets`. It refuses names that are not installed, and it never disables the essential `hermes-agent` skill.

**cost** counts tokens from the tool schemas and skill index lines in your current install. A skill's full SKILL.md loads only when the agent uses it, so the table counts only its one-line entry in the system prompt.

**resume** saves the text of each turn when the turn starts and marks it done when the turn ends. If the gateway is killed, restarted or loses power in between, the turn stays open, and the next process lists it under `/pending`. Turns you stop yourself with `/stop` are not listed. Replay resends the text only, not attachments. Without `allow_gateway_injection`, replay shows the text so you can paste it back.

**budget** prices every model call (main and auxiliary) with Hermes' own price table, falling back to `budget.prices` for models Hermes doesn't know. At `warn_pct` of the limit it posts one warning a day. At the limit it blocks new turns and stops tool calls in the turn that is running. The spend total is global and resets at local midnight.

## What it writes and stores

- **config.yaml:** only the keys listed under toggle, plus its own `plugins.entries.hermes-helm.settings`. Every change is logged with its old and new value in the plugin database.
- **Local database:** `<HERMES_HOME>/plugin-data/hermes-helm/helm.db`. It holds the text of your messages for 7 days (for resume), token counts and cost per model call (for budget), and the config change log.
- **Network:** none. It makes no network calls and sends nothing outside your Hermes install.

If your config is managed by Nix, hermes-helm refuses to write it and tells you so.

## Develop

```bash
cd tests && python -m pytest          # unit tests with a fake plugin context
hermes plugins doctor . --ci          # load check against Hermes' registries
hermes plugins validate .             # the catalog's admission check
```

MIT licensed.
