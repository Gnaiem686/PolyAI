#!/bin/bash

set -e

# A new control-plane instance ID changes this rendered user data, which creates
# a new Launch Template version and makes the ASG replace existing workers.
# Control-plane generation: ${control_plane_instance_id}

hostnamectl set-hostname "worker-$(hostname)"

# Install packages required for the Kubernetes and CRI-O repositories
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

# Configure Kubernetes networking
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

# Install and start CRI-O and the worker Kubernetes tools
apt-get update
apt-get install -y cri-o kubelet kubeadm

apt-mark hold cri-o kubelet kubeadm
systemctl enable --now crio
systemctl enable kubelet

# Install AWS CLI v2. Ubuntu 24.04 does not provide the awscli apt package.
curl -fsSL \
  "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" \
  -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp
/tmp/aws/install

# Keep reading the command from SSM until this worker joins successfully.
# During control-plane replacement, Parameter Store can briefly contain the
# previous control-plane address. Re-reading avoids permanently failing on it.
while true; do
  JOIN_COMMAND=$(aws ssm get-parameter \
    --region "${region}" \
    --name "/${name_prefix}/${environment}/kubeadm-join-command" \
    --with-decryption \
    --query "Parameter.Value" \
    --output text 2>/dev/null) || true

  if [ -n "$JOIN_COMMAND" ] && bash -c "$JOIN_COMMAND"; then
    echo "Worker joined the Kubernetes cluster."
    break
  fi

  echo "Waiting for a valid kubeadm join command..."
  sleep 15
done
