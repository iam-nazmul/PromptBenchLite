"""JUnit XML: one testcase per golden case plus one per gated metric."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from promptbench.pipeline import RunOutcome
from promptbench.scoring import Status


def render_junit(outcome: RunOutcome) -> str:
    root = ET.Element("testsuites", name="promptbench")
    for result, verdict in zip(outcome.results, outcome.verdict.suites, strict=True):
        ts = ET.SubElement(root, "testsuite", name=result.suite)
        tests = failures = errors = skipped = 0
        for case in result.cases:
            tests += 1
            tc = ET.SubElement(
                ts, "testcase", classname=result.suite, name=case.case_id, time=f"{case.output.latency_s:.3f}"
            )
            errored = [s for s in case.scores if s.errored]
            failed = [s for s in case.scores if s.passed is False]
            if errored:
                errors += 1
                ET.SubElement(tc, "error", message="; ".join(f"{s.key}: {s.error}" for s in errored))
            elif failed:
                failures += 1
                ET.SubElement(
                    tc, "failure", message="; ".join(f"{s.key}: {s.comment or s.value}" for s in failed)
                )
        for case_id in result.skipped:
            tests += 1
            skipped += 1
            tc = ET.SubElement(ts, "testcase", classname=result.suite, name=case_id)
            ET.SubElement(tc, "skipped")
        for m in verdict.metrics:
            tests += 1
            tc = ET.SubElement(ts, "testcase", classname=f"{result.suite}.gate", name=m.key)
            if m.status is Status.FAIL:
                failures += 1
                ET.SubElement(tc, "failure", message=m.reason)
        ts.set("tests", str(tests))
        ts.set("failures", str(failures))
        ts.set("errors", str(errors))
        ts.set("skipped", str(skipped))
    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True) + "\n"


def write_junit(outcome: RunOutcome, path: Path) -> None:
    path.write_text(render_junit(outcome), encoding="utf-8")
