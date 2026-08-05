terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.28"
    }

    http = {
      source  = "hashicorp/http"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.region
}

data "http" "current_public_ip" {
  url = "https://checkip.amazonaws.com"
}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  ssh_allowed_cidr = var.ssh_allowed_cidr != null ? var.ssh_allowed_cidr : "${trimspace(data.http.current_public_ip.response_body)}/32"
  environment      = terraform.workspace == "default" ? "shared" : terraform.workspace

  selected_availability_zones = slice(
    data.aws_availability_zones.available.names,
    0,
    2
  )
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "6.6.1"

  name = "${var.name_prefix}-${local.environment}-vpc"
  cidr = var.vpc_cidr

  azs            = local.selected_availability_zones
  public_subnets = var.public_subnet_cidrs

  enable_nat_gateway = false
  enable_vpn_gateway = false

  map_public_ip_on_launch = true

  tags = {
    Name        = "${var.name_prefix}-${local.environment}-vpc"
    Project     = "PolyAI"
    Environment = local.environment
    Terraform   = "true"
  }

  public_subnet_tags = {
    Name = "${var.name_prefix}-${local.environment}-public"
    Type = "public"
  }
}

module "k8s_cluster" {
  source = "./modules/k8s-cluster"

  name_prefix = var.name_prefix
  environment = local.environment
  region      = var.region

  vpc_id            = module.vpc.vpc_id
  public_subnet_ids = module.vpc.public_subnets

  control_plane_instance_type = var.control_plane_instance_type
  worker_instance_type        = var.worker_instance_type

  worker_min_size         = var.worker_min_size
  worker_max_size         = var.worker_max_size
  worker_desired_capacity = var.worker_desired_capacity

  ssh_key_name     = var.ssh_key_name
  ssh_allowed_cidr = local.ssh_allowed_cidr
  ami_id           = var.ami_id

  sns_topic_arn = aws_sns_topic.alerts.arn
}

module "ingress" {
  source = "./modules/ingress"

  name_prefix = var.name_prefix
  environment = local.environment

  vpc_id            = module.vpc.vpc_id
  public_subnet_ids = module.vpc.public_subnets

  worker_security_group_id = module.k8s_cluster.worker_security_group_id
  worker_asg_name          = module.k8s_cluster.worker_autoscaling_group_name

  hosted_zone_name = var.hosted_zone_name
  domain_prefix    = var.domain_prefix
  http_node_port   = var.ingress_http_node_port
}
