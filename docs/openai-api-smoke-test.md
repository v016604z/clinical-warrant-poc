# OpenAI API Smoke Test

一般測試不會呼叫 OpenAI。未設定 `RUN_OPENAI_API_SMOKE=1` 時，Smoke Test 會 skip；設定此旗標後，pytest 收集到該測試時就會執行，所以請只在準備好送出一筆可能產生費用的 API 請求時啟用。測試使用專案根目錄 `.env` 的 `OPENAI_API_KEY` 與可選的 `OPENAI_MODEL`，不會輸出金鑰。

先啟用專案使用的 Python 虛擬環境，再於 PowerShell 專案根目錄執行：

```powershell
$env:RUN_OPENAI_API_SMOKE = "1"
try {
    python -m pytest tests\test_openai_adapter.py::test_openai_api_structured_output_smoke -q
}
finally {
    Remove-Item Env:RUN_OPENAI_API_SMOKE -ErrorAction SilentlyContinue
}
```

未設定 opt-in 旗標時，此測試會 skip。`OPENAI_API_KEY` 不存在於 process environment 或 `.env` 時，測試會明確失敗，不會嘗試呼叫 API。

## Context Intake live smoke tests

Context Intake 的兩個跨層 live tests 預設 skip。明確設定 `RUN_CONTEXT_INTAKE_OPENAI_E2E=1` 才會執行；測試使用虛構的「包裹週一送達」事件，完整流程會向 OpenAI 請求路由及欄位抽取，另一測試單獨請求抽取。執行前需先核定 provider-side 支出預算；若獲授權，設 `OPENAI_MAX_RETRIES=0` 並僅挑選要執行的測試：

```powershell
$env:OPENAI_MAX_RETRIES = "0"
$env:RUN_CONTEXT_INTAKE_OPENAI_E2E = "1"
try {
    .\.venv\Scripts\python.exe -m pytest `
        tests/test_context_intake_openai_sqlite_integration.py::test_real_openai_orchestrator_sqlite_smoke -q
}
finally {
    Remove-Item Env:RUN_CONTEXT_INTAKE_OPENAI_E2E -ErrorAction SilentlyContinue
    Remove-Item Env:OPENAI_MAX_RETRIES -ErrorAction SilentlyContinue
}
```

此命令只執行一個最多包含路由及抽取兩次請求的測試。另一個測試名稱為 `test_real_openai_extractor_accepts_generic_event_schema`。此 smoke 是工程整合檢查，不是品質或臨床評估。另一個旗標 `RUN_CONTEXT_INTAKE_OPENAI_SMOKE=1` 會執行 `test_real_openai_extractor_smoke`，其內容涉及 HIV 暴露；未取得健康情境外傳明確同意前不可啟用。Repo 不會強制美元上限，應在 provider 設定預算並於執行後檢查用量。

本專案目前未獲授權將健康情境送往外部 API；文件列出 opt-in 方法不表示已執行或已取得同意。
