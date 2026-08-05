#!/bin/bash

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT

mkdir -p "$TEST_DIR/bin"

cat > "$TEST_DIR/bin/kubectl" <<'EOF'
#!/bin/bash
printf '%s\n' "$*" >> "$KUBECTL_CALLS"

if [[ "$*" == *"get nodes"* ]]; then
  printf 'worker-test True\n'
elif [[ "$*" == *"get persistentvolume "* ]]; then
  :
fi
EOF

cat > "$TEST_DIR/bin/helm" <<'EOF'
#!/bin/bash
exit 1
EOF

chmod +x "$TEST_DIR/bin/kubectl" "$TEST_DIR/bin/helm"
export KUBECTL_CALLS="$TEST_DIR/kubectl-calls"
export PATH="$TEST_DIR/bin:$PATH"

bash "$REPO_ROOT/infra/scripts/cleanup-cluster.sh"

grep -Fq \
  'delete pods --namespace dev --all --ignore-not-found --force --grace-period=0 --wait=false' \
  "$KUBECTL_CALLS"
grep -Fq \
  'delete pods --namespace prod --all --ignore-not-found --force --grace-period=0 --wait=false' \
  "$KUBECTL_CALLS"

echo "cleanup-cluster dead-node pod test passed"
