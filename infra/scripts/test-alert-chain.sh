#!/bin/bash

set -euo pipefail

FAILURE_MANIFEST="${1:-/tmp/polyai-bootstrap/k8s/monitoring/simulate-agent-failure.yaml}"
ALERT_NAME="AgentDevTargetDown"

export KUBECONFIG="${KUBECONFIG:-/etc/kubernetes/admin.conf}"

PROMETHEUS_CLUSTER_IP=$(
  kubectl get service \
    --namespace monitoring \
    monitoring-kube-prometheus-prometheus \
    --output=jsonpath='{.spec.clusterIP}'
)
PROMETHEUS_URL="http://${PROMETHEUS_CLUSTER_IP}:9090"

cleanup() {
  kubectl delete --ignore-not-found -f "$FAILURE_MANIFEST" >/dev/null
}

alert_is_in_state() {
  local expected_state="$1"

  curl --fail --silent --get \
    --data-urlencode "query=ALERTS{alertname=\"${ALERT_NAME}\",alertstate=\"${expected_state}\"}" \
    "${PROMETHEUS_URL}/api/v1/query" \
    | grep --quiet '"result":\[{'
}

wait_for_alert_state() {
  local expected_state="$1"
  local max_attempts="$2"

  for attempt in $(seq 1 "$max_attempts"); do
    if alert_is_in_state "$expected_state"; then
      echo "${ALERT_NAME} is ${expected_state}."
      return
    fi

    sleep 15
  done

  echo "Timed out waiting for ${ALERT_NAME} to become ${expected_state}."
  return 1
}

trap cleanup EXIT INT TERM

echo "Applying a temporary NetworkPolicy that blocks traffic to the dev Agent..."
kubectl apply -f "$FAILURE_MANIFEST"

echo "Waiting for the alert to become Pending..."
wait_for_alert_state pending 12

echo "Waiting for the alert to become Firing..."
wait_for_alert_state firing 20

echo "Leaving the alert firing for 60 seconds so Alertmanager can notify SNS..."
sleep 60

echo "Removing the simulated failure..."
cleanup

echo "Waiting for Prometheus to resolve the alert..."
for attempt in $(seq 1 20); do
  if ! alert_is_in_state pending && ! alert_is_in_state firing; then
    echo "${ALERT_NAME} is resolved. Check your mailbox for FIRING and RESOLVED messages."
    exit 0
  fi

  sleep 15
done

echo "Timed out waiting for ${ALERT_NAME} to resolve."
exit 1
