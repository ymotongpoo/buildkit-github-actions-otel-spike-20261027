#!/usr/bin/env python3
"""Feed completed GitHub API records to the standard local GitHub receiver."""
import json
import os
from pathlib import Path
import subprocess
import urllib.request
from urllib.parse import unquote

repository = os.environ["GITHUB_REPOSITORY"]
run_id = os.environ["OBSERVED_RUN_ID"]


def github(path):
    return json.loads(subprocess.check_output(["gh", "api", f"repos/{repository}/{path}"]))


run = github(f"actions/runs/{run_id}")
assert run["status"] == "completed", "Only completed workflow runs can be exported"
attempt = run["run_attempt"]
repo = json.loads(subprocess.check_output(["gh", "api", f"repos/{repository}"]))
pages = json.loads(subprocess.check_output([
    "gh", "api", "--paginate", "--slurp",
    f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"
]))
jobs = [job for page in pages for job in page["jobs"]]
assert jobs, "The workflow has no jobs to export"
authorization = dict(item.split("=", 1) for item in os.environ["OTEL_EXPORTER_OTLP_HEADERS"].split(","))["Authorization"]
env = dict(os.environ, GRAFANA_AUTHORIZATION=unquote(authorization))
name = "github-trace-export"
subprocess.run([
    "docker", "run", "--detach", "--name", name,
    "--publish", "127.0.0.1:19418:19418",
    "--env", "OTEL_EXPORTER_OTLP_ENDPOINT", "--env", "GRAFANA_AUTHORIZATION",
    "--mount", f"type=bind,source={Path('collector.yaml').resolve()},target=/etc/otelcol-contrib/config.yaml,readonly",
    "otel/opentelemetry-collector-contrib:0.164.0",
], env=env, check=True, stdout=subprocess.DEVNULL)
try:
    subprocess.run([
        "curl", "--silent", "--show-error", "--fail", "--retry", "20",
        "--retry-delay", "1", "--retry-all-errors", "--retry-max-time", "60",
        "http://127.0.0.1:19418/health",
    ], check=True, stdout=subprocess.DEVNULL)
    events = [("workflow_run", {"action": "completed", "repository": repo, "workflow_run": run})]
    events += [("workflow_job", {"action": "completed", "repository": repo, "workflow_job": job}) for job in jobs]
    for kind, payload in events:
        request = urllib.request.Request(
            "http://127.0.0.1:19418/events", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "X-GitHub-Event": kind}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            assert response.status in (200, 202), response.status
        print(f"Accepted {kind} event")
finally:
    subprocess.run(["docker", "stop", "--time", "20", name], check=True, stdout=subprocess.DEVNULL)
    logs = subprocess.check_output(["docker", "logs", name], stderr=subprocess.STDOUT).decode()
    assert '"level":"error"' not in logs and '"level": "error"' not in logs, "Collector reported an error"
    subprocess.run(["docker", "rm", name], check=True, stdout=subprocess.DEVNULL)
print(f"Exported workflow {run_id}, attempt {attempt}, {len(jobs)} jobs")
