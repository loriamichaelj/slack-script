# Multi-Cloud Anomaly Alerts

## Overview

Watches AWS, Azure and GCP and posts to Slack when something needs attention. It reads metrics and audit logs from each cloud's own monitoring, so it covers both how the services behave and what changes on the platform.

It runs on a schedule, checks each signal against what is normal or against a fixed limit, and alerts with the numbers and suggested next steps. Alerts follow up in a thread and close when the problem clears.

Scheduled reports sum up health and cost every day. Everything is deployed with Terraform and GitHub Actions, and kept within each cloud's free tiers as far as possible.
