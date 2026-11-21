"""Map source records without cleaning text or claiming snapshot verification."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any

from ..domain.contracts import (
    KnowledgeBaseValidationError,
    SourceRecord,
    canonical_json_bytes,
    parse_json_object,
)


_DEFAULT_MAPPING = {
    "id": "id", "title": "title", "text": "text",
    "source_name": "source_name", "source_url": "source_url",
    "updated_at": "updated_at", "category": "category",
}
_CDC_STATEMENT = (
    "依 CDC 政府網站資料開放宣告與著作權聲明保留來源署名；"
    "個人資料、第三方內容及特別標示資料依各自條件處理；不得暗示 CDC 背書。"
)


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        raise KnowledgeBaseValidationError(f"{label} must be an object with string keys")
    return dict(value)


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeBaseValidationError(f"{label} must be a nonempty string")
    return value


def _digest(content: str) -> str:
    try:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
    except UnicodeError as error:
        raise KnowledgeBaseValidationError("content contains invalid Unicode") from error


def _provenance(*, publisher, locator, attribution, rights, content, updated=None,
                collected=None, snapshot=None, snapshot_digest=None,
                basis="text_utf8_v1") -> dict[str, Any]:
    return {
        "publisher": publisher, "source_locator": locator,
        "source_updated_at": updated, "collected_at_utc": collected,
        "raw_content_sha256": _digest(content), "raw_content_hash_basis": basis,
        "raw_snapshot": snapshot, "raw_snapshot_sha256": snapshot_digest,
        "attribution": attribution, "rights": deepcopy(rights),
    }


def _read_jsonl(path: str | Path, adapter) -> Iterator[SourceRecord]:
    source = Path(path)
    try:
        with source.open("rb") as stream:
            for line_number, raw in enumerate(stream, 1):
                try:
                    text = raw.decode("utf-8")
                    if text.startswith("\ufeff"):
                        raise KnowledgeBaseValidationError("UTF-8 BOM is not allowed")
                    yield adapter.adapt(parse_json_object(text))
                except (UnicodeError, KnowledgeBaseValidationError) as error:
                    raise KnowledgeBaseValidationError(
                        f"{source}: line {line_number}: {error}"
                    ) from error
    except OSError as error:
        raise KnowledgeBaseValidationError(f"{source}: cannot read JSONL: {error}") from error


class GenericJsonlAdapter:
    """Configurable top-level field mapping; unused source fields stay nested."""

    def __init__(self, *, dataset_id: str, attribution: str,
                 rights: Mapping[str, Any], mapping: Mapping[str, str] | None = None,
                 document_type: str = "plain_text", content_type: str = "text/plain",
                 cleaning_profile: str = "plain_v1", language: str = "und",
                 collected_at_utc: str | None = None):
        effective = dict(_DEFAULT_MAPPING)
        if mapping is not None:
            overrides = _object(mapping, "mapping")
            try:
                canonical_json_bytes(overrides)
            except KnowledgeBaseValidationError as error:
                raise KnowledgeBaseValidationError(f"mapping: {error}") from error
            unknown = overrides.keys() - effective.keys()
            if unknown:
                raise KnowledgeBaseValidationError(f"unknown mapping fields: {sorted(unknown)}")
            for logical, source in overrides.items():
                effective[logical] = _string(source, f"mapping.{logical}")
        if len(set(effective.values())) != len(effective):
            raise KnowledgeBaseValidationError("mapping source keys must be unique")
        self._mapping = effective
        self._settings = {
            "schema_version": "1.0", "dataset_id": dataset_id,
            "document_type": document_type, "content_type": content_type,
            "cleaning_profile": cleaning_profile, "language": language,
        }
        # Reuse the domain validator for settings, including rights and profile pairing.
        validated = SourceRecord.from_dict({
            **self._settings, "source_record_id": "configuration-check",
            "title": "configuration", "content": "configuration",
            "provenance": _provenance(
                publisher="configuration", locator="fixture:configuration",
                attribution=attribution, rights=_object(rights, "rights"),
                content="configuration", collected=collected_at_utc,
            ),
        }).to_dict()
        self._provenance = validated["provenance"]

    def adapt(self, record: Mapping[str, Any]) -> SourceRecord:
        raw = _object(record, "record")
        values = {logical: raw.get(key) for logical, key in self._mapping.items()}
        content = _string(values["text"], self._mapping["text"])
        provenance = deepcopy(self._provenance)
        provenance.update({
            "publisher": values["source_name"], "source_locator": values["source_url"],
            "source_updated_at": values["updated_at"],
            "raw_content_sha256": _digest(content),
        })
        metadata: dict[str, Any] = {}
        if self._mapping["category"] in raw:
            metadata["source_category"] = values["category"]
        unused = {key: value for key, value in raw.items() if key not in self._mapping.values()}
        if unused:
            metadata["source_fields"] = unused
        return SourceRecord.from_dict({
            **self._settings, "source_record_id": values["id"],
            "title": values["title"], "content": content,
            "provenance": provenance, "attachments": [], "metadata": metadata,
        })

    def read_jsonl(self, path: str | Path) -> Iterator[SourceRecord]:
        return _read_jsonl(path, self)


class CdcQaAdapter:
    """Map collected CDC QA and manifest evidence; never read raw HTML files."""

    def __init__(self, manifest: Mapping[str, Any], *, intended_use: str,
                 usage_decision: str, dataset_id: str = "tw_cdc_hiv_qa",
                 rights_statement: str = _CDC_STATEMENT):
        self._manifest = deepcopy(_object(manifest, "manifest"))
        pages = self._manifest.get("pages")
        if not isinstance(pages, list):
            raise KnowledgeBaseValidationError("manifest.pages must be an array")
        self._snapshots: dict[tuple[str, str], str] = {}
        snapshot_digests: dict[str, str] = {}
        for item in pages:
            page = _object(item, "manifest.pages entry")
            if page.get("raw_snapshot") is None:
                continue
            key = (_string(page.get("url"), "manifest.pages.url"),
                   _string(page["raw_snapshot"], "manifest.pages.raw_snapshot"))
            digest = _string(page.get("html_sha256"), "manifest.pages.html_sha256")
            if key[1] in snapshot_digests and snapshot_digests[key[1]] != digest:
                raise KnowledgeBaseValidationError("conflicting manifest snapshot hashes")
            snapshot_digests[key[1]] = digest
            self._snapshots[key] = digest
        policies = self._manifest.get("reuse_policy_urls")
        if not isinstance(policies, list) or any(not isinstance(p, str) for p in policies):
            raise KnowledgeBaseValidationError("manifest.reuse_policy_urls must be a string array")
        evidence = self._manifest.get("policy_provenance", [])
        if not isinstance(evidence, list) or any(not isinstance(p, Mapping) for p in evidence):
            raise KnowledgeBaseValidationError("manifest.policy_provenance must be an object array")
        self._settings = {
            "schema_version": "1.0", "dataset_id": dataset_id,
            "document_type": "faq", "content_type": "text/html",
            "cleaning_profile": "cdc_faq_html_v1", "language": "zh-Hant",
        }
        validated = SourceRecord.from_dict({
            **self._settings, "source_record_id": "configuration-check",
            "title": "configuration", "content": "configuration",
            "provenance": _provenance(
                publisher="衛生福利部疾病管制署", locator="fixture:configuration",
                attribution=self._manifest.get("attribution"), content="configuration",
                rights={"status": "recorded", "statement": rights_statement,
                        "policy_locators": sorted(set(policies)),
                        "intended_use": intended_use, "usage_decision": usage_decision},
            ),
            "metadata": {"policy_provenance": evidence},
        }).to_dict()
        self._provenance = validated["provenance"]
        for (_url, snapshot), digest in self._snapshots.items():
            SourceRecord.from_dict({
                **validated,
                "provenance": {**self._provenance, "raw_snapshot": snapshot,
                               "raw_snapshot_sha256": digest},
            })

    def adapt(self, record: Mapping[str, Any]) -> SourceRecord:
        raw = _object(record, "record")
        title = _string(raw.get("question"), "question")
        content = _string(raw.get("answer_html"), "answer_html")
        expected = _digest(title + "\n" + content)
        if raw.get("content_sha256") != expected:
            raise KnowledgeBaseValidationError("content_sha256 does not match CDC QA payload")
        snapshot = raw.get("raw_snapshot")
        snapshot_digest = None
        if snapshot is not None:
            key = (_string(raw.get("page_url"), "page_url"),
                   _string(snapshot, "raw_snapshot"))
            if key not in self._snapshots:
                raise KnowledgeBaseValidationError("raw_snapshot has no matching manifest page")
            snapshot_digest = self._snapshots[key]
        provenance = deepcopy(self._provenance)
        provenance.update({
            "source_locator": raw.get("source_url"),
            "source_updated_at": raw.get("source_updated_at"),
            "collected_at_utc": raw.get("collected_at_utc"),
            "raw_content_sha256": raw["content_sha256"],
            "raw_content_hash_basis": "cdc_qa_payload_v1",
            "raw_snapshot": snapshot, "raw_snapshot_sha256": snapshot_digest,
        })
        source_attachments = raw.get("attachments", [])
        if not isinstance(source_attachments, list):
            raise KnowledgeBaseValidationError("attachments must be an array")
        attachments = []
        for item in source_attachments:
            attachment = _object(item, "attachment")
            label = attachment.get("label")
            if label is not None:
                _string(label, "attachment.label")
            attachments.append({
                "locator": _string(attachment.get("url"), "attachment.url"), "title": label,
                "media_type": None, "included": False,
            })
        attachments.sort(key=lambda a: (a["locator"], a["title"] or ""))
        metadata = {key: raw[key] for key in
                    ("page_url", "source_anchor", "source_faq_id", "answer_text") if key in raw}
        if "category" in raw:
            metadata["source_category"] = raw["category"]
        metadata["source_attachments"] = source_attachments
        metadata["policy_provenance"] = self._manifest.get("policy_provenance", [])
        consumed = {"id", "question", "answer_html", "source_url", "source_updated_at",
                    "collected_at_utc", "content_sha256", "raw_snapshot", "attachments",
                    "category", "page_url", "source_anchor", "source_faq_id", "answer_text"}
        unused = {key: value for key, value in raw.items() if key not in consumed}
        if unused:
            metadata["source_fields"] = unused
        return SourceRecord.from_dict({
            **self._settings, "source_record_id": raw.get("id"),
            "title": title, "content": content, "provenance": provenance,
            "attachments": attachments, "metadata": metadata,
        })

    def read_jsonl(self, path: str | Path) -> Iterator[SourceRecord]:
        return _read_jsonl(path, self)
