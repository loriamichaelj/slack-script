# Multi-Cloud Anomaly Alerts

## Overview

Watches metrics on AWS, Azure and GCP and posts a Slack alert when there is an anomaly. It runs on a schedule, makes one pass, and exits.

Each run reads the configured metrics from the cloud's own monitoring service and compares the newest points to earlier ones with a statistical detector. It alerts only when the change is large, lasts several points, and goes in a direction the metric cares about. An alert carries the baseline, the observed value, a console link and suggested next steps, and a cooldown stops repeats.

Scheduled routine reports run alongside the alerts: a heartbeat, a daily health digest of every metric, and a daily cost report per account.

With one job per cloud, each routine report arrives once per cloud. Set `slack.shared_message` in each cloud's config (see `config/config.example.yaml`) and the clouds fill in one Slack message instead: the first job posts it, the others add their section, and a cloud that has not reported shows as waiting. This needs a Slack bot token rather than the webhook, because a webhook cannot edit a message.
