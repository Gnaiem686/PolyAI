# Robust Destroy Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent dead Kubernetes nodes from blocking Terraform destroy while retaining strict deletion checks for monitoring EBS volumes.

**Architecture:** `cleanup-cluster.sh` keeps worker recovery, monitoring PVC deletion, and EBS PersistentVolume verification as hard gates. After storage is confirmed gone, namespace and Helm cleanup becomes nonblocking because those objects exist only inside the cluster Terraform is about to destroy.

**Tech Stack:** Bash, kubectl, Helm, GitHub Actions, Terraform, AWS EBS CSI.

## Global Constraints

- Preserve the acceptance flow: `terraform destroy` followed by provision and bootstrap recreates the system.
- Do not allow cleanup of disposable Kubernetes objects to prevent Terraform destroy.
- Do not continue if `ebs-sc` PersistentVolumes cannot be confirmed deleted.
- Do not modify `infra/grafana/dashboards/`.

---

### Task 1: Make post-storage cleanup nonblocking

**Files:**
- Modify: `infra/scripts/cleanup-cluster.sh`
- Modify: `infra/scripts/tests/test-cleanup-cluster.sh`
- Verify: `.github/workflows/destroy-cluster.yaml`

**Interfaces:**
- Consumes: Helm releases `monitoring`, `ingress-nginx`, and `aws-ebs-csi-driver`; Kubernetes namespaces and `ebs-sc` PersistentVolumes.
- Produces: exit code zero after accepted post-storage deletion requests, allowing the workflow's Terraform destroy step to run.

- [ ] **Step 1: Extend the failing shell regression test**

Make the Helm stub report all three releases as installed, record Helm calls,
and assert that none of the Helm uninstalls contain `--wait`. Assert that
monitoring pods are force-deleted before the blocking PVC deletion and that
namespace deletion uses `--wait=false`.

- [ ] **Step 2: Verify the regression test fails**

Run: `bash infra/scripts/tests/test-cleanup-cluster.sh`

Expected: failure because the current Helm uninstalls use blocking waits and
monitoring pods are removed only after PVC deletion.

- [ ] **Step 3: Implement the minimal cleanup change**

Request monitoring uninstall without waiting, force-delete monitoring pods,
then keep PVC deletion and EBS PV verification blocking. After EBS PVs are
gone, request ingress-nginx and EBS CSI uninstall without `--wait`, tolerate
post-storage cleanup errors with explicit warnings, and preserve asynchronous
namespace deletion. A failure to request monitoring uninstall remains fatal so
monitoring controllers cannot recreate storage after verification.

- [ ] **Step 4: Run local verification**

Run:

```bash
bash infra/scripts/tests/test-cleanup-cluster.sh
bash -n infra/scripts/cleanup-cluster.sh
git diff --check
terraform -chdir=infra/tf init -backend=false
terraform -chdir=infra/tf validate
```

Expected: shell test passes, Bash syntax is valid, no whitespace errors, and
Terraform reports `Success! The configuration is valid.`

- [ ] **Step 5: Audit task requirements and hand off Git commands**

Confirm fixed NodePorts, HTTPS ALB and ASG attachment, Route 53 data source and
records, dev/prod ingress resources, kube-prometheus-stack persistence and
retention, four application ServiceMonitors, ingress monitoring/dashboard,
SNS Alertmanager receiver, two custom alerts with severities, and automated
bootstrap declarations. Report any manual acceptance evidence still required.
