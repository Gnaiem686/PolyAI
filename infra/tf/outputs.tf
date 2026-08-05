output "control_plane_public_ip" {
  description = "Public IP address of the Kubernetes control plane"
  value       = module.k8s_cluster.control_plane_public_ip
}

output "control_plane_private_ip" {
  description = "Private IP address of the Kubernetes control plane"
  value       = module.k8s_cluster.control_plane_private_ip
}

output "control_plane_instance_id" {
  description = "EC2 instance ID of the Kubernetes control plane"
  value       = module.k8s_cluster.control_plane_instance_id
}

output "control_plane_security_group_id" {
  description = "Security group ID used by the Kubernetes control plane"
  value       = module.k8s_cluster.control_plane_security_group_id
}

output "worker_autoscaling_group_name" {
  description = "Name of the Kubernetes worker Auto Scaling Group"
  value       = module.k8s_cluster.worker_autoscaling_group_name
}

output "application_urls" {
  description = "Public HTTPS URLs exposed through the cluster ALB"
  value       = module.ingress.application_urls
}

output "load_balancer_dns_name" {
  description = "DNS name assigned to the public Application Load Balancer"
  value       = module.ingress.load_balancer_dns_name
}

output "alertmanager_sns_topic_arn" {
  description = "SNS topic used by Alertmanager"
  value       = aws_sns_topic.alerts.arn
}

output "ingress_http_node_port" {
  description = "Fixed HTTP NodePort used by the ALB target group"
  value       = var.ingress_http_node_port
}

output "ingress_https_node_port" {
  description = "Fixed HTTPS NodePort exposed by ingress-nginx"
  value       = var.ingress_https_node_port
}
