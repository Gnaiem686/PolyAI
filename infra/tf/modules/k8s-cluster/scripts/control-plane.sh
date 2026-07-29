#!/bin/bash

set -e

hostnamectl set-hostname control-plane

apt-get update
apt-get install -y apt-transport-https ca-certificates curl gpg unzip

# Disable swap
swapoff -a
sed -i '/ swap / s/^/#/' /etc/fstab

# Load Kubernetes kernel modules
cat <<EOF > /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF

modprobe overlay
modprobe br_netfilter

# Configure networking required by Kubernetes
cat <<EOF > /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF

sysctl --system

# Add the Kubernetes and CRI-O package repositories
mkdir -p /etc/apt/keyrings

curl -fsSL \
  https://pkgs.k8s.io/core:/stable:/v1.36/deb/Release.key \
  | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg

echo \
  "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.36/deb/ /" \
  > /etc/apt/sources.list.d/kubernetes.list

curl -fsSL \
  https://download.opensuse.org/repositories/isv:/cri-o:/stable:/v1.36/deb/Release.key \
  | gpg --dearmor -o /etc/apt/keyrings/cri-o-apt-keyring.gpg

echo \
  "deb [signed-by=/etc/apt/keyrings/cri-o-apt-keyring.gpg] https://download.opensuse.org/repositories/isv:/cri-o:/stable:/v1.36/deb/ /" \
  > /etc/apt/sources.list.d/cri-o.list

# Install and start CRI-O and the Kubernetes tools
apt-get update
apt-get install -y cri-o kubelet kubeadm kubectl

# Prevent automatic Kubernetes version upgrades
apt-mark hold cri-o kubelet kubeadm kubectl

systemctl enable --now crio
systemctl enable kubelet

# Initialize the Kubernetes control plane
PRIVATE_IP=$(hostname -I | awk '{print $1}')

kubeadm init \
  --apiserver-advertise-address="$PRIVATE_IP" \
  --cri-socket="unix:///var/run/crio/crio.sock" \
  --pod-network-cidr="192.168.0.0/16"

# Configure kubectl for the ubuntu user
mkdir -p /home/ubuntu/.kube
cp /etc/kubernetes/admin.conf /home/ubuntu/.kube/config
chown -R ubuntu:ubuntu /home/ubuntu/.kube

# Install AWS CLI v2. Ubuntu 24.04 does not provide the awscli apt package.
curl -fsSL \
  "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" \
  -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp
/tmp/aws/install

# Save the worker join command

# The ASG may replace a worker long after the first boot. A non-expiring token
# keeps the SSM join command valid for replacement workers. In production, a
# short-lived token generated on demand would provide stronger security.
JOIN_COMMAND=$(kubeadm token create --ttl 0 --print-join-command)
JOIN_COMMAND="$JOIN_COMMAND --cri-socket unix:///var/run/crio/crio.sock"

# Save the command in AWS Systems Manager Parameter Store
aws ssm put-parameter \
  --region "${region}" \
  --name "/${name_prefix}/${environment}/kubeadm-join-command" \
  --type "SecureString" \
  --value "$JOIN_COMMAND" \
  --overwrite
