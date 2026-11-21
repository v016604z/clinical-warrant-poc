# 情境評估

`evaluation/synthetic_hiv_cases.jsonl` 是獨立於分類 prototypes 和接線 mock cases 的小型研究資料集，共 20 筆虛構提問。每一行是一個案例，格式如下：

```json
{"id":"result-allow-01","input":{"query":"我在檢測報告上看到陰性，這個結果通常怎麼理解？","case":{"scenario_id":"eval-result-01","toy_rule_flag":"applicable"},"requested_scope":"education"},"expected":{"category":"result_interpretation","decision":"allow_education","missing_fields":[],"reason_codes":["all_checks_passed"]}}
```

`expected.category` 可為四種已知類別或 `unknown`；`decision`、`missing_fields` 與 `reason_codes` 是對應 warrant 結果的預期值。case 內缺欄位、`null`、空白字串以及非 education scope 都是有效情境資料，不是 JSONL 格式錯誤。每筆 `id` 必須非空且唯一；整份檔案會在模型載入前驗證，JSONL 不允許空行。

## 執行

先依[分類器文件](classifier.md)安裝 CPU 模型環境，再執行：

```powershell
.\.venv\Scripts\clinical-warrant.exe evaluate --input evaluation/synthetic_hiv_cases.jsonl --output evaluation-runs
```

也可用 `--threshold` 設定 `-1` 到 `1` 間的 cosine similarity 門檻，預設為 `0.5`。每個批次只建立一個 classifier/engine，並以同一模型處理所有案例。成功時 CLI stdout 輸出一行 JSON，含 `run_id`、`run_dir`、案例數與主要 metrics；評估錯誤詳情寫入 stderr。分類/決策與預期不符屬於評估結果，仍以 exit code `0` 完成；輸入、模型、推論或報告寫入失敗則非零結束，且不發布成功報告。

每次執行在輸出路徑下建立新的 `run-<UTC時間>-<識別碼>` 子目錄，不覆寫舊批次。報告會先在暫存目錄完整產生，再一次移入正式 run 目錄：

- `summary.json`：schema version、執行時間、threshold、model ID/revision、prototype/rule/dataset SHA-256、唯一 query 數、核心模型套件版本、metrics、分母、類別 confusion counts。
- `predictions.jsonl`：每例 expected 與 actual 分類/相似度/決策/規則/檢核/欄位/理由及逐項比對結果。
- `errors.jsonl`：至少一個預期欄位不符的案例；全空檔表示本次案例皆符合預期。

分類準確率與 unknown rate 都以全部有效案例為分母，包含預期 `unknown` 的案例；決策、missing-fields 與 reason-code 準確率也都是各自完全比對的案例數除以總案例數。欄位與理由以集合比對，因此不受陣列順序影響；報告仍保留原始順序。混淆矩陣依預期類別和預測類別計數。這些指標以案例加權，不是以唯一 query 加權的泛化準確率；相似度是 cosine similarity，不是機率。若沒有可計算的分母，數值為 `null`。

## 限制

所有 query、case ID、scenario ID 和條件值都是專案內的虛構測試資料；不得放入可識別個人或真實患者資料。資料用來檢查 PoC 分類與三態流程，不代表臨床驗證、醫療建議、安全性或準確率保證。不得使用此資料自動調整 threshold；若自行修改 prototypes、規則或門檻，應以相同資料與不同 run 保存前後報告，並人工解讀差異。未知分類也只是分類器結果，錯判 unknown 會列入分類指標及逐筆 errors。

## 固定模型 baseline

以固定 model revision、CPU 與 threshold `0.5` 執行一次 20-case 合成資料集：分類正確率為 19/20（0.95），unknown rate 為 2/20（0.10），決策、missing-fields 與 reason-code 比對皆為 20/20。資料集包含 20 個唯一 query，未用這批資料調整門檻。唯一分類錯誤是 `missing-null-marker`：預期 `result_interpretation`、實際為 `window_period`（cosine similarity 0.571972），但該例決策與其他欄位比對仍正確。完整可重現報告見[summary.json](results/baseline/summary.json)、[逐筆 predictions](results/baseline/predictions.jsonl)、[errors.jsonl](results/baseline/errors.jsonl)及[執行說明](results/baseline/README.md)。這只是單次小型軟體流程評估，不代表對新資料或臨床情境的泛化表現。
