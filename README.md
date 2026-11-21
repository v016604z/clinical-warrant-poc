# clinical-warrant-poc

A proof-of-concept for clinical warrant-based response decision support using sentence embeddings and rule-based validation.

## 專案結構

採用 Python Packaging Authority（PyPA）文件中的 `src` 佈局，將可匯入的程式碼與專案工具、文件分開。

```text
clinical-warrant-poc/
├── evaluation/
│   └── synthetic_hiv_cases.jsonl  # 獨立的合成評估資料
├── datasets/
│   └── tw_cdc_hiv_qa/          # CDC 愛滋 QA 蒐集輸出（raw、逐題資料與 manifest）
├── tools/
│   └── crawl_cdc_hiv_qa.py     # 限定 CDC 愛滋主題範圍的資料蒐集器
├── pyproject.toml             # 套件、CLI 與 pytest 設定
├── src/clinical_warrant/
│   ├── modules/                # 依業務能力劃分的模組化單體
│   │   ├── classification/    # 分類公開 API；內含 domain/application/infrastructure
│   │   ├── decision/          # warrant 決策公開 API；內含 application
│   │   └── evaluation/        # 情境評估公開 API；含 application/infrastructure
│   ├── shared/domain/         # 共用契約與 catalog 純型別/驗證
│   ├── infrastructure/        # 共用 JSON catalog loader
│   ├── interfaces/cli.py      # CLI adapter
│   ├── bootstrap/             # 組裝應用程式與 adapters
│   ├── data/                  # 套件內研究用途 JSON 資料
│   ├── __init__.py            # 套件版本
│   └── __main__.py            # python -m clinical_warrant 入口
├── tests/                     # 離線單元及 CLI 測試
├── docs/                      # 設計、評估與執行文件
├── .gitignore
├── LICENSE
└── README.md
```

目前已建立可安裝的 Python 套件與命令列入口。`decide` 可讀取 JSON 並輸出三態決策；`evaluate` 可執行 JSONL 情境評估並保存逐筆報告。

## 開發

使用 Python 3.10 以上版本，在專案目錄建立隔離環境並安裝套件與開發依賴：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

首次使用真實 encoder 前，依[分類器文件](docs/classifier.md)先安裝 PyTorch 官方 CPU wheel，再安裝固定版本的 model extra；模型第一次載入需連線下載，模型權重沿用 Hugging Face 快取，prototype vectors 可用 `CLINICAL_WARRANT_CACHE` 指定位置。

查看命令列說明並執行測試：

```powershell
.\.venv\Scripts\clinical-warrant.exe --help
.\.venv\Scripts\python.exe -m clinical_warrant --help
.\.venv\Scripts\python.exe -m pytest
```

句向量分類器使用的模型、revision、CPU 執行方式、快取與 128-token 限制，見[分類器文件](docs/classifier.md)。一般測試不載入模型；真實模型 smoke test 須明確啟用。

程式分層、模組公開 API、依賴方向與 Python import 入口，見[架構文件](docs/architecture.md)。本次重構移除了六個舊 root-level Python imports；請改用新的模組公開 API或組裝入口。

單筆決策 CLI 的 JSON 格式、三態優先順序與限制見[決策 CLI 文件](docs/decision-cli.md)。

CDC 愛滋公開問答的蒐集範圍、執行方式、原始快照與資料使用限制見[資料蒐集說明](docs/data-collection.md)。

可複用 RAG Knowledge Base 的六階段工作見[實作計畫](docs/clinical_warrant_rag_kb_pipeline_plan.md)；來源、文件與區塊契約及版本策略見[資料契約 v1](docs/rag-kb-schema.md)。目前已完成資料契約與來源 Adapter；清洗、切分、KB Pipeline 與 `kb build/merge/validate` 留待後續階段實作。

## 情境評估

使用 repo 內的合成測試資料執行情境評估；模型只在此命令開始後載入一次：

```powershell
.\.venv\Scripts\clinical-warrant.exe evaluate --input evaluation/synthetic_hiv_cases.jsonl --output evaluation-runs
```

每次執行會在輸出目錄新增獨立的 `run-*` 子目錄，包含 `summary.json`、`predictions.jsonl` 與 `errors.jsonl`。預期與實際結果不一致會記錄在報告中，不會使評估程序失敗；`errors.jsonl` 空白表示此批次各項預期欄位皆相符。所有案例都使用虛構文字與軟體流程用的玩具條件，不代表臨床驗證或準確率保證。資料格式、指標分母及比較方式見[情境評估文件](docs/evaluation.md)。

固定模型 revision、CPU 與預設 threshold `0.5` 的一次真實模型 baseline 為 20/20 分類正確率 19/20（0.95）、unknown rate 2/20（0.10），決策、缺漏欄位與 reason codes 均為 20/20；未使用評估資料調整 threshold。唯一分類錯誤是 `missing-null-marker`，但該例決策及其餘欄位比對正確。詳見[baseline 摘要](docs/results/baseline/summary.json)及[報告說明](docs/results/baseline/README.md)。

## 參考

- [PyPA：src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)：本專案目錄佈局的依據。
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)：後續命名、匯入與程式碼風格的參考；這份骨架並非 Google 的制式專案模板。
