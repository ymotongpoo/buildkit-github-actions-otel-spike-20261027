# GitHub Actions and BuildKit traces in Grafana Cloud

Temporary public experiment for sending BuildKit traces from a GitHub-hosted runner to Grafana Cloud.

The baseline workflow sends BuildKit traces over OTLP/HTTP Protobuf. It uses Buildx v0.29.1 and BuildKit v0.33.1, matching the preceding local-build experiment. It builds and runs a small BusyBox image.

Repository secrets:

- `GRAFANA_CLOUD_OTLP_ENDPOINT`: Grafana Cloud OTLP base endpoint, including `/otlp`.
- `GRAFANA_CLOUD_OTLP_HEADERS`: the OpenTelemetry authentication header from Grafana Cloud.
- `GRAFANA_CLOUD_OTLP_AUTH_B64`: the encoded credential portion, also registered for redaction during instrumentation.

Workflows run only on manual dispatch. Cloud credentials stay in Actions secrets and the temporary builder environment. No image is pushed to a registry.

## Baseline result

[Run 40436429094](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/actions/runs/40436429094) passed. Tempo returned trace `ca7dc175b66f4a8a353b411d729c2636`, with 87 spans: 33 from `buildx` and 54 from `buildkitd`. The `build .` span is the root, and all parent IDs resolve. The traced build lasted about 1.35 seconds; this excludes runner setup and the other Actions steps.

## Workflow trace experiment

`build.yml` instruments two jobs with [Thoth](https://github.com/plengauer/Thoth), pinned to commit `c6ece8c81027d5bc048a003ccf0215d75221f2c1`. The `build` job builds and runs the image. A second `verify-source` job checks the source fixture on a separate runner.

`export-workflow.yml` runs after the build workflow completes. It exports workflow metadata from the GitHub API. It observes only `BuildKit linked trace`, so it does not recursively observe its own exports. The job instrumentation provides the context that Buildx receives while the build runs.

Only traces are requested. The instrumentation's usage reporting is disabled, and configured credentials are included in its redaction settings.

## Verify the trace

Download the full OTLP-shaped trace JSON from Tempo, then run:

```sh
python3 scripts/verify-trace.py trace.json --mode linked
```

The verifier checks one trace ID, one workflow root, the build step and build job in the Buildx parent chain, the second job, and the absence of missing parent spans. Workflow success alone is insufficient for this check.

## GitHub approval required for the linked experiment

GitHub stopped [run 40436761654](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/actions/runs/40436761654) before creating any jobs, with conclusion `action_required` and the message:

> GitHub detected that this workflow file may be malicious. It will not run until someone with write access approves it.

The repository allows Actions, the baseline completed, and the configured Actions policy permits third-party actions. The specific reason for the detection is not exposed in that message. The linked workflow has not yet executed, so this repository does not yet demonstrate workflow-to-BuildKit parentage.

Review `.github/workflows/build.yml` at commit `b2eb2a24aeec560e594fc4cf1e8c0274dfebffe3` and use GitHub's approval flow on that run before continuing. No action-policy or detection bypass is applied here.

## Scope

The baseline uses a GitHub-hosted Ubuntu 24.04 runner, a small BusyBox Dockerfile, and direct BuildKit OTLP/HTTP export. It does not establish behavior for Docker Desktop, fork pull requests, matrix jobs, or caching across runs.
