# Context Intake — OpenAI API 整合計畫 v1.0

**建議路徑：** `docs/context-intake-openai-integration-plan.md`

**基準：** `dev` 分支，Commit `f4ac77e`

## 1. 專案目標

將既有 Context Intake 模組與 OpenAI API 整合，完成可以實際自由對話、分類問題、擷取個案資訊、持久化資料並顯示 Coverage 的端到端系統。

保留既有模組化單體架構、14 類 Sentence Transformer 分類器、Category Registry、SQLite Repository 及歷史四類 Warrant 決策流程。

初期僅使用虛構 HIV 衛教情境，不進行個人化臨床診斷或藥物決策。

## 2. 技術選擇

| 項目 | 技術 |
|---|---|
| 問題分類 | 既有 Sentence Transformer |
| LLM | OpenAI API，初始建議 `gpt-6-luna` |
| API | Responses API |
| 輸出格式 | Structured Outputs / Pydantic |
| 資料儲存 | 既有 SQLite Repository |
| 使用者介面 | Python CLI |
| 環境變數 | `OPENAI_API_KEY`、`OPENAI_MODEL` |
| 測試 | pytest、Fake Adapter、選擇性真實 API 測試 |

OpenAI 模型必須可由設定檔切換，不能直接寫死在業務邏輯中。

## 3. 五個 Commit

### Commit 1 — OpenAI 環境及 API Adapter

**建議名稱：**

`feat(openai): 新增OpenAI API設定與客戶端`

工作內容：

- 在 `pyproject.toml` 新增獨立 `openai` optional dependency。
- 延用 `.env.example`，補充模型名稱、逾時等設定。
- API Key 僅透過環境變數讀取，不寫入程式碼或 Git。
- 在 infrastructure 建立 OpenAI Client Adapter。
- 新增獨立 API smoke test，確認授權、模型存取與結構化輸出功能。
- 設定 timeout、有限次重試與錯誤處理。
- 預設不持久保存 API Response State。
- 記錄 token usage 與 API latency，不記錄 Key。

**驗收：** 可在開啟真實 API 測試時成功呼叫模型；未設定 Key 時有清楚錯誤，不影響離線測試。

### Commit 2 — 真實 LLM 欄位擷取

**建議名稱：**

`feat(context-intake): 串接OpenAI欄位選擇與資訊擷取`

主要檔案：

- `modules/context_intake/infrastructure/openai_extractor.py`
- `modules/context_intake/application/extraction.py`
- `bootstrap/composition.py`
- 對應測試

工作內容：

- 實作既有 `Extractor` Protocol。
- 將當前使用者訊息、Category JSON、已知個案欄位及必要上下文傳送給模型。
- 使用 Structured Outputs，讓模型產生可驗證的欄位選擇與擷取結果。
- 模型不得輸出不在 Category 中的欄位。
- 擷取值必須附上使用者原句中的依據片段，先由 Adapter 驗證，再轉換成既有 Extraction 契約。
- 無明確依據、未知或無法判斷時保持 `null`／不新增欄位。
- 僅透過 Service 寫入已接受資訊，不讓 LLM 直接操作 SQLite。
- 補問應以尚未取得且與目前問題相關的候選欄位為主。

**驗收：** 「我昨天有一次可能的暴露」只能取得暴露時間，不能擅自產生「性行為」等未提供的資訊。合法 JSON 格式本身不代表語意正確，測試需同時檢查資訊是否有據。

### Commit 3 — 自動 Case 管理與對話協調器

**建議名稱：**

`feat(context-intake): 新增對話路由與自動Case管理`

主要檔案：

- `modules/context_intake/application/conversation_orchestrator.py`
- `modules/context_intake/application/case_router.py`
- `modules/context_intake/infrastructure/openai_case_router.py`

工作內容：

- 建立統一對話入口。
- 新問題先透過 Sentence Transformer 分類一次，避免重複計算；待答補充則沿用 Active Category。
- 取得 Category 後，由 Case Router 根據使用者明示資訊及既有 Session 決定：建立 Case、延續 Case、不建立個案，或要求澄清。
- 不得僅因某個 Category 具有欄位就自動建立個案。
- 無法確定是否為同一事件時，不得合併資料。
- 使用者提供新事件時建立新 Case。
- 使用者修正資料時利用既有衝突確認與歷史紀錄機制。
- 保留原有 `ContextIntakeService.process_turn()` 的相容介面。
- LLM 不得直接指定任意 Case ID 或修改已保存資料。

**驗收：** 使用者不必自行設定 `new_case=True`，仍能完成建立個案、延續對話、跨 Category 共用欄位、修正與新 Case 隔離。

### Commit 4 — 真實互動 CLI 與 SQLite 串接

**建議名稱：**

`feat(cli): 新增OpenAI即時對話與SQLite整合`

工作內容：

- 增加 `clinical-warrant intake chat` 指令。
- 允許使用者自由輸入問題，不再使用固定 Fixture。
- 初始化持久 SQLite Repository。
- 為使用者提供匿名 Participant ID 與 Session ID，允許延續指定 Session。
- 每輪顯示辨識 Category、選取欄位、已知欄位、補問與 Coverage。
- 提供查看目前 Case、切換／清除 Case、退出對話等明確操作。
- SQLite 不記錄 API Key；預設不保存完整對話原文。
- API 發生錯誤時不得寫入不完整的個案資料。
- 原有 `intake demo/evaluate`、`decide/evaluate` 保持不變。

**驗收：** 關閉 CLI 後重新開啟指定 Session，能從 SQLite 恢復個案資訊與已知欄位。

### Commit 5 — 端到端測試與研究評估

**建議名稱：**

`test(context-intake): 完成OpenAI對話整合與回歸驗收`

工作內容：

- 建立固定的多輪合成對話測試集。
- 以 Fake OpenAI Adapter 執行完整離線測試。
- 額外提供明確選擇才會執行的真實 API 整合測試，避免一般 pytest 產生費用。
- 記錄分類、欄位選擇、擷取、重複補問及 Coverage 的結果。
- 記錄 API 呼叫次數、token usage、latency 與估算成本。
- 測試 API 超時、拒絕回覆、配額不足、錯誤 Schema、重試與 Session 恢復。
- 執行既有四類 Warrant、SQLite、分類器與 CLI 回歸測試。
- 更新 README 與使用說明。

**驗收：** 在實際可用的 Python 環境完成端到端執行，保存測試輸出。區分「工程測試通過」與「真實模型擷取品質」，不能以合成資料通過宣稱醫療安全性。

## 4. 安全與成本控制

- 初期全部使用虛構資料。
- API Key 不得出現在 Commit、錯誤訊息或測試報告。
- 僅傳送執行欄位擷取需要的上下文。
- 避免在 OpenAI 端額外建立長期對話狀態；多輪狀態由本地 SQLite 管理。
- 限制每輪模型呼叫次數、輸出長度、timeout 與 retry。
- 為測試設定明確的 API 使用預算。
- 若模型呼叫失敗，應提示使用者並保留前一次有效狀態，不得生成虛構欄位。
- Clinical Warrant 是否有足夠證據仍是獨立問題，不能直接以 Coverage 代替。

## 5. 最終完成條件

1. 可直接輸入任意測試問題。
2. 14 類 Sentence Transformer 分類器成功運作。
3. 系統載入正確 Category JSON。
4. OpenAI 真正選擇並擷取候選欄位。
5. 可自動建立、延續、澄清與分離 Case。
6. SQLite 可以保存並恢復 Session。
7. Coverage 正確顯示各 Category 已取得資訊。
8. 使用者可以完成至少三輪連續互動。
9. 不會因 API 失敗寫入不完整資訊。
10. 舊版四類 Warrant 流程與相關測試保持相容。

**不包含：** RAG、正式醫療診斷、醫院部署，以及尚未驗證的臨床充分性規則。

**Git 規範：** 依 Commit 順序執行，每階段完成後提交測試結果與建議 Commit 名稱，不自行 Commit 或 Push。