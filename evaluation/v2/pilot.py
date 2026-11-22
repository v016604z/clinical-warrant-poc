"""Build the local MedlinePlus sample from its preserved official captures."""

from __future__ import annotations

import hashlib
import argparse
import json
import re
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO / "src"))

from clinical_warrant import __version__
from clinical_warrant.modules.knowledge_base.application.chunking import chunking_fingerprint
from clinical_warrant.modules.knowledge_base.application.pipeline import build_run, validate_run
from clinical_warrant.modules.knowledge_base.domain.policies import QualityPolicy
from clinical_warrant.modules.knowledge_base.infrastructure.adapters import GenericJsonlAdapter
from clinical_warrant.modules.knowledge_base.infrastructure.cleaning import CLEANING_VERSION, clean_source_record
from clinical_warrant.modules.knowledge_base.infrastructure.input_reader import read_inputs
from clinical_warrant.modules.knowledge_base.infrastructure.run_io import publish_run, read_run


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_same_or_new(path: Path, raw: bytes) -> None:
    if path.exists():
        if path.read_bytes() != raw:
            raise FileExistsError(f"refusing to replace changed pilot evidence: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


def capture_records(capture_manifest: dict) -> list[dict]:
    records = []
    api_by_url = {
        entry["url"]: entry for entry in capture_manifest["requests"]
        if entry["url"].startswith("https://wsearch.nlm.nih.gov/ws/query?")
    }
    topics = {
        "https://medlineplus.gov/hiv.html": ("api_hiv.xml", "topic_hiv.html"),
        "https://medlineplus.gov/hivprepandpep.html": ("api_prep_pep.xml", "topic_hiv_prep_pep.html"),
    }
    topic_ids = {"https://medlineplus.gov/hiv.html": "1",
                 "https://medlineplus.gov/hivprepandpep.html": "7347"}
    for page_url, (api_name, html_name) in topics.items():
        api_entry = next((entry for entry in capture_manifest["requests"]
                          if Path(entry["path"]).name == api_name), None)
        if not api_entry or api_entry.get("http_status") != 200:
            raise ValueError(f"missing successful API capture for {page_url}")
        api_root = ET.fromstring(Path(api_entry["path"]).read_bytes())
        topic = None
        for document in api_root.findall(".//document"):
            candidate = document.find("./content/health-topic")
            if candidate is not None and candidate.attrib.get("url") == page_url:
                topic = candidate
                break
        if topic is None:
            raise ValueError(f"API query did not return allowlisted topic: {page_url}")
        summary_node = topic.find("full-summary")
        summary_html = summary_node.text if summary_node is not None else None
        if not isinstance(summary_html, str) or not summary_html.strip():
            raise ValueError(f"API full-summary field missing for {page_url}")
        if topic.attrib.get("language") != "English":
            raise ValueError(f"unexpected API language for {page_url}")
        if topic.attrib.get("id") != topic_ids[page_url]:
            raise ValueError(f"unexpected stable topic ID for {page_url}: {topic.attrib.get('id')}")

        html_entry = next((entry for entry in capture_manifest["requests"]
                           if Path(entry["path"]).name == html_name), None)
        if not html_entry or html_entry.get("http_status") != 200:
            raise ValueError(f"missing successful visible-date page capture for {page_url}")
        html_text = Path(html_entry["path"]).read_text(encoding="utf-8")
        match = re.search(r"Last\s+updated\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", html_text, re.I)
        if not match:
            updated_at = None
        else:
            updated_at = datetime.strptime(match.group(1), "%B %d, %Y").date().isoformat()
        records.append({
            "id": "medlineplus:" + topic.attrib["id"],
            "title": topic.attrib["title"],
            "text": summary_html,
            "source_name": "National Library of Medicine (MedlinePlus)",
            "source_url": page_url,
            "updated_at": updated_at,
            "category": "HIV prevention and health topic summary",
            "geographic_scope": "US",
            "use_role": "supplementary_reference",
            "source_language": "en",
            "api_topic_id": topic.attrib["id"],
            "date_created": topic.attrib.get("date-created"),
            "query_capture": api_entry["url"],
            "summary_field": "full-summary",
        })
    return sorted(records, key=lambda record: record["source_url"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="new, unused run directory inside this pilot root")
    args = parser.parse_args()
    evidence_root = ROOT / "source"
    raw_root = evidence_root / "raw"
    capture_manifest_path = evidence_root / "capture_manifest.json"
    capture_manifest = json.loads(capture_manifest_path.read_text(encoding="utf-8"))
    requests = {Path(item["path"]).name: item for item in capture_manifest["requests"]}
    required_raw = {
        "api_hiv.xml", "api_prep_pep.xml", "topic_hiv.html", "topic_hiv_prep_pep.html",
        "usingcontent.html", "webservice_terms.html", "medlineplus_robots.txt", "wsearch_robots.txt",
    }
    if not required_raw <= requests.keys():
        raise ValueError(f"missing capture entries: {sorted(required_raw - requests.keys())}")
    for name in required_raw:
        entry = requests[name]
        raw = (raw_root / name).read_bytes()
        if sha256(raw) != entry["sha256"] or len(raw) != entry["bytes"]:
            raise ValueError(f"capture hash/length mismatch: {name}")

    rows = capture_records(capture_manifest)
    normalized_path = ROOT / "source" / "normalized.jsonl"
    normalized_bytes = b"".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        for row in rows
    )
    write_same_or_new(normalized_path, normalized_bytes)

    rights = {
        "status": "recorded",
        "statement": "Only NLM-authored MedlinePlus health-topic summaries are public domain; exclude third-party encyclopedia, drug, image and linked content. Credit Source: MedlinePlus, National Library of Medicine.",
        "policy_locators": [
            "https://medlineplus.gov/about/developers/webservices/",
            "https://medlineplus.gov/about/using/usingcontent/",
        ],
        "intended_use": "local offline supplementary knowledge-base conversion evaluation only",
        "usage_decision": "allowed",
    }
    mapping = {"id": "id", "title": "title", "text": "text", "source_name": "source_name",
               "source_url": "source_url", "updated_at": "updated_at", "category": "category"}
    rights_path = ROOT / "rights" / "rights.json"
    mapping_path = ROOT / "rights" / "mapping.json"
    rights_bytes = json.dumps(rights, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    mapping_bytes = json.dumps(mapping, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    write_same_or_new(rights_path, rights_bytes)
    write_same_or_new(mapping_path, mapping_bytes)

    api_filename = {
        "https://medlineplus.gov/hiv.html": "api_hiv.xml",
        "https://medlineplus.gov/hivprepandpep.html": "api_prep_pep.xml",
    }
    record_adapters = []
    source_inputs = []
    normalized_lines = normalized_bytes.splitlines(keepends=True)
    for index, (row, line) in enumerate(zip(rows, normalized_lines), 1):
        api_entry = requests[api_filename[row["source_url"]]]
        collected_at = datetime.fromisoformat(api_entry["collected_at_utc"].replace("Z", "+00:00")).replace(
            microsecond=0).isoformat().replace("+00:00", "Z")
        adapter = GenericJsonlAdapter(
            dataset_id="medlineplus_hiv_topics", attribution="Source: MedlinePlus, National Library of Medicine.",
            rights=rights, mapping=mapping, document_type="article", content_type="text/html",
            cleaning_profile="html_v1", language="en", collected_at_utc=collected_at,
        )
        record_adapters.append({"source_record_id": row["id"], "collected_at_utc": collected_at,
                                "adapter_config": adapter.to_config()})
        source_inputs.extend(read_inputs(normalized_path, adapter, raw_bytes=line))
        source_inputs[-1] = replace(source_inputs[-1], line_number=index)
    policy = QualityPolicy(as_of="2026-11-22", stale_after_days=730,
                           require_time_sensitive_review=True)
    chunking = {"algorithm_version": "structure-v1", "max_chars": 1200, "overlap_chars": 100}
    input_paths = [(normalized_path, "input"), (rights_path, "rights_config"),
                   (mapping_path, "mapping_config")]
    input_paths.extend((raw_root / name, "source_or_policy_evidence") for name in sorted(required_raw))
    input_paths.append((capture_manifest_path, "capture_manifest"))
    evidence = [{"path": str(path.resolve()), "sha256": sha256(path.read_bytes()), "role": role}
                for path, role in input_paths]
    evidence.sort(key=lambda item: (item["role"], item["path"], item["sha256"]))
    started_at = utc_now()
    adapter_manifest = dict(record_adapters[0]["adapter_config"])
    adapter_manifest["provenance"] = {**adapter_manifest["provenance"], "collected_at_utc": None}
    adapter_manifest["per_record_overrides"] = record_adapters
    metadata = {
        "schema_version": "1.0", "pipeline_version": __version__, "operation": "build",
        "adapter": adapter_manifest,
        "source_root": None, "inputs": evidence,
        "cleaning_config": {"version": CLEANING_VERSION, "profiles": ["html_v1"]},
        "chunking_config": chunking, "chunking_fingerprint": chunking_fingerprint(chunking),
        "quality_policy": policy.to_dict(), "strict": False,
        "started_at_utc": started_at, "completed_at_utc": None, "output_hashes": {},
        "counts": {}, "complete": False,
        "policy_provenance": [{
            "url": "https://medlineplus.gov/about/using/usingcontent/",
            "scope": "NLM-produced health-topic summaries only; excluded third-party content and media",
            "snapshot_sha256": requests["usingcontent.html"]["sha256"],
            "decision": "allowed for the stated local offline supplementary evaluation use",
        }],
        "capture_manifest": str(capture_manifest_path.resolve()),
    }
    run = build_run(source_inputs,
                    cleaner=clean_source_record, policy=policy, chunking_config=chunking,
                    strict=False, run_metadata=metadata)
    run = replace(run, manifest={**run.manifest, "completed_at_utc": utc_now()})
    output = (args.output_dir if args.output_dir and args.output_dir.is_absolute()
              else ROOT / args.output_dir if args.output_dir
              else ROOT / "runs" / "build").resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError("output directory must stay inside the pilot root")
    if output.exists():
        raise FileExistsError(f"refusing to replace existing pilot run: {output}")
    validate_run(run)
    published = publish_run(output, run, validator=validate_run)
    persisted = read_run(published)
    validate_run(persisted)

    report = {
        "captured_topics": [{"source_record_id": row["id"], "title": row["title"],
                             "source_url": row["source_url"], "source_updated_at": row["updated_at"],
                             "collected_at_utc": next(item["collected_at_utc"] for item in record_adapters
                                                       if item["source_record_id"] == row["id"]),
                             "summary_chars": len(row["text"])} for row in rows],
        "api_queries": [requests[name]["url"] for name in ("api_hiv.xml", "api_prep_pep.xml")],
        "api_topic_ids_returned": {
            name: [node.attrib.get("id") for node in ET.parse(requests[name]["path"]).getroot().findall(".//health-topic")]
            for name in ("api_hiv.xml", "api_prep_pep.xml")
        },
        "quality_report": run.quality_report,
        "document_quality": [{"document_id": doc.document_id, "status": doc.quality["status"],
                               "flags": list(doc.quality["flags"]), "chunk_count": sum(
                                   chunk.document_id == doc.document_id for chunk in run.chunks)}
                              for doc in run.documents],
        "run_path": str(published.resolve()),
        "validated": True,
        "raw_evidence_request_count": len(capture_manifest["requests"]),
        "wsearch_robots_http_status": requests["wsearch_robots.txt"]["http_status"],
    }
    report_path = ROOT / ("report.json" if output.name == "build" else f"report-{output.name}.json")
    write_same_or_new(report_path, json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
