data "aws_route53_zone" "shared" {
  name         = var.hosted_zone_name
  private_zone = false
}

locals {
  base_domain = "${var.domain_prefix}.${trimsuffix(var.hosted_zone_name, ".")}"

  hostnames = toset([
    "frontend-dev.${local.base_domain}",
    "agent-dev.${local.base_domain}",
    "frontend-prod.${local.base_domain}",
    "agent-prod.${local.base_domain}",
    "grafana.${local.base_domain}",
    "prometheus.${local.base_domain}",
    "argocd.${local.base_domain}"
  ])

  common_tags = {
    Project     = "PolyAI"
    Environment = var.environment
    Terraform   = "true"
  }
}

resource "aws_acm_certificate" "cluster" {
  domain_name       = "*.${local.base_domain}"
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-${var.environment}-wildcard"
  })
}

resource "aws_route53_record" "certificate_validation" {
  for_each = {
    for option in aws_acm_certificate.cluster.domain_validation_options :
    option.domain_name => {
      name   = option.resource_record_name
      record = option.resource_record_value
      type   = option.resource_record_type
    }
  }

  allow_overwrite = true
  zone_id         = data.aws_route53_zone.shared.zone_id
  name            = each.value.name
  type            = each.value.type
  ttl             = 60
  records         = [each.value.record]
}

resource "aws_acm_certificate_validation" "cluster" {
  certificate_arn = aws_acm_certificate.cluster.arn
  validation_record_fqdns = [
    for record in aws_route53_record.certificate_validation : record.fqdn
  ]
}

resource "aws_security_group" "alb" {
  name        = "${var.name_prefix}-${var.environment}-alb-sg"
  description = "Allow public HTTPS traffic to the PolyAI ALB"
  vpc_id      = var.vpc_id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-${var.environment}-alb-sg"
  })
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.alb.id
  description       = "Allow HTTPS from the internet"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "alb_all_outbound" {
  security_group_id = aws_security_group.alb.id
  description       = "Allow outbound traffic to worker nodes"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "worker_from_alb" {
  security_group_id            = var.worker_security_group_id
  referenced_security_group_id = aws_security_group.alb.id
  description                  = "Allow ALB traffic to ingress-nginx HTTP NodePort"
  from_port                    = var.http_node_port
  to_port                      = var.http_node_port
  ip_protocol                  = "tcp"
}

resource "aws_lb" "cluster" {
  name               = substr("${var.name_prefix}-${var.environment}-alb", 0, 32)
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids

  drop_invalid_header_fields = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-${var.environment}-alb"
  })
}

resource "aws_lb_target_group" "ingress" {
  name        = substr("${var.name_prefix}-${var.environment}-ingress", 0, 32)
  port        = var.http_node_port
  protocol    = "HTTP"
  target_type = "instance"
  vpc_id      = var.vpc_id

  deregistration_delay = 30

  health_check {
    enabled  = true
    path     = "/healthz"
    port     = "traffic-port"
    protocol = "HTTP"
    # ingress-nginx returns 404 for an unknown Host header. Receiving that
    # response proves that the NodePort and controller are reachable.
    matcher             = "200-499"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-${var.environment}-ingress"
  })
}

resource "aws_autoscaling_attachment" "worker_target_group" {
  autoscaling_group_name = var.worker_asg_name
  lb_target_group_arn    = aws_lb_target_group.ingress.arn
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.cluster.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.cluster.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ingress.arn
  }

  tags = local.common_tags
}

resource "aws_route53_record" "applications" {
  for_each = local.hostnames

  zone_id = data.aws_route53_zone.shared.zone_id
  name    = each.value
  type    = "A"

  alias {
    name                   = aws_lb.cluster.dns_name
    zone_id                = aws_lb.cluster.zone_id
    evaluate_target_health = true
  }
}
