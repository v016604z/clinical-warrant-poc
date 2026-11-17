# 決策 CLI

第五階段加入單筆 `decide` 命令。它只分類輸入、檢查玩具規則並輸出 JSON 決策，不產生衛教文字、不呼叫生成式模型，也不推斷 query 內未明示的用途範圍。

## 輸入與執行

輸入檔是 UTF-8 JSON object，外層欄位為 `query`、`case` 與 `requested_scope`：

```json
{
  "query": "我的愛滋篩檢報告結果該怎麼看？",
  "case": {
    "scenario_id": "synthetic-cli",
    "toy_rule_flag": "applicable"
  },
  "requested_scope": "education"
}
```

```powershell
.\.venv\Scripts\clinical-warrant.exe decide --input request.json
```

可用 `--threshold` 覆寫未知分類門檻，預設 `0.5`。首次分類需要 model extra 及本機 CPU 模型；安裝與快取方式見[分類器文件](classifier.md)。成功輸出任何三態決策（包括 `restrict`）均以 exit code `0` 結束，stdout 僅有一筆 `DecisionResult` JSON，內含分類類別與相似度、對應 `rule_id`、三個檢核狀態、`missing_fields`、`reason_codes` 與 `decision`。無效 UTF-8、JSON/契約格式或讀檔錯誤會寫到 stderr、stdout 留空並以 exit code `2` 結束；模型載入或決策執行失敗也會寫到 stderr、stdout 留空並以 exit code `1` 結束，不輸出替代決策。未實作的 `evaluate` 命令以 exit code `2` 結束。

## 檢核與三態優先順序

必要 case 欄位只把缺 key、`null` 或空白字串視為缺漏；`False`、`0` 等值會保留並供玩具條件比較。適用性條件所需 marker 缺漏時，Rule Applicability 為 `undetermined`，不是 `fail`。每個結果恰好包含 Case Sufficiency、Rule Applicability、Response Scope 各一項；未執行的檢核標為 `skipped`。

| 條件 | 決策與 reason | 檢核狀態與補問欄位 |
|---|---|---|
| 分類為 `unknown` | `restrict` / `unknown_intent` | 三項皆 `skipped`；不列 `missing_fields`。 |
| `requested_scope` 不等於 `education` | `restrict` / `scope_mismatch` | Response Scope 為 `fail`，另兩項 `skipped`；不列 `missing_fields`。 |
| 適用 marker 已有值且明確不符合玩具條件 | `restrict` / `rule_not_applicable` | Rule Applicability 為 `fail`，Case Sufficiency `skipped`，Response Scope `pass`；不列 `missing_fields`，不追問無關缺欄位。 |
| 缺少必要欄位，且尚未確認規則不適用 | `need_more_info` / `case_info_missing` | Case Sufficiency `fail`；marker 若缺則 Rule Applicability `undetermined`，若符合則 `pass`；只列必要缺漏欄位。 |
| 範圍符合、必要欄位齊全、玩具條件符合 | `allow_education` / `all_checks_passed` | 三項皆 `pass`；`missing_fields` 為空。 |

範圍和規則皆是軟體流程示範：`toy_rule_flag` 值沒有醫療意義，不含真實風險或時間門檻。`allow_education` 只是 toy decision label，不會附上任何衛教內容，也不是臨床建議或安全性驗證。`evaluate` 仍保留為未實作命令，會明確非零結束。
