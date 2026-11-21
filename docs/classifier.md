# 句向量分類器

分類器以每類多個中文 prototype 問句作比較，計算 query 向量與所有 prototype 向量的 cosine similarity，先取每類最高分，再選最高分類。相似度低於門檻時回傳 `unknown`；分數等於門檻仍接受該類別。預設門檻為 `0.5`，是待模擬資料校準的實驗參數，不是機率或臨床信心值。

## 模型與執行

使用 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`，固定 Hub revision `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`，並在本機 CPU 執行。第一次載入需要網路並下載模型檔；之後由 Hugging Face Hub 快取重用。呼叫 `QuestionClassifier.from_pretrained()` 建立真實 encoder；`QuestionClassifier` 也接受相同介面的 encoder，以便離線單元測試。

在 Windows PowerShell 的專案 `.venv` 中，先從 PyTorch 官方 CPU wheel index 安裝 CPU 版，再安裝 model extra：

```powershell
.\.venv\Scripts\python.exe -m pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -e ".[dev,model]"
```

model extra 固定 `sentence-transformers==6.3.0`、`transformers==5.20.2` 與 `torch==2.14.1`。首次模型載入仍需可連線至 Hugging Face Hub。

此模型的最大序列長度為 128 tokens。超長輸入會受模型 tokenizer 的長度上限影響；本階段不做 query chunking，也不保證超長問題的分類結果。

原型向量快取預設在作業系統使用者快取目錄下的 `clinical-warrant-poc` 子目錄。可用 `CLINICAL_WARRANT_CACHE` 環境變數或 `cache_dir` 參數指定目錄。若透過 `cache_dir` 指定，模型檔案會放在該目錄的 `hub` 子目錄；未指定時使用 Hugging Face Hub 預設快取。快取只保存 prototype embeddings，不保存 query 或個案資料。快取識別含模型 ID、固定 revision、prototype 內容 SHA-256 與格式版本；檔案以同目錄暫存檔原子替換，無效或損壞的快取會重建。

分類器不會用相似度錯誤替代結果，也不會在模型載入或編碼失敗時回傳 `unknown`；此類狀況會明確拋出 `ClassifierError`。一般單元測試使用可注入假 encoder，不需要安裝或下載模型。設定 `RUN_SENTENCE_TRANSFORMER_SMOKE=1` 才會執行真實中文模型 smoke test，該測試可能下載模型。

## 使用分類器

安裝 model extra 後，可直接在 Python 呼叫分類器：

```python
from clinical_warrant.bootstrap.composition import build_warrant_engine

engine = build_warrant_engine(threshold=0.5)
result = engine.classifier.classify("有哪些預防愛滋感染的方式？")
print(result.category.value, result.similarity)
```

`build_warrant_engine()` 由組裝層建立真實 encoder、catalog 與快取。分類模組公開 API `clinical_warrant.modules.classification.QuestionClassifier` 採依賴注入，建構時需提供 encoder 與 prototypes。舊的 `clinical_warrant.classifier` Python import 已移除；請改用此公開 API或組裝入口。分層與公開入口見[架構文件](architecture.md)。

以下 PowerShell 指令會把 prototype 快取放在被 Git 忽略的專案 `.venv/model-cache`；模型權重沿用 Hugging Face 預設快取。指令也會明確啟用真實模型 smoke test：

```powershell
$env:CLINICAL_WARRANT_CACHE = Join-Path (Get-Location) ".venv\model-cache"
$env:RUN_SENTENCE_TRANSFORMER_SMOKE = "1"
.\.venv\Scripts\python.exe -m pytest tests/test_classifier.py::test_real_encoder_chinese_smoke -q
Remove-Item Env:RUN_SENTENCE_TRANSFORMER_SMOKE
Remove-Item Env:CLINICAL_WARRANT_CACHE
```
