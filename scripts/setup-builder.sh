#!/usr/bin/env bash
set -euo pipefail
: "${OTEL_EXPORTER_OTLP_ENDPOINT:?Missing OTLP endpoint}"
: "${OTEL_EXPORTER_OTLP_HEADERS:?Missing OTLP authentication headers}"
docker buildx create --name ci-otel --driver docker-container \
  --driver-opt image=moby/buildkit:v0.33.1 \
  --driver-opt env.OTEL_TRACES_EXPORTER=otlp \
  --driver-opt env.OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf \
  --driver-opt "env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT%/}/v1/traces" \
  --driver-opt "env.OTEL_EXPORTER_OTLP_TRACES_HEADERS=${OTEL_EXPORTER_OTLP_HEADERS}" \
  --bootstrap >/dev/null
