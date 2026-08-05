# Robust Cluster Destroy Cleanup

## Goal

Ensure the destroy workflow reaches `terraform destroy` even when Kubernetes
pods are stuck on workers that AWS has already terminated, without leaking
EBS volumes used by monitoring.

## Safety Boundary

Monitoring PVC and EBS PersistentVolume deletion remains blocking. If those
volumes cannot be confirmed deleted, cleanup fails so the workflow does not
silently leave chargeable AWS disks behind.

After EBS volumes are gone, all remaining resources exist only inside the
cluster. Their cleanup is best-effort and must not block Terraform from
destroying the EC2 instances, ASG, networking, and other managed resources.

## Cleanup Flow

1. Wait for a Ready worker so the EBS CSI controller can operate.
2. Require Helm and request removal of the monitoring release with
   `--ignore-not-found`, without waiting for pods on dead workers. Operational
   Helm failures remain fatal. Force-delete monitoring pods so they release
   PVC protection, delete the PVCs, and confirm no `ebs-sc` PersistentVolumes
   remain.
3. Request deletion of ArgoCD Applications.
4. Force-delete pods in `dev`, `prod`, `monitoring`, and `argocd`, because a
   terminated worker's kubelet cannot finish their grace periods.
5. Request namespace deletion without waiting for completion.
6. Request ingress-nginx and EBS CSI Helm uninstalls without waiting for pods
   on dead workers.
7. Delete the storage class and allow the workflow to run Terraform destroy.

## Failure Handling

- Failure before EBS volume deletion is confirmed stops the workflow.
- Failure to request monitoring Helm release removal stops the workflow so its
  controllers cannot recreate storage after verification.
- Post-storage Kubernetes deletions are nonblocking and may log warnings.
- Terraform remains responsible for deleting Terraform-managed AWS resources.

## Verification

The cleanup script test will simulate installed Helm releases and record every
`kubectl` and `helm` invocation. It will verify that:

- monitoring storage cleanup retains its blocking checks;
- dead-node pods are force-deleted in all workload namespaces;
- namespace deletion does not wait;
- ingress-nginx and EBS CSI uninstall commands do not use `--wait`;
- the script reaches successful completion when Kubernetes deletion requests
  are accepted.
