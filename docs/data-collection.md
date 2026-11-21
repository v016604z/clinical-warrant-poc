# CDC 愛滋 QA 資料蒐集

本文件說明如何從衛生福利部疾病管制署（CDC）指定的愛滋主題頁，蒐集公開問答作為研究參考語料。蒐集器只走核准的主題分支，不抓全站；產出的資料不是臨床標準答案，也不可當作臨床 gold label。

## 範圍與來源

入口頁為[愛滋問答](https://www.cdc.gov.tw/Category/List/qTp6DeK3rmOlqcVc7diAkA)。只蒐集以下六個分支及其列明的主題頁：

| 分支 | 允許的內容頁 |
| --- | --- |
| 認識愛滋 | `/Category/List/1FuOwO6RRWN2gq9ULJ1Srw`；其下認識 HIV/AIDS、傳染途徑、不會傳染的途徑、空窗期、可能感染的症狀等主題頁 |
| 愛滋篩檢服務 | `/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ` |
| 預防母子垂直感染 | `/Category/QAPage/qcdRrymODh9YF69ewsA5Qw` |
| 藥癮愛滋減害 | `/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw` |
| PrEP | `/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w`、`/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g` |
| PEP | `/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg` |

認識愛滋的五個主題頁分別是 `SpEUrQI64Q_EV_DI8NsYTw`、`YXJ9H8_nDgSuviJ6pA7_aA`、`tN3OCfprezBUk9jVnWC8Yg`、`My0uZvjAFs11NWjujWXvBg`、`fV5yD36S7dZuzHVcqFgQ-Q`。蒐集器應以明確核准清單限制 URL；分類頁的側欄含其他 CDC 主題，不可把頁面上所有連結都當成蒐集範圍。

`robots.txt` 禁止抓取 `/File/`、`/Uploads/`、`/LogFiles/`、`/TTS/`。附件只保留頁面提供的 URL 與可得描述，不下載附件。只發出單一連線請求，請求間至少等待兩秒；對暫時性網路或伺服器錯誤有限重試，遇到禁止或不存在的頁面不反覆請求。

問答頁的題目、答案和逐題更新日期已存在 HTML 回應中，不需執行 JavaScript。單頁可能含多題，應逐張 FAQ 卡片擷取題目、答案和該卡片自己的更新日期；日期可能為空。record identity 使用 canonical page URL 加正規化題目文字。頁面 heading/collapse ID（例如 `heading5511`、`headingOne83069`）可保留為來源 anchor，但目前沒有證據確認它跨頁面更新穩定。保留 answer HTML，另提供純文字答案，避免表格、清單或換行資訊在文字正規化時遺失。蒐集時間使用 UTC。原始頁面以內容 SHA-256 識別並保存，manifest 記錄各頁狀態、hash、題數及錯誤，讓原始內容可供核對。

## 執行

使用 Python 3.10 以上版本，在隔離環境安裝 collector extra；它只增加 HTML parser，不會安裝模型：

```powershell
python -m pip install -e ".[collect]"
python tools/crawl_cdc_hiv_qa.py --output-dir datasets/tw_cdc_hiv_qa
```

預設不覆寫已存在的輸出目錄。確認要延續既有蒐集時才使用 `--resume`：它會重新檢查 robots.txt；hash 驗證通過的 raw HTML（含授權來源頁）會從快照重用，只有缺頁或 hash 不符才會重新請求。需要全新快照時請指定新的輸出目錄。`--resume` 會更新 manifest 的本次執行時間，逐題原始蒐集時間則保留在 `qa.jsonl` 的 `collected_at_utc`。

```powershell
python tools/crawl_cdc_hiv_qa.py --output-dir datasets/tw_cdc_hiv_qa --resume
```

每次蒐集輸出原始頁面快照、逐題 `qa.jsonl` 和 `manifest.json`。每筆 QA 包含穩定識別、題目、answer text/HTML、來源頁與分類、逐題 CDC 更新日期（可為 null）、UTC 蒐集時間、內容 hash、附件 metadata 與 raw 路徑；manifest 記錄逐頁 HTTP 狀態、hash、題數、重複/錯誤資訊、robots/授權聲明及是否完整。部分成功會留下可檢查的輸出，但不代表六個分支都已完整蒐集；請先檢查 manifest 的 complete 狀態。欄位名稱以程式輸出的 schema 為準。

## 使用與授權限制

CDC 的[政府網站資料開放宣告](https://www.cdc.gov.tw/Category/FPage/TxkBIR9agw_IBRRmvn9TcQ)允許符合宣告範圍的資料重製、改作等利用，並要求註明來源；宣告也列出個人資料、第三方內容、特別標示資料等例外。[著作權聲明](https://www.cdc.gov.tw/Category/FPage/rvmij-b1qdDYyX_Olv67VQ)另說明著作權保護及合理使用範圍。這不等於 CDC 全站內容皆無條件開放，也不應標示為 CC BY 4.0。使用者仍須逐項尊重頁面標記、第三方權利與個資規範，並註明 CDC 為來源；不得使人誤認為 CDC 背書本專案。

本資料是公開衛教問答的參考語料，可協助理解常見題型或形成分類研究種子；它不是實際患者/使用者 query，也沒有由臨床專家逐筆審定的 gold labels。不得輸入患者個資，不得把 CDC 問答當作本系統臨床建議或安全性的驗證。資料及 hash 只對應各次取得的頁面快照；來源可能更新，重跑應保留舊快照並比較 manifest，不應覆寫歷史資料。
