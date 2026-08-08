#!/bin/bash

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
VALUES_FILE="${REPO_ROOT}/infra/k8s/monitoring/values.yaml"

grep -Fq 'gnetId: 9614' "$VALUES_FILE"
grep -Fq 'name: nginx-ingress-controller' "$VALUES_FILE"
grep -Fq 'path: /var/lib/grafana/dashboards/default' "$VALUES_FILE"

echo "Grafana Nginx dashboard provider configuration is valid."
