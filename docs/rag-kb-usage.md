# RAG Knowledge Base 使用與驗收

此文件說明本機離線 build、merge、validate 的最小操作。資料契約與完整驗收情境見[資料契約 v1](rag-kb-schema.md)及[實作計畫](clinical_warrant_rag_kb_pipeline_plan.md)。

## 建置 CDC 快照

以下命令只讀取 repository 內既有資料，不重新蒐集網頁。`--as-of` 與 `--stale-after-days` 必填；`--usage-decision` 必須依目標用途與來源證據判定。若尚未確認，使用 `unknown`，文件會保留並依品質結果隔離。

```powershell
.\.venv\Scripts\clinical-warrant.exe kb build --adapter cdc_qa --source-root datasets/tw_cdc_hiv_qa --input datasets/tw_cdc_hiv_qa/qa.jsonl --output-dir evaluation-runs/kb-cdc --intended-use local_reference --usage-decision unknown --as-of 2026-11-22 --stale-after-days 1095
.\.venv\Scripts\clinical-warrant.exe kb validate --dataset evaluation-runs/kb-cdc
```

只有七個 run 檔會進入正式輸出：`documents.jsonl`、`chunks.jsonl`、`issues.jsonl`、`rejected.jsonl`、`reviews.jsonl`、`quality_report.json`、`manifest.json`。manifest 記錄輸入及輸出 SHA-256；`reviews.jsonl` 即使沒有人工審查也會存在且為空檔。

## 匯入 generic JSONL

`--rights-config` 必須是 UTF-8 JSON object，包含完整權利欄位。未知權利應維持 `unknown`；不得為了取得 chunks 假設授權。可選的 `--mapping` 將邏輯欄位映射到來源欄名。

```json
{
  "status": "unknown",
  "statement": "Reuse terms have not been verified.",
  "policy_locators": [],
  "intended_use": "local_fixture_validation",
  "usage_decision": "unknown"
}
```

```powershell
.\.venv\Scripts\clinical-warrant.exe kb build --adapter generic_jsonl --input tests/fixtures/kb_generic.jsonl --output-dir evaluation-runs/kb-generic --dataset-id example_articles --attribution "Example Publisher" --rights-config rights.json --as-of 2026-11-22 --stale-after-days 1095
.\.venv\Scripts\clinical-warrant.exe kb validate --dataset evaluation-runs/kb-generic
.\.venv\Scripts\clinical-warrant.exe kb merge --inputs evaluation-runs/kb-cdc evaluation-runs/kb-generic --output-dir evaluation-runs/kb-merged
.\.venv\Scripts\clinical-warrant.exe kb validate --dataset evaluation-runs/kb-merged
```

輸出目錄必須不存在；build/merge 不會覆寫既有 run。`--strict` 預設為 false；啟用後，任何 error issue 或 rejected row 都會使操作非零失敗。失敗診斷目錄含 `failure.json`、`issues.jsonl`、`rejected.jsonl`，不含成功 manifest；非 strict 可發布有效剩餘資料，但報告仍會列出拒收與隔離。

人工審查紀錄由受信任的審查流程提供，不是此 CLI 的審查介面。每行格式如下，`review_ref` 是同一 run 中的邏輯參照鍵：

```json
{"review_ref":"review:example","record":{"document_id":"example_articles:article-1","document_version":"sha256:<64 lowercase hex>","source_fingerprint":"<64 lowercase hex>","flags":[],"decision":"approved","reviewer":"Reviewer name","reviewed_at_utc":"2026-11-22T00:00:00Z","reason":"Reviewed for the recorded intended use."}}
```

Run 驗證會核對 review ref、文件版本、來源指紋、決策與 flags；改變內容、來源或用途後，舊審查不可沿用。`approved` 不能覆蓋 `usage_decision="prohibited"`。quality flags 只描述資料與來源完整性，不代表臨床正確性審核。

## Commit 6 驗收紀錄

測試固定使用 `as_of=2026-11-22`。CDC CLI 測試對 119 筆輸入逐筆核對，結果為 119 documents、0 rejected、0 exact duplicates、118 ready、1 needs_review、0 excluded、118 chunks；唯一 needs_review 是附件依賴項，正文提及「二者的比較請詳見下表」，因此保留文件但不產生 chunk。build 前後比對 `qa.jsonl`、manifest 與 raw snapshot 樹的 bytes hash，未改變來源資料。CDC 測試採 `intended_use=e2e_test_only` 及測試用 allowed 決策；這是 pipeline fixture 設定，不代表真實重用授權。

混合來源 CLI 測試以 CDC、專案撰寫 generic fixture 與 unknown-rights fixture 合併：121 input documents，119 ready 輸出文件／chunks，2 筆 quarantine（needs_review 及 rights_not_approved）。另一測試用兩個 dataset 的相同 clean content 驗證保留兩個 document ID、報告一個 cross-source group、exact duplicate count 為零；反轉輸入順序後，資料檔、quality report 與非時間欄位 manifest 一致。

負面 E2E 測試驗證同 ID 版本／metadata 衝突、strict merge 錯誤診斷、既存輸出保護、重算 canonical bytes 與 output hashes 後的 chunk/document/report/config 語義竄改、review 證據合併與 hash，以及來源／版本變更使舊 review 失效、prohibited 不可由 approved 繞過。完整 pytest 為 **384 passed、1 skipped，9.07 秒**；唯一 skip 是需明確 opt-in 並載入 pinned model 的真實模型 smoke test。端到端 run 均在 pytest 暫存目錄建立，未將生成資料留在版本庫。
