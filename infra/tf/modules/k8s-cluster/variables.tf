variable "name_prefix" {
  description = "Prefix used for Kubernetes cluster resource names"
  type        = string
}

variable "environment" {
  description = "Logical environment name for the shared cluster"
  type        = string
}

variable "region" {
  description = "AWS region where the cluster is deployed"
  type        = string
}

variable "image_bucket_name" {
  description = "Existing S3 bucket used by workloads for image input and output objects"
  type        = string
}

variable "vpc_id" {
  description = "ID of the VPC used by the Kubernetes cluster"
  type        = string
}

variable "public_subnet_ids" {
  description = "IDs of the public subnets used by control-plane and worker nodes"
  type        = list(string)
}

variable "control_plane_instance_type" {
  description = "EC2 instance type for the Kubernetes control plane"
  type        = string
}

variable "worker_instance_type" {
  description = "EC2 instance type for Kubernetes worker nodes"
  type        = string
}

variable "worker_min_size" {
  description = "Minimum number of worker nodes in the Auto Scaling Group"
  type        = number
}

variable "worker_max_size" {
  description = "Maximum number of worker nodes in the Auto Scaling Group"
  type        = number
}

variable "worker_desired_capacity" {
  description = "Desired number of worker nodes in the Auto Scaling Group"
  type        = number
}

variable "ssh_key_name" {
  description = "Existing EC2 key pair name used for SSH access"
  type        = string
}

variable "ssh_allowed_cidr" {
  description = "CIDR allowed to access the control plane over SSH"
  type        = string
}

variable "ami_id" {
  description = "AMI ID used by the control plane and worker nodes"
  type        = string
}

variable "sns_topic_arn" {
  description = "SNS topic that Alertmanager running on worker nodes may publish to"
  type        = string
}
