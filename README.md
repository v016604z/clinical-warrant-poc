# clinical-warrant-poc

A proof-of-concept for clinical warrant-based response decision support using sentence embeddings and rule-based validation.

## 專案結構

採用 Python Packaging Authority（PyPA）文件中的 `src` 佈局，將可匯入的程式碼與專案工具、文件分開。

```text
clinical-warrant-poc/
├── pyproject.toml             # 套件、CLI 與 pytest 設定
├── src/
│   └── clinical_warrant/
│       ├── __init__.py        # 套件版本與初始化
│       ├── __main__.py        # python -m clinical_warrant 入口
│       └── cli.py             # argparse 命令列骨架
├── tests/
│   └── test_cli.py            # 最小套件與 CLI smoke tests
├── scripts/
│   └── .gitkeep               # 一次性工作腳本
├── docs/
│   └── ...                    # 設計與使用文件
├── .gitignore
├── LICENSE
└── README.md
```

目前已建立可安裝的 Python 套件與命令列入口。`decide` 與 `evaluate` 僅保留未來階段的參數介面；目前會明確回報尚未實作，不會產生決策或評估結果。

## 開發

使用 Python 3.10 以上版本，在專案目錄建立隔離環境並安裝套件與開發依賴：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

查看命令列說明並執行測試：

```powershell
.\.venv\Scripts\clinical-warrant.exe --help
.\.venv\Scripts\python.exe -m clinical_warrant --help
.\.venv\Scripts\python.exe -m pytest
```

## 參考

- [PyPA：src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)：本專案目錄佈局的依據。
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)：後續命名、匯入與程式碼風格的參考；這份骨架並非 Google 的制式專案模板。
