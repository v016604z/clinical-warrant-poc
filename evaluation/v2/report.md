# MedlinePlus HIV health-topic pilot

Collected 2026-11-22 (UTC). Publisher: U.S. National Library of Medicine (MedlinePlus). The intended use is local offline supplementary knowledge-base conversion evaluation; these materials are not Taiwan policy or a clinical decision source.

## Captures

The official Health Topics XML service was queried twice, with eight total GETs including topic pages, policy/service documentation, and robots checks. The first query (`db=healthTopics`, `term=HIV`, `retmax=5`, `rettype=topic`) returned five records; only the allowlisted HIV page was normalized. The second (`term=title:"HIV: PrEP and PEP"`, same limits/format) returned the allowlisted PrEP/PEP page. XML records contain `<health-topic>` and `<full-summary>`; normalized content is the exact `full-summary` HTML text, not snippets. No linked pages, images, encyclopedia text, drug monographs, or other third-party material were fetched.

| Topic | Source record ID | Official URL | Visible page update date | Summary HTML characters |
|---|---|---|---|---:|
| HIV | `medlineplus:1` | https://medlineplus.gov/hiv.html | 2025-03-26 | 5,356 |
| HIV: PrEP and PEP | `medlineplus:7347` | https://medlineplus.gov/hivprepandpep.html | 2025-08-26 | 5,548 |

Dates came from each captured page's visible “Last updated” text. The API `date-created` is retained separately and was not used as an update date. Each record's `raw_content_sha256` hashes its exact extracted summary HTML; the complete API response hashes and HTTP metadata are in `source/capture_manifest.json`. The final build includes that capture manifest itself as input evidence (SHA-256 `d293c0ba8319bfc1bfa95efcfcb9490fdf09d9d500da2c356ce01bb53b7e4ebe`). Per-record `collected_at_utc` follows the matching API response: ID 1 `2026-11-22T06:41:22Z`, ID 7347 `2026-11-22T06:41:56Z`; both complete adapter configs are in the manifest's `per_record_overrides`.

## Rights and access

Rights are recorded only for the Health Topic summary field, with `usage_decision=allowed` for `local offline supplementary knowledge-base conversion evaluation only` and attribution `Source: MedlinePlus, National Library of Medicine.` The captured [MedlinePlus content policy](https://medlineplus.gov/about/using/usingcontent/) explicitly lists “Summaries on health topic pages” in its “Content that is not copyrighted” section (captured HTML lines 326–331); the next lines require source acknowledgement (337–340). The snapshot SHA-256 is `d9fca47303d9ea3ba42cf756af0f66986bbf6fbb2ba85e77b2af6805e53b2985`, stored at `source/raw/usingcontent.html` and referenced in the capture manifest. The topic pages identify National Library of Medicine as publisher, and the API documentation defines `FullSummary` as the topic text summary with HTML formatting. Other materials remain excluded: MedlinePlus identifies A.D.A.M. encyclopedia content, ASHP drug monographs, and many images as copyrighted or separately licensed.

The official API is free and requires no registration or API key; NLM limits it to 85 requests/minute/IP and recommends 12–24 hour caching. MedlinePlus `robots.txt` returned HTTP 200 and disallows `/xml/` and `/xml/vocabulary/`; the separate API host's `robots.txt` returned 404. No bulk XML path was requested.

## Pipeline results

The MedlinePlus run uses the existing `GenericJsonlAdapter` (`article`, `text/html`, `html_v1`, English) and cleaner. Policy: `as_of=2026-11-22`, `stale_after_days=730`, `require_time_sensitive_review=true`.

| Run | Input documents | Ready | Needs review | Rejected | Chunks |
|---|---:|---:|---:|---:|---:|
| MedlinePlus build v2 | 2 | 0 | 2 (`time_sensitive`) | 0 | 0 |
| CDC unknown-rights build | 119 | 0 | 119 (`rights_unknown` on all) | 0 | 0 |
| Mixed merge v2 | 121 input / 0 indexed output | 0 | 121 quarantined | 0 | 0 |

The CDC run used the existing local 119-record dataset with `usage_decision=unknown`; no CDC use permission was inferred. The mixed merge retained both input-run policy/config records and quarantined all 119 CDC documents as `rights_not_approved` plus both MedlinePlus records as `needs_review`. `read_run` and `validate_run` passed for all three final published runs. Output hashes matched the bytes on disk. `quality_report.clinical_judgment` remains false. The earlier `runs/build`, `runs/merged` and their reports are superseded; use the v2 paths below.

Run directories:

- `runs/build_v2` — final MedlinePlus build
- `runs/cdc-unknown` — conservative CDC run
- `runs/merged_v2` — final combined quarantine run

## Reproduction

Use the repository's existing Python runner. The MedlinePlus script performs no network requests; it uses preserved captures. It refuses to replace source/config evidence or an existing output run. A rerun can specify a new, unused output directory inside the pilot root.

```powershell
$py = 'C:\Users\PGW\AppData\Local\Temp\clinical-warrant-pytest-env\python\python.exe'
& $py evaluation-runs/official-source-pilot-20261122/pilot.py --output-dir runs/build-rerun
& $py -m clinical_warrant kb merge --inputs evaluation-runs/official-source-pilot-20261122/runs/build-rerun evaluation-runs/official-source-pilot-20261122/runs/cdc-unknown --output-dir evaluation-runs/official-source-pilot-20261122/runs/merged-rerun
```

The first query's exact URL and response hash are in `source/capture_manifest.json`; so are the second query, evidence-page captures, timestamps, status, headers, lengths, and hashes. The local captures are sufficient to reproduce the conversion without another GET.
