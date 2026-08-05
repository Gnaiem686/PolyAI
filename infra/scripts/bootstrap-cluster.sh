#!/bin/bash

set -euo pipefail

CALICO_VERSION="v3.32.1"
ARGOCD_VERSION="v3.4.2"
HELM_VERSION="v3.20.2"
INGRESS_NGINX_CHART_VERSION="4.14.3"
EBS_CSI_CHART_VERSION="2.62.0"
KUBE_PROMETHEUS_STACK_CHART_VERSION="86.0.0"
ARGOCD_APP_DIR="${1:-/tmp/polyai-bootstrap/argocd}"
INGRESS_MANIFEST_DIR="${2:-/tmp/polyai-bootstrap/k8s/ingress}"
STORAGE_MANIFEST_DIR="${3:-/tmp/polyai-bootstrap/k8s/storage}"
MONITORING_MANIFEST_DIR="${4:-/tmp/polyai-bootstrap/k8s/monitoring}"
SNS_TOPIC_ARN="${5:?SNS topic ARN is required}"
AWS_REGION="${6:?AWS region is required}"
ADMIN_SSH_CIDR="${7:?Administrator CIDR is required}"
INGRESS_HTTP_NODE_PORT="${8:?Ingress HTTP NodePort is required}"
INGRESS_HTTPS_NODE_PORT="${9:?Ingress HTTPS NodePort is required}"

export KUBECONFIG="/etc/kubernetes/admin.conf"

TEMP_FILES=()

cleanup_temp_files() {
  local file

  for file in "${TEMP_FILES[@]}"; do
    rm -f "$file"
  done
}

trap cleanup_temp_files EXIT

install_helm() {
  if command -v helm >/dev/null 2>&1; then
    return
  fi

  local archive="helm-${HELM_VERSION}-linux-amd64.tar.gz"
  local download_url="https://get.helm.sh/${archive}"
  local temp_dir

  temp_dir=$(mktemp -d)
  trap 'rm -rf "$temp_dir"' RETURN

  curl --fail --silent --show-error --location \
    --output "${temp_dir}/${archive}" \
    "$download_url"
  curl --fail --silent --show-error --location \
    --output "${temp_dir}/${archive}.sha256sum" \
    "${download_url}.sha256sum"

  (
    cd "$temp_dir"
    sha256sum --check "${archive}.sha256sum"
    tar --extract --gzip --file "$archive"
  )

  install --mode=0755 "${temp_dir}/linux-amd64/helm" /usr/local/bin/helm
}

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

echo "Installing Helm ${HELM_VERSION}..."
install_helm

echo "Installing ingress-nginx ${INGRESS_NGINX_CHART_VERSION}..."

helm repo add ingress-nginx \
  https://kubernetes.github.io/ingress-nginx \
  --force-update

RENDERED_INGRESS_VALUES=$(mktemp)
TEMP_FILES+=("$RENDERED_INGRESS_VALUES")

sed \
  -e "s|__HTTP_NODE_PORT__|${INGRESS_HTTP_NODE_PORT}|g" \
  -e "s|__HTTPS_NODE_PORT__|${INGRESS_HTTPS_NODE_PORT}|g" \
  "${INGRESS_MANIFEST_DIR}/values.yaml" \
  > "$RENDERED_INGRESS_VALUES"

helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --version "$INGRESS_NGINX_CHART_VERSION" \
  --values "$RENDERED_INGRESS_VALUES" \
  --wait \
  --timeout 10m

echo "Installing AWS EBS CSI Driver ${EBS_CSI_CHART_VERSION}..."

helm repo add aws-ebs-csi-driver \
  https://kubernetes-sigs.github.io/aws-ebs-csi-driver \
  --force-update

helm upgrade --install aws-ebs-csi-driver \
  aws-ebs-csi-driver/aws-ebs-csi-driver \
  --namespace kube-system \
  --version "$EBS_CSI_CHART_VERSION" \
  --values "${STORAGE_MANIFEST_DIR}/aws-ebs-csi-driver-values.yaml" \
  --wait \
  --timeout 10m

kubectl apply -f "${STORAGE_MANIFEST_DIR}/ebs-storageclass.yaml"

echo "Installing kube-prometheus-stack ${KUBE_PROMETHEUS_STACK_CHART_VERSION}..."

helm repo add prometheus-community \
  https://prometheus-community.github.io/helm-charts \
  --force-update

RENDERED_MONITORING_VALUES=$(mktemp)
TEMP_FILES+=("$RENDERED_MONITORING_VALUES")

sed \
  -e "s|__SNS_TOPIC_ARN__|${SNS_TOPIC_ARN}|g" \
  -e "s|__AWS_REGION__|${AWS_REGION}|g" \
  "${MONITORING_MANIFEST_DIR}/values.yaml" \
  > "$RENDERED_MONITORING_VALUES"

helm upgrade --install monitoring \
  prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --version "$KUBE_PROMETHEUS_STACK_CHART_VERSION" \
  --values "$RENDERED_MONITORING_VALUES" \
  --wait \
  --timeout 15m

RENDERED_PROMETHEUS_INGRESS=$(mktemp)
TEMP_FILES+=("$RENDERED_PROMETHEUS_INGRESS")

sed \
  -e "s|__ADMIN_SSH_CIDR__|${ADMIN_SSH_CIDR}|g" \
  "${MONITORING_MANIFEST_DIR}/prometheus-ingress.yaml" \
  > "$RENDERED_PROMETHEUS_INGRESS"

kubectl apply \
  -f "${MONITORING_MANIFEST_DIR}/grafana-ingress.yaml" \
  -f "$RENDERED_PROMETHEUS_INGRESS" \
  -f "${MONITORING_MANIFEST_DIR}/ingress-nginx-servicemonitor.yaml" \
  -f "${MONITORING_MANIFEST_DIR}/polyai-prometheus-rules.yaml"

echo "Installing ArgoCD ${ARGOCD_VERSION}..."

kubectl create namespace argocd \
  --dry-run=client \
  --output=yaml \
  | kubectl apply -f -

kubectl apply \
  --namespace argocd \
  --server-side \
  --force-conflicts \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"

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

echo "Exposing ArgoCD through ingress-nginx..."
kubectl apply -f "${INGRESS_MANIFEST_DIR}/argocd-ingress.yaml"

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
