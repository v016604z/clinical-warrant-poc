# 資料契約與模擬目錄

此階段只定義資料形狀並提供可打包的研究用範例，不執行分類、規則檢核或決策。資料皆為虛構軟體測試用內容，不含病患資料、醫療判斷、風險值或時間門檻，也不是衛教內容。

## 輸入契約

`DecisionInput` 的 JSON 外層必須恰有 `query`、`case`、`requested_scope` 三個欄位：

```json
{
  "query": "接觸後隔一段時間再檢測，結果會有差別嗎？",
  "case": {"scenario_id": "synthetic-a"},
  "requested_scope": "education"
}
```

`query` 與 `requested_scope` 必須是非空字串；`case` 必須是 JSON object，但其中可以缺少後續模擬規則需要的欄位。缺少 `case` 內容不屬於輸入格式錯誤。`requested_scope` 保留呼叫端明示字串，education 以外的值仍是有效輸入，供後續階段依明示範圍處理。

## 輸出契約

- `QuestionType` 有四個已知類別 `result_interpretation`、`window_period`、`exposure_risk`、`prevention_education`，以及分類結果用的 `unknown`。
- `Decision` 值為 `allow_education`、`need_more_info`、`restrict`。
- 每個 `CheckResult` 由三項檢核之一、狀態與可選理由組成。`pass` 表示檢核通過；`fail` 表示已檢核且未通過；`undetermined` 表示已嘗試判斷但資料不足；`skipped` 表示因前置條件而未執行。
- `DecisionResult` 保留分類與相似度、可空的 `rule_id`、檢核結果、`missing_fields`、`reason_codes` 與最終決策。Cosine similarity 尚未計算時可為 `null`，否則須為 `[-1, 1]` 中的有限數值；bool、非有限值與超界值無效。每個結果必須恰有三種 `CheckKind` 各一次；此為輸出形狀檢查，不執行決策組合邏輯。

## 套件資料

`clinical_warrant.data` 內的 `prototypes.json` 是四類虛構 HIV 篩檢衛教自然問句；`rules.json` 是四筆符號式玩具規則，使用 `toy_rule_flag` 的模擬標記；`mock_cases.json` 包含完整欄位、缺少必要模擬欄位與標記不符合的虛構案例。問句與 fixtures 只用於資料/套件接線，不是獨立評估集，不提供醫療建議，也不代表醫療規則。

目錄 loader 使用 `importlib.resources` 讀取 JSON，安裝後不依賴目前工作目錄。載入時檢查四類 prototype 非空且唯一、每類有對應唯一規則，以及 mock case 的 rule reference、category 與完整/缺漏欄位標記一致。
