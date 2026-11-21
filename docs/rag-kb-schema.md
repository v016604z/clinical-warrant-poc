# RAG Knowledge Base 資料契約 v1

本文件是[實作計畫](clinical_warrant_rag_kb_pipeline_plan.md) Commit 1 的規範。`schema_version` 固定為字串 `"1.0"`；後續 Commit 才實作 Adapter、驗證、清洗、切分與 CLI。目前的 `kb build/merge/validate` 是預期介面。

## 1. 用途、來源與權限

產物供 RAG Indexer 使用，保存證據文本及來源；不產生 embeddings、向量索引、醫療決策或 gold labels。CDC FAQ 是公開衛教參考語料，不是患者 query 或經專家審定的答案，清洗通過不表示臨床正確。測試只用公開或虛構資料，不含患者個資。

CDC 蒐集範圍、署名要求、開放宣告與著作權例外沿用[資料蒐集說明](data-collection.md)及[資料集說明](../datasets/tw_cdc_hiv_qa/README.md)。既有 [manifest](../datasets/tw_cdc_hiv_qa/manifest.json) 的 `reuse_policy_urls`、`attribution`、`policy_provenance` 是本次快照的權利證據，不代表目前網站政策已重新確認。不得把 CDC 全站標為 CC BY 4.0，也不得暗示 CDC 背書。

每個來源須保留 publisher、署名、使用條件或政策定位，並針對明確的 intended_use 記錄使用判定；不得自行猜測授權。rights.status 只表示依據是否已記錄，不能直接決定允許使用。只有 `status="recorded"`、`usage_decision="allowed"` 且條件已具備，才可能通過權利準入。依據或判定未知時以 `needs_review/rights_unknown` 隔離；`usage_decision="prohibited"` 優先設為 `excluded/rights_prohibited`，不可人工繞過。第三方或另有標示的內容依其條件處理。KB 本身與程式碼的授權不可取代來源內容權利。

## 2. 通用型別與邊界

| 規則 | v1 定義 |
| --- | --- |
| JSON / JSONL | UTF-8、無 BOM；JSONL 每行一個物件；拒絕重複 object key、NaN、Infinity 及無效 Unicode。 |
| 必填 | 表內「是」表示 key 必須存在；只有標示 `null` 的欄位可為 null。可選 key 缺省值寫於表內，不可擅用 null。 |
| 字串 | 除明示允許外，須非空且不只空白；不得含 NUL。 |
| 日期 | `YYYY-MM-DD`，須是有效日期；UTC 時間為 `YYYY-MM-DDTHH:MM:SSZ`，不可用本機時區或本次執行時間補造來源日期。 |
| SHA-256 | 裸 digest 為 64 個小寫十六進位字元；只有 `document_version` 使用 `sha256:` 前綴。 |
| 擴充 | 核心欄位以本文件為準；來源額外欄位放 `metadata`，值須為合法 JSON；未知核心欄位視為驗證錯誤。 |
| 順序 | attachments 按 `(locator, title)` 排序且不重複（排序時 null title 視為空字串）；flags、policy_locators 為排序去重字串陣列；metadata 的陣列順序照來源保留。 |

SourceRecord 是 Adapter 輸出的來源紀錄，保留未清洗內容。KnowledgeDocument 是一筆完整的清洗後文件，包含待審或排除項。KnowledgeChunk 是通過索引準入的文件片段，必須能精確回查 Document。非 FAQ 不需 question/answer 欄位，不將文章偽裝成問答。

### 2.1 SourceRecord

| 欄位 | 型別 | 必填 | 語意／缺省值 |
| --- | --- | --- | --- |
| schema_version | string | 是 | `"1.0"`。 |
| dataset_id | string | 是 | 命名空間，符合 `[a-z0-9][a-z0-9_-]*`，不可包含 `:`。 |
| source_record_id | string | 是 | 來源內穩定且非空的 ID，不以行號識別；保留原值，不做 trim 或 Unicode 改寫，不含控制字元。可含 `:`，document_id 只在第一個 `:` 分隔。 |
| document_type | string enum | 是 | `faq`、`guideline_section`、`article`、`plain_text`。 |
| title | string | 是 | 原始問題或標題。 |
| content | string | 是 | 原始答案／正文；FAQ 的問題由 title 提供。 |
| content_type | string enum | 是 | `text/plain` 或 `text/html`，須符合 content。 |
| language | string | 否 | 缺省 `und`；已知繁體中文使用 `zh-Hant`，不因資料來源自行猜測。 |
| cleaning_profile | string | 否 | 缺省 `plain_v1`，僅適用純文字；HTML 必須明確指定受支援的 profile，例如 `cdc_faq_html_v1`。未知 profile 拒收。 |
| provenance | object | 是 | 見下表；輸出 Document 時改名為 source，加入 dataset_id、source_record_id。 |
| attachments | array of Attachment | 否 | 缺省 `[]`；與 metadata 分離，保留來源提供的連結。 |
| metadata | object | 否 | 缺省 `{}`；原分類等來源欄位；不可覆蓋核心欄位。 |

`provenance` 與 Document 的 `source` 共用下列欄位。所有 key 均必填，可為 null 的欄位要明確保留 null，以區分未知資料與遺失欄位。

| 欄位 | 型別 | 語意 |
| --- | --- | --- |
| publisher | string | 可辨識的來源機構或作者。 |
| source_locator | string | 原始 URL（含可得 anchor），或可重現的文件 ID＋頁碼等定位；不能製造假 URL。 |
| source_updated_at | string / null | 來源更新日期；未知為 null。 |
| collected_at_utc | string / null | 原始擷取時間；未知為 null，不補成 run 時間。 |
| raw_content_sha256 | string | 原始紀錄內容 digest，依 raw_content_hash_basis 計算。 |
| raw_content_hash_basis | string enum | `cdc_qa_payload_v1` 或 `text_utf8_v1`，見第 3 節。 |
| raw_snapshot | string / null | 相對 source root 的原始快照路徑；不得逃出 root；未知為 null。 |
| raw_snapshot_sha256 | string / null | 快照完整 bytes 的 digest；與 raw_snapshot 同時為 null 或同時非 null。 |
| attribution | string | 保留來源署名；與 policy 條件一併供下游傳遞。 |
| rights | object | 所有 key 均必填：`status: recorded|unknown` 僅表示依據是否已記錄；`statement: string` 為非空條件／判定依據描述；`policy_locators: string[]` 可為 `[]`；`intended_use: string` 為非空目的識別／描述；`usage_decision: allowed|unknown|prohibited` 針對此用途，由來源 mapping/config 明確提供，不可從 statement 文案自動推論。recorded 不代表 allowed，未完成用途評估時須明確填 unknown；禁止默認 allowed。 |

沒有 raw snapshot 仍可匯入可追溯的純文字紀錄，原始輸入檔及其 hash 必須由 run manifest 保存。提供 snapshot 時必須核對完整 bytes hash，不能將 snapshot 路徑存在當作已驗證；缺失、越界、hash 不符屬錯誤。

Attachment 的 key 均必填：`locator: string`（來源附件 URL 或離線位置）、`title: string|null`、`media_type: string|null`、`included: bool`。只有附件內容實際納入本文且可追溯時才設 included=true。來源答案依賴未納入的附件時，設 `attachment_dependency` 及 needs_review；只列有參考附件不等於答案一定依賴附件。

### 2.2 KnowledgeDocument

| 欄位 | 型別 | 必填 | 語意 |
| --- | --- | --- | --- |
| schema_version | string | 是 | `"1.0"`。 |
| document_id | string | 是 | `dataset_id + ":" + source_record_id`，與清洗內容無關。 |
| document_version | string | 是 | `"sha256:" + H(version_projection)`，見第 3 節。 |
| document_type | string enum | 是 | 同 SourceRecord。 |
| title | string | 是 | 正規化後問題／標題。 |
| content_text | string | 是 | 清洗後的完整檢索文本；FAQ 為 `問題：{title}\n回答：{clean_answer}`，其他型別為 `{title}\n{clean_body}`。 |
| language | string | 是 | SourceRecord 的明確值或缺省 `und`。 |
| source | object | 是 | 完整 provenance 加 dataset_id、source_record_id；不可丟失日期、權利、raw hash／快照。 |
| metadata | object | 是 | 保留來源 metadata；`supersedes` 如有，為已確認的先前 document_id 字串，不能猜測。 |
| attachments | array of Attachment | 是 | 依通用規則排序，沒有附件為 `[]`。 |
| quality | object | 是 | 見下表。 |

quality 所有 key 必填：

| 欄位 | 型別 | 規則 |
| --- | --- | --- |
| status | string enum | `ready`：機器資料完整性與權利準入通過；`needs_review`：可保存但預設無 chunks；`excluded`：排除，不產生 chunks。 |
| flags | array of string | 排序去重；如 `cms_noise_removed`、`attachment_dependency`、`staleness_review`、`time_sensitive`、`rights_unknown`、`rights_prohibited`、`exact_content_duplicate`。 |
| review_status | string enum | `unreviewed`、`approved`、`rejected`；與機器 status 分開。 |
| review_ref | string / null | unreviewed 時為 null；approved/rejected 時必須指向隨 run 保存、由 manifest hash 覆蓋的審查紀錄。 |

人工放行不能只改 review_status。審查紀錄必須包含 document_id、document_version、`source_fingerprint=H(source)`、允許覆核的 flags、decision、reviewer、reviewed_at_utc 和理由。只有來源指紋與版本均相符、approved 且明確覆核所有阻擋 flags，才能將可放行的 needs_review 文件重新檢核為 ready；原 flags 和 review_ref 保留。內容或來源（含 rights 的用途／使用判定）改變即須重審。權利未知須先補足明確依據及 allowed 判定、滿足條件後重新檢核，不能單靠 approved 直接放行。raw hash 不符、缺必要身分／usage_decision=prohibited 等硬性錯誤不能靠人工 status 繞過。rejected 一律不可索引。

### 2.3 KnowledgeChunk

| 欄位 | 型別 | 必填 | 語意 |
| --- | --- | --- | --- |
| schema_version | string | 是 | `"1.0"`。 |
| chunk_id | string | 是 | `"chunk:" + H(chunk_identity)`，見第 3 節。 |
| document_id / document_version | string | 是 | 精確引用本 run 的 Document。 |
| chunk_index | integer | 是 | 單一文件內從 0 連續遞增；不接受 bool。 |
| text | string | 是 | 必須等於 `document.content_text[char_start:char_end]`，不得另加問題前綴或標題。 |
| char_start / char_end | integer | 是 | Unicode code point offset，起點含、終點不含，`0 <= start < end <= len(content_text)`；不是 UTF-8 bytes，也不是 UTF-16 code unit。 |
| source_locator | string | 是 | 與 Document.source.source_locator 相同。 |
| metadata | object | 是 | 至少含 dataset_id、document_type、language、source_updated_at（可 null）、source_category（可 null）；皆由 Document 複製，額外來源欄位放 `source_metadata` object，缺省 `{}`。 |

相同 run 的 chunks 只引用 ready 且非 rejected 的文件。下游必須連同文件來源／權利資訊使用，不能因 chunks 欄位較少就省略署名。文件的完整 source 與 attachments 仍在 documents.jsonl 可由 identity 回查。

## 3. ID、內容版本與可重現 hash

令 `C(x) = json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')`，`H(x) = hashlib.sha256(C(x)).hexdigest()`。C 不附 BOM、空白縮排或結尾換行，不額外正規化字串；只對下述已驗證的投影使用。hash 投影不用浮點數，以避免跨實作數值序列化差異。

| 名稱 | 精確輸入與用途 |
| --- | --- |
| 原始 CDC QA hash | `sha256((original_question + "\n" + original_answer_html).encode('utf-8')).hexdigest()`；必須與原 `content_sha256` 相同；basis=`cdc_qa_payload_v1`。保持原字串，不先清洗。 |
| 原始通用內容 hash | `sha256(original_content.encode('utf-8')).hexdigest()`；basis=`text_utf8_v1`，即使 HTML 也對原 content 字串計算。原 title 等其他輸入由輸入檔 hash 保護。 |
| raw snapshot／輸入／輸出檔 hash | `sha256(file_bytes).hexdigest()`；不做 C，不移除檔案結尾換行。整頁 HTML digest 與 QA payload digest 分開保存。 |
| version_projection | `{"document_type": d.document_type, "title": d.title, "content_text": d.content_text, "language": d.language, "attachments": d.attachments}`。attachments 只含第 2 節四個規範欄位，先按規定排序。 |
| clean_content_sha256 | `H(version_projection)`；document_version 為 `sha256:` 加此 digest。沒有第二套純 text hash 冒用相同名稱。 |
| chunking_config | 完整有效設定 `{"algorithm_version":"structure-v1","max_chars":1200,"overlap_chars":100}`；`max_chars > 0`、`0 <= overlap_chars < max_chars`，均為 integer 非 bool。CLI 省略值也要展開。 |
| chunking_fingerprint | `H(chunking_config)`，放 manifest。 |
| chunk_identity | `{"document_id": c.document_id, "document_version": c.document_version, "chunking_fingerprint": fingerprint, "chunk_index": c.chunk_index, "char_start": c.char_start, "char_end": c.char_end}`。 |

dataset_id 不含冒號，因此組合 ID 無歧義；禁止以輸入順序、Python hash()、run UUID 或現在時間產生內容 ID。CDC 保留原 `id`，但其題目更名可能改變來源 ID；需 `supersedes` 或人工對應才能連結，不能假定 anchor 永遠穩定。

文件版本只對本文、標題、型別、語言及附件語意變動。dataset/record identity、provenance、metadata、rights、quality、擷取／審查／run 時間和 pipeline 版本不進 version_projection；相關變動仍被整份檔案 hash 與 manifest 記錄，且不代表可無聲去重。清洗規則版本改變但結果相同時，document_version 不變；規則版本差異仍可從 manifest 查出。chunking 改變只影響 chunk ID，不改文件內容版本。

## 4. Adapter 映射與完整範例

### 4.1 CDC 既有輸入

以 [qa.jsonl](../datasets/tw_cdc_hiv_qa/qa.jsonl)、同一 source root 的 manifest 和 raw 為輸入，不重新爬取。保留原始 119 筆；計數須執行時讀取，不能硬編碼通用邏輯。

| CDC 欄位／資料 | SourceRecord 目的欄位 |
| --- | --- |
| CLI dataset-id | dataset_id；本資料為 `tw_cdc_hiv_qa`。 |
| id | source_record_id，原值保留。 |
| question / answer_html | title / content；document_type=`faq`，content_type=`text/html`，language=`zh-Hant`，cleaning_profile=`cdc_faq_html_v1`。 |
| source_url | provenance.source_locator，含 anchor。 |
| source_updated_at / collected_at_utc | provenance 同名欄位，未知日期保留 null。 |
| content_sha256 | provenance.raw_content_sha256，basis=`cdc_qa_payload_v1`；重算驗證。 |
| raw_snapshot | provenance.raw_snapshot；依 manifest.pages 的 URL/快照對應 html_sha256，填 raw_snapshot_sha256，核對實際 bytes。 |
| manifest.attribution / reuse_policy_urls | provenance.attribution / rights.policy_locators；rights.statement 保留既有政策限制及例外，status=`recorded` 只表示已記錄政策。rights.intended_use 與 usage_decision 另由明確來源 mapping/config 提供，不能將 recorded 直接當 allowed；未完成用途評估時填 unknown。policy_provenance 納入 run 的來源證據。本文件未評估 CDC 對特定用途的實際准許。 |
| 來源機構 | publisher=`衛生福利部疾病管制署`，此為 Adapter 明確來源設定。 |
| category | metadata.source_category。 |
| page_url / source_anchor / source_faq_id / answer_text | metadata 同名保存，原 answer_text 供核對，不當作已清洗正文。 |
| attachments 中 url / label | Attachment.locator / title；未知 media_type=null，現有未下載附件 included=false。 |

### 4.2 非醫療通用來源

以下各 JSON 是完整的最小範例；來源為本專案虛構測試文字，無外部授權推論。generic_jsonl 預設將 id/title/text/source_name/source_url/updated_at/category 映射至 record ID/title/content/publisher/locator/updated date/source_category；來源權利及語言由明確設定提供。使用離線 source_locator 時，以 mapping 將來源欄位指向 source_locator，不能偽造 URL。映射檔與完整設定一併存入 manifest；未知欄位保留 metadata，映射衝突／缺必要欄位拒收。通用來源未指定 document_type 時缺省為 `plain_text`；此例明確設定 document_type=`article`、dataset-id=`example_articles`、language=`zh-Hant`、profile=`plain_v1`，權利設定僅對本專案自行撰寫文字的 `fixture_validation` 用途明確 allowed，不推論 CDC 或其他來源已獲准使用；未提供擷取時間及快照時使用 null。

原始 JSONL 的一行（此例將 source_url 欄位映射為離線定位）：

<!-- example: generic_input -->
```json
{"id":"article-001","title":"示例","text":"甲乙","source_name":"Example Publisher","source_url":"fixture:example_articles/article-001","updated_at":"2026-11-01","category":"示範"}
```

Adapter 輸出 SourceRecord：

<!-- example: source_record -->
```json
{
  "schema_version": "1.0",
  "dataset_id": "example_articles",
  "source_record_id": "article-001",
  "document_type": "article",
  "title": "示例",
  "content": "甲乙",
  "content_type": "text/plain",
  "language": "zh-Hant",
  "cleaning_profile": "plain_v1",
  "provenance": {
    "publisher": "Example Publisher",
    "source_locator": "fixture:example_articles/article-001",
    "source_updated_at": "2026-11-01",
    "collected_at_utc": null,
    "raw_content_sha256": "f73ab1f5c2b9542c9cea79597b69a5c4dc106721d7de6fa9e4303c0fe45cfe3d",
    "raw_content_hash_basis": "text_utf8_v1",
    "raw_snapshot": null,
    "raw_snapshot_sha256": null,
    "attribution": "資料來源：Example Publisher（虛構測試資料）",
    "rights": {
      "status": "recorded",
      "statement": "本專案自行撰寫的非醫療測試文字；明確允許 fixture_validation，僅供驗證此虛構 fixture，無外部來源權利推論。",
      "policy_locators": [],
      "intended_use": "fixture_validation",
      "usage_decision": "allowed"
    }
  },
  "attachments": [],
  "metadata": {
    "source_category": "示範"
  }
}
```

清洗後 KnowledgeDocument（plain_v1 在此例不改寫原文字）：

<!-- example: document -->
```json
{
  "schema_version": "1.0",
  "document_id": "example_articles:article-001",
  "document_version": "sha256:2970f96d317b9f22ddbcc6e14330ea20c9210fbab9c0ff32589b6ca3ad09306b",
  "document_type": "article",
  "title": "示例",
  "content_text": "示例\n甲乙",
  "language": "zh-Hant",
  "source": {
    "dataset_id": "example_articles",
    "source_record_id": "article-001",
    "publisher": "Example Publisher",
    "source_locator": "fixture:example_articles/article-001",
    "source_updated_at": "2026-11-01",
    "collected_at_utc": null,
    "raw_content_sha256": "f73ab1f5c2b9542c9cea79597b69a5c4dc106721d7de6fa9e4303c0fe45cfe3d",
    "raw_content_hash_basis": "text_utf8_v1",
    "raw_snapshot": null,
    "raw_snapshot_sha256": null,
    "attribution": "資料來源：Example Publisher（虛構測試資料）",
    "rights": {
      "status": "recorded",
      "statement": "本專案自行撰寫的非醫療測試文字；明確允許 fixture_validation，僅供驗證此虛構 fixture，無外部來源權利推論。",
      "policy_locators": [],
      "intended_use": "fixture_validation",
      "usage_decision": "allowed"
    }
  },
  "metadata": {
    "source_category": "示範"
  },
  "attachments": [],
  "quality": {
    "status": "ready",
    "flags": [],
    "review_status": "unreviewed",
    "review_ref": null
  }
}
```

有效 chunking 設定與其 fingerprint：

<!-- example: chunking -->
```json
{
  "config": {
    "algorithm_version": "structure-v1",
    "max_chars": 1200,
    "overlap_chars": 100
  },
  "fingerprint": "558534cded4d3359081b3c3a3f25cc090537ba9a07b170b9b8a739c5ab068806"
}
```

KnowledgeChunk：本文共 5 個 code points，完整區間 `[0:5]`：

<!-- example: chunk -->
```json
{
  "schema_version": "1.0",
  "chunk_id": "chunk:6a69c9556e297c5fff02f1af6a14492ef7e3651cb2c262e520cde798476e7cff",
  "document_id": "example_articles:article-001",
  "document_version": "sha256:2970f96d317b9f22ddbcc6e14330ea20c9210fbab9c0ff32589b6ca3ad09306b",
  "chunk_index": 0,
  "text": "示例\n甲乙",
  "char_start": 0,
  "char_end": 5,
  "source_locator": "fixture:example_articles/article-001",
  "metadata": {
    "dataset_id": "example_articles",
    "document_type": "article",
    "language": "zh-Hant",
    "source_updated_at": "2026-11-01",
    "source_category": "示範",
    "source_metadata": {
      "source_category": "示範"
    }
  }
}
```

## 5. 清洗、切分與索引準入

`plain_v1` 和 HTML profile 共用文字正規化順序：CRLF/CR 轉 LF；Unicode NFC（不做 NFKC、不轉簡繁）；非換行空白含 NBSP 轉半形空白，連續水平空白壓成一個；去除各行頭尾空白；連續空行最多留一個；去除全文頭尾空行。title 正規化後須為單行，原有換行以空白取代。原始內容與 hash 不做這些處理。程式不得改寫醫療用語、數值、單位、日期、否定詞或條件。

HTML 先移除 Comment/script/style 和確認的 CMS 節點，再保留段落、br、清單邊界與項目。CDC profile 僅精確移除已知 `日期 發送處 start/end`、檔案列表及報表模板標記，配合上下文；不能用廣泛關鍵字正則刪除正文。無法安全保留的表格結構標記 needs_review。空標題／正文、殘留已知模板、來源無法追溯、raw hash 不符等均有 issues；不可偽裝成 ready。

FAQ 優先完整 QA；其他型別優先保留完整文件。超過 max_chars 時使用原文區間，依標題／段落、清單、句子邊界選擇不超上限的最遠切點；沒有合法邊界才以 code point 上限切分。下一片段依 overlap_chars 回退，須確保 start 前進；長清單項目也不能截掉尾端。不得對片段另做 strip、改寫或補標題。具體邊界選擇與回退規則由 `algorithm_version` 鎖定，變動需升版。所有片段必須滿足第 2.3 節，區間聯集覆蓋全文，允許重疊但不能有缺口；不得默默截斷。1200/100 是初始工程預設，後續可依檢索指標調整。

來源更新日期未知或偏舊只記錄審查提示，不直接認定內容錯誤。時間敏感項加 time_sensitive；若政策要求審查則 needs_review。staleness 的判定參考日與門檻必須是明確輸入設定，保存於 manifest，不能偷偷使用現在日期影響可重現輸出。ready 與 approved 各自獨立，附件、權利或時間審查的放行依第 2.2 節紀錄。

## 6. 合併、錯誤與 run 輸出

同 ID＋版本且 `C(整份 Document)` 相同才精確去重，對應 chunks 也須以相同設定重現。若本文版本相同而 provenance、rights、metadata、quality 或審查紀錄不同，預設回報 `metadata_conflict`，不任選一筆遺失證據；未來若引入明確合併政策需另版規範。同 ID 不同版本為 `version_conflict`，預設失敗；必須提供可追溯的版本選擇／審核設定才可明確啟用某版並保存歷史。不同 ID 相同 clean hash 保留各自來源，僅報告跨來源內容重複，不以相似度自動去重。同一文件在不同 chunking 設定下不能直接混入同一 run；merge 預設要求一致設定，否則明確失敗。

build / merge 的正式 run 包含以下檔案，空集合也輸出空 JSONL。build 保存所有合法 Document；merge 正式 documents/chunks 預設只收 ready 且 review_status 非 rejected、權利準入及必要審查約束均通過的文件。needs_review/excluded 等隔離文件留在原 run，merge 品質報告記錄其 input run、document_id／版本、原因與計數；未知或缺失狀態是驗證錯誤，不得默認 ready。JSONL 以 C(record)＋單一 LF 編碼，documents 按 document_id、chunks 按 `(document_id, chunk_index)` 排序，issues/rejected 按 `(input_locator, line_number, code)` 排序（null 行號視為 -1），同鍵再按 C(record) bytes 排序。輸入與執行時間只屬於 manifest，不進 ID。

| 檔案 | 最低契約 |
| --- | --- |
| documents.jsonl | build：所有可符合 Document 契約的文件，含 ready/needs_review/excluded，不可與 rejected 重複計數。merge：僅通過上述準入的 ready 文件，隔離文件不寫入正式文件集。 |
| chunks.jsonl | 僅 ready、非 rejected 文件的可索引片段，保留精確引用及區間。 |
| issues.jsonl | 每筆含 `input_locator:string`、`line_number:integer|null`、`dataset_id:string|null`、`source_record_id:string|null`、`document_id:string|null`、`code:string`、`severity:warning|error`、`message:string`；無法解析 ID 時仍以檔案＋行號追溯。 |
| rejected.jsonl | 無法成為合法 Document 的原始紀錄；每筆含 input_locator、line_number、dataset_id、source_record_id、code（型別同 issues）、`raw_record:object|string|null`，保留可得原輸入；不得靜默跳過。 |
| quality_report.json | schema_version、input_count、document_count、rejected_count、duplicate_count、ready/needs_review/excluded_count、chunk_count、issue_count、flag_counts、缺日期／附件／來源分布、衝突與跨來源重複統計；merge 另列隔離文件的 input identity、原因與計數，輸入狀態與正式輸出狀態分列；皆由實際輸入與產出計算。 |
| manifest.json | schema_version、pipeline_version、adapter 及完整 mapping、清洗／chunking 規則版本與完整設定、chunking_fingerprint、來源根目錄定位、所有輸入及來源快照／政策證據的路徑與檔案 SHA-256、各來源 intended_use、usage_decision 及決策依據／可追溯來源、輸出檔案 SHA-256、計數、strict、staleness 參考日、started_at_utc/completed_at_utc、complete。不雜湊 manifest 自身，所有其他輸出含審查檔均須覆蓋。 |

report 必須可對帳：build 的 `input_count = document_count + rejected_count + duplicate_count`，三個品質狀態數總和等於 document_count；merge 額外分列各輸入文件／chunk 數、去重、隔離與衝突，正式 document_count 只計通過準入者，不用 CDC 固定筆數當成功條件。每一筆衍生紀錄的來源關係均由其 identity 和 manifest 的來源資料集／輸入檔定位追溯。

輸出不得指向來源檔或來源根目錄；新 run 已存在即失敗。先在同一檔案系統的暫存目錄產出、驗證全部內容與 hash，通過後才原子發布，避免半成品成為正式 KB。不覆寫 datasets 中 qa.jsonl、manifest.json、raw 或既有 run。單筆失敗保留 issues/rejected 於失敗診斷目錄；strict 有 error 時非零退出，不發布 complete=true；非 strict 可發布已排除錯誤紀錄的完整 run，但拒收與計數必須如實揭露。merge conflict 預設為整次失敗，不可靜默套用非 strict 放行。

## 7. 後續實作驗收案例

以下是後續 Commit 的驗收要求，並非此文件階段已實作的功能：

| 案例 | 必須驗證的結果 |
| --- | --- |
| 本文非醫療範例 | JSON 可解析，原始／clean/config/chunk hash 可重算，offset `[0:5]` 與原文一致。 |
| CDC 原始 119 筆與非 CDC fixture | 使用同一 SourceRecord→Document→Chunk 契約；保留身分、來源、權利及原 hash，不更動來源 bytes。 |
| 非法 JSON、缺 ID／定位／正文、錯 hash | 具來源行號與錯誤原因；strict 非零，沒有假成功 manifest。 |
| HTML Comment/CMS／清單與長本文 | 雜訊移除，列表和關鍵數值保留；片段精確引用，完整覆蓋且有進展。 |
| 附件依賴、權利未知、審查失效 | needs_review，無正式 chunks；版本／source fingerprint 改變後舊審查不可沿用。 |
| 用途判定 prohibited／改變 intended_use | prohibited 為 excluded/rights_prohibited，不可人工放行；用途改變使來源指紋改變，須重新評估及審查。 |
| merge 混合 ready／needs_review／excluded | 正式 documents/chunks 僅收通過準入的 ready；其餘留原 run，報告可追溯隔離原因／計數，缺失或未知 status 不默認 ready。 |
| 重跑及輸入順序改變 | 相同有效設定與來源內容得到相同 ID、版本、Document/Chunk 記錄與排序；manifest 的輸入檔 hash 如實反映 bytes 差異。 |
| 同 ID 同版本／不同版本／metadata 不同 | 完全相同才去重；不同版本或 metadata 預設明確衝突。 |
| 跨來源同文 | 保留各自文件與引用，只標重複。 |
| 改 chunk、manifest hash 或引用 | validate 重算後偵測損壞；與既有 decide/evaluate baseline 無回歸。 |

Commit 1 只驗證文件範例、hash/offset、連結及變更範圍；完整實作與端到端驗收依[六階段計畫](clinical_warrant_rag_kb_pipeline_plan.md)進行。
