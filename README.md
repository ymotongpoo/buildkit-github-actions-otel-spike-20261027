# GitHub Actions and BuildKit traces in Grafana Cloud

Temporary public experiment for sending BuildKit traces from a GitHub-hosted runner to Grafana Cloud.

The baseline workflow sends BuildKit traces over OTLP/HTTP Protobuf. It uses Buildx v0.29.1 and BuildKit v0.33.1, matching the preceding local-build experiment. It builds and runs a small BusyBox image.

Repository secrets:

- `GRAFANA_CLOUD_OTLP_ENDPOINT`: Grafana Cloud OTLP base endpoint, including `/otlp`.
- `GRAFANA_CLOUD_OTLP_HEADERS`: the OpenTelemetry authentication header from Grafana Cloud.

Workflows run only on manual dispatch. Cloud credentials stay in Actions secrets and the temporary builder environment. No image is pushed to a registry.

## Baseline result

[Run 40436429094](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/actions/runs/40436429094) passed. Tempo returned trace `ca7dc175b66f4a8a353b411d729c2636`, with 87 spans: 33 from `buildx` and 54 from `buildkitd`. The `build .` span is the root, and all parent IDs resolve. The traced build lasted about 1.35 seconds; this excludes runner setup and the other Actions steps.

## Linked result

[Build run 40437818776](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/actions/runs/40437818776) and [its CI metadata export](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/actions/runs/40437872708) both passed.

Tempo returned one trace, `d186f60d435cbf0d2af27d385e372d12`, with 108 unique spans: 21 from `github-actions`, 33 from `buildx`, and 54 from `buildkitd`. It contains both jobs, one root, and zero missing parents. The Dockerfile RUN span descends through the actual workflow, job, build step, and Buildx span IDs. See [the verified IDs and counts](evidence/linked-verification.json).

The initial trace search found the BuildKit spans before the CI root arrived. After the export workflow completed, Tempo combined them under the workflow root. This demonstrates eventual assembly, not live availability of every CI span during the build.

## Workflow trace experiment

`build.yml` runs two jobs on separate GitHub-hosted runners. The `build` job builds and runs the image. The `verify-source` job then checks the source fixture.

Before the build step, `scripts/ci-parent.py` reads the current job ID from the GitHub API. It calculates the same trace and step span IDs as OpenTelemetry Collector's GitHub receiver v0.164.0, then passes that step's `TRACEPARENT` to Buildx. The step name must be unique within the job.

After the build workflow completes, `export-workflow.yml` runs `scripts/export-workflow.py`. It fetches the completed run and job records from the GitHub API, reconstructs their completed-event envelopes, and feeds them to the standard GitHub receiver in a short-lived Collector. The receiver creates the workflow, job, queue, and step spans and exports them to Grafana Cloud.

The expected hierarchy is:

```text
BuildKit linked trace
├── build
│   └── Build Docker image
│       └── build .
│           └── BuildKit Dockerfile steps
└── verify-source
    └── Verify source fixture
```

BuildKit exports its detailed spans while the build runs. CI spans arrive after the workflow completes. The full trace is therefore not available immediately during the build. This configuration exports traces only and does not require an internet-facing webhook receiver.

The ID rules are pinned to [githubreceiver v0.164.0](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.164.0/receiver/githubreceiver/trace_event_handling.go). They are receiver implementation details, not a universal OpenTelemetry ID convention. Recheck them when upgrading the Collector. This spike resolves jobs by their default names and does not cover matrix jobs or reusable workflows.

## Verify the trace

Download the full OTLP-shaped trace JSON from Tempo, then run:

```sh
python3 scripts/verify-trace.py trace.json --mode linked
```

The verifier checks one trace ID, one workflow root, the build step and build job in the Buildx parent chain, the second job, and the absence of missing parent spans. Workflow success alone is insufficient for this check.

## Earlier Thoth attempt

GitHub initially stopped [run 40436761654](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/actions/runs/40436761654) before creating jobs, with conclusion `action_required`. The owner reviewed and approved the workflow. Attempt 2 then failed in Thoth's initialization because a runner Node.js binary could not be found. The same path handling exists in stable v5.64.0, so this experiment switched to the standard GitHub receiver rather than modifying the runner instrumentation.

The earlier implementation and evidence remain in the Git history. No repository Actions policy was weakened.

## Scope

The baseline uses Docker Engine 28.0.4 on a GitHub-hosted Ubuntu 24.04 runner, Buildx v0.29.1, BuildKit v0.33.1, a small BusyBox Dockerfile, and direct BuildKit OTLP/HTTP export. It does not establish behavior for Docker Desktop, fork pull requests, matrix jobs, or caching across runs.

## Reproduce

Configure the two repository secrets above for your own Grafana Cloud stack. The workflows need only the standard GitHub token with `contents: read` and `actions: read`; no GitHub App or PAT is required.

```sh
gh workflow run baseline.yml --ref main -R ymotongpoo/buildkit-github-actions-otel-spike-20261027
gh workflow run build.yml --ref main -R ymotongpoo/buildkit-github-actions-otel-spike-20261027
```

For the linked case, wait for `Export completed workflow trace` as well as the build workflow. Use the workflow run ID and attempt to calculate the trace ID, or find the Buildx span with:

```traceql
{ resource.ci.run.id = "<run ID>" && name = "build ." }
```

Then retrieve that full trace and run the verifier above.
