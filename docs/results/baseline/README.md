# 模擬案例 baseline

此 baseline 是一次固定設定的虛構情境評估，供重現與檢視，不代表臨床驗證，也沒有前後改善比較。

來源資料：[synthetic_hiv_cases.jsonl](../../../evaluation/synthetic_hiv_cases.jsonl)

## 執行設定

- 模型：`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- 固定 Hub revision：`e8f8c211226b894fcb81acc59f3b34ba3efd5f42`
- 執行裝置：CPU
- 套件：sentence-transformers 6.3.0、transformers 5.20.2、torch 2.14.1+cpu
- 分類門檻：`0.5`；本次沒有調整門檻或 gold labels
- 案例數：20；唯一問句數：20

使用已下載的模型權重時，可用下列 PowerShell 命令重跑：

```powershell
$env:HF_HUB_OFFLINE = "1"
$env:CLINICAL_WARRANT_CACHE = Join-Path (Get-Location) ".venv\model-cache"
.\.venv\Scripts\clinical-warrant.exe evaluate --input evaluation\synthetic_hiv_cases.jsonl --output "$env:TEMP\clinical-warrant-baseline-runs" --threshold 0.5
```

## 結果檔案

- [summary.json](summary.json)：指標、混淆矩陣及執行 metadata
- [predictions.jsonl](predictions.jsonl)：每筆輸入、預期值與實際結果
- [errors.jsonl](errors.jsonl)：不符預期的案例

`summary.json` 內的 `encoder_type` 與 `classifier_type` 是該次 baseline 執行時的歷史 metadata，保留當時記錄的 Python 路徑，不代表目前仍提供相同 imports。

## 本次結果

- 分類正確率：19/20（95%）
- 預測為 unknown：2/20（10%）
- 決策正確率：20/20（100%）
- missing fields 比對：20/20（100%）
- reason codes 比對：20/20（100%）
- 唯一分類錯誤：`missing-null-marker`，預期 `result_interpretation`，實際 `window_period`，similarity `0.571972`。此類別的 gold 共 7 例，其中 6 例分類正確、1 例被分到 `window_period`。

決策正確率 100% 不代表真實臨床準確度。此模擬資料的四類規則共用必要欄位與適用標記條件，因此該分類錯誤沒有改變此案例需要補充資料的決策。解讀結果時應同時檢視分類與決策指標；本小型虛構資料集不支持臨床效能或泛化主張。
