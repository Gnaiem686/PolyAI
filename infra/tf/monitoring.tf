resource "aws_sns_topic" "alerts" {
  name = "${var.name_prefix}-${local.environment}-alerts"

  tags = {
    Name        = "${var.name_prefix}-${local.environment}-alerts"
    Project     = "PolyAI"
    Environment = local.environment
    Terraform   = "true"
  }
}

resource "aws_sns_topic_subscription" "email" {
  count = var.alert_email == null ? 0 : 1

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
