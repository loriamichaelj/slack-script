# Multi-Cloud Anomaly Alerts

## Overview

Watches metrics on AWS, Azure and GCP and posts a Slack alert when there is an anomaly. It runs on a schedule, makes one pass, and exits, and the same image runs on Lambda, Cloud Run and Azure Container Apps.

Each run reads the configured metrics from the cloud's own monitoring service and compares the newest points to earlier ones with a statistical detector. It alerts only when the change is large, lasts several points, and goes in the direction the metric cares about. An alert carries the baseline, the observed value, a console link and suggested next steps, and a cooldown stops repeats.

Routine reports run alongside the alerts: a heartbeat at 00:00, 06:00, 12:00 and 18:00 New York time, a health digest at 09:00 and a cost report at 09:30. Every cloud fills in one shared Slack message per report, a few minutes apart, which needs a Slack bot token ([setup](examples/slack-app.md)); without it, each cloud posts its own message to the webhook.
