# Slack app for the shared routine message

An incoming webhook can only post new messages. To have every cloud fill in one routine message
(`slack.shared_message` in the config), the jobs use a Slack bot token to find and edit it.

## Manifest

Copy this as it is. It sits outside the numbered steps so no line carries extra indentation, which would break the YAML.

```yaml
display_information:
  name: Anomaly Alerts
features:
  bot_user:
    display_name: Anomaly Alerts
    always_online: false
oauth_config:
  scopes:
    bot:
      - chat:write
      - channels:history
settings:
  org_deploy_enabled: false
  socket_mode_enabled: false
  token_rotation_enabled: false
```

`channels:history` is for public channels. For a private channel use `groups:history` instead.

## Create the app

1. Go to <https://api.slack.com/apps>, choose **Create New App**, then **From a manifest**, pick the workspace, and paste the manifest above.
2. **Install to Workspace**, then copy the **Bot User OAuth Token** (it starts with `xoxb-`) from **OAuth & Permissions**.
3. Add the bot to the channel: in the channel, type `/invite @Anomaly Alerts`. The bot can only read and edit its message in channels it is in.
4. Find the channel ID (channel details, at the bottom). It goes in `slack.shared_message.channel`.

Keep the app inside your own workspace. Slack limits `conversations.history` to one call a minute for apps distributed through its Marketplace, but not for an app built for your own workspace.

## Store the token

Store the token by hand, once per cloud, from your own terminal, so it never enters Terraform state or any other file. The commands are in each seed README:

- AWS: `terraform/aws/seed/README.md`, an SSM parameter `/anomaly-alerts/slack-bot-token`
- Azure: `terraform/azure/seed/README.md`, a Key Vault secret `slack-bot-token`
- GCP: `terraform/gcp/seed/README.md`, a Secret Manager secret `slack-bot-token` (created by the GCP seed)
