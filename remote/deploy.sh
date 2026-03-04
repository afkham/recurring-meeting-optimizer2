#!/usr/bin/env bash
# deploy.sh — full deployment of meeting-optimizer to Kubernetes
#
# Prerequisites:
#   - kubectl configured and pointing at your cluster
#   - Docker logged in to your registry
#   - credentials.json, token.json, chat_webhooks.json present in the project root
#   - token.json obtained by running: python3 main.py --dry-run
#
# Usage:
#   cd /path/to/recurring-meeting-optimizer2
#   IMAGE=your-registry/meeting-optimizer:latest ./remote/deploy.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE_DIR="$PROJECT_ROOT/remote"
IMAGE="${IMAGE:-your-registry/meeting-optimizer:latest}"

echo "==> Building image: $IMAGE"
docker build -f "$REMOTE_DIR/Dockerfile" -t "$IMAGE" "$PROJECT_ROOT"

echo "==> Pushing image: $IMAGE"
docker push "$IMAGE"

echo "==> Creating Kubernetes Secret (optimizer-secrets)"
kubectl create secret generic optimizer-secrets \
  --from-file=credentials.json="$PROJECT_ROOT/credentials.json" \
  --from-file=initial-token.json="$PROJECT_ROOT/token.json" \
  --from-file=chat_webhooks.json="$PROJECT_ROOT/chat_webhooks.json" \
  --save-config \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> Applying PersistentVolumeClaim"
kubectl apply -f "$REMOTE_DIR/pvc.yaml"

echo "==> Running init Job (bootstraps PVC with token.json and sent_reminders.json)"
kubectl delete job optimizer-init --ignore-not-found
kubectl apply -f "$REMOTE_DIR/init-job.yaml"
kubectl wait --for=condition=complete job/optimizer-init --timeout=120s
kubectl logs job/optimizer-init

echo "==> Applying CronJob"
# Substitute the actual image name into the manifest before applying.
sed "s|your-registry/meeting-optimizer:latest|$IMAGE|g" \
  "$REMOTE_DIR/cronjob.yaml" | kubectl apply -f -

echo ""
echo "==> Deployment complete."
echo "    Trigger a test run with:"
echo "      kubectl create job --from=cronjob/meeting-optimizer optimizer-test"
echo "      kubectl logs -f job/optimizer-test"
