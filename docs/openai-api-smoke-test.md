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
