# Operational notes

## Local synthetic demo

Start the API on loopback, with `.env.example` copied to a private `.env`. AI is disabled by default. The catalogue is synthetic, which independently disables backend source collectors. Do not remove that marker unless you have replaced the catalogue with validated, authorized real records.

The poller intentionally exits before making requests when the catalogue is synthetic. Acquisition scripts in `data/scripts/` remain explicit network tools for authorized research; they are not part of the automatic demo startup.

## External integrations

Telegram requires your own private bot token. An optional LLM requires explicit opt-in, a private provider key and a supported model identifier. Those integrations send data externally and may incur charges. Use invented requests and no medical documents or identifiers in demonstrations.

After assembling authorized real data, source collection still needs deliberate enablement, source availability checks, supervision, persistent storage, compatible source formats and a shared database path. The historical macOS launchd configuration and machine paths are not included.

## Before remote access

- Set `LAZIOFLOW_ENV=production` and a strong private `LAZIOFLOW_API_KEY` in backend and bot.
- Use HTTPS, perimeter access controls, request-size controls and suitable quotas/provider budgets.
- Inspect the JSON `status` from `/health`; HTTP 200 alone is not proof of source freshness.
- Keep databases, caches and logs outside version control; validate backups if storing observations.
- Configure a responsible operator, complete privacy notice and data/service retention policies.
- Obtain qualified review of safety paths before any real public healthcare use.

The built-in quotas are per process and reset on restart. Multiple workers require shared external enforcement. Session expiry and `/stop` do not delete messages from Telegram or data retained by an AI provider. The prototype is not a certified or production-hardened healthcare service.
