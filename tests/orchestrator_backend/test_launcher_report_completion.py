from app.services import launcher


REPORT_TEMPLATE = """# Penetration Test Report

## Executive Summary
{summary}

## Methodology
The agent performed recon, collection, consume/test, exploit, and report phases.

## Findings
{findings}

## Attack Path Narrative
No exploitable attack path was confirmed during this engagement.

## Appendix
Artifacts and queue coverage are recorded in the engagement workspace.
"""


def test_no_confirmed_vulnerabilities_report_counts_as_substantive():
    report = REPORT_TEMPLATE.format(
        summary="No confirmed vulnerabilities were recorded in findings.md.",
        findings="No confirmed vulnerabilities were recorded in findings.md.",
    )

    assert launcher._report_has_substantive_content(report)


def test_legacy_no_confirmed_findings_phrase_still_counts_as_substantive():
    report = REPORT_TEMPLATE.format(
        summary="No confirmed findings were recorded in findings.md.",
        findings="No confirmed findings were recorded in findings.md.",
    )

    assert launcher._report_has_substantive_content(report)


def test_report_without_no_finding_phrase_or_finding_sections_is_not_substantive():
    report = REPORT_TEMPLATE.format(
        summary="The engagement produced a report shell.",
        findings="Findings are pending.",
    )

    assert not launcher._report_has_substantive_content(report)
