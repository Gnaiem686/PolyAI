#!/bin/bash

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
ROOT_MAIN="${REPO_ROOT}/infra/tf/main.tf"
MODULE_MAIN="${REPO_ROOT}/infra/tf/modules/k8s-cluster/main.tf"
TFVARS="${REPO_ROOT}/infra/tf/tfvars/us-east-1.tfvars"

grep -Eq 'bedrock_model_id[[:space:]]*=[[:space:]]*var\.bedrock_model_id' "$ROOT_MAIN"
grep -Eq 'bedrock_model_id[[:space:]]*=[[:space:]]*"amazon\.nova-micro-v1:0"' "$TFVARS"
grep -Fq 'resource "aws_iam_role_policy" "worker_bedrock_invoke"' "$MODULE_MAIN"
grep -Fq '"bedrock:InvokeModel"' "$MODULE_MAIN"
grep -Fq 'Resource = "arn:aws:bedrock:${var.region}::foundation-model/${var.bedrock_model_id}"' "$MODULE_MAIN"

echo "Worker Bedrock model policy configuration is valid."
