# Multi-Cloud Anomaly Alerts

## Overview

Watches the whole platform on AWS, Azure and GCP and posts to Slack when something needs attention. It reads metrics and audit logs from each cloud's own monitoring service: IAM and policy changes, new keys, logging changes, anything made public, new projects or regions, and deleted keys from CloudTrail, the GCP org log sink and the Azure Activity Log, plus site uptime, job failures and the app's own health. It runs on a schedule, makes one pass and exits, and the same image runs on Lambda, Cloud Run and Azure Container Apps.

Each metric is tested with a statistical detector, which alerts on a large change that lasts and goes the way the metric cares about, or with a fixed limit, which alerts on any audit event. An alert shows the value, what is normal, the change in plain words, a console link and next steps. With the Slack bot token ([setup](examples/slack-app.md)) each alert is a thread: reminders go in it, it turns green when the metric recovers, and alerts that fire together arrive as one group.

Routine reports run alongside the alerts: a heartbeat at 00:00, 06:00, 12:00 and 18:00 New York time, a health digest at 09:00 and a cost report for every billing account at 09:30, each one Slack message that every cloud fills in. To keep the bill low, audit metrics are read once per 30 minutes, secrets live in free stores, and GitHub Actions plans and applies the Terraform (only the GCP org and Azure seed roots are applied by hand).
