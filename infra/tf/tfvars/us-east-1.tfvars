region = "us-east-1"
ami_id = "ami-052355af2a014bd2c"

vpc_cidr = "10.0.0.0/16"

public_subnet_cidrs = [
  "10.0.1.0/24",
  "10.0.2.0/24"
]

ssh_key_name = "gnaiem-key"

worker_min_size         = 1
worker_max_size         = 3
worker_desired_capacity = 1
