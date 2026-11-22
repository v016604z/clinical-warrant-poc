# Context Intake — 實作計畫 v1.0

**建議路徑：** `docs/context-intake-implementation-plan.md`

## 1. 實作原則

延續專案既有的 Python `src` layout、Modular Monolith 與 Domain / Application / Infrastructure 分層。

保持既有 `decide`、`evaluate` 的輸入輸出契約不變。

採取 Context Intake 專用的 14 類分類路徑，保留原始 4 類分類器、`QuestionType`、prototype / rule catalog、`WarrantEngine` 與評估資料作為既有決策路徑。可複用同一 Sentence Transformer encoder 實作，但不可將 14 類加入舊四類的 validator、直接餵給 Warrant，或改動舊 `DecisionResult` JSON、reason codes、CLI 退出碼與 prototype 快取識別。新路徑另有結果型別、Registry、cache namespace / 指紋、校準門檻及評估報告；未定義 14 類到四類的自動映射，未來如需整合須另行審查。Category 候選欄位及 Coverage 不作為 Warrant 必填條件。

本計畫的 Commit 1 僅核對並修訂文件契約；Commit 2–6 才逐步實作。現行 `src/clinical_warrant/` 尚無 Context Intake Registry、14 類分類器或 SQLite 模組，現有 research catalog loader 也只載入四類資料。現有三份研究 JSON 實際位於根目錄 `data/`，而 loader 指向尚不存在的 `src/clinical_warrant/data/` 套件資源；Commit 2 必須先校正此佈局並驗證舊 loader，再加入 14 類 JSON。架構文件描述的是現況，下列路徑與資料表均屬後續實作目標。

## 2. 六個 Commit

| 階段 | 工作內容 | 建議 Commit |
|---|---|---|
| 1 | 確定功能規格、資料契約與驗收條件 | `docs(context-intake): 釐清功能規格與資料契約` |
| 2 | 整合 14 份 JSON、驗證欄位與分類索引 | `feat(category): 新增十四類問題設定與欄位索引` |
| 3 | 擴充 Sentence Transformer 十四類分類路徑 | `feat(classification): 新增十四類語意分類與未知判斷` |
| 4 | 建立多輪對話狀態、AI 欄位選擇及抽取介面 | `feat(context-intake): 新增對話式個案資訊蒐集` |
| 5 | 導入 SQLite 與欄位修改歷史 | `feat(storage): 新增個案資訊與對話歷程保存` |
| 6 | 加入 Coverage、CLI 示範及實驗評估 | `feat(evaluation): 新增欄位覆蓋追蹤與整合測試` |

## 3. 各階段驗收

### Commit 1 — 規格與契約

- 定義 Category、Case、Attribute、Session 等概念。
- 確定 Category JSON 與 SQLite 資料表契約。
- 確定目前 4 類與新 14 類的隔離方式。
- 明確區分 AI 建議欄位和經專家驗證的必要欄位。
- 文件明定兩種分類結果型別、組裝入口、快取與評估資料的隔離邊界；既有 `decide` / `evaluate` 契約不變。
- 文件核對 v2 目錄恰有 14 份 JSON，明定 `fields` 物件與空物件、共享欄位型別、套件資源目標路徑及六表鍵／外鍵／Coverage 公式。
- 本 Commit 的驗收以文件與現有程式／v2 JSON 對照、差異審查為準；不以尚未實作的 Registry、資料庫或新 CLI 測試作為通過條件。

### Commit 2 — Category Registry

- 整合 v2 的 14 個 Category JSON。
- 每個 JSON 均能正確解析與驗證。
- `category_id` 不得重複。
- 同名欄位的資料型別與意義必須一致。
- 完成套件資源打包，安裝後仍能讀取 JSON。
- `fields: {}` 必須是合法類別設定。
- 一個 `category_id` 對應一份檔案；每份只有 `category_id`、`category_name`、`fields`，每個 `fields[field_key]` 只有 `type`、`description`，型別接受 v2 的 `string`、`boolean`、`integer`。
- 先建立可由 `importlib.resources.files("clinical_warrant.data")` 存取的 `src/clinical_warrant/data/` package，將根目錄 `data/` 的三份研究 JSON 原樣放入，保留 `load_research_catalog()` 的內容與介面，並驗證舊四類載入流程。
- 將新檔案置於 `src/clinical_warrant/data/context_intake/categories/`；以 `importlib.resources` 及白名單 ID 讀取，更新套件資料設定並以 wheel / sdist 安裝後讀取測試驗證新舊資源，均不依賴工作目錄。
- Registry 版本由 14 份內容指紋重現，並可供事件與 Coverage 引用；發布新版本時保留不可變的舊目錄，不擴充三欄 Category JSON。

### Commit 3 — Classification

- 複用既有 Sentence Transformer encoder 介面，另建 14 類分類器與 Prototype Catalog；prototype 獨立於 Category JSON，其 14 個 ID 必須與 Registry 完全一致，舊四類 classifier / catalog 驗證規則保持原狀。
- 新分類快取識別包含模型 ID / revision、14 類目錄版本與 prototype 指紋，使用獨立 namespace；舊快取識別保持原狀。
- 新結果回傳 Top-1 / Top-2 的 `category_id` 與相似度、unknown 狀態、模型及目錄版本；不修改既有 `ClassificationResult` / `DecisionResult`。
- 使用開發資料校準門檻，不直接沿用舊版 0.5 當作有效設定。
- 保留原始 4 類 `decide` / `evaluate` 行為。
- 14 類結果不得直接傳入 `WarrantEngine`；未來映射不屬於此 Commit。
- 使用獨立開發集調門檻、獨立問題測試集輸出混淆矩陣及 Macro-F1；不改寫既有四類評估報告或 20 例 baseline。

### Commit 4 — Context Intake

- 實作 Active Category / Active Case。
- 新增 AI 欄位選擇與資訊擷取介面。
- AI 只能輸出 Category JSON 定義的欄位。
- 透過結構化 JSON 契約驗證 AI 輸出。
- 對缺值、矛盾資料、欄位修正進行處理。
- 支援使用者回答上一輪補充問題。
- 明定 Session 可跨多 Case、Case 可跨多 Category；補問延續待答的 Case / Category，新事件另建 Case，無法確定時先澄清。
- 只有明確取得或確認且型別有效的欄位值可進入 Case；跨 Category 同 key 共用，矛盾值須澄清，不得直接覆寫。
- 欄位抽取器設計為可替換介面，離線測試使用 Fake Extractor，實際 LLM Adapter 獨立整合。

### Commit 5 — SQLite

- 建立資料表與初始化、遷移機制。
- 使用 Python 標準庫 `sqlite3`。
- 保存 Session、Case、分類事件與已知欄位。
- 同一欄位重複提取時不重複計數。
- 修改欄位後保留版本歷程。
- 支援查詢與刪除指定 Case。
- 使用 SQLite in-memory database 測試，正式資料檔不進入 Git。
- 驗證 Participant / Session / Case 歸屬及 Active Case 的複合外鍵約束、`(case_id, field_key)` 唯一性、同交易更新目前值與歷史，以及刪除 Case 後沒有懸空參照。
- `turn_events` 保存可空 Case / Category、分類版本、Top-1 / Top-2 及選取欄位；無 Case 的一般衛教 turn 可保存，預設不寫入原始對話。

### Commit 6 — Coverage 與評估

- 新增 `intake` CLI 指令供互動測試。
- 查詢個案已涉及的 Category。
- 輸出各 Category 的已知、未知與已選欄位數。
- 驗證欄位覆蓋統計與 Category 切換。
- Coverage 使用指定版本 Category 欄位集合、Case 已知欄位集合、該 Case + Category 最近一次完成選欄的 turn 所記集合計算；共享 key 在同 Case 去重，同時可計入多個 Category。
- 建立多輪模擬對話測試集。
- 保存分類錯誤、欄位抽取錯誤與修正前後結果。
- 更新 README、架構文件與執行教學。

## 4. 必測情境

1. 一般 HIV 知識問題分類後，`fields` 為空，不要求個案資料。
2. 使用者提問暴露風險，分類後載入正確 JSON。
3. 使用者只回答「昨天」，系統能連結上一輪要求的時間資訊。
4. 使用者從暴露風險轉問空窗期，同一 Case 的已知資料可重用。
5. 同一使用者描述第二次暴露，應建立新 Case，避免覆蓋第一次。
6. `false` 必須計為已取得的有效布林值；`null` 不能計入。
7. AI 提出不存在於 JSON 的欄位時，系統必須拒絕。
8. unknown／低信心分類不可直接選取任意 Category。
9. 一個 Category 有零個候選欄位時，Coverage 顯示 N/A。
10. 舊版 4 類分類、決策與評估測試持續通過。
11. 14 類結果不進入舊 `WarrantEngine`；修改新 Category 欄位或 Coverage，不改變相同舊 `DecisionInput` 的決策、檢核與 reason codes。
12. 同 Case 切換 Category 時共享 `field_key` 可重用且不重複保存；改值後目前值與歷史一致，第二個 Case 不繼承第一個 Case 的欄位。
13. 需緊急轉介的模擬情境不因一般補問或 Coverage 未滿而延遲轉介。

## 5. 評估與交付

分類實驗記錄 Accuracy、Macro-F1、各類 Precision / Recall、Unknown Rate 與混淆矩陣。

欄位蒐集實驗記錄抽取正確率、已確認欄位數、資訊重複詢問次數、欄位修正情況及 Coverage。

獨立保存模型與分類目錄版本，使修改前後結果可比較。避免將原型句子的改寫版本同時放入開發集與測試集。

實驗結果僅代表分類與資訊蒐集的技術表現，不宣稱醫療決策正確性。

**交付範圍：** 14 類分類、Category Registry、Context Intake、SQLite、Coverage、CLI 測試、pytest、實驗報告與開發文件。

不自行 Push；每階段完成後由開發者審查並決定 Commit。
