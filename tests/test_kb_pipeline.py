"""Application-level build, merge, and run validation contracts."""

from copy import deepcopy

import pytest

from clinical_warrant.modules.knowledge_base.application.pipeline import (
    PipelineFailure,
    build_run,
    merge_runs,
    validate_run,
)
from clinical_warrant.modules.knowledge_base.domain.policies import CleanedContent, QualityPolicy
from clinical_warrant.modules.knowledge_base.domain.runs import SourceInput
from clinical_warrant.modules.knowledge_base.infrastructure.adapters import GenericJsonlAdapter


RIGHTS = {
    "status": "recorded", "statement": "Fixture rights statement.",
    "policy_locators": [], "intended_use": "fixture_validation", "usage_decision": "allowed",
}
CHUNKING = {"algorithm_version": "structure-v1", "max_chars": 80, "overlap_chars": 4}


def cleaner(source):
    return CleanedContent(source.title, source.content, (), "pipeline-fixture-v1")


def make_input(record_id, *, dataset="fixture", text="A short answer.", rights=None, locator=None):
    adapter = GenericJsonlAdapter(dataset_id=dataset, attribution="Fixture", rights=rights or RIGHTS)
    source = adapter.adapt({
        "id": record_id, "title": f"Title {record_id}", "text": text,
        "source_name": "Fixture publisher", "source_url": locator or f"fixture:{dataset}/{record_id}",
        "updated_at": "2026-11-20", "category": "test",
    })
    return SourceInput("fixture.jsonl", 1, {"id": record_id, "text": text}, source)


def build(inputs, *, as_of="2026-11-22", strict=False, config=None):
    return build_run(
        inputs, cleaner=cleaner,
        policy=QualityPolicy(as_of=as_of, stale_after_days=30),
        chunking_config=config or CHUNKING, strict=strict,
        run_metadata={"adapter": "generic_jsonl", "source_root": "fixture"},
    )


def test_build_reconciles_preparation_rejection_and_exact_duplicates():
    good = make_input("one")
    malformed = SourceInput("fixture.jsonl", 2, {"bad": True}, None,
                            "missing required fields", "invalid_source_record")
    run = build([good, good, malformed])

    assert len(run.documents) == len(run.chunks) == 1
    assert len(run.rejected) == 1
    assert run.quality_report["input_count"] == 3
    assert run.quality_report["duplicate_count"] == 1
    assert run.quality_report["input_count"] == (
        run.quality_report["document_count"] + run.quality_report["rejected_count"]
        + run.quality_report["duplicate_count"]
    )
    assert run.rejected[0]["raw_record"] == {"bad": True}
    validate_run(run)


def test_strict_build_fails_with_rejected_row_diagnostics():
    malformed = SourceInput("fixture.jsonl", 3, {"bad": True}, None,
                            "missing required fields", "invalid_source_record")
    with pytest.raises(PipelineFailure) as caught:
        build([make_input("one"), malformed], strict=True)
    assert caught.value.rejected[0]["line_number"] == 3
    assert caught.value.issues[0]["code"] == "invalid_source_record"


def test_merge_strict_rejects_errors_from_previously_nonstrict_build():
    malformed = SourceInput("fixture.jsonl", 3, {"bad": True}, None,
                            "missing required fields", "invalid_source_record")
    partial = build([make_input("one"), malformed])
    with pytest.raises(PipelineFailure, match="strict merge"):
        merge_runs([partial], strict=True)
    forged = deepcopy(partial.manifest)
    forged["strict"] = True
    object.__setattr__(partial, "manifest", forged)
    with pytest.raises(Exception, match="strict build run"):
        validate_run(partial)


def test_identity_conflict_fails_even_when_build_is_non_strict():
    first = make_input("same", text="First version.")
    second = make_input("same", text="Second version.")
    with pytest.raises(PipelineFailure, match="identity conflicts") as caught:
        build([first, second])
    assert {issue["code"] for issue in caught.value.issues} == {"version_conflict"}


def test_merge_quarantines_nonready_docs_and_preserves_each_input_policy():
    ready = build([make_input("ready")], as_of="2026-11-22")
    excluded_rights = {**RIGHTS, "usage_decision": "prohibited"}
    excluded = build([make_input("excluded", rights=excluded_rights)], as_of="2026-11-23")

    merged = merge_runs([excluded, ready], run_metadata={"adapter": "merge"})

    assert [document.document_id for document in merged.documents] == ["fixture:ready"]
    assert len(merged.chunks) == len(ready.chunks)
    quarantine = merged.quality_report["quarantined_documents"]
    assert [(row["document_id"], row["reason"], row["count"]) for row in quarantine] == [
        ("fixture:excluded", "rights_not_approved", 1)
    ]
    policies = merged.manifest["quality_policy"]["input_run_policies"]
    assert {entry["quality_policy"]["as_of"] for entry in policies} == {"2026-11-22", "2026-11-23"}
    assert len(merged.quality_report["input_runs"]) == 2
    validate_run(merged)


def test_merge_rejects_different_chunking_configs():
    first = build([make_input("one")])
    second = build([make_input("two")], config={**CHUNKING, "max_chars": 81})
    with pytest.raises(PipelineFailure, match="different chunking"):
        merge_runs([first, second])


def test_merge_validator_reconciles_manifest_input_summaries_and_quarantine():
    ready = build([make_input("ready")])
    excluded = build([make_input("excluded", rights={**RIGHTS, "usage_decision": "prohibited"})])
    merged = merge_runs([ready, excluded])
    forged = deepcopy(merged.manifest)
    forged["input_summaries"][0]["document_count"] += 1
    object.__setattr__(merged, "manifest", forged)
    with pytest.raises(Exception, match="input_summaries"):
        validate_run(merged)


def test_merge_duplicate_quarantined_document_counts_occurrences_and_unique_identity():
    excluded = build([make_input("excluded", rights={**RIGHTS, "usage_decision": "prohibited"})])
    merged = merge_runs([excluded, excluded])
    report = merged.quality_report
    assert report["input_document_count"] == 2
    assert report["duplicate_count"] == 1
    assert report["quarantine_count"] == 2
    assert len(report["quarantined_documents"]) == 2
    validate_run(merged)


def test_validator_checks_complete_manifest_evidence_shape_and_timestamps():
    run = build([make_input("one")])
    forged = deepcopy(run.manifest)
    forged.update({
        "complete": True, "adapter": {"type": "generic_jsonl", "mapping": {"id": "id"},
                                       "settings": {"dataset_id": "fixture"},
                                       "provenance": {"rights": {}}}, "source_root": None,
        "inputs": [{"path": "fixture.jsonl", "role": "input", "sha256": "z" * 64}],
        "started_at_utc": "2026-11-22T00:00:00Z", "completed_at_utc": "2026-11-22T00:00:01Z",
    })
    object.__setattr__(run, "manifest", forged)
    with pytest.raises(Exception, match="evidence"):
        validate_run(run)


def test_validator_recomputes_chunks_and_rejects_tampered_report():
    run = build([make_input("one", text="Sentence one. Sentence two.")])
    changed = deepcopy(run.quality_report)
    changed["source_counts"] = {"forged": 99}
    object.__setattr__(run, "quality_report", changed)
    with pytest.raises(Exception, match="source_counts"):
        validate_run(run)

