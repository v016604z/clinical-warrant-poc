"""Validated, immutable schema-v1 entities; no cleaning or filesystem access."""

from __future__ import annotations

from dataclasses import MISSING, dataclass, field, fields
from datetime import date, datetime
from enum import Enum
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any, Mapping


class KnowledgeBaseValidationError(ValueError):
    """A contract violation, including the offending JSON field path."""


class DocumentType(str, Enum):
    FAQ = "faq"
    GUIDELINE_SECTION = "guideline_section"
    ARTICLE = "article"
    PLAIN_TEXT = "plain_text"


class ContentType(str, Enum):
    PLAIN = "text/plain"
    HTML = "text/html"


class QualityStatus(str, Enum):
    READY = "ready"
    NEEDS_REVIEW = "needs_review"
    EXCLUDED = "excluded"


class ReviewStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    APPROVED = "approved"
    REJECTED = "rejected"


def _fail(path: str, message: str) -> None:
    raise KnowledgeBaseValidationError(f"{path}: {message}")


def _text(value: Any, path: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str):
        _fail(path, "must be a string")
    if nonempty and not value.strip():
        _fail(path, "must not be empty")
    if "\x00" in value:
        _fail(path, "must not contain NUL")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise KnowledgeBaseValidationError(f"{path}: invalid Unicode") from error
    return value


def _json_value(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, str):
        _text(value, path, nonempty=False)
    elif isinstance(value, float):
        if not math.isfinite(value):
            _fail(path, "must be finite")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _text(key, path + ".<key>", nonempty=False)
            _json_value(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _json_value(item, f"{path}[{index}]")
    else:
        _fail(path, "must be a JSON value")


class _Pairs(list):
    pass


@dataclass(frozen=True)
class _Constant:
    name: str


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse an object while rejecting duplicate keys and nonstandard JSON."""
    _text(text, "$")
    if text.startswith("\ufeff"):
        _fail("$", "UTF-8 BOM is not permitted")
    try:
        raw = json.loads(text, object_pairs_hook=_Pairs, parse_constant=_Constant)
    except (ValueError, RecursionError) as error:
        raise KnowledgeBaseValidationError(f"$: invalid JSON: {error}") from error

    def unpack(value: Any, path: str) -> Any:
        if isinstance(value, _Constant):
            _fail(path, f"invalid JSON constant {value.name}")
        if isinstance(value, _Pairs):
            result: dict[str, Any] = {}
            for key, item in value:
                _text(key, path + ".<key>", nonempty=False)
                if key in result:
                    _fail(f"{path}.{key}", "duplicate key")
                result[key] = unpack(item, f"{path}.{key}")
            return result
        if isinstance(value, list):
            return [unpack(item, f"{path}[{index}]") for index, item in enumerate(value)]
        _json_value(value, path)
        return value

    try:
        result = unpack(raw, "$")
    except RecursionError as error:
        raise KnowledgeBaseValidationError("$: JSON nesting is too deep") from error
    if not isinstance(result, dict):
        _fail("$", "must be a JSON object")
    return result


def _object(value: Any, path: str, required: set[str], optional: set[str] | None = None) -> Mapping:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    _json_value(value, path)
    missing = required - value.keys()
    extra = value.keys() - required - (optional or set())
    if missing:
        _fail(path, "missing fields: " + ", ".join(sorted(missing)))
    if extra:
        _fail(path, "unexpected fields: " + ", ".join(sorted(extra)))
    return value


def _choice(value: Any, choices: set[str], path: str) -> str:
    _text(value, path)
    if value not in choices:
        _fail(path, "must be one of " + ", ".join(sorted(choices)))
    return value


def _integer(value: Any, path: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(path, f"must be an integer >= {minimum}")
    return value


def _digest(value: Any, path: str, prefix: str = "") -> None:
    _text(value, path)
    if not re.fullmatch(re.escape(prefix) + r"[0-9a-f]{64}", value):
        _fail(path, f"must be {prefix!r} followed by 64 lowercase hex characters")


def _dataset(value: Any, path: str) -> None:
    _text(value, path)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value):
        _fail(path, "invalid dataset namespace")


def _record_id(value: Any, path: str) -> None:
    _text(value, path)
    if any(ord(char) < 32 or 127 <= ord(char) < 160 for char in value):
        _fail(path, "must not contain control characters")


def _document_id(value: Any, path: str) -> tuple[str, str]:
    _text(value, path)
    namespace, separator, record = value.partition(":")
    if not separator:
        _fail(path, "must contain a dataset namespace and source record ID")
    _dataset(namespace, path + ".dataset_id")
    _record_id(record, path + ".source_record_id")
    return namespace, record


def _date(value: Any, path: str, *, utc: bool = False) -> None:
    if value is None:
        return
    _text(value, path)
    pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z" if utc else r"\d{4}-\d{2}-\d{2}"
    if not re.fullmatch(pattern, value):
        _fail(path, "must be an ISO UTC timestamp" if utc else "must be an ISO date")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ") if utc else date.fromisoformat(value)
    except ValueError as error:
        raise KnowledgeBaseValidationError(f"{path}: invalid date/time") from error


def _strings(value: Any, path: str) -> None:
    if not isinstance(value, (list, tuple)):
        _fail(path, "must be an array")
    for index, item in enumerate(value):
        _text(item, f"{path}[{index}]")
    if list(value) != sorted(set(value)):
        _fail(path, "must be sorted and unique")


def _rights(value: Any, path: str) -> None:
    obj = _object(value, path, {"status", "statement", "policy_locators", "intended_use", "usage_decision"})
    _choice(obj["status"], {"recorded", "unknown"}, path + ".status")
    _choice(obj["usage_decision"], {"allowed", "unknown", "prohibited"}, path + ".usage_decision")
    _text(obj["statement"], path + ".statement")
    _text(obj["intended_use"], path + ".intended_use")
    _strings(obj["policy_locators"], path + ".policy_locators")


PROVENANCE_FIELDS = {
    "publisher", "source_locator", "source_updated_at", "collected_at_utc",
    "raw_content_sha256", "raw_content_hash_basis", "raw_snapshot", "raw_snapshot_sha256",
    "attribution", "rights",
}


def _provenance(value: Any, path: str, *, source: bool = False) -> None:
    obj = _object(value, path, PROVENANCE_FIELDS | ({"dataset_id", "source_record_id"} if source else set()))
    for name in ("publisher", "source_locator", "attribution"):
        _text(obj[name], f"{path}.{name}")
    _date(obj["source_updated_at"], path + ".source_updated_at")
    _date(obj["collected_at_utc"], path + ".collected_at_utc", utc=True)
    _digest(obj["raw_content_sha256"], path + ".raw_content_sha256")
    _choice(obj["raw_content_hash_basis"], {"cdc_qa_payload_v1", "text_utf8_v1"}, path + ".raw_content_hash_basis")
    snapshot, digest = obj["raw_snapshot"], obj["raw_snapshot_sha256"]
    if (snapshot is None) != (digest is None):
        _fail(path + ".raw_snapshot", "snapshot path and digest must both be null or present")
    if snapshot is not None:
        _text(snapshot, path + ".raw_snapshot")
        if snapshot.startswith("/") or "\\" in snapshot or ":" in snapshot or any(part in {"", ".", ".."} for part in snapshot.split("/")):
            _fail(path + ".raw_snapshot", "must be a relative path within the source root")
        _digest(digest, path + ".raw_snapshot_sha256")
    _rights(obj["rights"], path + ".rights")
    if source:
        _dataset(obj["dataset_id"], path + ".dataset_id")
        _record_id(obj["source_record_id"], path + ".source_record_id")


def _attachments(value: Any, path: str) -> None:
    if not isinstance(value, (list, tuple)):
        _fail(path, "must be an array")
    keys = []
    for index, item in enumerate(value):
        where = f"{path}[{index}]"
        obj = _object(item, where, {"locator", "title", "media_type", "included"})
        _text(obj["locator"], where + ".locator")
        for name in ("title", "media_type"):
            if obj[name] is not None:
                _text(obj[name], where + "." + name)
        if type(obj["included"]) is not bool:
            _fail(where + ".included", "must be a boolean")
        keys.append((obj["locator"], obj["title"] or ""))
    if keys != sorted(set(keys)):
        _fail(path, "must be sorted and unique by locator and title")


def _metadata(value: Any, path: str) -> None:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    _json_value(value, path)
    if "supersedes" in value:
        _document_id(value["supersedes"], path + ".supersedes")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Return schema-v1 canonical JSON bytes without a trailing newline."""
    try:
        _json_value(value)
        return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except KnowledgeBaseValidationError:
        raise
    except (ValueError, RecursionError) as error:
        raise KnowledgeBaseValidationError(f"$: cannot encode JSON: {error}") from error


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def document_version_for(payload: Mapping[str, Any]) -> str:
    """Hash the exact semantic projection, excluding provenance and reviews."""
    names = {"document_type", "title", "content_text", "language", "attachments"}
    if not isinstance(payload, Mapping) or not names <= payload.keys():
        _fail("document", "missing semantic version fields")
    _choice(payload["document_type"], set(DocumentType), "document.document_type")
    for name in ("title", "content_text", "language"):
        _text(payload[name], "document." + name)
    _attachments(payload["attachments"], "document.attachments")
    return "sha256:" + canonical_sha256({name: payload[name] for name in names})


def chunking_fingerprint(config: Mapping[str, Any]) -> str:
    obj = _object(config, "chunking_config", {"algorithm_version", "max_chars", "overlap_chars"})
    _choice(obj["algorithm_version"], {"structure-v1"}, "chunking_config.algorithm_version")
    maximum = _integer(obj["max_chars"], "chunking_config.max_chars", 1)
    overlap = _integer(obj["overlap_chars"], "chunking_config.overlap_chars")
    if overlap >= maximum:
        _fail("chunking_config.overlap_chars", "must be less than max_chars")
    return canonical_sha256(obj)


def chunk_id_for(payload: Mapping[str, Any], config: Mapping[str, Any]) -> str:
    names = {"document_id", "document_version", "chunk_index", "char_start", "char_end"}
    if not isinstance(payload, Mapping) or not names <= payload.keys():
        _fail("chunk", "missing identity fields")
    _document_id(payload["document_id"], "chunk.document_id")
    _digest(payload["document_version"], "chunk.document_version", "sha256:")
    for name in ("chunk_index", "char_start", "char_end"):
        _integer(payload[name], "chunk." + name)
    if payload["char_end"] <= payload["char_start"]:
        _fail("chunk.char_end", "must be greater than char_start")
    return "chunk:" + canonical_sha256({**{name: payload[name] for name in names}, "chunking_fingerprint": chunking_fingerprint(config)})


class _Entity:
    @classmethod
    def from_dict(cls, value: Any):
        definitions = fields(cls)
        required = {field.name for field in definitions if field.default is MISSING and field.default_factory is MISSING}
        optional = {field.name for field in definitions} - required
        try:
            data = _object(value, cls.__name__, required, optional)
            return cls(**data)
        except RecursionError as error:
            raise KnowledgeBaseValidationError(f"{cls.__name__}: JSON nesting is cyclic or too deep") from error

    @classmethod
    def from_json(cls, text: str):
        return cls.from_dict(parse_json_object(text))

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _plain(getattr(self, field.name)) for field in fields(self)}

    def to_json(self) -> str:
        return canonical_json_bytes(self.to_dict()).decode("utf-8")

    def _seal(self) -> None:
        for field in fields(self):
            object.__setattr__(self, field.name, _freeze(getattr(self, field.name)))


@dataclass(frozen=True)
class SourceRecord(_Entity):
    schema_version: str
    dataset_id: str
    source_record_id: str
    document_type: str
    title: str
    content: str
    content_type: str
    provenance: Mapping[str, Any]
    language: str = "und"
    cleaning_profile: str = "plain_v1"
    attachments: tuple = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _choice(self.schema_version, {"1.0"}, "schema_version")
        _dataset(self.dataset_id, "dataset_id")
        _record_id(self.source_record_id, "source_record_id")
        _choice(self.document_type, set(DocumentType), "document_type")
        _choice(self.content_type, set(ContentType), "content_type")
        for name in ("title", "content", "language"):
            _text(getattr(self, name), name)
        profiles = {"plain_v1": "text/plain", "html_v1": "text/html", "cdc_faq_html_v1": "text/html"}
        _choice(self.cleaning_profile, set(profiles), "cleaning_profile")
        if profiles[self.cleaning_profile] != self.content_type or (self.cleaning_profile == "cdc_faq_html_v1" and self.document_type != "faq"):
            _fail("cleaning_profile", "is incompatible with content_type/document_type")
        _provenance(self.provenance, "provenance")
        raw = self.title + "\n" + self.content if self.provenance["raw_content_hash_basis"] == "cdc_qa_payload_v1" else self.content
        if hashlib.sha256(raw.encode("utf-8")).hexdigest() != self.provenance["raw_content_sha256"]:
            _fail("provenance.raw_content_sha256", "does not match the original payload")
        _attachments(self.attachments, "attachments")
        _metadata(self.metadata, "metadata")
        self._seal()


@dataclass(frozen=True)
class KnowledgeDocument(_Entity):
    schema_version: str
    document_id: str
    document_version: str
    document_type: str
    title: str
    content_text: str
    language: str
    source: Mapping[str, Any]
    metadata: Mapping[str, Any]
    attachments: tuple
    quality: Mapping[str, Any]

    def __post_init__(self) -> None:
        _choice(self.schema_version, {"1.0"}, "schema_version")
        namespace, record = _document_id(self.document_id, "document_id")
        _provenance(self.source, "source", source=True)
        if (namespace, record) != (self.source["dataset_id"], self.source["source_record_id"]):
            _fail("document_id", "does not match source identity")
        _choice(self.document_type, set(DocumentType), "document_type")
        for name in ("title", "content_text", "language"):
            _text(getattr(self, name), name)
        if "\n" in self.title or "\r" in self.title:
            _fail("title", "must be a normalized single line")
        prefix = f"問題：{self.title}\n回答：" if self.document_type == "faq" else self.title + "\n"
        if not self.content_text.startswith(prefix) or not self.content_text[len(prefix):].strip():
            _fail("content_text", "must contain the declared title prefix and a nonempty body")
        _attachments(self.attachments, "attachments")
        _metadata(self.metadata, "metadata")
        _digest(self.document_version, "document_version", "sha256:")
        if self.document_version != document_version_for(self.to_dict()):
            _fail("document_version", "does not match the semantic content")
        quality = _object(self.quality, "quality", {"status", "flags", "review_status", "review_ref"})
        _choice(quality["status"], set(QualityStatus), "quality.status")
        _choice(quality["review_status"], set(ReviewStatus), "quality.review_status")
        _strings(quality["flags"], "quality.flags")
        if quality["review_status"] == "unreviewed":
            if quality["review_ref"] is not None:
                _fail("quality.review_ref", "must be null for unreviewed documents")
        else:
            _text(quality["review_ref"], "quality.review_ref")
        rights = self.source["rights"]
        if rights["usage_decision"] == "prohibited":
            if quality["status"] != "excluded" or "rights_prohibited" not in quality["flags"]:
                _fail("quality", "prohibited use requires excluded and rights_prohibited")
        elif rights["status"] == "unknown" or rights["usage_decision"] == "unknown":
            if quality["status"] == "ready" or "rights_unknown" not in quality["flags"]:
                _fail("quality", "unknown rights must block readiness and carry rights_unknown")
        if "attachment_dependency" in quality["flags"] and quality["status"] == "ready" and quality["review_status"] != "approved":
            _fail("quality", "attachment dependency requires review before indexing")
        self._seal()

    def validate_review(self, review: Mapping[str, Any]) -> None:
        """Check a supplied audit record, not its file/ref or manifest hash.

        Callers remain responsible for resolving review_ref to the persisted,
        hash-verified record. This method neither loads files nor grants approval.
        """
        obj = _object(review, "review", {"document_id", "document_version", "source_fingerprint", "flags", "decision", "reviewer", "reviewed_at_utc", "reason"})
        for name in ("document_id", "document_version"):
            if obj[name] != getattr(self, name):
                _fail("review." + name, "does not match this document")
        _digest(obj["source_fingerprint"], "review.source_fingerprint")
        if obj["source_fingerprint"] != canonical_sha256(self.source):
            _fail("review.source_fingerprint", "does not match the current source/use")
        _strings(obj["flags"], "review.flags")
        _choice(obj["decision"], {"approved", "rejected"}, "review.decision")
        if obj["decision"] != self.quality["review_status"]:
            _fail("review.decision", "does not match quality.review_status")
        informational = {"cms_noise_removed", "exact_content_duplicate"}
        if obj["decision"] == "approved" and not (set(self.quality["flags"]) - informational) <= set(obj["flags"]):
            _fail("review.flags", "does not cover the document's review flags")
        _text(obj["reviewer"], "review.reviewer")
        _text(obj["reason"], "review.reason")
        if obj["reviewed_at_utc"] is None:
            _fail("review.reviewed_at_utc", "must not be null")
        _date(obj["reviewed_at_utc"], "review.reviewed_at_utc", utc=True)
        if obj["decision"] == "approved" and self.source["rights"]["usage_decision"] == "prohibited":
            _fail("review.decision", "cannot approve prohibited use")


@dataclass(frozen=True)
class KnowledgeChunk(_Entity):
    schema_version: str
    chunk_id: str
    document_id: str
    document_version: str
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    source_locator: str
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        _choice(self.schema_version, {"1.0"}, "schema_version")
        namespace, _ = _document_id(self.document_id, "document_id")
        _digest(self.document_version, "document_version", "sha256:")
        _digest(self.chunk_id, "chunk_id", "chunk:")
        for name in ("chunk_index", "char_start", "char_end"):
            _integer(getattr(self, name), name)
        if self.char_end <= self.char_start:
            _fail("char_end", "must be greater than char_start")
        _text(self.text, "text", nonempty=False)
        if not self.text:
            _fail("text", "must not be empty")
        if len(self.text) != self.char_end - self.char_start:
            _fail("text", "length does not match its code point interval")
        _text(self.source_locator, "source_locator")
        if not isinstance(self.metadata, Mapping):
            _fail("metadata", "must be an object")
        _json_value(self.metadata, "metadata")
        required = {"dataset_id", "document_type", "language", "source_updated_at", "source_category"}
        if not required <= self.metadata.keys():
            _fail("metadata", "missing index metadata fields")
        if self.metadata["dataset_id"] != namespace:
            _fail("metadata.dataset_id", "does not match document_id")
        _choice(self.metadata["document_type"], set(DocumentType), "metadata.document_type")
        _text(self.metadata["language"], "metadata.language")
        _date(self.metadata["source_updated_at"], "metadata.source_updated_at")
        if self.metadata["source_category"] is not None:
            _text(self.metadata["source_category"], "metadata.source_category")
        data = dict(self.metadata)
        data.setdefault("source_metadata", {})
        if not isinstance(data["source_metadata"], Mapping):
            _fail("metadata.source_metadata", "must be an object")
        object.__setattr__(self, "metadata", data)
        self._seal()

    def validate_reference(self, document: KnowledgeDocument, config: Mapping[str, Any]) -> None:
        """Verify supplied text/metadata/config, without chunking or audit I/O.

        An approved review still requires document.validate_review(audit) and
        run-level verification of review_ref and its manifest hash by the caller.
        """
        if not isinstance(document, KnowledgeDocument):
            _fail("document", "must be a KnowledgeDocument")
        if document.quality["status"] != "ready" or document.quality["review_status"] == "rejected":
            _fail("document.quality", "document is not eligible for indexing")
        if self.document_id != document.document_id or self.document_version != document.document_version:
            _fail("document_id/document_version", "does not reference the supplied document")
        if self.char_end > len(document.content_text) or self.text != document.content_text[self.char_start:self.char_end]:
            _fail("text", "does not equal the referenced document interval")
        if self.source_locator != document.source["source_locator"]:
            _fail("source_locator", "does not match the referenced document")
        expected = {"dataset_id": document.source["dataset_id"], "document_type": document.document_type,
                    "language": document.language, "source_updated_at": document.source["source_updated_at"],
                    "source_category": document.metadata.get("source_category"), "source_metadata": document.metadata}
        for name, value in expected.items():
            if self.metadata[name] != value:
                _fail("metadata." + name, "does not match the referenced document")
        if self.chunk_id != chunk_id_for(self.to_dict(), config):
            _fail("chunk_id", "does not match the reference and chunking config")
