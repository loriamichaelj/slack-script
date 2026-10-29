# Run from cron

The simplest setup: a laptop or VM with read-only cloud credentials.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[all]"      # or just .[aws], .[azure], .[gcp]
cp config/config.example.yaml config/config.yaml
cp .env.example .env                   # then set SLACK_WEBHOOK_URL
```

## Try it first

```bash
.venv/bin/anomaly-alerts --config config/config.yaml --dry-run --verbose
```

`--dry-run` prints the exact Slack payloads and does not post or write state.

## Schedule

Every 5 minutes, matching the default `period`:

```cron
*/5 * * * * cd /opt/slack-script && .venv/bin/anomaly-alerts --config config/config.yaml >> /var/log/anomaly-alerts.log 2>&1
```

- The job reads `.env` from the working directory, so `cd` into the project first.
- The state file (`.state/alerts.json` by default) is relative to the working directory. Keep it on a disk that survives reboots so the cooldown holds.
- Exit codes: `0` ok, `1` a fetch or Slack post failed, `2` bad config or setup.

## Routine reports

Add these next to the anomaly job so a quiet channel still shows the tool is alive:

```cron
0 */6 * * * cd /opt/slack-script && .venv/bin/anomaly-alerts routine --config config/config.yaml >> /var/log/anomaly-alerts.log 2>&1
0 9 * * *   cd /opt/slack-script && .venv/bin/anomaly-alerts routine --kind digest --config config/config.yaml >> /var/log/anomaly-alerts.log 2>&1
30 9 * * *  cd /opt/slack-script && .venv/bin/anomaly-alerts routine --kind cost --config config/config.yaml >> /var/log/anomaly-alerts.log 2>&1
```

- Heartbeat every 6 hours, digest and cost once a day. Cron uses the machine's local time zone.
- Set `SLACK_ROUTINE_WEBHOOK_URL` in `.env` to send them to their own channel.
- The cost job needs a `cost` section in the config and billing read access (see the README).

