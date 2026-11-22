# Context Intake — 功能規格 v1.0

**建議路徑：** `docs/context-intake-spec.md`

## 1. 目標

實作依問題類別驅動的對話式個案資訊蒐集模組，辨識使用者意圖、載入候選個案欄位、累積已知資訊，並追蹤各類別的資訊覆蓋情況。

本階段不使用 RAG、不進行臨床診斷，也不要求建立具有醫學效力的必填欄位規則。

## 2. 核心功能

### F01 — 問題分類

- 使用既有的 Sentence Transformer 模型與餘弦相似度。
- 擴充為 14 個問題類別，使用統一的 `category_id`。
- 保留 `unknown` 結果，不強迫低相似度問題歸類。
- 保存最高與次高類別分數，供後續分析分類混淆。
- 相似度不是機率；門檻必須透過開發集調整。
- 使用者若正在回答上一輪的補充問題，應沿用有效的 Active Category，不可將短句單獨誤判為新問題。

14 類是 Context Intake 專用的分類目錄，`category_id` 不等同既有四類 `QuestionType`。新的分類結果另有 `top1_category_id`、`top1_similarity`、`top2_category_id`、`top2_similarity`、`is_unknown`、`model_id`、`model_revision` 與 `catalog_version`；`unknown` 是結果狀態，不是第 15 份 Category JSON。Top-1 即使低於門檻仍保留供分析，Active Category 只能由已接受的分類或明確的對話延續取得。新結果不可直接傳給既有 `WarrantEngine`；`decide` / `evaluate` 仍使用原四類分類器、規則與輸出契約。兩套分類的 prototype、門檻校準、快取識別與評估資料分開保存；未經另行審查的類別映射不屬於本計畫。

### F02 — Category Registry

- 將 14 份 JSON 放入 Python 套件資源。
- JSON 只保存 `category_id`、`category_name`、`fields`。
- 每個 Category 內的欄位 key 唯一，並有型別與中文描述。
- 只允許載入登錄的 Category，避免由不受信任的輸入直接組合檔案路徑。
- 多個 Category 共用相同概念時，使用一致的欄位 key。
- 保留分類目錄版本，方便未來新增欄位後重新計算 Coverage。

一個 `category_id` 對應一份 JSON，共 14 份；每份只有 `category_id`、`category_name`、`fields` 三個頂層欄位，例如：

```json
{
  "category_id": "personal_exposure_risk",
  "category_name": "個人暴露風險",
  "fields": {
    "exposure_datetime": {
      "type": "string",
      "description": "可能暴露的發生時間，可保留「昨天」等原始描述"
    }
  }
}
```

`fields` 是以 `field_key` 為鍵的物件，每個值只有 `type`、`description`；`type` 只接受 v2 目錄中的 `string`、`boolean`、`integer`，`fields: {}` 合法。`category_id` 與 `field_key` 使用穩定的英文 snake_case，名稱及描述使用非空字串。跨 Category 重複的 `field_key` 必須具有相同型別與語義；目前 v2 目錄的重複欄位亦使用相同描述。14 類 JSON 不使用既有四類 prototype 的 `category` / `label_zh`、規則的 `question_type` / `required_case_fields` 格式。

Commit 2 將 v2 的 `data/CDC_HIV_FAQ_Problem_Categories_JSON_v2/categories/*.json` 複製到 `src/clinical_warrant/data/context_intake/categories/` 套件資源，並設定 wheel / sdist 包含該路徑。現有三份研究 JSON 位於專案根目錄 `data/`，但既有 loader 讀取 `clinical_warrant.data`，目前 `src/clinical_warrant/data/` 尚不存在；Commit 2 須一併校正這三份檔案的套件資源佈局，保留原始內容及 `load_research_catalog()` 行為。新增獨立 Registry loader，透過 `importlib.resources` 及已登錄的 ID 載入。分類目錄版本 `catalog_version` 記於 Registry／事件中，不加進每份三欄 JSON；版本由 14 份內容指紋重現，發布新版本時保留不可變的舊目錄，供歷史統計使用。14 類 prototype 另於 Commit 3 建立，其類別 ID 必須與 Registry 一致，不能把 Category 欄位檔當成 prototype 檔。

### F03 — AI 欄位選擇與資訊擷取

AI 接收目前問題、Active Category、對應 JSON、已知欄位與必要的對話上下文。

輸出內容包括：

- `selected_fields`：AI 認為與當前問題有關的候選欄位。
- `extracted_attributes`：從使用者文字取得的欄位值。
- `selection_reason`：選擇欄位的簡短理由。
- `clarification_question`：需要補問時提出的問題。

AI 只能選擇 JSON 中存在的欄位，不能自行發明醫療欄位、病史或檢驗結果。

AI 的欄位選擇屬於**尚未經臨床驗證的資訊需求假設**，不是醫療必要條件。

Commit 4 的 extractor JSON 固定包含 `selected_fields`、`extracted_attributes`、`selection_reason`、`clarification_question` 與 `clarification_field_key`；問句非空時須提供已選取且屬於目前 Category 的欄位 key。解析器只保留 Registry 型別正確且明確提供的值。`turn_id` 與 `case_id` 由 Context Intake service 指派，不接受 extractor 指派。

`selected_fields` 是目前 Active Category 的 `field_key` 集合；Extractor 的 `extracted_attributes` 僅輸出欄位 key 與值，service 驗證 Registry 型別並接受後，才賦予 Case 與來源輪次。無 Case 的一般衛教 turn 不抽取個案欄位。只接受使用者明確提供或確認的值；推測值與未提供值不得寫成已知。不同 Category 已有的同 key 值可供參照，但在本輪 Active Category 不含此 key 時不可新增到該 Category 的選取集合。AI 的選取、Coverage 或缺漏不得自動轉成既有 Warrant 的 `required_case_fields`、`DecisionInput.case` 或決策理由。

### F04 — 多輪對話

- 保存 Active Category 與 Active Case。
- 保留不同 Category 的歷史。
- 使用者修改資料時更新目前值，保留修改紀錄。
- 若同一使用者提出新的暴露事件，應建立新 Case，避免覆蓋另一個事件的資料。
- 未知問題或分類模糊時，要求使用者澄清，不強制套用欄位清單。
- 使用者未明確提供的資訊保持未知；`false`、`0` 等有效值不可誤判為缺漏。

`Participant` 是匿名使用者，可有多個 `Session`；一個 `Session` 是連續對話，包含多個依序的 turn，可涉及多個 `Case`。`Case` 是同一 Participant 的一次暴露事件或其他個案情境，不隨 Category 切換而變；`Session` 保存可空的 `active_case_id` 與 `active_category_id`。Commit 4 的呼叫者必須以 `new_case=True` 明確表示個案情境，包括首次個案與每次新暴露；只有 Category 欄位或分類結果不足以證明使用者描述個人事件，未明示時不建立 Case、不抽取個案欄位。新事件另建 Case；切換 Category 若仍在談同一事件則沿用 Case；跨 Session 重新使用 Case 須由使用者明確指認，不依匿名 ID 自動合併。一般衛教或 `unknown` turn 可不綁定 Case，`unknown` 時清除或暫停 Active Category，等待澄清。補問回答沿用前一輪待答欄位所屬的 Case 與 Category，不能僅憑短句重新分類，且本輪抽取只可更新被詢問的欄位；該 turn 的分類分數可空，須記錄其 Category 來自對話延續。

Commit 4 的 Session 另以 `TurnEvent` 保留結構化輪次歷史：`turn_id`、可空的 Case／Category、Category 來源、分類結果、選取欄位與 Registry 版本。unknown 事件的 Case／Category 可空；補問與 handoff 亦留事件。事件不保存原始訊息內容，處理失敗的 turn 不加入歷史。

呼叫者可用 `clear_case=True` 結束目前 Case 的作用範圍。既有 Case 與事件歷史保留，該輪重新分類且不做個案抽取；新 Category 的個人資訊須待 caller 明確建立新 Case 後才收集。

`Attribute` 是 Case 中由 `field_key` 識別的目前值，不隸屬單一 Category；相同 key 在多類別共用同一值。修正時以新明確值取代目前值並保留前後版本及來源輪次；相互矛盾且尚未確認的值先待澄清，不覆蓋已確認值。未提供、`null`、空白字串及語義上的「不知道」均不計為已知；`false`、`0` 均計為已知。

Commit 4 的狀態目前保存在記憶體。值與既有值相衝突時保留舊值並記錄待確認候選；只有呼叫者明確確認候選或以 `correct_fields` 標示更正，才更新目前值並附加 history。

### F05 — SQLite 保存

採用匿名使用者識別碼，規劃六張資料表：

| 資料表 | 責任 |
|---|---|
| `participants` | 匿名使用者識別 |
| `sessions` | `session_id`、`participant_id`、可空的 `active_case_id` / `active_category_id`、`active_catalog_version` 與待答欄位；一個 Participant 可有多個 Session |
| `case_contexts` | `case_id`、`participant_id`；一個 Participant 可有多個 Case，新暴露事件另建 Case |
| `turn_events` | `turn_id`、`session_id`、`participant_id`、可空的 `case_id` / `category_id`、順序、可空的分類 Top-1/Top-2、Category 來源、模型／目錄版本、`selected_fields`；不預設保存原始對話 |
| `case_attributes` | `(case_id, field_key)` 複合主鍵、型別化 JSON 值、來源 `turn_id`、更新時間；同 Case 同 key 只有一個目前值 |
| `attribute_history` | `history_id`、`case_id`、`field_key`、來源 `turn_id`、舊值／新值與新增／修正／確認動作 |

`participants` 以 `participant_id` 為主鍵；其餘 ID 均為主鍵或受相應外鍵約束。`case_contexts` 另有 `(participant_id, case_id)` 唯一鍵；`sessions` 以 `(participant_id, active_case_id)` 指向同一 Participant 的 Case。`turn_events` 的 `participant_id` 必須與 Session 相同，非空 `case_id` 亦須指向同一 Participant 的 Case；可用複合外鍵落實。`active_category_id`、事件 `category_id` 與事件中的選取欄位須存在於對應版本的 Registry；`unknown` 以空 Category 表示。`case_attributes` 不含 `category_id` 作為鍵，同一 Case 可跨 Category 共用資訊；`attribute_history` 參照 Case、欄位及來源 turn。更新目前值與寫入歷史須在同一交易完成。刪除 Case 時，在同一交易清除 Session Active Case 與事件 Case 參照，並刪除其欄位、歷史，不能留下懸空參照。這六表只保存研究所需的結構化資料，不預設寫入原始對話或直接識別資訊。

### F06 — Coverage Tracking

每個 Category 至少提供以下數值：

| 指標 | 定義 |
|---|---|
| `catalog_count` | Category JSON 定義的候選欄位數 |
| `selected_count` | 該 Case 與 Category 最近一次完成選欄的 turn 中，AI 選取的候選欄位數 |
| `known_count` | 該 Case 已明確取得的候選欄位數 |
| `selected_known_count` | AI 選取且目前已知的欄位數 |
| `selected_unknown_count` | AI 選取但尚未取得的欄位數 |

可另外顯示 `known_count / catalog_count` 作為欄位覆蓋率。

設 `F` 為指定 Registry 版本中該 Category 的欄位 key 集合，`K` 為指定 Case 中已明確提供／確認且值非缺漏的 key 集合，`S` 為該 Case + Category 最近一次完成欄位選擇的 turn 所記 `selected_fields`（無此 turn 時為空集合）：`catalog_count=|F|`、`selected_count=|S∩F|`、`known_count=|K∩F|`、`selected_known_count=|S∩K∩F|`、`selected_unknown_count=|S∩F|−selected_known_count`。同一 key 在同一 Case 只計一次，但可分別計入含該 key 的多個 Category；切換 Category 不刪除舊資料。統計應標示使用的 `case_id`、`category_id` 與 Registry 版本；目錄變更後可用新版本重算，歷史結果依不可變的舊版 Registry 與欄位歷史重算。沒有 Case 的衛教 turn 不宣稱已知個案欄位。

**Coverage 不代表 Clinical Warrant 的資訊充分性或醫療安全性。**

若 `catalog_count = 0`，顯示 `N/A`，不視為 100% 完整。

### F07 — 醫療與資料安全

- 使用模擬資料進行初期實驗。
- 不根據欄位覆蓋率直接提供感染診斷或用藥決策。
- 可能需要緊急就醫的暴露問題，不應因等待補問而延遲轉介。
- 緊急轉介判斷優先於一般補問流程；缺少候選欄位或 Coverage 未滿不得阻止轉介。
- 上游 caller 若已有緊急轉介判斷，可傳入 `urgent_handoff=True`；service 立即回傳 `handoff_required`，不分類、不抽取、不清除既有待答狀態，也不自行判斷醫療急迫性。
- 不將真實個人身分、原始對話及敏感健康資訊預設寫入實驗資料庫。
- 提供個案資料刪除與資料庫重建能力。
- 資料庫檔案與密鑰不得提交 Git。

## 3. 非本階段範圍

- RAG 與向量知識庫檢索。
- Clinical Warrant 醫療規則的專家驗證。
- 真實病患資料或醫院系統串接。
- 自動產生個人化醫療診斷。
- Web UI 或正式部署。
