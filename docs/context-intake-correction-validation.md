# Context Intake Commit C 驗收紀錄

## 執行環境

- 日期：2026-11-23（Asia/Taipei）
- 工作目錄：`C:\GitHub\clinical-warrant-poc`
- Shell：PowerShell
- 分支／HEAD：`dev`／`31866283d9940ec95fe15de1472eade6ff2f1b47`
- Python：`py -0p` 回報 `No installed Pythons found!`；`py -3 --version` 回報 `No installed Python found!`。六條 `py -3` 驗收命令均為 stdout `No installed Python found!`、exit 112、stderr 空白；無法取得 Python 版本，也未執行 pytest 或 CLI。
- WSL 備援：`wsl.exe --list --quiet` 回報 `Wsl/EnumerateDistros/Service/E_ACCESSDENIED`，無法列舉發行版。

## 命令與結果

| 命令 | 結果 |
|---|---|
| `py -3 -m pytest -q` | **Blocked / unverified**；`No installed Python found!`，exit 112。無測試總數或 passed/failed/skipped 可報。 |
| `py -3 -m clinical_warrant --help` | **Blocked / unverified**；`No installed Python found!`，exit 112。 |
| `py -3 -m clinical_warrant intake demo --fixture evaluation/context_intake/synthetic_multiturn.json` | **Blocked / unverified**；`No installed Python found!`，exit 112。未產生 stdout 回放結果。 |
| `py -3 -m clinical_warrant intake evaluate --input evaluation/context_intake/synthetic_multiturn.json --output evaluation-runs/context-intake-C-validation/intake` | **Blocked / unverified**；`No installed Python found!`，exit 112。未產生或檢查 `summary.json`、`predictions.jsonl`、`errors.jsonl`。 |
| `py -3 -m pytest -q tests/test_cli.py tests/test_warrant.py tests/test_classifier.py` | **Blocked / unverified**；`No installed Python found!`，exit 112。 |
| `py -3 -m pytest -q tests/test_context_intake_sqlite.py tests/test_context_intake_persistence_integration.py` | **Blocked / unverified**；`No installed Python found!`，exit 112。 |
| `git check-ignore -v runtime-data/intake.sqlite3` | **通過**；exit 0，輸出 `.gitignore:75:runtime-data/ runtime-data/intake.sqlite3`。 |
| `git ls-files '*.db' '*.sqlite' '*.sqlite3'` | exit 0，無輸出；此次查詢未發現符合這三種副檔名的已追蹤檔案。此命令未搜尋其他副檔名或歷史提交。 |
| `git ls-files '*.db' '*.sqlite' '*.sqlite3' '*.db-journal' '*.db-wal' '*.db-shm' '*.sqlite-journal' '*.sqlite-wal' '*.sqlite-shm' '*.sqlite3-journal' '*.sqlite3-wal' '*.sqlite3-shm'` | exit 0，無輸出；此次查詢亦未發現已追蹤的常見 SQLite 側寫檔。 |
| `Test-Path evaluation/context_intake/synthetic_multiturn.json`、`git ls-files -- evaluation/context_intake/synthetic_multiturn.json` | fixture 存在且已追蹤，檔案大小 4475 bytes。以 PowerShell 檢查 `.steps.Count` 為 **9**；先前讀取 `.turns` 所得 1 輪是欄位查錯，不是 fixture 輪數。 |
| PowerShell `ConvertFrom-Json` 檢查 | runtime 回報 14 個 Category JSON 與多輪 fixture 均可解析；這不替代 Python loader 或 pytest 驗證。 |

補充 `.gitignore` 檢查：以下兩組 `git check-ignore -v` 均 exit 0 並各輸出 12 行。scratch 路徑逐項命中 `.gitignore` 第 63–74 行的 `*.db`、`*.sqlite`、`*.sqlite3` 及相應 `-journal`、`-wal`、`-shm` 規則；`runtime-data/` 下相同 12 個名稱全部命中 `.gitignore:75:runtime-data/`。

```powershell
git check-ignore -v scratch/intake.db scratch/intake.sqlite scratch/intake.sqlite3 scratch/intake.db-journal scratch/intake.db-wal scratch/intake.db-shm scratch/intake.sqlite-journal scratch/intake.sqlite-wal scratch/intake.sqlite-shm scratch/intake.sqlite3-journal scratch/intake.sqlite3-wal scratch/intake.sqlite3-shm
git check-ignore -v runtime-data/intake.db runtime-data/intake.sqlite runtime-data/intake.sqlite3 runtime-data/intake.db-journal runtime-data/intake.db-wal runtime-data/intake.db-shm runtime-data/intake.sqlite-journal runtime-data/intake.sqlite-wal runtime-data/intake.sqlite-shm runtime-data/intake.sqlite3-journal runtime-data/intake.sqlite3-wal runtime-data/intake.sqlite3-shm
```

## 尚未驗證與限制

- pytest 全套、Warrant/CLI 回歸、SQLite/service integration 測試均未執行；SQLite 外鍵、rollback、刪除、重啟讀回及跨 Case 隔離仍屬 **unverified**。
- `intake demo` 與 `intake evaluate` 未執行，沒有實際逐輪 stdout、報告目錄或 `errors.jsonl` 數量可供驗收。fixture 有 9 輪只是檔案結構檢查，不代表回放通過。
- 12 種常見資料庫與 sidecar 命名已用 `git check-ignore -v` 驗證；這不是對所有可能自訂副檔名或資料庫命名的完整涵蓋證明。
- `git ls-files` 的結果只涵蓋命令列出的副檔名，不是提交歷史或敏感資料稽核。
- 多輪 fixture 使用合成資料與 fixture adapter；即使命令可執行，其結果也只支持離線流程／契約檢查，不代表真實模型、外部使用者或臨床效能。本次沒有真實 LLM 或醫療驗證。

因此本紀錄不將 Commit C 標為完整驗收通過；待具備可用 Python 的環境後，需重跑上述 blocked 命令並追加真實輸出。
