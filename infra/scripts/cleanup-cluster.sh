#!/bin/bash

set -euo pipefail

export KUBECONFIG="${KUBECONFIG:-/etc/kubernetes/admin.conf}"

echo "Removing kube-prometheus-stack..."

if helm status monitoring --namespace monitoring >/dev/null 2>&1; then
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

kubectl delete namespace dev prod \
  --ignore-not-found \
  --wait=true \
  --timeout=10m

echo "Removing cluster add-ons..."

kubectl delete namespace monitoring argocd \
  --ignore-not-found \
  --wait=true \
  --timeout=10m

if helm status ingress-nginx --namespace ingress-nginx >/dev/null 2>&1; then
  helm uninstall ingress-nginx --namespace ingress-nginx --wait --timeout 10m
fi

if helm status aws-ebs-csi-driver --namespace kube-system >/dev/null 2>&1; then
  helm uninstall aws-ebs-csi-driver --namespace kube-system --wait --timeout 10m
fi

kubectl delete storageclass ebs-sc --ignore-not-found

echo "Kubernetes resources are clean. Terraform can now destroy AWS infrastructure."
