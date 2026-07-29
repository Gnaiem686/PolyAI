variable "region" {
  description = "AWS region where the Kubernetes cluster will be provisioned"
  type        = string
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

variable "name_prefix" {
  description = "Prefix used for AWS resource names"
  type        = string
  default     = "gnaiem-tf"
}
