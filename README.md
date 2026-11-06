# hermes-helm

`/helm` in Discord opens a menu for the Hermes agent you run 24/7:

- **MCP, Skills, Toolsets.** Everything installed, ranked by the tokens it adds to every request. Tap items to switch them, or All on / All off, then Done. Skills open by category.
- **Lost turns.** Messages a gateway restart or crash killed mid-reply. Tap one to send it again.
- **Budget.** Today's spend and the last 7 days. Tap a daily limit; at the limit Hermes stops taking new turns.

Hermes can already change these, but only in the CLI, the desktop app or `config.yaml`. In Discord, `/tools`, `/toolsets`, `/skills` and `/plugins` are CLI-only, so changing anything from your phone means an SSH session.

Only the owner can use it.

## Install

```bash
hermes plugins install phucnht/hermes-helm
hermes plugins enable hermes-helm
```

Add your Discord user ID (Developer Mode, right-click your name, Copy User ID), then restart the gateway:

```yaml
plugins:
  entries:
    hermes-helm:
      allow_gateway_injection: true   # lets Lost turns resend a message by itself
      settings:
        owner_ids: ["123456789012345678"]
```

## Typing instead of tapping

Every view also takes text, which is what the CLI and agents use:

| | |
|---|---|
| `/helm mcp` · `skills` · `toolsets` | the ranked list |
| `/helm skills pdf web off` · `mcp all on` | switch one, several or all; skills apply on `/reload-skills` or `/new`, MCP within a minute, toolsets on the next message |
| `/helm lost` · `lost 2` · `lost clear` | list, resend, dismiss |
| `/helm budget` · `budget 5` · `budget off` | spend, set or remove the daily limit |
| `/helm modules budget off` | hide a whole section (`toggle`, `resume`, `budget`) |

## How it counts

**Tokens** follow Hermes' own rule for `/context`: a tool's schema or a skill's index line, bytes ÷ 4. A skill's full SKILL.md loads only when used, so it is not counted. An MCP server that is off shows no number, since it isn't connected.

**Spend** prices every model call, main and auxiliary, with your `budget.prices` first and Hermes' price table second. Hermes prices a ChatGPT/Codex subscription at $0, so on a subscription add a rate if you want a limit:

```yaml
      settings:
        budget: {daily_usd: 5, warn_pct: 80, prices: {gpt-5.4: [2, 8]}}   # USD per 1M input, output tokens
```

At `warn_pct` it posts one warning a day. At the limit it blocks new turns and stops tool calls in the running one. The total resets at local midnight.

**Lost turns** are saved when a turn starts and closed when it ends. A turn still open when the gateway dies shows up after the restart. Turns you stop with `/stop` don't. Only text is resent, not attachments.

## What it writes and stores

- **config.yaml:** `mcp_servers.<name>.enabled`, `skills.disabled`, `agent.disabled_toolsets` (the keys `hermes mcp`, `hermes skills config` and `hermes tools` write), and its own `plugins.entries.hermes-helm.settings`. Each change is logged with its old and new value. If Nix manages your config, it refuses to write.
- **`<HERMES_HOME>/plugin-data/hermes-helm/helm.db`:** your message text for 7 days (for lost turns), tokens and cost per model call, and the change log.
- **Network:** none.

## Develop

```bash
cd tests && python -m pytest          # unit tests with a fake plugin context
hermes plugins doctor . --ci          # load check against Hermes' registries
hermes plugins validate .             # the catalog's admission check
```

MIT licensed.
