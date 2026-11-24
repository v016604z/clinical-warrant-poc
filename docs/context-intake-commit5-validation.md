# Context Intake Commit 5 驗收與結果解讀

本文件將離線工程流程驗收、真實模型品質評估及臨床效能分開說明。三者的資料、方法與可支持的結論不同，不能互相替代。

## 合成端到端 runner

固定 fixture 位於 `evaluation/context_intake/synthetic_e2e_multiturn.json`；runner 是 `scripts/run_context_intake_synthetic_e2e.py`，預設報告輸出至 `evaluation/context_intake/synthetic_e2e_report.json`。在專案根目錄、已建立的虛擬環境中執行：

```powershell
.\.venv\Scripts\python.exe scripts\run_context_intake_synthetic_e2e.py
```

可用 `--fixture PATH` 指定 fixture，或用 `--output PATH` 指定報告位置。成功時命令列摘要包含報告路徑、expected check 結果、errors、fake provider call 次數與 external API call 次數；完整 JSON 另含 `metadata`、`metrics`、逐輪 `predictions`、`errors`、最終 `session` 與 `limitations`，目前產物為[synthetic E2E 報告](../evaluation/context_intake/synthetic_e2e_report.json)。有 expected check 不符時 exit code 為 1，否則為 0。重跑會原子替換指定報告檔。

目前固定 fixture 的一次成功執行記錄在上述報告中：5 turns、0 errors、2 次 fake classifier calls、10 次 fake adapter calls（router 5 次、extractor 5 次）、4 次從 SQLite 恢復 Session、1 次重複補問；最後有 2 個 Case，各自的 `personal_exposure_risk` Coverage 是 2/14。報告標示 `external_api_calls=0`、`actual_external_api_cost_usd=0.0`。這些數字是該 fixture 的工程流程結果，不是對未知對話的成功率。

Fake adapter 不提供 provider token 用量，因此 input/output/total tokens 為 `null`，估算模型費用也為 `null`；網路 API latency 為 `null`。報告中的 `local_fake_adapter_ms` 是本機 fake 程式執行時間，不是模型延遲或 API 效能。回合輸出的分類與擷取值都由 fixture 提供，不是模型預測。

## 離線工程測試

Commit 5 的離線跨層測試以 Fake Classifier、Fake Responses Adapter 及 SQLite fixture 執行，並使用實際 Orchestrator、OpenAI Extractor/Case Router wrapper 與 Repository。它可檢查呼叫契約、session 恢復、欄位狀態、Coverage、錯誤處理，以及失敗時不保存不完整個案。Fake 回應是測試程式指定的結果；通過只表示軟體路徑符合測試預期，不代表模型能從自然語言正確理解或抽取資訊。

下列離線回歸命令不設定 live opt-in 旗標；四個真實 API smoke tests 因而預期 skip。請在已安裝 `.[dev,openai,model]` 的環境中執行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_evaluation.py tests/test_cli.py tests/test_context_intake_classifier.py tests/test_context_intake_openai_sqlite_integration.py tests/test_openai_adapter.py tests/test_context_intake_case_router.py tests/test_context_intake_openai_extractor.py tests/test_context_intake_intake.py tests/test_context_intake_coverage.py tests/test_context_intake_sqlite.py tests/test_context_intake_conversation_orchestrator.py
```

pytest 支援以位置參數指定測試模組或 node ID；`-q` 縮減輸出，`--tb=short` 顯示較短 traceback。參數用法見[pytest CLI 文件](https://docs.pytest.org/en/stable/how-to/usage.html)。

最近一次指定離線回歸的結果為 **152 passed、4 skipped、exit code 0**。四個 skip 分別是 `test_openai_api_structured_output_smoke`、`test_real_openai_extractor_smoke`、`test_real_openai_orchestrator_sqlite_smoke` 與 `test_real_openai_extractor_accepts_generic_event_schema`。只有明確設定對應 opt-in 旗標才會發送 API 請求。此數字僅對應上列測試檔，不是全套 pytest 的結果。

最後一次較完整的 Warrant/分類/Context Intake 回歸為 **216 passed、5 skipped、exit code 0**。全套 `python -m pytest -q --tb=short` 結果為 **565 passed、6 skipped、8 failed、16 errors、exit code 1**。失敗及錯誤屬於此階段以外的既有 CDC/KB 資料路徑問題（舊路徑 `src/clinical_warrant/data/tw_cdc_hiv_qa` 不存在），以及 `src/clinical_warrant/data/__init__.py` 的 BOM 導致 architecture 測試 SyntaxError；Commit 5 沒有修改這些路徑或檔案。請勿把全套失敗歸因於 synthetic runner，也勿把全套結果描述為通過。

## 真實 API opt-in 與預算

真實 API 測試預設不執行。執行前必須確認：

- 已取得將測試內容送往 OpenAI 的明確授權。`test_real_openai_extractor_smoke` 會傳送 HIV 暴露情境；未取得健康情境外傳同意前不得啟用。
- `RUN_CONTEXT_INTAKE_OPENAI_E2E=1` 的兩個 live test 使用虛構的「包裹週一送達」文字，不含 HIV 或真實個案；仍須確認授權將合成測試文字送往 OpenAI。此旗標會啟用兩個測試，一次完整跨層情境最多包含一個路由及一個抽取請求，另一個測試再發一個抽取請求。
- 在 API 提供者端為本次測試設定可接受的支出預算。Repository 沒有美元硬上限；預設最多可能重試 2 次。獲授權進行測試時，將 `OPENAI_MAX_RETRIES=0` 並只選取指定測試，以限制請求數；執行後檢查用量及費用。
- 僅使用專案 `.env` 或程序環境提供的金鑰；勿將金鑰放入命令列、文件、測試報告或 Git。

現有的通用 Responses API smoke test 說明與命令見[OpenAI API Smoke Test](openai-api-smoke-test.md)。Context Intake extractor 單項 smoke 旗標為 `RUN_CONTEXT_INTAKE_OPENAI_SMOKE=1`；新跨層 live 測試旗標為 `RUN_CONTEXT_INTAKE_OPENAI_E2E=1`。這些 live API 測試本次均未啟用。

真實模型品質評估不使用此 synthetic runner。分類資料集 `dev.jsonl`/`test.jsonl` 的來源、切分與指標邊界見[14 類分類資料說明](../evaluation/context_intake/README.md)；欄位抽取需要獨立且有證據標註的資料及人工品質審查。

## 模型品質與臨床效能

- **真實模型品質**：需使用明確標註且與訓練/prototype 分離的資料，分別評估 Category 分類及欄位擷取；模型版本、Registry、欄位 gold labels、證據支持度與錯誤類型都應記錄。`synthetic_multiturn.json` 是固定 fixture，不能當作真實模型品質資料。`dev.jsonl`/`test.jsonl` 是 14 類意圖分類研究資料，只能支援其定義範圍內的分類指標，不評估欄位抽取。
- **臨床效能**：本階段沒有臨床研究、臨床專家逐筆裁定或安全性評估。Coverage 是資料欄位的完成程度，不是醫療證據充分性，也不能證明建議安全或正確。

任何 fixture、Fake 或分類指標均不得宣稱系統已完成醫療驗證。
