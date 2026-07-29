data "aws_vpc" "cluster" {
  id = var.vpc_id
}

####################################
# Control Plane IAM Role
####################################

resource "aws_iam_role" "control_plane" {
  name = "${var.name_prefix}-${var.environment}-control-plane-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "ec2.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })
}

####################################
# Control Plane IAM Policies
####################################

resource "aws_iam_role_policy_attachment" "control_plane_eks_cluster_policy" {
  role       = aws_iam_role.control_plane.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_iam_role_policy_attachment" "control_plane_ebs_csi_policy" {
  role       = aws_iam_role.control_plane.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

resource "aws_iam_role_policy_attachment" "control_plane_ecr_read_only" {
  role       = aws_iam_role.control_plane.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

####################################
# Control Plane Instance Profile
####################################

resource "aws_iam_instance_profile" "control_plane" {
  name = "${var.name_prefix}-${var.environment}-control-plane-profile"
  role = aws_iam_role.control_plane.name
}

####################################
# Control Plane Security Group
####################################

resource "aws_security_group" "control_plane" {
  name        = "${var.name_prefix}-${var.environment}-control-plane-sg"
  description = "Security group for the Kubernetes control plane"
  vpc_id      = var.vpc_id

  tags = {
    Name        = "${var.name_prefix}-${var.environment}-control-plane-sg"
    Environment = var.environment
    Terraform   = "true"
  }
}

####################################
# Control Plane Security Group Rules
####################################

resource "aws_vpc_security_group_ingress_rule" "control_plane_ssh" {
  security_group_id = aws_security_group.control_plane.id

  description = "Allow SSH from the Terraform runner public IP"
  from_port   = 22
  to_port     = 22
  ip_protocol = "tcp"
  cidr_ipv4   = var.ssh_allowed_cidr
}

resource "aws_vpc_security_group_ingress_rule" "control_plane_intra_vpc" {
  security_group_id = aws_security_group.control_plane.id

  description = "Allow all traffic from inside the VPC"
  ip_protocol = "-1"
  cidr_ipv4   = data.aws_vpc.cluster.cidr_block
}

resource "aws_vpc_security_group_egress_rule" "control_plane_all_outbound" {
  security_group_id = aws_security_group.control_plane.id

  description = "Allow all outbound traffic"
  ip_protocol = "-1"
  cidr_ipv4   = "0.0.0.0/0"
}

####################################
# Control Plane EC2 Instance
####################################

resource "aws_instance" "control_plane" {
  ami           = var.ami_id
  instance_type = var.control_plane_instance_type
  subnet_id     = var.public_subnet_ids[0]
  key_name      = var.ssh_key_name

  vpc_security_group_ids = [
    aws_security_group.control_plane.id
  ]

  iam_instance_profile = aws_iam_instance_profile.control_plane.name

  associate_public_ip_address = true

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = templatefile("${path.module}/scripts/control-plane.sh", {
    region      = var.region
    name_prefix = var.name_prefix
    environment = var.environment
  })

  user_data_replace_on_change = true

  tags = {
    Name        = "${var.name_prefix}-${var.environment}-control-plane"
    Environment = var.environment
    Terraform   = "true"
  }

  depends_on = [
    aws_iam_role_policy.control_plane_join_command,
    aws_iam_role_policy_attachment.control_plane_eks_cluster_policy,
    aws_iam_role_policy_attachment.control_plane_ebs_csi_policy,
    aws_iam_role_policy_attachment.control_plane_ecr_read_only
  ]
}

####################################
# Control Plane Join Command Policy
####################################

resource "aws_iam_role_policy" "control_plane_join_command" {
  name = "${var.name_prefix}-${var.environment}-control-plane-join-command"
  role = aws_iam_role.control_plane.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "ssm:PutParameter"
        ]

        Resource = "arn:aws:ssm:${var.region}:*:parameter/${var.name_prefix}/${var.environment}/kubeadm-join-command"
      }
    ]
  })
}

####################################
# Worker IAM Role
####################################

resource "aws_iam_role" "worker" {
  name = "${var.name_prefix}-${var.environment}-worker-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "ec2.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })
}

####################################
# Worker IAM Policies
####################################

resource "aws_iam_role_policy_attachment" "worker_ecr_read_only" {
  role       = aws_iam_role.worker.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_role_policy" "worker_join_command" {
  name = "${var.name_prefix}-${var.environment}-worker-join-command"
  role = aws_iam_role.worker.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "ssm:GetParameter"
        ]

        Resource = "arn:aws:ssm:${var.region}:*:parameter/${var.name_prefix}/${var.environment}/kubeadm-join-command"
      }
    ]
  })
}

####################################
# Worker Instance Profile
####################################

resource "aws_iam_instance_profile" "worker" {
  name = "${var.name_prefix}-${var.environment}-worker-profile"
  role = aws_iam_role.worker.name
}

####################################
# Worker Security Group
####################################

resource "aws_security_group" "worker" {
  name        = "${var.name_prefix}-${var.environment}-worker-sg"
  description = "Security group for Kubernetes worker nodes"
  vpc_id      = var.vpc_id

  tags = {
    Name        = "${var.name_prefix}-${var.environment}-worker-sg"
    Environment = var.environment
    Terraform   = "true"
  }
}

####################################
# Worker Security Group Rules
####################################

resource "aws_vpc_security_group_ingress_rule" "worker_ssh" {
  security_group_id = aws_security_group.worker.id

  description = "Allow SSH from the Terraform runner public IP"
  from_port   = 22
  to_port     = 22
  ip_protocol = "tcp"
  cidr_ipv4   = var.ssh_allowed_cidr
}

resource "aws_vpc_security_group_ingress_rule" "worker_intra_vpc" {
  security_group_id = aws_security_group.worker.id

  description = "Allow all traffic from inside the VPC"
  ip_protocol = "-1"
  cidr_ipv4   = data.aws_vpc.cluster.cidr_block
}

resource "aws_vpc_security_group_egress_rule" "worker_all_outbound" {
  security_group_id = aws_security_group.worker.id

  description = "Allow all outbound traffic"
  ip_protocol = "-1"
  cidr_ipv4   = "0.0.0.0/0"
}

####################################
# Worker Launch Template
####################################

resource "aws_launch_template" "worker" {
  name_prefix = "${var.name_prefix}-${var.environment}-worker-"

  image_id      = var.ami_id
  instance_type = var.worker_instance_type
  key_name      = var.ssh_key_name

  iam_instance_profile {
    name = aws_iam_instance_profile.worker.name
  }

  network_interfaces {
    associate_public_ip_address = true
    security_groups = [
      aws_security_group.worker.id
    ]
  }

  user_data = base64encode(
    templatefile("${path.module}/scripts/worker.sh", {
      region                    = var.region
      name_prefix               = var.name_prefix
      environment               = var.environment
      control_plane_instance_id = aws_instance.control_plane.id
    })
  )

  tag_specifications {
    resource_type = "instance"

    tags = {
      Name        = "${var.name_prefix}-${var.environment}-worker"
      Environment = var.environment
      Terraform   = "true"
    }
  }

  tags = {
    Name        = "${var.name_prefix}-${var.environment}-worker-template"
    Environment = var.environment
    Terraform   = "true"
  }
}

####################################
# Worker Auto Scaling Group
####################################

resource "aws_autoscaling_group" "worker" {
  name = "${var.name_prefix}-${var.environment}-worker-asg"

  min_size         = var.worker_min_size
  max_size         = var.worker_max_size
  desired_capacity = var.worker_desired_capacity

  vpc_zone_identifier = var.public_subnet_ids

  health_check_type         = "EC2"
  health_check_grace_period = 300

  launch_template {
    id      = aws_launch_template.worker.id
    version = aws_launch_template.worker.latest_version
  }

  instance_refresh {
    strategy = "Rolling"

    preferences {
      instance_warmup        = 300
      min_healthy_percentage = 0
    }
  }

  lifecycle {
    precondition {
      condition     = var.worker_min_size <= var.worker_desired_capacity
      error_message = "worker_min_size cannot be greater than worker_desired_capacity."
    }

    precondition {
      condition     = var.worker_desired_capacity <= var.worker_max_size
      error_message = "worker_desired_capacity cannot be greater than worker_max_size."
    }
  }

  tag {
    key                 = "Name"
    value               = "${var.name_prefix}-${var.environment}-worker"
    propagate_at_launch = true
  }

  tag {
    key                 = "Environment"
    value               = var.environment
    propagate_at_launch = true
  }

  tag {
    key                 = "Terraform"
    value               = "true"
    propagate_at_launch = true
  }

  depends_on = [
    aws_iam_role_policy.worker_join_command,
    aws_iam_role_policy_attachment.worker_ecr_read_only
  ]
}
