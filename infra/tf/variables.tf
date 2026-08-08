variable "region" {
  description = "AWS region where the Kubernetes cluster will be provisioned"
  type        = string
}

variable "image_bucket_name" {
  description = "Existing S3 bucket used by PolyAI services for original and processed images"
  type        = string

  validation {
    condition     = length(trimspace(var.image_bucket_name)) > 0
    error_message = "image_bucket_name must not be empty."
  }
}

variable "ami_id" {
  description = "Pinned Ubuntu AMI ID for the selected AWS region"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the Kubernetes VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for the two public subnets"
  type        = list(string)

  validation {
    condition     = length(var.public_subnet_cidrs) == 2
    error_message = "Exactly two public subnet CIDR blocks must be provided."
  }
}

variable "control_plane_instance_type" {
  description = "EC2 instance type for the Kubernetes control plane"
  type        = string
  default     = "t3.medium"
}

variable "worker_instance_type" {
  description = "EC2 instance type for Kubernetes worker nodes"
  type        = string
  default     = "t3.medium"
}

variable "worker_min_size" {
  description = "Minimum number of worker nodes"
  type        = number
  default     = 1

  validation {
    condition     = var.worker_min_size >= 0
    error_message = "worker_min_size must be zero or greater."
  }
}

variable "worker_max_size" {
  description = "Maximum number of worker nodes"
  type        = number
  default     = 3

  validation {
    condition     = var.worker_max_size >= 1 && var.worker_max_size <= 3
    error_message = "worker_max_size must be between 1 and 3."
  }
}

variable "worker_desired_capacity" {
  description = "Desired number of worker nodes"
  type        = number
  default     = 1

  validation {
    condition     = var.worker_desired_capacity >= 0
    error_message = "worker_desired_capacity must be zero or greater."
  }
}

variable "ssh_key_name" {
  description = "Existing AWS EC2 key pair name used for SSH access"
  type        = string
}

variable "ssh_allowed_cidr" {
  description = "Administrator public IPv4 /32 CIDR allowed to SSH to the cluster nodes; defaults to the Terraform runner IP for local use"
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.ssh_allowed_cidr == null ? true : (
      can(cidrnetmask(var.ssh_allowed_cidr))
      && can(regex("/32$", var.ssh_allowed_cidr))
    )
    error_message = "ssh_allowed_cidr must be a valid IPv4 /32 CIDR, for example 203.0.113.10/32."
  }
}

variable "name_prefix" {
  description = "Prefix used for AWS resource names"
  type        = string
  default     = "gnaiem-tf"
}

variable "hosted_zone_name" {
  description = "Existing public Route 53 hosted zone used for cluster DNS records"
  type        = string
  default     = "fursa.click"
}

variable "domain_prefix" {
  description = "Student-specific DNS label created beneath the shared hosted zone"
  type        = string
  default     = "gnaiem"
}

variable "ingress_http_node_port" {
  description = "Fixed ingress-nginx HTTP NodePort targeted by the ALB"
  type        = number
  default     = 30080

  validation {
    condition     = var.ingress_http_node_port >= 30000 && var.ingress_http_node_port <= 32767
    error_message = "ingress_http_node_port must be in the Kubernetes NodePort range 30000-32767."
  }
}

variable "ingress_https_node_port" {
  description = "Fixed ingress-nginx HTTPS NodePort"
  type        = number
  default     = 30443

  validation {
    condition     = var.ingress_https_node_port >= 30000 && var.ingress_https_node_port <= 32767
    error_message = "ingress_https_node_port must be in the Kubernetes NodePort range 30000-32767."
  }
}

variable "alert_email" {
  description = "Email endpoint subscribed to monitoring alerts; confirmation is required after apply"
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.alert_email == null ? true : can(
      regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email)
    )
    error_message = "alert_email must be a valid email address."
  }
}
