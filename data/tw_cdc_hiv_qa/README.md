# CDC 台灣愛滋 QA 資料集

此目錄保存一次限定範圍的 CDC 愛滋知識與預防 QA 頁面快照，以及從頁面逐題擷取的研究參考資料。這不是臨床 gold dataset，也不是實際患者或使用者 query。

## 本次蒐集

- QA 逐筆蒐集時間：2026-11-21 11:47:44–11:48:04 UTC（依 `qa.jsonl` 的 `collected_at_utc`）。
- 狀態：`manifest.json` 的 `complete` 為 `true`；13 個核准內容路徑均回傳 HTTP 200，0 個頁面錯誤。
- 逐題資料：`qa.jsonl` 共 119 筆，0 個重複 ID；每題問答皆非空，source updated date 均有值（缺日期欄位仍允許為 null）。
- 原始 HTML：`raw/` 共 15 個檔案，其中 13 個為核准主題頁（含入口分類頁與認識愛滋子分類頁），另 2 個是授權/著作權說明頁的 provenance 快照。所有 raw 檔案的 hash 可由 manifest 核對。
- 附件：發現 1 個附件連結，只保留 URL metadata；沒有下載附件。

| 核准主題分支 | QA 筆數 |
| --- | ---: |
| 認識愛滋（5 個子頁） | 47 |
| 愛滋篩檢服務 | 9 |
| 預防母子垂直感染 | 12 |
| 藥癮愛滋減害 | 10 |
| PrEP（認識 PrEP、計畫服務） | 29 |
| PEP | 12 |
| **總計** | **119** |

## 檔案與品質核對

- `qa.jsonl`：每行一個 FAQ，含 `id`、question、answer text/HTML、來源 URL、分類、逐題來源更新日期、UTC 蒐集時間、內容 SHA-256、來源 anchor/FAQ ID、附件 URL metadata，以及指向原始 HTML 的 `raw_snapshot`。
- `raw/`：頁面 HTML 快照；每頁以來源 URL 和 HTML SHA-256 命名，方便重現正規化結果與比較版本。
- `manifest.json`：核准範圍、robots 與授權來源、逐頁 HTTP 狀態/日期標頭/hash/題數、policy provenance、錯誤、重複計數與 complete 狀態。

本次已離線核對 JSONL 119 行皆可解析；各頁題數與輸出相符；所有 record ID、QA 內容 hash、原始 HTML hash 與路徑均可驗證；沒有重複 ID、空問答或範圍外頁面。日期反映本次取得的 CDC 頁面，來源之後更新時請建立新快照，不覆寫此份資料。

`manifest.json` 的 `started_at_utc` / `completed_at_utc` 反映最近一次 `--resume` 快照核對（2026-11-21 11:50:34–11:50:35 UTC）；該次以先前保存且 hash 相符的 robots.txt 內容做離線檢查，並重用所有 hash 相符的本機 raw，沒有發出網路請求。逐題 `collected_at_utc` 保留首次 live fetch 時間。

## 來源與使用限制

來源是[CDC 台灣愛滋知識與預防問答](https://www.cdc.gov.tw/Category/List/qTp6DeK3rmOlqcVc7diAkA)，完整頁面清單和原始快照 hash 見 manifest。資料蒐集依據 CDC 的[政府網站資料開放宣告](https://www.cdc.gov.tw/Category/FPage/TxkBIR9agw_IBRRmvn9TcQ)與[著作權聲明](https://www.cdc.gov.tw/Category/FPage/rvmij-b1qdDYyX_Olv67VQ)保存來源證據。開放宣告要求註明來源，並有個資、第三方作品及特別標示內容等例外；這不等於全站無條件開放，也不代表 CC BY 4.0。使用時請遵守頁面標記及第三方權利，不得使人誤認為 CDC 背書。

這些內容是一般衛教問答，可用於參考語料或分類研究種子；它們不是實際臨床提問，也未經專家逐題審定為臨床標準答案。不得將其用來宣稱醫療建議品質、安全性或臨床效能已驗證。蒐集器細節見[資料蒐集文件](../../docs/data-collection.md)。
