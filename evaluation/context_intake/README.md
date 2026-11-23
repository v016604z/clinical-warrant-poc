# Context Intake 14 類分類評估資料

`dev.jsonl` 與 `test.jsonl` 是固定、互不重疊的分類資料。CDC 部分使用本 repo 的 `data/tw_cdc_hiv_qa/qa.jsonl` 119 筆問題文字；標籤依 `data/CDC_HIV_FAQ_Problem_Categories_JSON_v2/FAQ_SOURCE_MAPPING.md` 的逐題來源對照，並以其中連結的 `source_anchor` 對回 CDC 記錄。每筆 CDC 記錄的 `id` 與 `source_faq_id` 均是來源 QA 的 SHA-256 ID。

固定切分方法：依 14 類標籤分組，再按 FAQ ID 字典序排列；每類從第一筆開始交錯分配至 dev、test。這使 14 類都同時出現在兩份資料；樣本數為偶數的類別平均切分，奇數類別的多一筆放在 dev。CDC 題目共 63 筆 dev、56 筆 test；其餘 10 筆為手寫的非 HIV 題目，dev/test 各 5 筆，標籤為 `unknown`。兩份檔案中的所有案例 ID 及 CDC FAQ ID 均須不重複。

門檻只根據 dev 的 Top-1 cosine similarity 校準。候選值為 `-1`、`1` 及 dev 全部 Top-1 分數；預測規則是分數小於門檻時為 `unknown`，相等仍接受 Top-1。選擇 14 個已知類別加 `unknown` 的 Macro-F1 最高門檻；同分時選較低門檻。門檻固定後才載入並評估 test。報告提供 14 類已知分類 Macro-F1 與含 unknown 的 15 類 Macro-F1、Accuracy、各類 P/R/F1/support、unknown rate、OOD false acceptance、混淆矩陣與逐題輸出。

## 多輪對話模擬 Fixture

`synthetic_multiturn.json` 是離線工程流程的合成對話，不屬於上述分類資料。每輪的 `selected_fields` 是要檢查的候選欄位；被選取不表示使用者已提供該欄位。`extractor_response.extracted_attributes` 是假擷取器的原始輸出，可含空字串或 `null`；`expected_extracted_attributes` 是解析後本輪應接受的值，報告的 `predictions[].extracted_attributes` 顯示實際接受值。`expected_attributes` 則表示該輪結束後 Case 累積的目前狀態。

第一輪只明確提供暴露時間，因此 `exposure_route` 保持未知。第二、三輪轉問 PEP 與空窗期時，Case 仍保有已知時間，但本輪不重新擷取該時間。Fixture 可檢查新擷取值與累積狀態是否符合標註；fixture classifier / extractor 通過只代表工程流程符合預期，不能證明自然語言的語義依據。通用 Parser 能檢查欄位、格式與型別，無法判斷抽取值是否真的由使用者文字支持。跨 Category 暴露時間的正規欄位與更正一致性留待 Commit B 處理。本節不代表已執行相關測試。

## 限制

- FAQ 的 14 類標籤是研究用人工歸類，不是 CDC 官方 taxonomy 或實際使用者 query，也不是臨床 gold labels。
- 分類本身依 FAQ_SOURCE_MAPPING 的同一來源整理而來，雖然 FAQ ID 不跨 dev/test 重複，但這不是跨來源泛化測試。稀有類只有 2–3 題，因此各切分最多只有 1–2 題，指標波動很大。
- OOD 例子是少量手寫、與 HIV 無關的生活問題，只能檢查明顯非目標輸入；不能代表真實未知意圖分布。false-acceptance 分母只計 test 的 5 筆 OOD 題。
- Prototype catalog 獨立於這兩個資料集撰寫；禁止從 FAQ 原句或改寫建立 prototype。報告記錄 prototype SHA-256；如 runtime 無法提供，報告會標示 identity unavailable。
- 指標只評估研究用途的意圖分類，不代表臨床效能或醫療安全性。

執行方式（需安裝 `.[dev,model]` 並可載入固定模型）：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_context_intake.py
```

每次在 `evaluation-runs/context-intake/` 下新增不可覆寫的 run 目錄，包含 `summary.json`、`predictions.jsonl` 與 `errors.jsonl`。此 runner 不讀取或改寫既有四類評估資料及 baseline。
