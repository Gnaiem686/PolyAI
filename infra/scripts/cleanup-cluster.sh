#!/bin/bash

set -euo pipefail

export KUBECONFIG="${KUBECONFIG:-/etc/kubernetes/admin.conf}"

echo "Waiting for a worker node required by cluster add-ons..."

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
    echo "Timed out waiting for a Ready worker node."
    exit 1
  fi

  sleep 10
done

echo "Removing kube-prometheus-stack..."

if command -v helm >/dev/null 2>&1 \
  && helm status monitoring --namespace monitoring >/dev/null 2>&1; then
  kubectl rollout status \
    --namespace kube-system \
    deployment/ebs-csi-controller \
    --timeout=10m

  helm uninstall monitoring --namespace monitoring --wait --timeout 10m
fi

kubectl delete persistentvolumeclaim \
  --namespace monitoring \
  --all \
  --ignore-not-found \
  --wait=true \
  --timeout=10m

echo "Waiting for the EBS CSI driver to delete monitoring volumes..."

for attempt in $(seq 1 60); do
  EBS_PVS=$(
    kubectl get persistentvolume \
      --output=jsonpath='{range .items[?(@.spec.storageClassName=="ebs-sc")]}{.metadata.name}{"\n"}{end}'
  )

  if [ -z "$EBS_PVS" ]; then
    break
  fi

  if [ "$attempt" -eq 60 ]; then
    echo "Timed out waiting for EBS-backed PersistentVolumes to be deleted:"
    echo "$EBS_PVS"
    exit 1
  fi

  sleep 10
done

echo "Removing ArgoCD-managed workloads..."

kubectl delete applications.argoproj.io \
  --namespace argocd \
  --all \
  --ignore-not-found \
  --wait=false

# Pods assigned to a worker that was terminated outside Kubernetes cannot
# finish their normal grace period because that node's kubelet is gone.
# Remove their API objects so namespace deletion can make progress during
# destroy. These namespaces contain no remaining cloud-backed storage because
# EBS PersistentVolumes were checked above.
for namespace in dev prod monitoring argocd; do
  kubectl delete pods \
    --namespace "$namespace" \
    --all \
    --ignore-not-found \
    --force \
    --grace-period=0 \
    --wait=false
done

echo "Removing cluster add-ons..."

kubectl delete namespace dev prod monitoring argocd \
  --ignore-not-found \
  --wait=false

if command -v helm >/dev/null 2>&1 \
  && helm status ingress-nginx --namespace ingress-nginx >/dev/null 2>&1; then
  helm uninstall ingress-nginx --namespace ingress-nginx --wait --timeout 10m
fi

if command -v helm >/dev/null 2>&1 \
  && helm status aws-ebs-csi-driver --namespace kube-system >/dev/null 2>&1; then
  helm uninstall aws-ebs-csi-driver --namespace kube-system --wait --timeout 10m
fi

kubectl delete storageclass ebs-sc --ignore-not-found

echo "Kubernetes resources are clean. Terraform can now destroy AWS infrastructure."
