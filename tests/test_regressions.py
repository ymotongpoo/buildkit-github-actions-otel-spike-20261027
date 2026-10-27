"""Regression cases from the article review; no GitHub or Cloud writes."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def trace_fixture():
    groups = {"github-actions": [], "buildx": [], "buildkitd": []}

    def add(service, ident, parent, name):
        groups[service].append({
            "traceId": "a" * 32, "spanId": f"{ident:016x}",
            "parentSpanId": f"{parent:016x}" if parent else "", "name": name,
        })

    add("github-actions", 1, 0, "BuildKit linked trace")
    add("github-actions", 2, 1, "build")
    add("github-actions", 3, 2, "Build Docker image")
    add("github-actions", 6, 1, "verify-source")
    add("buildx", 4, 3, "build .")
    add("buildkitd", 5, 4, "[4/4] RUN cat message.txt > result.txt")
    return {"resourceSpans": [
        {"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]},
         "scopeSpans": [{"spans": spans}]}
        for service, spans in groups.items()
    ]}


class TraceVerifierTests(unittest.TestCase):
    def verify(self, data):
        with tempfile.TemporaryDirectory(prefix="buildkit-verifier-") as tmp:
            path = Path(tmp) / "trace.json"
            path.write_text(json.dumps(data))
            return subprocess.run(
                ["python3", str(ROOT / "scripts/verify-trace.py"), str(path), "--mode", "linked"],
                capture_output=True, text=True,
            )

    def test_connected_trace_passes(self):
        result = self.verify(trace_fixture())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["passed"])

    def test_duplicate_id_fails(self):
        data = trace_fixture()
        spans = data["resourceSpans"][0]["scopeSpans"][0]["spans"]
        spans.append(copy.deepcopy(spans[0]))
        result = self.verify(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Duplicate span IDs", result.stderr)

    def test_detached_cycle_fails(self):
        data = trace_fixture()
        spans = data["resourceSpans"][0]["scopeSpans"][0]["spans"]
        spans.extend([
            {"traceId": "a" * 32, "spanId": "1" * 16, "parentSpanId": "2" * 16, "name": "A"},
            {"traceId": "a" * 32, "spanId": "2" * 16, "parentSpanId": "1" * 16, "name": "B"},
        ])
        result = self.verify(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Parent cycle", result.stderr)

    def test_missing_parent_fails(self):
        data = trace_fixture()
        data["resourceSpans"][-1]["scopeSpans"][0]["spans"][0]["parentSpanId"] = "f" * 16
        result = self.verify(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing parents", result.stderr)


class WorkflowExporterTests(unittest.TestCase):
    def execute(self, *, run_attempt=1, job_attempt=1, logs='{"level":"info"}\n'):
        calls, posts = [], []
        job = {"id": 100, "run_id": 42, "run_attempt": job_attempt, "status": "completed"}

        def output(args, **kwargs):
            calls.append(args)
            if args[0] == "gh":
                path = args[-1]
                if path.endswith("/attempts/1/jobs?per_page=100"):
                    return json.dumps([{"jobs": [job]}]).encode()
                if path.endswith("/actions/runs/42/attempts/1"):
                    return json.dumps({"id": 42, "run_attempt": run_attempt, "status": "completed"}).encode()
                if path == "repos/owner/repo":
                    return b'{"full_name":"owner/repo"}'
                self.fail("Unexpected API path: " + path)
            self.assertEqual(args[:2], ["docker", "logs"])
            return logs.encode()

        def command(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0)

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def request(req, **kwargs):
            posts.append(json.loads(req.data))
            return Response()

        environment = {
            "GITHUB_REPOSITORY": "owner/repo", "OBSERVED_RUN_ID": "42",
            "OBSERVED_RUN_ATTEMPT": "1", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:1/otlp",
            "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Basic synthetic-test-value",
        }
        failure = None
        with patch.dict(os.environ, environment, clear=True), \
             patch("subprocess.check_output", output), patch("subprocess.run", command), \
             patch("urllib.request.urlopen", request), contextlib.redirect_stdout(io.StringIO()):
            try:
                runpy.run_path(str(ROOT / "scripts/export-workflow.py"), run_name="__main__")
            except (AssertionError, json.JSONDecodeError) as exc:
                failure = exc
        return calls, posts, failure

    def test_notified_attempt_is_used(self):
        calls, posts, failure = self.execute()
        self.assertIsNone(failure)
        paths = [call[-1] for call in calls if call[0] == "gh"]
        self.assertIn("repos/owner/repo/actions/runs/42/attempts/1", paths)
        self.assertNotIn("repos/owner/repo/actions/runs/42", paths)
        self.assertEqual(posts[0]["workflow_run"]["run_attempt"], 1)
        self.assertEqual(posts[1]["workflow_job"]["run_attempt"], 1)

    def test_other_run_attempt_is_rejected_before_container_start(self):
        calls, posts, failure = self.execute(run_attempt=2)
        self.assertIsInstance(failure, AssertionError)
        self.assertEqual(posts, [])
        self.assertFalse(any(call[:2] == ["docker", "run"] for call in calls))

    def test_other_job_attempt_is_rejected_before_container_start(self):
        calls, posts, failure = self.execute(job_attempt=2)
        self.assertIsInstance(failure, AssertionError)
        self.assertEqual(posts, [])
        self.assertFalse(any(call[:2] == ["docker", "run"] for call in calls))

    def test_export_error_fails_and_removes_container(self):
        calls, posts, failure = self.execute(logs='{"level": "error", "msg":"Exporting failed"}\n')
        self.assertIsInstance(failure, AssertionError)
        self.assertIn("Collector reported an error", str(failure))
        self.assertIn(["docker", "rm", "--force", "github-trace-export"], calls)

    def test_non_json_logs_fail_and_remove_container(self):
        calls, posts, failure = self.execute(logs="timestamp\terror\tExporting failed\n")
        self.assertIsInstance(failure, json.JSONDecodeError)
        self.assertIn(["docker", "rm", "--force", "github-trace-export"], calls)


if __name__ == "__main__":
    unittest.main()
