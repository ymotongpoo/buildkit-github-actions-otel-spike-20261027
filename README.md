# GitHub Actions and BuildKit traces in Grafana Cloud

Temporary public experiment for sending BuildKit traces from a GitHub-hosted runner to Grafana Cloud.

The baseline workflow sends BuildKit traces over OTLP/HTTP Protobuf. It uses Buildx v0.29.1 and BuildKit v0.33.1, matching the preceding local-build experiment. It builds and runs a small BusyBox image.

Repository secrets:

- `GRAFANA_CLOUD_OTLP_ENDPOINT`: Grafana Cloud OTLP base endpoint, including `/otlp`.
- `GRAFANA_CLOUD_OTLP_HEADERS`: the OpenTelemetry authentication header from Grafana Cloud.
- `GRAFANA_CLOUD_OTLP_AUTH_B64`: the encoded credential portion, also registered for redaction during instrumentation.

Workflows run only on manual dispatch. Cloud credentials stay in Actions secrets and the temporary builder environment. No image is pushed to a registry.

The next experiment will connect workflow, job, step, and BuildKit spans into one trace.
