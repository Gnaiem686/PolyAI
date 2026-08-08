#!/bin/bash

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
ROOT_MAIN="${REPO_ROOT}/infra/tf/main.tf"
MODULE_MAIN="${REPO_ROOT}/infra/tf/modules/k8s-cluster/main.tf"
TFVARS="${REPO_ROOT}/infra/tf/tfvars/us-east-1.tfvars"

grep -Fq 'image_bucket_name = var.image_bucket_name' "$ROOT_MAIN"
grep -Fq 'image_bucket_name = "gnaiem-polyai-images"' "$TFVARS"
grep -Fq 'resource "aws_iam_role_policy" "worker_s3_objects"' "$MODULE_MAIN"
grep -Fq '"s3:GetObject"' "$MODULE_MAIN"
grep -Fq '"s3:PutObject"' "$MODULE_MAIN"
grep -Fq 'Resource = "arn:aws:s3:::${var.image_bucket_name}/*"' "$MODULE_MAIN"

echo "Worker S3 object policy configuration is valid."
