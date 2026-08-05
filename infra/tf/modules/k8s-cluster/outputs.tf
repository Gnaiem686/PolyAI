output "control_plane_public_ip" {
  description = "Public IP address of the Kubernetes control-plane instance"
  value       = aws_instance.control_plane.public_ip
}

output "control_plane_private_ip" {
  description = "Private IP address of the Kubernetes control-plane instance"
  value       = aws_instance.control_plane.private_ip
}

output "control_plane_instance_id" {
  description = "EC2 instance ID of the Kubernetes control plane"
  value       = aws_instance.control_plane.id
}

output "control_plane_security_group_id" {
  description = "Security group ID used by the Kubernetes control plane"
  value       = aws_security_group.control_plane.id
}

output "worker_autoscaling_group_name" {
  description = "Name of the worker Auto Scaling Group"
  value       = aws_autoscaling_group.worker.name
}

output "worker_security_group_id" {
  description = "Security group ID used by Kubernetes worker nodes"
  value       = aws_security_group.worker.id
}

output "worker_iam_role_name" {
  description = "IAM role used by Kubernetes worker nodes"
  value       = aws_iam_role.worker.name
}
