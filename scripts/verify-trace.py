#!/usr/bin/env python3
"""Check observed Tempo span IDs and ancestry, not just the workflow exit code."""
import argparse
import base64
import collections
import json
import re
from pathlib import Path


def identifier(value):
    if not value:
        return ""
    if re.fullmatch(r"[0-9a-fA-F]{16}|[0-9a-fA-F]{32}", value):
        return value.lower()
    return base64.b64decode(value).hex()


def attributes(items):
    return {item["key"]: next(iter(item["value"].values())) for item in items}


def has_label(span, label):
    return span["name"] == label or label in span["attributes"].values()


parser = argparse.ArgumentParser()
parser.add_argument("trace", type=Path)
parser.add_argument("--mode", choices=["baseline", "linked"], required=True)
args = parser.parse_args()
data = json.loads(args.trace.read_text())
trace = data.get("trace", data)
spans = []
for resource in trace["resourceSpans"]:
    service = attributes(resource.get("resource", {}).get("attributes", [])).get("service.name", "")
    for scope in resource.get("scopeSpans", []):
        for span in scope["spans"]:
            spans.append({
                "id": identifier(span["spanId"]),
                "parent": identifier(span.get("parentSpanId", "")),
                "trace": identifier(span["traceId"]),
                "name": span["name"],
                "service": service,
                "attributes": attributes(span.get("attributes", [])),
            })

trace_ids = {span["trace"] for span in spans}
assert len(trace_ids) == 1, "More than one trace ID in the response"
by_id = {span["id"]: span for span in spans}
roots = [span for span in by_id.values() if not span["parent"] or set(span["parent"]) == {"0"}]
missing = [span for span in by_id.values() if span["parent"] and set(span["parent"]) != {"0"} and span["parent"] not in by_id]
builds = [span for span in by_id.values() if span["name"] == "build ."]
assert len(builds) == 1, f"Expected one build span, found {len(builds)}"
assert any(span["service"] == "buildkitd" for span in spans), "No BuildKit spans"

def ancestry(current):
    path = []
    while current:
        assert current["id"] not in {span["id"] for span in path}, "Parent cycle"
        path.append(current)
        current = by_id.get(current["parent"])
    return path


path = ancestry(builds[0])

result = {
    "mode": args.mode,
    "traceId": next(iter(trace_ids)),
    "spanCount": len(spans),
    "uniqueSpanCount": len(by_id),
    "services": dict(collections.Counter(span["service"] for span in spans)),
    "roots": [{k: span[k] for k in ["id", "name", "service"]} for span in roots],
    "missingParentCount": len(missing),
    "buildAncestry": [{k: span[k] for k in ["id", "parent", "name", "service"]} for span in reversed(path)],
}

if args.mode == "baseline":
    assert builds[0] in roots, "Baseline build is unexpectedly nested"
else:
    assert len(roots) == 1, f"Expected one workflow root, found {len(roots)}"
    assert not missing, f"Missing parents: {len(missing)}"
    assert has_label(path[-1], "BuildKit linked trace"), "Build does not reach the workflow root"
    assert any(has_label(span, "Build Docker image") for span in path[1:]), "No Actions build step in ancestry"
    assert any(has_label(span, "build") for span in path[1:]), "No build job in ancestry"
    second_job = next((span for span in by_id.values() if has_label(span, "verify-source")), None)
    assert second_job, "Second job absent from trace"
    assert ancestry(second_job)[-1]["id"] == roots[0]["id"], "Second job has a different root"
    dockerfile_step = next((span for span in by_id.values() if span["service"] == "buildkitd" and "RUN cat message.txt" in span["name"]), None)
    assert dockerfile_step, "Dockerfile RUN span absent"
    dockerfile_path = ancestry(dockerfile_step)
    assert builds[0]["id"] in {span["id"] for span in dockerfile_path}, "Dockerfile step does not descend from build ."
    result["dockerfileAncestry"] = [{k: span[k] for k in ["id", "parent", "name", "service"]} for span in reversed(dockerfile_path)]
    result["secondJobRootVerified"] = True

result["passed"] = True
print(json.dumps(result, indent=2))
