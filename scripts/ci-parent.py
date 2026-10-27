#!/usr/bin/env python3
"""Match githubreceiver v0.164.0's deterministic trace and step span IDs."""
import hashlib
import json
import os
import subprocess

run = os.environ["GITHUB_RUN_ID"]
attempt = os.environ["GITHUB_RUN_ATTEMPT"]
repository = os.environ["GITHUB_REPOSITORY"]
jobs = json.loads(subprocess.check_output([
    "gh", "api", f"repos/{repository}/actions/runs/{run}/attempts/{attempt}/jobs?per_page=100"
]))["jobs"]
matches = [job for job in jobs if job["name"] == os.environ["GITHUB_JOB"]]
assert len(matches) == 1, "Expected one job matching GITHUB_JOB; matrix jobs need explicit resolution"
job_id = matches[0]["id"]
trace_id = hashlib.sha256(f"{run}{attempt}t".encode()).hexdigest()[:32]
step_id = hashlib.sha256(f"{job_id}-Build Docker image-s".encode()).hexdigest()[16:32]
traceparent = f"00-{trace_id}-{step_id}-01"
with open(os.environ["GITHUB_OUTPUT"], "a") as output:
    output.write(f"traceparent={traceparent}\n")
print(f"TRACEPARENT={traceparent}")
