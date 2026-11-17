# clinical-warrant-poc

A proof-of-concept for clinical warrant-based response decision support using sentence embeddings and rule-based validation.

## 專案結構

採用 Python Packaging Authority（PyPA）文件中的 `src` 佈局，將可匯入的程式碼與專案工具、文件分開。

```text
clinical-warrant-poc/
├── src/
│   └── clinical_warrant/
│       └── .gitkeep       # 主套件：可重複使用的 Python 程式碼
├── tests/
│   └── .gitkeep           # 測試，依主套件的模組安排
├── scripts/
│   └── .gitkeep           # 執行入口與一次性工作腳本，共用邏輯放回主套件
├── docs/
│   └── .gitkeep           # 設計、使用方式與開發文件
├── .gitignore
├── LICENSE
└── README.md
```

目前僅建立目錄骨架。`.gitkeep` 是讓 Git 保留空目錄的慣例檔名，不具 Python 套件功能；目錄加入實際檔案後即可移除。

開始實作時，再加入 `src/clinical_warrant/__init__.py` 與根目錄的 `pyproject.toml`，設定套件與依賴，並以 editable install 進行開發。現階段尚無可安裝或執行的 Python 套件。

## 參考

- [PyPA：src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)：本專案目錄佈局的依據。
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)：後續命名、匯入與程式碼風格的參考；這份骨架並非 Google 的制式專案模板。
