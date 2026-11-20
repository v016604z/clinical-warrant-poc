# Clinical Warrant PoC：6 個 commit 完成基礎框架

本文件記錄原定實作方案與驗收條件；六個階段均已完成實作與驗收。前五階段 commit 對照及第六階段提交訊息見文末。各階段方案保留作為設計和驗收依據。

## 需求依據與範圍

提案《類神經網路商業應用 期末專案提案.pdf》明定：

- 第 1 頁：研究動機是判斷醫療衛教回答是否適用於個案，而不只看一般知識正確性；以匿名個案管理情境說明必要資料不足的風險。
- 第 2 頁：以獨立 Python PoC 進行，不修改原有醫療衛教機器人；使用預訓練 Sentence Transformer 與餘弦相似度辨識問題類型，低信心時保留未知；不重新訓練大型模型。Clinical Warrant 檢核包含個案資訊充分性（Case Sufficiency）、衛教規則適用性（Rule Applicability）、回應範圍控制（Response Scope）。
- 第 3 頁：流程為使用者問題與模擬個案資料 → 語意分類 → 取得檢核規則 → warrant 檢核 → 輸出決策及原因。決策分為「允許提供衛教」、「需要補充資訊」、「限制回答」；用少量虛構 HIV 衛教情境做分類、資料充分性與決策測試，並比較修正前後結果。
- 第 4 頁：不使用真實病患資料、不串接醫院系統、不宣稱臨床部署或安全性；僅驗證技術可行性與討論限制。

本次已選定的實作預設：

- 規則與資料使用虛構模擬情境；不提供具臨床意義的風險門檻、暴露時間門檻或醫療建議。
- 系統只輸出決策與理由，不產生衛教文字，也不呼叫生成式 LLM。
- 首次執行可從模型 Hub 下載 encoder，在本機 CPU 執行；模型與 prototype 向量使用快取，不將權重或快取加入 Git。
- 不做網站、服務 API、資料庫或醫院系統串接。
- 採 Python >=3.10、`src` layout、`pyproject.toml` 與 pytest。CLI 以標準庫 `argparse` 為基礎；核心資料契約採 dataclass 與 JSON 序列化。

## 端到端架構與介面

預定流程：`query + mock case → 分類 → 三項檢核 → 三態決策 → 評估`。

| 模組 | 職責 |
|---|---|
| `contracts` | 定義輸入、分類結果、檢核結果、決策與評估資料契約；處理 JSON 驗證與序列化。 |
| `classifier` | 將 query 編碼，與四類問題 prototypes 比較 cosine similarity，回傳最佳類別、相似度或未知。 |
| `rules` | 保存虛構模擬規則、各類必要欄位與適用條件；執行三項檢核。 |
| `decision` | 協調分類、檢核及決策優先順序，產生單筆決策報告。 |
| `cli` | 提供 `decide` 與 `evaluate` 命令，處理輸入輸出與錯誤退出碼。 |
| `evaluation` | 執行帶預期結果的 JSONL 測試集，產出逐筆結果、彙總指標與錯誤明細。 |

分類類別固定為四類：`result_interpretation`（結果判讀）、`window_period`（空窗期）、`exposure_risk`（暴露風險）、`prevention_education`（預防衛教）。模型使用 [`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)，在 CPU 建立 query 與 prototype 向量並計算 cosine similarity。原型向量可快取，但需標記模型 revision 與 prototypes 版本；不追蹤模型權重或快取。初始未知分類門檻設為 `0.5`，僅為需經模擬資料校準的實驗值，不是機率或臨床信心保證。

CLI 契約：

- `clinical-warrant decide --input <file>`：讀取 JSON，欄位包含 `query`、`case` 與 `requested_scope`；回傳 JSON，包含分類與相似度、規則 ID、三項檢核狀態、`missing_fields`、`reason_codes` 與決策。決策值為 `allow_education`、`need_more_info`、`restrict`。
- `clinical-warrant evaluate --input <file> --output <dir>`：讀取含預期結果的 JSONL 測試集，輸出逐筆結果、彙總指標與錯誤明細。
- 輸入外層契約欄位（例如 `query`、`case`、`requested_scope`）缺失或型別錯誤、JSON 格式錯誤，或模型載入/執行失敗時，將錯誤寫至 stderr 並以非零狀態結束；不可產生替代或猜測的決策。`case` 物件內缺少規則所需的個案資料屬於有效輸入，應正常執行並依決策規則回傳 `need_more_info`，不視為格式錯誤。

## 規則與決策優先順序

三項檢核各自回報 pass、fail、undetermined 或 skipped。Case Sufficiency 在確認缺少必要欄位時為 fail；Rule Applicability 因所需資料缺漏而無法判斷時為 undetermined；skipped 表示依優先順序未執行該檢核。

決策順序如下：

1. 分類未知（低於門檻或無法取得有效分類）時，輸出 `restrict`，理由為 `unknown_intent`。
2. 只依明示的 `requested_scope` 判斷範圍；值不是明確的 `education` 時，輸出 `restrict`，理由為 `scope_mismatch`。不另從 `query` 推斷用途或判斷越界。
3. 已知類別且範圍內，若已有資料足以確認玩具規則條件不符合，即使仍缺少無關必要欄位，也輸出 `restrict`，reason 為 `rule_not_applicable`。
4. 已知類別且範圍內，若尚未確認規則不適用且必要欄位缺漏，輸出 `need_more_info`，並列出所需補齊欄位。
5. 只有分類已知、範圍符合、必要欄位齊全且三項檢核皆通過時，輸出 `allow_education`。

未知分類或範圍越界優先於缺資料；不應為越界情境要求補充資料。模擬規則不得設定真實醫療風險判定或時間門檻，也不得宣稱醫學正確性。

## 六階段 commit 與驗收

| 階段 | 建議 commit message | 工作內容 | 階段驗收 |
|---|---|---|---|
| 1 | `docs(plan): 新增提案實作方案與階段驗收標準` | 新增本計畫，記錄提案依據、範圍、介面、規則優先順序與驗收矩陣。 | 文件內容與提案頁碼相符，並清楚區分提案要求與選定預設。 |
| 2 | `build(core): 建立 Python 套件與開發驗證環境` | 建立 `pyproject.toml`、`src/clinical_warrant` 套件、pytest 設定及 CLI 入口骨架。 | Python >=3.10 可安裝；套件可匯入；CLI help 可執行；pytest 可發現測試。 |
| 3 | `feat(data): 定義決策契約與模擬情境規則` | 定義 JSON/dataclass 契約、四類 prototypes、模擬 case、必要欄位與規則。 | 契約可解析有效輸入並拒絕錯誤格式；規則皆為模擬資料且沒有臨床門檻。 |
| 4 | `feat(classifier): 新增句向量分類與未知判斷` | 加入指定 encoder、CPU 載入、prototype embedding 快取、cosine 分類與可設定 threshold。 | 可在固定向量的離線單元測試中驗證四類、改寫及 unknown；另有明確 opt-in 的真模型中文整合測試。 |
| 5 | `feat(warrant): 串接三項檢核與命令列決策` | 實作 Case Sufficiency、Rule Applicability、Response Scope、優先序與 `decide` CLI。 | 決策 label、reason codes、missing fields、各檢核狀態符合本文件矩陣；輸入或模型錯誤非零退出且不產生決策。 |
| 6 | `test(evaluation): 新增情境評估與執行文件` | 實作 JSONL 評估器、逐筆與彙總報告、錯誤明細及執行說明。 | 測試集涵蓋本文件矩陣；可記錄調整前後結果；README 說明安裝、首次下載、CLI、測試與限制。 |

每階段通過驗收與審閱後，依序建立該階段本機 commit，不 push。

## 最小測試矩陣與交付條件

評估資料至少涵蓋：

| 情境 | 預期驗收 |
|---|---|
| 四類各有標準問句與至少兩種語意改寫 | 分到對應類別；類別及 score 可檢視。 |
| 低相似度或未知問題 | `restrict`，reason 為 `unknown_intent`。 |
| 類別已知且完整資料、模擬規則適用 | 三檢核通過，決策為 `allow_education`。 |
| 類別已知且必要欄位缺漏 | `need_more_info`；Case Sufficiency 為 fail；Rule Applicability 若所需資料缺漏則為 undetermined，若已確認條件符合則為 pass。 |
| 完整資料但規則條件明確不符合 | `restrict`，reason 為 `rule_not_applicable`。 |
| 明確越出 education scope | `restrict`，reason 為 `scope_mismatch`。 |
| unknown 同時缺少 case 欄位 | 優先 `restrict / unknown_intent`，不錯誤要求補問。 |
| scope 越界同時缺少 case 欄位 | 優先 `restrict / scope_mismatch`，不要求補問。 |

單元測試以固定或假 embeddings 測試分類、規則與決策，確保一般測試離線可執行；另提供一次真實中文 encoder 整合測試，需由使用者明確啟動，允許首次下載模型。評估輸出至少包含分類準確率、未知率、決策準確率、缺欄位比對結果及逐筆錯誤明細。調整 prototypes、門檻或規則時，保留可比較的調整前後結果；不預設或保證任何準確率，也不將小型模擬評估解讀為臨床驗證。

最終交付包含 Python 套件與 CLI、模擬規則及情境、pytest 測試、JSONL 評估輸出、README 執行說明與本計畫。模型權重、快取、真實病患資料、衛教生成、網站/API/資料庫與醫院串接均不在交付範圍。

## 階段實作對照

前五階段以表列 SHA 對照，第六階段以本次提交訊息識別。

| 階段 | 提交 | 紀錄 |
|---|---|---|
| 1 | `7f81070` | 提案、實作方案與階段驗收標準。 |
| 2 | `f7d83b2` | Python 套件、開發環境與 CLI 骨架。 |
| 3 | `fcd8b85` | JSON 契約、模擬規則與套件資料。 |
| 4 | `6635d55` | 句向量分類器與 unknown 判斷。 |
| 5 | `9fe62ad` | 三項 warrant 檢核與 `decide` CLI。 |
| 6 | `test(evaluation): 新增情境評估與執行文件` | 實作與驗收已完成：20 筆合成案例、分類/unknown/決策/欄位/理由指標與逐筆錯誤報告；README、評估文件與 CLI 說明已同步。 |

## 後續架構階段：Layered Architecture + Modular Monolith

以下是六階段 PoC 交付後新增的架構整理，不改寫前述歷史方案、commit 對照或 baseline。程式依 classification、decision、evaluation 業務能力分模組；需要時在模組內分 domain/application/infrastructure。共用契約與純 catalog 型別放在 `shared/domain`，JSON catalog loader 放在 `infrastructure/catalog.py`，CLI adapter 位於 `interfaces/cli.py`，依賴由 `bootstrap/composition.py` 組裝。分類模型/cache 與評估報告 I/O 留在各自模組的 infrastructure。

重構維持單一 Python distribution 與 CLI，不改決策/JSON 契約、模型識別或 cache identity；既有 root-level import modules 作為相容 facade。架構與依賴方向詳見[軟體架構文件](architecture.md)。本階段的完成狀態以實際程式遷移、測試與安裝包資源驗證為準。
