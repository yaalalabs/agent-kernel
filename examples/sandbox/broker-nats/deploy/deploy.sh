#!/bin/bash

# Installs (or upgrades) this example's Agent Kernel chart release:
#
#   ./deploy.sh [local] [helm args...]
#
#   local        install the chart from this checkout (ak-deployment/ak-k8s/chart) instead of
#                the published OCI artifact. CI always deploys this way, so a branch's chart
#                changes are what gets tested, never the released chart.
#   helm args    appended to `helm upgrade --install`: --set transport.type=kafka,
#                --wait --timeout 600s, --kube-context kind-ak, another -f overlay, ...
#
# Same contract as ../build.sh local and ./package.sh local: users start Agent Kernel from the
# published versions, the pipeline from local dependencies. Layers the chart's dev flavor
# (values-dev.yaml) and this example's sandbox-values.yaml (the three images, the sandbox worker
# tier, and the namespace hardening).
# app_test.py runs this script in local mode.
#
# Environment overrides: HELM (the helm command, e.g. "microk8s helm"), RELEASE (default ak),
# FLAVOR (the chart's values-<flavor>.yaml, default dev).

set -euo pipefail

CHART_REF="oci://ghcr.io/yaalalabs/charts/agent-kernel"
# The published chart version; scripts/update_chart_versions.py pins it to each release.
CHART_VERSION="0.9.0"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCAL_CHART="$SCRIPT_DIR/../../../../ak-deployment/ak-k8s/chart"
EXAMPLE_VALUES="$SCRIPT_DIR/../sandbox-values.yaml"

# shellcheck disable=SC2206  # HELM may carry a prefix such as "microk8s helm"
HELM=(${HELM-helm})
RELEASE="${RELEASE-ak}"
FLAVOR="${FLAVOR-dev}"

if [[ ${1-} == "local" ]]; then
  shift
  # A clean machine (CI) has no chart repo definitions; dependency build needs them even with
  # Chart.lock present.
  "${HELM[@]}" repo add --force-update valkey https://valkey-io.github.io/valkey-helm/
  "${HELM[@]}" repo add --force-update nats https://nats-io.github.io/k8s/helm/charts/
  "${HELM[@]}" dependency build "$LOCAL_CHART"
  CHART=("$LOCAL_CHART")
  FLAVOR_VALUES="$LOCAL_CHART/values-${FLAVOR}.yaml"
else
  # The flavor values files ship inside the chart: unpack the pinned version to read them.
  CHART_DIR="$(mktemp -d)"
  trap 'rm -rf "$CHART_DIR"' EXIT
  "${HELM[@]}" pull "$CHART_REF" --version "$CHART_VERSION" --untar --untardir "$CHART_DIR"
  CHART=("$CHART_REF" --version "$CHART_VERSION")
  FLAVOR_VALUES="$CHART_DIR/agent-kernel/values-${FLAVOR}.yaml"
fi

"${HELM[@]}" upgrade --install "$RELEASE" "${CHART[@]}" \
  -f "$FLAVOR_VALUES" -f "$EXAMPLE_VALUES" "$@"
