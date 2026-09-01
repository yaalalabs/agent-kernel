#!/bin/bash

# Builds the three container images the Helm chart deploys for this example (io-handler,
# agent-runner, and the sandbox worker):
#
#   ./package.sh [local]
#
#   local   install agentkernel from ../../../../ak-py/dist instead of the published release
#
# Mirrors examples/k8s/openai-queue-mode/deploy/package.sh: dependencies are staged into
# dist-*/data with pip's --target layout and copied into python:3.12-slim. The images run on
# Linux whatever the build host is, so uv cross-installs for the Linux platform matching the
# host architecture (Docker builds target it by default).

set -euo pipefail

MODE="${1-}"
if [[ $MODE != "local" && -n $MODE ]]; then
  echo "usage: ./package.sh [local]" >&2
  exit 2
fi

# manylinux_2_28 for parity with the base example; python:3.12-slim (Debian bookworm,
# glibc 2.36) satisfies it comfortably.
case "$(uname -m)" in
  arm64 | aarch64) PLATFORM="aarch64-manylinux_2_28" ;;
  *) PLATFORM="x86_64-manylinux_2_28" ;;
esac

IMAGE_TAG="${IMAGE_TAG-dev}"

create_deployment_package() {
  local component="$1" entry="$2"
  local dist="dist-${component}"

  pushd ../

  rm -rf "$dist"
  mkdir -p "$dist/data"
  if [[ $MODE != "local" ]]; then
    uv pip install -r requirements.txt --target="$dist/data" \
      --python-platform "$PLATFORM" --python-version 3.12 --only-binary :all:
  else
    uv pip install -r requirements.txt --target="$dist/data" \
      --python-platform "$PLATFORM" --python-version 3.12 --only-binary :all: \
      --find-links ../../../ak-py/dist
    uv pip install --force-reinstall --no-deps --no-index --no-cache --target="$dist/data" \
      --find-links ../../../ak-py/dist agentkernel
  fi
  cp "$entry" "$dist/data/"
  cp "config.nats.yaml" "$dist/data/config.yaml"

  popd

  cp "Dockerfile.${component}" "../${dist}/Dockerfile"
  docker build -t "ak-sbx-${component}:${IMAGE_TAG}" "../${dist}"
}

pushd ../
uv export --no-hashes --no-dev > requirements.txt
popd

create_deployment_package io-handler app_io_handler.py
create_deployment_package agent-runner app_agent_runner.py
create_deployment_package sandbox-worker app_sandbox_worker.py

rm -f ../requirements.txt

echo
echo "Built ak-sbx-io-handler:${IMAGE_TAG}, ak-sbx-agent-runner:${IMAGE_TAG}, and ak-sbx-sandbox-worker:${IMAGE_TAG}"
