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
