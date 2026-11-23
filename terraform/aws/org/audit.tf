# Audit events that matter every time, as CloudWatch metrics from the trail's log group. Each
# match adds 1 to a metric in the PlatformAudit namespace; the alert job reads them and alerts
# on any count above zero. Custom metrics are free up to 10 per account; this adds 7.

locals {
  # AWS services acting on their own (KMS keeping a multi-region key in sync, a service creating
  # its service-linked role) call from an *.amazonaws.com host, not an IP. They are not changes
  # anyone made, so the change metrics leave them out.
  not_a_service = "$.sourceIPAddress != \"*.amazonaws.com\""

  audit_filters = {
    # The root user doing anything, or a console sign-in without MFA.
    "RootOrNoMfaSignIn" = "{ ($.userIdentity.type = \"Root\" && $.userIdentity.invokedBy NOT EXISTS && $.eventType != \"AwsServiceEvent\") || ($.eventName = \"ConsoleLogin\" && $.additionalEventData.MFAUsed != \"Yes\" && $.userIdentity.type = \"IAMUser\") }"

    # Any change to IAM or to Organizations (policies, roles, users, SCPs). Terraform applies make
    # these too, so the alert is a prompt to confirm, not a verdict.
    "IamChanges" = "{ (($.eventSource = \"iam.amazonaws.com\") || ($.eventSource = \"organizations.amazonaws.com\")) && ($.readOnly IS FALSE) && ($.errorCode NOT EXISTS) && (${local.not_a_service}) }"

    # Long-lived credentials: the account has no IAM users, so any of these is new.
    "AccessKeyCreated" = "{ ($.eventName = \"CreateAccessKey\") || ($.eventName = \"CreateLoginProfile\") || ($.eventName = \"UpdateLoginProfile\") }"

    # The trail or this log group changed: logs could stop arriving.
    "LoggingChanged" = "{ ($.eventName = \"StopLogging\") || ($.eventName = \"DeleteTrail\") || ($.eventName = \"UpdateTrail\") || ($.eventName = \"PutEventSelectors\") || (($.eventName = \"DeleteLogGroup\" || $.eventName = \"DeleteMetricFilter\" || $.eventName = \"PutRetentionPolicy\") && $.requestParameters.logGroupName = \"${aws_cloudwatch_log_group.trail.name}\") }"

    # A security group opened to new traffic, or an S3 public access block removed.
    "MadePublic" = "{ (($.eventName = \"AuthorizeSecurityGroupIngress\") || ($.eventName = \"DeleteBucketPublicAccessBlock\") || ($.eventName = \"DeletePublicAccessBlock\")) && ($.errorCode NOT EXISTS) }"

    # Changes made outside the home region. Everything here runs in one region, so a write
    # anywhere else is new footprint, or someone else's.
    "OutsideHomeRegion" = "{ ($.awsRegion != \"${var.region}\") && ($.readOnly IS FALSE) && ($.eventType = \"AwsApiCall\") && (${local.not_a_service}) }"

    # A KMS key disabled or scheduled for deletion makes what it encrypted unreadable.
    "KmsKeyDisabled" = "{ ($.eventSource = \"kms.amazonaws.com\") && (($.eventName = \"DisableKey\") || ($.eventName = \"ScheduleKeyDeletion\")) }"
  }
}

resource "aws_cloudwatch_log_metric_filter" "audit" {
  for_each       = local.audit_filters
  name           = each.key
  log_group_name = aws_cloudwatch_log_group.trail.name
  pattern        = each.value

  metric_transformation {
    name          = each.key
    namespace     = var.metric_namespace
    value         = "1"
    default_value = "0"
    unit          = "Count"
  }
}
