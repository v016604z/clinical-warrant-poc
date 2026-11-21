# Clinical Warrant PoC｜可複用的 RAG Knowledge Base 資料處理 Pipeline 實作計畫

> **性質**：待實作計畫（不是已完成紀錄）  
> **參考專案**：[v016604z/clinical-warrant-poc](https://github.com/v016604z/clinical-warrant-poc)  
> **參考風格**：[`docs/implementation-plan.md`](https://github.com/v016604z/clinical-warrant-poc/blob/main/docs/implementation-plan.md)  
> **預期存放位置**：`docs/rag-kb-pipeline-plan.md`  
> **實作規模**：最多 **6 個本機 commit**，每階段獨立驗收，不自動 push。  
> **資料基準**：2026-11-21 `main` 分支，`datasets/tw_cdc_hiv_qa/qa.jsonl` 共 119 筆。

## 1. 目標與研究定位

### 1.1 核心目標

將已爬取的 **119 筆台灣 CDC HIV FAQ**，透過一套可重複執行、可擴充來源、可驗證的處理流程，轉換為 **RAG-ready Knowledge Base**。未來增加其他資料（例如其他政府機關 FAQ、人工整理的指引文字、已抽取的 PDF 文字）時，只需新增來源適配器（Adapter）或提供通用 JSONL 欄位映射，即可沿用同一條 Pipeline，並合併至相同資料契約。

設計原則：**來源蒐集與下游整理分離、通用契約與來源邏輯分離、原始資料與衍生資料分離、知識資料與實驗標註資料分離**。

### 1.2 本次交付（In Scope）

- 來源適配器：`cdc_qa`、`generic_jsonl` 兩種實作；後者用於證明跨來源可複用。
- 共用文件契約、文字清洗、欄位驗證、品質標記、來源追溯。
- RAG 文件標準化、以文件/段落為邊界的 deterministic chunking。
- ID/版本管理、精確去重、品質報告、異常紀錄、可重跑與跨來源合併。
- CLI：`kb build`、`kb merge`、`kb validate`；不影響既有 `decide`／`evaluate`。
- CDC 119 筆端到端驗證，外加至少一組**非 CDC** 的通用 JSONL fixture。
- README／契約／新增來源的操作指南與測試。

### 1.3 明確不做（Out of Scope）

- 不重寫或重新爬取 CDC 來源；以既有 `qa.jsonl`、`raw/`、`manifest.json` 為輸入。
- 不開發通用 PDF/OCR/Word 網站爬蟲；未來以新 Adapter 擴充。
- 不導入向量資料庫、Embedding 建索引、LLM 回答或 RAG 檢索服務。**本階段交付的是與向量資料庫無關的、可直接供索引器讀取的標準 Knowledge Base 文件。**
- 不產生醫療個案規則、Clinical Warrant gold labels 或臨床回答正確性標註。
- 不自動將「來源較舊」判定為醫學錯誤；不自動修寫醫療內容。
- 不接觸真實患者資料，不宣稱臨床驗證。

## 2. 現有資料盤點與待解決問題

來源：[`datasets/tw_cdc_hiv_qa/`](https://github.com/v016604z/clinical-warrant-poc/tree/main/datasets/tw_cdc_hiv_qa)。

| 項目 | 目前觀察 | 本計畫處理方式 |
|---|---|---|
| FAQ | 119 筆、14 個原始欄位、無重複 ID | 不覆寫原資料，轉成統一 `KnowledgeDocument` |
| 來源快照 | 13 個核准頁、15 份 HTML（含 2 份政策頁） | 保留 `source_url`、原始 ID、raw path、原始 hash、更新/擷取時間 |
| HTML 雜訊 | 119/119 答案含 `日期 發送處` 註解文字 | 清除非內容註解與 CMS 樣板雜訊，保留醫療語意 |
| 其他版面雜訊 | 9 筆含「檔案列表／週報表／月報表…」樣板字樣 | 僅移除精確匹配且具上下文的版面標記，不刪除真正內容 |
| 資料時效 | 101/119 筆的來源更新日期落於 2019–2021 年 | 標記待查核與時間敏感內容，不以年份直接刪除 |
| 附件完整性 | 1 筆 PrEP/PEP 比較問答只保留附件 URL | 標記 `attachment_dependency`；未取得附件內容時不可宣稱證據完整 |
| 資料用途 | CDC 主題分類、衛教 FAQ | **不是**患者 query、Clinical Warrant 標註或臨床 gold dataset |

> 以上數量是啟動前的盤點基準，驗收時須**重新讀取輸入與 manifest** 產生真實報告；不得把 119、101、9 等數字硬編碼在通用程式邏輯中。

## 3. 目標架構：Modular Monolith + Source Adapters

沿用既有 `src/clinical_warrant/`、Layered Architecture、Modular Monolith。新增一個 `knowledge_base` 業務模組，不直接依賴 classification、decision、evaluation 的內部實作。

```text
clinical-warrant-poc/
├── datasets/
│   ├── tw_cdc_hiv_qa/                # 既有來源（immutable）
│   │   ├── qa.jsonl
│   │   ├── manifest.json
│   │   └── raw/
│   └── ...                           # 未來其他來源的原始輸入
├── src/clinical_warrant/
│   ├── modules/
│   │   └── knowledge_base/
│   │       ├── __init__.py           # 模組公開 API
│   │       ├── domain/
│   │       │   ├── contracts.py      # SourceRecord / KnowledgeDocument / KnowledgeChunk
│   │       │   └── policies.py       # 穩定 ID、版本與品質政策
│   │       ├── application/
│   │       │   ├── pipeline.py       # 調度讀取、標準化、清洗、驗證、切分、輸出
│   │       │   ├── cleaning.py       # 可測試的文字/HTML 清洗策略
│   │       │   └── chunking.py       # 決定性切分與來源引用
│   │       └── infrastructure/
│   │           ├── adapters/
│   │           │   ├── cdc_qa.py     # 現有 CDC JSONL → SourceRecord
│   │           │   └── generic_jsonl.py # 新來源映射 → SourceRecord
│   │           └── files.py          # JSONL、manifest、report、原子寫入
│   ├── interfaces/cli.py             # 擴充 kb build/merge/validate
│   └── bootstrap/composition.py      # 組裝 Adapter + Pipeline
├── tests/
│   ├── test_kb_contracts.py
│   ├── test_kb_adapters.py
│   ├── test_kb_cleaning.py
│   ├── test_kb_chunking.py
│   ├── test_kb_merge.py
│   └── test_kb_cli_e2e.py
└── docs/
    ├── rag-kb-pipeline-plan.md       # 本文件
    ├── rag-kb-schema.md             # 契約與版本說明
    └── rag-kb-usage.md              # 使用與擴充指南
```

以上是**建議結構**；實作時只建立有實際程式的層與檔案，不為目錄對稱建立空檔案。

### 資料流

```text
CDC qa.jsonl ──────► cdc_qa Adapter ─────┐
                                         │
其他來源 JSONL ───► generic_jsonl Adapter ┤
                                         ▼
                                  SourceRecord
                                         │
                     schema 檢核 + 標準化 + text cleaning
                                         ▼
                               KnowledgeDocument
                                         │
                         quality flags / provenance
                                         │
                     可索引狀態檢核 + deterministic chunk
                                         ▼
                                KnowledgeChunk
                                         │
                     版本化 build + 跨來源 merge/validate
                                         ▼
                    RAG-ready Knowledge Base（JSONL）
                        （未來由 Indexer 匯入向量庫）
```

**重要邊界**：Adapter 負責理解來源 schema；共用 Pipeline **不應出現 `if source == "CDC"` 類型的內容清洗分支**。若來源有特殊 CMS 結構，可透過 Adapter 輸出 `content_type`、`cleaning_profile` 等明確設定，選用對應的 Cleaner。不同來源的共用驗證、chunking、報告與合併邏輯則完全共用。

## 4. 統一資料契約（Schema v1）

### 4.1 SourceRecord：Adapter 的最小輸出

所有 Adapter 都必須提供：

- `dataset_id`：來源命名空間，例如 `tw_cdc_hiv_qa`、`hospital_guideline_2026`。
- `source_record_id`：該來源內可穩定識別的 ID；不可使用輸入行號作唯一依據。
- `document_type`：如 `faq`、`guideline_section`、`article`、`plain_text`。
- `title`、`content`：來源原始標題與主體內容（可為 HTML 或純文字）。
- `content_type`：`text/plain` 或 `text/html`；需對應實際內容。
- `provenance`：來源機構、`source_locator`（URL 或可重現的文件/頁碼定位）、更新日期、擷取日期、原始內容 hash/快照（可提供時）。
- `metadata`：可擴充的原始分類、語言、附件、使用條件等欄位。

缺少必要來源身分或主體內容時不得默默產出正常文件；必須記錄拒收原因。

### 4.2 KnowledgeDocument：通用、可引用的清洗後文件

**範例：CDC FAQ 的預期輸出**（省略部分 hash）：

```json
{
  "schema_version": "1.0",
  "document_id": "tw_cdc_hiv_qa:76f858054012e21104c75e82264da5757947b329ad70a828782eca92790c884a",
  "document_version": "sha256:<clean-content-hash>",
  "document_type": "faq",
  "title": "與愛滋病患聊天，會不會被感染？",
  "content_text": "問題：與愛滋病患聊天，會不會被感染？\n回答：不會。愛滋病毒的傳染須透由體液、血液的交換，空氣並不是愛滋病毒的傳染途徑，且唾液也不會造成傳染。",
  "language": "zh-Hant",
  "source": {
    "dataset_id": "tw_cdc_hiv_qa",
    "publisher": "衛生福利部疾病管制署",
    "source_record_id": "76f858054012e21104c75e82264da5757947b329ad70a828782eca92790c884a",
    "source_locator": "https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5507",
    "source_updated_at": "2019-08-13",
    "collected_at_utc": "2026-11-21T11:47:48Z",
    "raw_snapshot": "raw/b2723c08e2e8180a-c457d6794e24d0aa.html",
    "raw_content_sha256": "<original-content-hash>",
    "attribution": "資料來源：衛生福利部疾病管制署"
  },
  "metadata": {
    "source_category": "認識愛滋／不會傳染的途徑"
  },
  "attachments": [],
  "quality": {
    "status": "ready",
    "flags": ["cms_noise_removed"],
    "review_status": "unreviewed"
  }
}
```

> `document_id = dataset_id + ":" + source_record_id`；內容更正應產生新 `document_version`，**不要因為清洗後文字改變就產生新 document_id**。CDC 原 `id` 由頁面 URL + 正規化問題組成，問題文字改版時原 ID 可能改變；若需追蹤這類更名，應記錄 `supersedes` 或人工對應關係，而非假設其永遠穩定。
>
> `document_version` 建議是清洗後標準內容與相關結構的 SHA-256；另保留**原始** `content_sha256`，避免混淆來源 hash 與衍生 hash。

### 4.3 KnowledgeChunk：供 RAG 索引的最小單位

```json
{
  "schema_version": "1.0",
  "chunk_id": "<deterministic-chunk-id>",
  "document_id": "tw_cdc_hiv_qa:<source-record-id>",
  "document_version": "sha256:<clean-content-hash>",
  "chunk_index": 0,
  "text": "問題：...\n回答：...",
  "char_start": 0,
  "char_end": 120,
  "source_locator": "https://www.cdc.gov.tw/Category/QAPage/...#heading5507",
  "metadata": {
    "dataset_id": "tw_cdc_hiv_qa",
    "document_type": "faq",
    "source_category": "認識愛滋／不會傳染的途徑",
    "source_updated_at": "2019-08-13"
  }
}
```

- `text` 須和 `KnowledgeDocument.content_text[char_start:char_end]` 一致；**範例中 `char_end` 為示意值，不是實際字元長度**。
- `chunk_id` 由 `document_id`、版本、chunking 設定指紋及 chunk index/offset 決定；相同輸入與設定，重跑須得到相同 IDs 與文本。
- chunk 不能失去 `document_id`、資料來源與可引用定位；URL 片段 anchor 若失效，仍應可回到來源頁及原始快照。
- `metadata` 是通用索引欄位，額外的來源專屬屬性可另保留，不任意丟棄。

### 4.4 `generic_jsonl` 的輸入範例

```json
{
  "id": "article-001",
  "title": "示範資料標題",
  "text": "這是一篇來自其他合法來源的示範文字。",
  "source_name": "Example Publisher",
  "source_url": "https://example.org/articles/001",
  "updated_at": "2026-11-01",
  "category": "示範主題"
}
```

透過命令列指定 `--dataset-id example_articles` 與 JSON 欄位映射設定（可使用此預設欄位組合）後，得到**相同的 KnowledgeDocument / KnowledgeChunk 契約**。本次驗證時必須至少實際整合一個此類 fixture，而不只撰寫介面宣告。

對無 URL 的離線 PDF 衍生內容，未來 Adapter 可提供 `source_locator`（例如文件識別 + 頁碼）代替 URL，但必須保證可以溯源；不能製造假的網頁地址。

## 5. Pipeline 的處理政策

### 5.1 清洗與正規化

1. 保留 raw 與原 `qa.jsonl` 不變；**不要直接覆寫來源**。
2. HTML 清洗時先移除 `Comment`、`script`、`style` 與確定不屬於正文的 CMS 模板節點；再擷取正文。
3. 保留標題、段落、編號列表、換行、數值單位及醫學術語。對表格若日後支援，須保留行列對應或標記需審查，不能直接攤平造成意義錯置。
4. 移除 CDC 來源中確定是模板的 `日期 發送處 start/end`、`檔案列表 start/end`、各類「報表 start/end」等**已知雜訊**；用精確規則和上下文檢查，不做會刪除一般醫療用語的廣泛正則式。
5. 統一多餘空白、空行、換行與必要 Unicode 表現；**不自行改寫醫療敘述、劑量、期間、數值、條件或日期**。
6. FAQ 的檢索內文預設為 `問題：...\n回答：...`；其他文件型態使用自身標題＋正文，不強行偽裝成 QA。
7. 文字清洗結果與 raw hash、clean hash、Pipeline 規則版本分別保存，便於回歸比對。

### 5.2 品質檢核與索引準入（Quality Gate）

- 基本檢核：UTF-8/JSON 可解析、必要欄位非空、ID 唯一、資料來源可追溯、來源快照/雜湊可核對、清洗後內容非空、不殘留已知模板標記。
- 附件依賴：若答案只說「詳見附件」但附件未納入內容，標記 `attachment_dependency`，預設 `needs_review`，**不得當作已涵蓋完整答案的可索引證據**。
- 時效性：保留來源更新日期並記錄 `staleness_review`；檢測時間、用藥規則、費用、補助、服務據點等時間敏感條目可增加 `time_sensitive` 標記。**僅憑年份不能判錯或直接刪除**。
- 內容相似：重複 ID/完全相同內容由程式檢核；高語意相似只能提示審查，不能自動當成相同醫療證據。
- 建議 `quality.status`：`ready`、`needs_review`、`excluded`；`review_status`：`unreviewed`、`approved`、`rejected`。這兩者不能互相取代；`ready` 僅表示通過**機器資料完整性檢核**，不表示臨床審核通過。
- `kb merge` 與下游索引器預設只接收 `ready`，對 `needs_review` 顯示報告並隔離；允許將審查通過的條目以可追溯的審查檔明確放行，不能靜默放行。
- 資料權利：保留來源/署名/使用條件或政策連結；CDC 開放宣告不能一律誤標成 CC BY 4.0。

### 5.3 Chunking 與去重政策

- FAQ **優先保留完整 QA 為單一 chunk**，避免將問題與答案拆開。若超過可設定長度，先按標題、段落、清單項目切分，再必要時依句子切分。
- 長度參數（例如 `max_chars=1200`、`overlap_chars=100`）需放在設定，作為**初始工程預設**而非最佳檢索參數。日後可由 RAG 指標調整。
- 不截斷超長內容而不報告；切分後應能追溯原文區間並檢查覆蓋率。
- **精確去重**：同一 `document_id` + 同一版本不可重複入庫；不同版本不得無聲覆蓋。
- **跨來源重複**：不同機構可能刊登相同文字；預設保留各自的 `document_id` 與來源紀錄，標記內容 hash 相同，避免去重後失去原始出處。
- 併入同一 Knowledge Base 時需能區分文件身分、版本與來源，並輸出重複/衝突統計。

### 5.4 可重現性、版本與錯誤策略

- 同一輸入 bytes + 相同設定版本 → 正規化文件、chunk 文本、文件/區塊 ID 一致；執行時間只出現在 `manifest`，不得影響內容身份。
- 來源資料/清洗規則/chunking 設定有變更，必須能由 manifest 查出差異。
- 輸出新 run 目錄，禁止未明示的覆寫；使用暫存目錄 + 原子發布，避免半成品成為正式 KB。
- 單筆解析或驗證失敗應記錄在 `rejected.jsonl` / `issues.jsonl`，不靜默跳過。缺少必要欄位或 hash 驗證失敗時，strict 模式應非零退出且不發布 `complete=true` 的版本。
- 同一 `document_id` 出現不同有效版本，`merge` 預設報錯並列出衝突；僅在有明確的版本選擇政策或審核結果時，才允許指定啟用某版；保留歷史紀錄。
- 不使用患者資料作測試；一般測試離線執行，不要求下載 embedding 模型或連線 CDC。

## 6. CLI 與輸出成果

### 6.1 CLI 設計（預期介面，尚未實作）

```powershell
# 由已存在的 CDC 119 筆來源建立一個不可覆寫的 run
clinical-warrant kb build `
  --adapter cdc_qa `
  --input datasets/tw_cdc_hiv_qa/qa.jsonl `
  --source-root datasets/tw_cdc_hiv_qa `
  --dataset-id tw_cdc_hiv_qa `
  --output-dir kb-runs/cdc-hiv-v1

# 通用新來源；不需要修改共用的清洗、切分與 merge 程式
clinical-warrant kb build `
  --adapter generic_jsonl `
  --input datasets/example_articles.jsonl `
  --dataset-id example_articles `
  --output-dir kb-runs/example-v1

# 合併成單一、可被 RAG Indexer 消費的版本
clinical-warrant kb merge `
  --inputs kb-runs/cdc-hiv-v1 kb-runs/example-v1 `
  --output-dir kb-runs/knowledge-base-v1

# 驗證文件、chunk、版本、引用與 manifest
clinical-warrant kb validate --dataset kb-runs/knowledge-base-v1
```

CLI 可在既有 `clinical-warrant` 指令中新增 `kb` 子命令，並保留 `python -m clinical_warrant` 支援。`generic_jsonl` 對非標準欄名可另提供 `--mapping config.json`；實作時應保證無映射設定也能讀取本文範例格式。

### 6.2 每次 build / merge 的輸出

```text
kb-runs/<run-id>/
├── documents.jsonl       # 所有通過資料契約的標準文件（含需審查狀態）
├── chunks.jsonl          # 僅輸出符合索引準入政策的 chunks
├── issues.jsonl          # 每筆警示、清理紀錄、待人工審查原因
├── rejected.jsonl        # 格式錯誤／無法處理的來源資料與錯誤資訊
├── quality_report.json   # 品質統計、各來源分布、時效與附件問題
└── manifest.json         # schema/pipeline/config 版本、來源/輸出 hash、完成狀態
```

`quality_report.json` 至少應包含：輸入筆數、成功標準化筆數、ready / needs_review / excluded 筆數、chunks 數、拒收數、精確重複/跨來源重複數、清洗標記次數、附件依賴數、來源日期分布、source locator 缺漏數。**品質旗標不是臨床判決**，報告需明示這點。

**與 RAG 的介面**：下游 Indexer 只讀 `chunks.jsonl`，使用 `chunk_id` 作索引鍵，儲存 `document_id`、`document_version`、`source_locator` 和其他 metadata。未來替換 Chroma、FAISS、Qdrant 或其他儲存後端時，不需要改寫資料清洗流程。

## 7. 六階段 Commit 實作與驗收

| 階段 | Commit 名稱（建議） | 實作工作 | 必須通過的階段驗收 |
|---|---|---|---|
| **1** | `docs(kb):定義可複用知識庫資料處理規格` | 新增本計畫與 schema v1、資料用途/權限、來源身分、ID/版本策略、清洗/切分/合併準則。 | 文件明確區分 SourceRecord / Document / Chunk；列出必填欄位與輸入/輸出範例；確認原始資料不覆寫。 |
| **2** | `feat(kb):建立標準契約與多來源適配器` | 建立 `knowledge_base` 模組、domain contracts/驗證、`cdc_qa` 與 `generic_jsonl` Adapter、欄位映射。 | 119 筆 CDC 原資料可無損映射來源身分；至少一筆非 CDC fixture 可用**同一**契約；非法來源輸入有明確錯誤；既有 CLI/測試無回歸。 |
| **3** | `feat(kb):加入文字清洗與資料品質檢核` | 清除 HTML Comment/CMS 雜訊、保留段落與清單、紀錄原/新 hash；來源、附件與時效品質檢查。 | 119 筆都可清除 `日期 發送處` 雜訊；表列項目及關鍵醫療數值不被改寫；附件依賴項被標記；`issues` 含可追溯 record ID。 |
| **4** | `feat(kb):加入可重現切分與精確去重` | 文件轉 chunk、offset 與 citation 保留、chunk 版本/ID 決定性、精確去重與衝突標示。 | 同輸入同設定重跑後內容與 IDs 一致；FAQ 優先完整切分；超長文件不遺漏；跨來源重複仍保留來源。 |
| **5** | `feat(kb):提供命令列建置合併與品質報告` | 擴充 `kb build/merge/validate`，版本化 run、原子發布、manifest/quality report、合併與衝突處理。 | 三命令可執行；build 無需網路/模型；merge 可整合 CDC 與 generic；validate 可偵測破壞的 chunk 引用/hash；預設不覆寫輸出。 |
| **6** | `test(kb):完成CDC資料與跨來源端到端驗收` | 完整 pytest、119 筆 fixture/快照端到端核對、第二來源整合、README／使用文件、問題統計與最終驗收紀錄。 | CDC input=119，文件筆數與拒收/隔離數可對帳；所有正式 chunks 來源可追溯；跨來源 merge 成功；原 CLI baseline 與既有測試維持；不 push。 |

### 各階段的最小測試矩陣

| 測試情境 | 預期結果 |
|---|---|
| CDC 119 筆原始 JSONL | 全部能載入或逐筆有明確拒收原因；不得靜默少資料 |
| HTML 註解與 CMS 樣板 | 被清除，且答案主要文字及清單保留 |
| 含 HTML `<ol>/<ul>/<br>` | 輸出保留清單/段落分界 |
| 附件中才有核心內容 | `needs_review / attachment_dependency`，預設不進入可索引 chunks |
| 舊的 `source_updated_at` | 來源日期保留，視政策標記審查，不因年份直接重寫或刪除 |
| 缺少 source locator、無 ID、空內容、格式損毀 | 拒收並記錄行號/來源 ID/原因；strict 模式失敗 |
| 同筆輸入重跑、輸入順序改變 | IDs、標準文件與 chunk 內容一致；輸出採穩定排序 |
| 同一 document ID，同版重複 | 不重複入庫，報告去重原因 |
| 同一 document ID，不同版本 | 預設報衝突，不無聲覆寫 |
| 兩來源內容高度相似或相同 | 保留兩者來源出處，標記相似/精確重複以供審查 |
| 非 CDC generic JSONL | 經同一 Pipeline 輸出相同 schema，能 merge 到同一 KB |
| 手動竄改 chunk/manifest/hash | `kb validate` 會抓出不一致並非零結束 |
| 已存在的 `output-dir` | 非明確允許時拒絕覆寫 |
| 現有 `decide` / `evaluate` | 新功能不改動其輸入契約、判斷與 baseline 行為 |

## 8. 最終完成定義（Definition of Done）

- [ ] 原 CDC `qa.jsonl`、`manifest.json`、`raw/` 未被覆寫，且所有來源可回查。
- [ ] 119 筆能逐筆對帳；清洗掉已知 HTML/CMS 雜訊，且保留必要資訊。
- [ ] 有可執行、可驗證的 `SourceRecord → KnowledgeDocument → KnowledgeChunk` 流程。
- [ ] 至少兩種 Adapter 已實作並測試；**新增資料來源不需要修改核心 Pipeline**。
- [ ] `documents.jsonl`、`chunks.jsonl`、`issues.jsonl`、`rejected.jsonl`、`quality_report.json`、`manifest.json` 完備。
- [ ] 可辨識附件不完整、來源時效、缺漏、重複與衝突，不會把資料整理誤稱為臨床正確性審核。
- [ ] 同一輸入及設定的產出可重現；版本與引用完整；嚴重錯誤不產生假成功 manifest。
- [ ] `kb build`／`kb merge`／`kb validate` 可離線執行；測試通過且既有 `decide`、`evaluate` 不回歸。
- [ ] README 說明安裝、執行、新增 Adapter、通用 JSONL 匯入、版本治理及使用限制。
- [ ] 最多 6 個本機 commit，各階段附可追蹤驗收；**不自動 push**。

## 9. 研究使用與後續階段

本 Pipeline 的產物是**證據文本與來源資訊**，而不是訓練好的向量模型，也不是 Clinical Warrant 的決策標籤。後續可獨立發展：

1. **RAG Indexer**：使用 `chunks.jsonl` 建立 embeddings 與檢索索引，檢索結果保留 `chunk_id` / `source_locator` 供引用。
2. **Clinical Warrant 情境資料**：另行建立合成個案、必要資訊清單與 `allow / need_more_info / restrict` 的人工標註評估集。
3. **醫療證據複核**：優先查核時間敏感、依賴附件、來源不完整的條目。清理通過不等於內容臨床正確。
4. **其他來源擴充**：例如 CDC 其他 FAQ、台灣官方醫療指引、已經合法抽取的 PDF/文件；只需要新增 Adapter 或欄位映射，沿用本計畫共用輸出契約。

**交付判準**：任何新的合法資料來源，只要能提供穩定來源身分、可追溯位置與文本內容，即可透過來源 Adapter 轉成相同 `KnowledgeDocument` 與 `KnowledgeChunk`，並用 `kb merge` 納入同一版 RAG-ready Knowledge Base；無需重寫 CDC 爬蟲、分類器或資料處理核心。

---

### 參考原始碼與文件

- [`docs/implementation-plan.md`](https://github.com/v016604z/clinical-warrant-poc/blob/main/docs/implementation-plan.md)：既有 6 階段 commit 的架構與驗收風格。
- [`docs/architecture.md`](https://github.com/v016604z/clinical-warrant-poc/blob/main/docs/architecture.md)：Modular Monolith、Layered Architecture 與依賴方向。
- [`docs/data-collection.md`](https://github.com/v016604z/clinical-warrant-poc/blob/main/docs/data-collection.md)：CDC 蒐集範圍、原始快照、來源政策。
- [`datasets/tw_cdc_hiv_qa/qa.jsonl`](https://github.com/v016604z/clinical-warrant-poc/blob/main/datasets/tw_cdc_hiv_qa/qa.jsonl)：119 筆既有 FAQ。
- [`datasets/tw_cdc_hiv_qa/manifest.json`](https://github.com/v016604z/clinical-warrant-poc/blob/main/datasets/tw_cdc_hiv_qa/manifest.json)：來源狀態、hash、頁面與計數。
- [`tools/crawl_cdc_hiv_qa.py`](https://github.com/v016604z/clinical-warrant-poc/blob/main/tools/crawl_cdc_hiv_qa.py)：既有爬蟲與來源解析器。
