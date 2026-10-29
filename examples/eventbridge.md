# Run on AWS with EventBridge Scheduler

Package the tool as a container and run it as a scheduled ECS Fargate task. Lambda also works, but the cooldown state needs somewhere persistent (see below).

## Image

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir ".[aws]"
ENTRYPOINT ["anomaly-alerts", "--config", "config/config.yaml"]
```

## Schedule

```bash
aws scheduler create-schedule \
  --name anomaly-alerts \
  --schedule-expression "rate(5 minutes)" \
  --flexible-time-window Mode=OFF \
  --target '{
    "Arn": "arn:aws:ecs:us-east-1:123456789012:cluster/ops",
    "RoleArn": "arn:aws:iam::123456789012:role/anomaly-alerts-scheduler",
    "EcsParameters": {
      "TaskDefinitionArn": "arn:aws:ecs:us-east-1:123456789012:task-definition/anomaly-alerts",
      "LaunchType": "FARGATE",
      "NetworkConfiguration": {"awsvpcConfiguration": {"Subnets": ["subnet-aaaa"], "AssignPublicIp": "ENABLED"}}
    }
  }'
```

## Permissions and secrets

- Task role: `cloudwatch:GetMetricData`, plus `ce:GetCostAndUsage` if you run the cost report.
- Inject `SLACK_WEBHOOK_URL` into the task definition from Secrets Manager or SSM Parameter Store (`secrets` block), not as a plain environment value.
- To watch Azure or GCP from AWS, add workload identity federation or service-account credentials and install the matching extra.

## State

A Fargate task starts with an empty disk, so the cooldown resets every run and a lasting anomaly re-alerts every 5 minutes. Point `state.path` in the config at an EFS mount to keep it:

```yaml
state:
  path: /mnt/state/alerts.json
```

## Routine reports

Reuse the same task definition and pass the routine arguments as a container override. One schedule per report:

```bash
aws scheduler create-schedule \
  --name anomaly-alerts-digest \
  --schedule-expression "cron(0 9 * * ? *)" \
  --schedule-expression-timezone UTC \
  --flexible-time-window Mode=OFF \
  --target '{
    "Arn": "arn:aws:ecs:us-east-1:123456789012:cluster/ops",
    "RoleArn": "arn:aws:iam::123456789012:role/anomaly-alerts-scheduler",
    "EcsParameters": {
      "TaskDefinitionArn": "arn:aws:ecs:us-east-1:123456789012:task-definition/anomaly-alerts",
      "LaunchType": "FARGATE",
      "NetworkConfiguration": {"awsvpcConfiguration": {"Subnets": ["subnet-aaaa"], "AssignPublicIp": "ENABLED"}}
    },
    "Input": "{\"containerOverrides\": [{\"name\": \"anomaly-alerts\", \"command\": [\"routine\", \"--kind\", \"digest\"]}]}"
  }'
```

The override is appended to the image's `ENTRYPOINT`, so the task runs `anomaly-alerts --config config/config.yaml routine --kind digest`. Repeat with `heartbeat` on `rate(6 hours)` and `cost` on `cron(30 9 * * ? *)`. Inject `SLACK_ROUTINE_WEBHOOK_URL` the same way as the main webhook.

