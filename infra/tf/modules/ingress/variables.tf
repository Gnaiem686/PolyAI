variable "name_prefix" {
  description = "Prefix used for ingress AWS resource names"
  type        = string
}

variable "environment" {
  description = "Logical environment name for the shared cluster"
  type        = string
}

variable "vpc_id" {
  description = "ID of the Kubernetes VPC"
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnet IDs used by the internet-facing ALB"
  type        = list(string)
}

variable "worker_security_group_id" {
  description = "Security group attached to the Kubernetes worker nodes"
  type        = string
}

variable "worker_asg_name" {
  description = "Name of the worker Auto Scaling Group attached to the target group"
  type        = string
}

variable "hosted_zone_name" {
  description = "Existing public Route 53 hosted zone"
  type        = string
}

variable "domain_prefix" {
  description = "DNS label used beneath the shared hosted zone"
  type        = string
}

variable "http_node_port" {
  description = "Fixed ingress-nginx HTTP NodePort"
  type        = number
}
