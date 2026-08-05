#!/bin/bash

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT

mkdir -p "$TEST_DIR/bin"

cat > "$TEST_DIR/bin/kubectl" <<'EOF'
#!/bin/bash
printf '%s\n' "$*" >> "$KUBECTL_CALLS"
printf 'kubectl %s\n' "$*" >> "$COMMAND_CALLS"

if [[ "$*" == *"get nodes"* ]]; then
  printf 'worker-test True\n'
elif [[ "$*" == "get namespace monitoring --ignore-not-found --output=name" ]]; then
  if [ "${MONITORING_NAMESPACE_LOOKUP_ERROR:-false}" = "true" ]; then
    exit 45
  fi
  if [ "${MONITORING_NAMESPACE_EXISTS:-true}" = "true" ]; then
    printf 'namespace/monitoring\n'
  fi
elif [[ "$*" == *"rollout status --namespace kube-system deployment/ebs-csi-controller"* ]] \
  && [ "${EBS_CONTROLLER_EXISTS:-true}" = "false" ]; then
  exit 46
elif [[ "$*" == *"get persistentvolume "* ]]; then
  if [ "${EBS_PVS_REMAIN:-false}" = "true" ]; then
    printf 'pv-test\n'
  fi
elif [ "${FAIL_POST_STORAGE:-false}" = "true" ] \
  && { [[ "$*" == "delete applications.argoproj.io "* ]] \
    || [[ "$*" == "delete pods --namespace dev "* ]] \
    || [[ "$*" == "delete pods --namespace prod "* ]] \
    || [[ "$*" == "delete pods --namespace argocd "* ]] \
    || [[ "$*" == "delete namespace "* ]] \
    || [[ "$*" == "delete storageclass "* ]]; }; then
  exit 43
fi
EOF

cat > "$TEST_DIR/bin/helm" <<'EOF'
#!/bin/bash
printf '%s\n' "$*" >> "$HELM_CALLS"
printf 'helm %s\n' "$*" >> "$COMMAND_CALLS"

if [ "${1:-}" = "uninstall" ] \
  && [ "${2:-}" = "monitoring" ] \
  && [ "${FAIL_MONITORING_UNINSTALL:-false}" = "true" ]; then
  exit 42
fi

if [ "${1:-}" = "uninstall" ] \
  && [ "${2:-}" != "monitoring" ] \
  && [ "${FAIL_POST_STORAGE:-false}" = "true" ]; then
  exit 44
fi

if [ "${1:-}" = "status" ] || [ "${1:-}" = "uninstall" ]; then
  exit 0
fi

exit 1
EOF

cat > "$TEST_DIR/bin/sleep" <<'EOF'
#!/bin/bash
exit 0
EOF

chmod +x "$TEST_DIR/bin/kubectl" "$TEST_DIR/bin/helm" "$TEST_DIR/bin/sleep"
export KUBECTL_CALLS="$TEST_DIR/kubectl-calls"
export HELM_CALLS="$TEST_DIR/helm-calls"
export COMMAND_CALLS="$TEST_DIR/command-calls"
export PATH="$TEST_DIR/bin:$PATH"

mkdir -p "$TEST_DIR/bin-without-helm"
ln -s "$TEST_DIR/bin/kubectl" "$TEST_DIR/bin-without-helm/kubectl"
ln -s "$TEST_DIR/bin/sleep" "$TEST_DIR/bin-without-helm/sleep"
ln -s "$(command -v awk)" "$TEST_DIR/bin-without-helm/awk"
ln -s "$(command -v seq)" "$TEST_DIR/bin-without-helm/seq"

bash "$REPO_ROOT/infra/scripts/cleanup-cluster.sh"

grep -Fq \
  'delete pods --namespace dev --all --ignore-not-found --force --grace-period=0 --wait=false' \
  "$KUBECTL_CALLS"
grep -Fq \
  'delete pods --namespace prod --all --ignore-not-found --force --grace-period=0 --wait=false' \
  "$KUBECTL_CALLS"
grep -Fq \
  'delete pods --namespace monitoring --all --ignore-not-found --force --grace-period=0 --wait=false' \
  "$KUBECTL_CALLS"
grep -Fq \
  'delete pods --namespace argocd --all --ignore-not-found --force --grace-period=0 --wait=false' \
  "$KUBECTL_CALLS"
grep -Fq \
  'delete namespace dev prod monitoring argocd --ignore-not-found --wait=false' \
  "$KUBECTL_CALLS"

if grep -Eq 'delete namespace .*--wait=true' "$KUBECTL_CALLS"; then
  echo "namespace cleanup must not block Terraform destroy" >&2
  exit 1
fi

grep -Fq \
  'uninstall monitoring --namespace monitoring --no-hooks --ignore-not-found' \
  "$HELM_CALLS"
grep -Fq \
  'uninstall ingress-nginx --namespace ingress-nginx' \
  "$HELM_CALLS"
grep -Fq \
  'uninstall aws-ebs-csi-driver --namespace kube-system' \
  "$HELM_CALLS"

if grep -E 'uninstall (monitoring|ingress-nginx|aws-ebs-csi-driver).*--wait' "$HELM_CALLS"; then
  echo "Helm cleanup must not wait for pods on dead workers" >&2
  exit 1
fi

MONITORING_POD_DELETE_LINE=$(grep -nF \
  'kubectl delete pods --namespace monitoring --all --ignore-not-found --force --grace-period=0 --wait=false' \
  "$COMMAND_CALLS" | cut -d: -f1)
PVC_DELETE_LINE=$(grep -nF \
  'kubectl delete persistentvolumeclaim --namespace monitoring --all --ignore-not-found --wait=true --timeout=10m' \
  "$COMMAND_CALLS" | cut -d: -f1)

if [ "$MONITORING_POD_DELETE_LINE" -ge "$PVC_DELETE_LINE" ]; then
  echo "monitoring pods must be removed before waiting for PVC deletion" >&2
  exit 1
fi

if FAIL_MONITORING_UNINSTALL=true \
  bash "$REPO_ROOT/infra/scripts/cleanup-cluster.sh" >/dev/null 2>&1; then
  echo "monitoring uninstall failure must stop storage cleanup" >&2
  exit 1
fi

if EBS_PVS_REMAIN=true \
  bash "$REPO_ROOT/infra/scripts/cleanup-cluster.sh" >/dev/null 2>&1; then
  echo "remaining EBS PersistentVolumes must stop cleanup" >&2
  exit 1
fi

FAIL_POST_STORAGE=true \
  bash "$REPO_ROOT/infra/scripts/cleanup-cluster.sh" >/dev/null 2>&1

EBS_CONTROLLER_EXISTS=false \
  bash "$REPO_ROOT/infra/scripts/cleanup-cluster.sh" >/dev/null 2>&1

MONITORING_NAMESPACE_EXISTS=false \
PATH="$TEST_DIR/bin-without-helm" \
  /bin/bash "$REPO_ROOT/infra/scripts/cleanup-cluster.sh" >/dev/null 2>&1

if MONITORING_NAMESPACE_EXISTS=true \
  PATH="$TEST_DIR/bin-without-helm" \
  /bin/bash "$REPO_ROOT/infra/scripts/cleanup-cluster.sh" >/dev/null 2>&1; then
  echo "missing Helm must fail when the monitoring namespace still exists" >&2
  exit 1
fi

if MONITORING_NAMESPACE_LOOKUP_ERROR=true \
  PATH="$TEST_DIR/bin-without-helm" \
  /bin/bash "$REPO_ROOT/infra/scripts/cleanup-cluster.sh" >/dev/null 2>&1; then
  echo "monitoring namespace lookup errors must stop cleanup" >&2
  exit 1
fi

echo "cleanup-cluster dead-node pod test passed"
