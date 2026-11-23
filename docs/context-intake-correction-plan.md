# Context Intake 修正計畫（Commit 6 後工程驗收）

- **專案**：[`v016604z/clinical-warrant-poc`](https://github.com/v016604z/clinical-warrant-poc)
- **檢查基準**：`dev` 分支，`aa46468b49622f26f8a0c9e74ea3e6ce97ed3cb8`（2026-11-23）
- **文件定位**：Commit 1–6 既有規劃完成後的**缺陷修正與實際驗收計畫**，不是重寫原計畫
- **目標**：消除合成測試的無依據資訊、統一同一暴露事件在跨 Category 下的資料語義、保護 SQLite 資料檔，並以實際測試輸出完成驗收
- **約束**：不使用 RAG、不制定臨床必填規則、不將 Coverage 視為醫療充分性、不修改既有四類 Warrant 決策契約、不使用真實病患資料

> **狀態說明**：本文件是待執行計畫。檢查時已發現程式與測試檔存在，但沒有足夠證據證明最新版的完整測試已成功執行；以下驗收項目不得在實際執行前標成通過。

## 一、問題與修正優先級

| 優先級 | 問題 | 現有證據 | 預期修正 |
|---|---|---|---|
| P0 | 合成 Fixture 將未說明的暴露方式擷取為「性行為」 | `evaluation/context_intake/synthetic_multiturn.json` 第 1 輪只說「我昨天有一次可能的暴露」 | 不得產生 `exposure_route="性行為"`；正確保留未知 |
| P0 | 未在本輪說明的資料被當作新擷取值 | 同 Fixture 第 2 輪只問 PEP，卻重新擷取「昨天」；第 3 輪只問空窗期，也新生成暴露時間 | 已知 Case 欄位只能重用，不得假裝是本輪再次提供 |
| P0 | 同一暴露事件的時間被存成不同 key，後續更正不一致 | `exposure_datetime` 與 `last_possible_exposure_date` 在不同 Category 中共存；Fixture 更正後前者為「前天」、後者仍為「昨天」 | 統一同一 Case／同一事件的時間欄位，跨 Category 即時重用更正值 |
| P1 | 任意命名 SQLite 檔未全面排除 Git | `.gitignore` 現有 `db.sqlite3` / `db.sqlite3-journal`，沒有涵蓋常見自訂資料庫名與 WAL/SHM 檔 | 新增明確忽略規則、確認沒有資料庫被追蹤 |
| P1 | 驗收紀錄不足 | `intake demo/evaluate` 與相關 pytest 已有程式，但尚未有完整成功執行的可核對結果 | 實際執行並保存指令、環境、結果與失敗原因 |

## 二、修正範圍與詳細規格

### 修正 A：合成多輪資料必須有可追溯的文字依據

**主要檔案**

- `evaluation/context_intake/synthetic_multiturn.json`
- `src/clinical_warrant/modules/context_intake/application/simulation.py`
- `tests/test_context_intake_simulation_cli.py`
- `tests/test_context_intake_extraction.py`
- `evaluation/context_intake/README.md`

**行為定義**

1. `extracted_attributes` 只能代表**使用者於當輪明確說明或當輪明確確認**的資訊；前輪已儲存的值應經由 `known_attributes`／`CaseState` 重用，不得重新算作「本輪擷取」。
2. `selected_fields` 代表 AI 在此類別想檢查的**候選欄位**；欄位即使被選中，也可以沒有 `extracted_attributes` 值。
3. `null`／空字串／「不知道」不得計入已知值；`false`、`0` 則是有效的已知值。
4. 不得因篩檢、PEP、空窗期等主題，推測使用者的性行為方式、暴露時間、檢驗結果或伴侶狀況。
5. Fixture 的 `expected_attributes` 必須由當輪明示資訊及 Case 中前輪已確認的資訊推導，不能把錯誤擷取當作正確標籤。
6. 新增至少一個**負向情境**：使用者未提暴露方式但假擷取器回傳 `exposure_route="性行為"`，測試必須揭露此錯誤。注意：目前通用 Parser 只能驗證結構與型別，**無法證明文字語意有據**；不要把 Parser 通過視為無幻覺驗證。

**建議調整原有 Fixture**

| 輪次 | 使用者原句 | 建議處理 |
|---|---|---|
| 1 | 「我昨天有一次可能的暴露」 | 新建 Case；僅擷取 `exposure_datetime="昨天"`；`exposure_route` 保留未知 |
| 2 | 「我也想問暴露後預防」 | 切至 `pep_post_exposure`，直接重用 Case 的 `exposure_datetime`；本輪不重新擷取「昨天」 |
| 3 | 「我想知道檢驗的空窗期」 | 切至 `window_period`，重用同一時間欄位；可選取 `test_date` 等候選欄位，未知不得填造 |
| 4 | 「更正一下，暴露時間是前天」 | 僅依使用者明確更正更新時間為「前天」；所有引用同一事件時間的 Category 立即看到更正 |
| 5–7 | 原有未知檢驗日期、新 Case、OOD 問題 | 保留既有測試目的，但依新欄位名稱更新預期狀態 |

**驗收**

- [ ] 第 1 輪 `exposure_route` 不會出現在 Case 已知欄位。
- [ ] 第 2、3 輪不會把上輪已知時間計入「本輪新擷取」。
- [ ] 更正後，跨 Category 看到相同的最新時間；無舊值殘留。
- [ ] 原有「重複詢問、修正、新 Case、unknown、Coverage」測試仍能涵蓋相同情境。
- [ ] Fixture 報告清楚標示 `fixture-classifier` / `fixture-extractor`，不得宣稱真實 AI 擷取正確率。

### 修正 B：明確定義暴露事件的欄位語義

**主要檔案**

- `src/clinical_warrant/data/context_intake/categories/window_period.json`
- `src/clinical_warrant/data/context_intake/categories/test_result_interpretation.json`
- `src/clinical_warrant/data/context_intake/categories/personal_exposure_risk.json`（確認描述，不一定要改）
- `src/clinical_warrant/data/context_intake/categories/pep_post_exposure.json`（確認描述，不一定要改）
- `evaluation/context_intake/synthetic_multiturn.json`
- 相關 `tests/test_category_registry.py`、`tests/test_context_intake_intake.py`、`tests/test_context_intake_coverage.py`、`tests/test_context_intake_state.py`
- `docs/context-intake-spec.md`、`docs/architecture.md`、`data/CDC_HIV_FAQ_Problem_Categories_JSON_v2/README.md`（說明原始 v2 與 runtime 版差異）

**建議決策（需按事件語義實作，不可單純全域字串取代）**

- 以 **`exposure_datetime`** 作為「目前 `case_id` 所代表的單一次暴露事件時間」的唯一正規 key。
- `window_period` 與 `test_result_interpretation` 若詢問的確實是**同一個 Case 的暴露**，將 `last_possible_exposure_date` 改用 `exposure_datetime`，利用現有 `(case_id, field_key)` 的共享機制。
- **不可認定「最近一次可能暴露」一定等於「目前這次暴露」**。如使用者描述多次事件，須明確選擇 Active Case／建立新 Case／要求澄清；尚不能決定指向哪個 Case 時，不應自動複製或合併時間。
- `last_test_date` 與 `test_date`、`hiv_test_result` 與 `test_result` 也可能有語義重疊，但本次**只盤點、不自行合併**，避免超出確定範圍。
- 請依 `CategoryRegistry` 的共享欄位型別與描述一致性驗證更新，檢查各 Category 同名欄位的 `type`、`description` 完全一致。
- Runtime 欄位定義有改動就產生**新的 Registry `catalog_version`**；新快取 identity 需隨版本更新。保留原始 v2 目錄作為來源快照，勿悄悄覆寫歷史來源資料。

**歷史 SQLite 注意事項**

- 舊資料可能保存 `last_possible_exposure_date`，**不可靜默丟棄或無條件搬成 `exposure_datetime`**。
- 目前仍屬研究／模擬階段時，可明確使用新資料庫重跑合成案例；但要在 README 註記「舊 Registry 版本的 Active Session 不可直接以新 Registry 恢復」。
- 如果要保留既有 SQLite 資料，應另開 migration，先核對同一 Case 是否存在兩個時間值；有衝突必須標示待確認，不可選一個直接覆蓋。
- 不修改舊四類 `QuestionType`、`WarrantEngine`、`DecisionInput`、`DecisionResult` 或 `decide/evaluate` 契約。

**驗收**

- [ ] 四個涉及該暴露事件時間的 Category 可共用同一 `exposure_datetime`。
- [ ] 更正時間後再查 `window_period`，`known_count` 不重複，值為最新已確認值。
- [ ] 第二個 Case 不繼承第一個 Case 的暴露時間。
- [ ] 模糊的「最近一次」情境不會無依據合併不同事件。
- [ ] Registry 版本更新，14 個 `category_id` 與 Prototype Catalog 對應保持不變。
- [ ] Category JSON 仍只有 `category_id`、`category_name`、`fields` 三個頂層欄位。
- [ ] 空欄位類別 `hiv_basics` 的 `fields: {}` 行為保持不變。

### 修正 C：SQLite 檔案保護及驗收紀錄

**主要檔案**

- `.gitignore`
- `docs/architecture.md`、`README.md`
- 視測試結果修正相關 `tests/test_context_intake_sqlite.py`、`tests/test_context_intake_persistence_integration.py`、`tests/test_cli.py`

**檔案保護**

- 新增以實際開發慣例為準的 `.gitignore` 規則，至少涵蓋 `*.db`、`*.sqlite`、`*.sqlite3` 及常見 `-journal`、`-wal`、`-shm` 側寫檔，並建議統一使用不追蹤的 `runtime-data/` 目錄。
- 執行 `git check-ignore -v runtime-data/intake.sqlite3` 及其他自訂檔名，確認規則生效。
- 執行 `git ls-files` 檢查是否已有資料庫被追蹤；**若已追蹤，僅修改 `.gitignore` 不會自動解除追蹤**。若涉及敏感資料，需另行檢查提交歷史與存取風險。
- 不提交任何真實個案 SQLite 檔、對話原文或 API Key。

**實際執行的最低驗收指令**

```bash
python -m pytest -q
python -m clinical_warrant --help
python -m clinical_warrant intake demo --fixture evaluation/context_intake/synthetic_multiturn.json
python -m clinical_warrant intake evaluate --input evaluation/context_intake/synthetic_multiturn.json --output evaluation-runs/context-intake
python -m pytest -q tests/test_cli.py tests/test_warrant.py tests/test_classifier.py
git check-ignore -v runtime-data/intake.sqlite3
git ls-files '*.db' '*.sqlite' '*.sqlite3'
```

- [ ] 正常執行 pytest，記錄 Python 版本、測試總數、passed/failed/skipped；不可用「測試檔存在」代替執行結果。
- [ ] `intake demo` 可回放完整 Fixture，沒有非預期欄位。
- [ ] `intake evaluate` 產生 `summary.json`、`predictions.jsonl`、`errors.jsonl`，並檢查 error 數量及每輪狀態。
- [ ] 舊版 `decide` / `evaluate` 相關測試通過，未因 14 類 Registry 變更而改變決策輸出。
- [ ] SQLite 的參照完整性、刪除、rollback、重啟讀回及跨 Case 隔離測試通過。
- [ ] `.gitignore` 能排除自訂檔名與側寫檔。
- [ ] 輸出記錄註明測試是在何種環境實際執行、失敗項目、剩餘限制；不誇稱曾執行真實 LLM 或醫療驗證。
- [ ] 若環境缺少模型，清楚將離線 pytest 與真實 Sentence Transformer 評估分開列示。

## 三、建議工作分配：3 個 Commit

### Commit A — 修正 Fixture 資料污染

`fix(context-intake): 修正合成對話無依據的欄位擷取`

- 修正合成對話與預期標籤，確保 `extracted_attributes` 不憑空補值。
- 更新 Fixture 回放斷言與無依據擷取負向測試。
- 不對真實模型效果下結論。

### Commit B — 統一跨類別事件時間

`refactor(category): 統一同個案暴露時間欄位與更正行為`

- 統一同一 Case 的暴露時間 key，更新 Category JSON、相關測試與多輪 Fixture。
- 保持事件隔離、目錄版本變更與原始 v2 快照不變。
- 明定舊 SQLite 資料的處理方式，避免靜默遷移。

> **順序建議**：Commit A 可先修掉無根據的暴露方式；Commit B 才處理跨 Category 時間 key。完成後統一重跑整份多輪 Fixture。

### Commit C — 補強檔案保護及完成實測驗收

`test(context-intake): 補齊資料庫防護與回歸驗收紀錄`

- 補 `.gitignore`、相容性回歸、SQLite 測試及說明文件。
- 實際執行最低驗收命令並保存結果摘要。
- 若有失敗，先修正或明確列出 blocker，不可直接標「驗收完成」。

**開發流程約束**：一次只執行一個 Commit 的範圍；完成後提出變更摘要與建議提交訊息。**不要自行 commit、push，也不要在未經審閱時自動進下一階段**。

## 四、驗收結束應提供的成果

1. **修改清單**：逐檔列出 JSON、Fixture、測試、文件、`.gitignore` 變更。
2. **欄位對照**：修正前後 event-scoped 暴露時間欄位及各 Category 使用情形。
3. **實驗證據**：pytest 結果、CLI stdout／報告路徑、`errors.jsonl` 的差異。
4. **相容性證據**：原本四類 Warrant 輸入輸出與相關測試保持不變。
5. **待處理事項**：非本次範圍的風險與後續整合工作。

## 五、明確排除的下一階段工作

以下工作**不屬於這次修正計畫**，建議在工程驗收完成後另立工作項目：

- 真實 LLM Adapter：把 `Extractor` Protocol 接至模型服務，讓 AI 自主選欄與擷取，並評估語義依據及錯誤擷取率。
- 自由文字互動：提供真正能輸入任意使用者問題的對話介面；目前 `intake demo --step` 只是暫停後繼續固定 Fixture。
- 自動 Case 建立／切換：建立上層對話控制器，決定新事件、同一事件延續或需要澄清，不要求使用者手動傳 `new_case=True`。
- 專家判斷規則：如有醫療專業人員參與，再定義或驗證臨床必要欄位與醫療判斷門檻。
- 真實模型與外部使用者評估：另建經設計的測試集，不能把 fixture exact match 當作 Sentence Transformer、LLM 或醫療能力證據。

**完成定義**：修正後的合成資料不再憑空擷取資訊、同 Case 的暴露時間只存在一個正規欄位且更正一致、SQLite 檔案受到版本控制保護，並有可核對的實際回歸測試結果；不要求於此階段完成真實 LLM 對話系統。
