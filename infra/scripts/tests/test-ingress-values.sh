#!/bin/bash

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
VALUES_FILE="${REPO_ROOT}/infra/k8s/ingress/values.yaml"

EXPECTED_PROXY_CIDRS='proxy-real-ip-cidr: "10.0.0.0/16,192.168.0.0/16"'

if ! grep -Fq "$EXPECTED_PROXY_CIDRS" "$VALUES_FILE"; then
  echo "ingress-nginx must trust forwarded client IPs from both the VPC and Calico pod CIDRs."
  exit 1
fi

echo "Ingress forwarded-client-IP configuration is valid."
