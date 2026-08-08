#!/bin/bash

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
VALUES_FILE="${REPO_ROOT}/infra/k8s/monitoring/values.yaml"
BOOTSTRAP_SCRIPT="${REPO_ROOT}/infra/scripts/bootstrap-cluster.sh"

grep -Fq 'https://grafana.com/api/dashboards/9614/revisions/1/download' "$BOOTSTRAP_SCRIPT"
grep -Fq 'create configmap nginx-ingress-controller-dashboard' "$BOOTSTRAP_SCRIPT"
grep -Fq 'grafana_dashboard=1' "$BOOTSTRAP_SCRIPT"

if grep -Fq 'dashboardProviders:' "$VALUES_FILE"; then
  echo "The Grafana sidecar must be used instead of an additional static dashboard provider."
  exit 1
fi

echo "Grafana Nginx dashboard sidecar configuration is valid."
