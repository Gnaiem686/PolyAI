#!/bin/bash

set -euo pipefail

CALICO_VERSION="v3.32.1"
ARGOCD_APP_DIR="${1:-/tmp/polyai-bootstrap/argocd}"

export KUBECONFIG="/etc/kubernetes/admin.conf"

echo "Installing Calico ${CALICO_VERSION}..."

kubectl apply \
  --server-side \
  --force-conflicts \
  -f "https://raw.githubusercontent.com/projectcalico/calico/${CALICO_VERSION}/manifests/v1_crd_projectcalico_org.yaml"

kubectl apply \
  --server-side \
  --force-conflicts \
  -f "https://raw.githubusercontent.com/projectcalico/calico/${CALICO_VERSION}/manifests/tigera-operator.yaml"

kubectl wait \
  --namespace tigera-operator \
  --for=condition=Available \
  deployment/tigera-operator \
  --timeout=10m

# AWS may place the control plane and workers in the same subnet. Always use
# VXLAN so cross-node pod traffic is encapsulated instead of being rejected by
# EC2 source/destination checks.
curl --fail --silent --show-error --location \
  "https://raw.githubusercontent.com/projectcalico/calico/${CALICO_VERSION}/manifests/custom-resources.yaml" \
  | sed 's/encapsulation: VXLANCrossSubnet/encapsulation: VXLAN/' \
  | kubectl apply -f -

kubectl wait \
  --for=condition=Ready \
  node/control-plane \
  --timeout=15m

# ASG replacements terminate EC2 instances without deleting their Kubernetes
# Node objects. Ignore stale NotReady objects and require at least one current
# worker to become Ready.
READY_WORKER=""

for attempt in $(seq 1 90); do
  READY_WORKER=$(
    kubectl get nodes \
      --selector='!node-role.kubernetes.io/control-plane' \
      --output=jsonpath='{range .items[*]}{.metadata.name}{" "}{range .status.conditions[?(@.type=="Ready")]}{.status}{end}{"\n"}{end}' \
      | awk '$2 == "True" { print $1; exit }'
  )

  if [ -n "$READY_WORKER" ]; then
    echo "Worker $READY_WORKER is Ready."
    break
  fi

  if [ "$attempt" -eq 90 ]; then
    echo "Timed out waiting for a Ready worker."
    exit 1
  fi

  sleep 10
done

echo "Installing ArgoCD..."

kubectl create namespace argocd \
  --dry-run=client \
  --output=yaml \
  | kubectl apply -f -

kubectl apply \
  --namespace argocd \
  --server-side \
  --force-conflicts \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml"

kubectl wait \
  --namespace argocd \
  --for=condition=Available \
  deployment \
  --all \
  --timeout=10m

kubectl rollout status \
  --namespace argocd \
  statefulset/argocd-application-controller \
  --timeout=10m

echo "Creating application namespaces..."

for namespace in dev prod; do
  kubectl create namespace "$namespace" \
    --dry-run=client \
    --output=yaml \
    | kubectl apply -f -
done

echo "Applying ArgoCD Applications..."
kubectl apply -f "$ARGOCD_APP_DIR"

echo "Cluster bootstrap completed."
kubectl get nodes
kubectl get applications --namespace argocd
