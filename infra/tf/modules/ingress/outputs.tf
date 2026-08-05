output "load_balancer_dns_name" {
  description = "DNS name assigned to the public Application Load Balancer"
  value       = aws_lb.cluster.dns_name
}

output "application_urls" {
  description = "Public HTTPS URLs exposed through the ALB"
  value = {
    for hostname in local.hostnames : hostname => "https://${hostname}"
  }
}

output "certificate_arn" {
  description = "Validated ACM wildcard certificate ARN"
  value       = aws_acm_certificate_validation.cluster.certificate_arn
}
