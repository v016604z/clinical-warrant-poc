# CDC HIV FAQ 問題類別與個案欄位（精簡版 v2）

基於 `clinical-warrant-poc` 的 **119 筆台灣 CDC HIV FAQ** 歸納的 14 個研究用問題類別。

## 檔案結構

- `categories/*.json`：每個類別一個 JSON，只有 `category_id`、`category_name` 與 `fields`。
- `FAQ_SOURCE_MAPPING.md`：各候選欄位的 CDC 依據、推論性質，以及 119 筆來源對照。

## JSON 格式

```json
{
  "category_id": "personal_exposure_risk",
  "category_name": "個人暴露風險",
  "fields": {
    "exposure_datetime": {
      "type": "string",
      "description": "可能暴露的發生時間，可保留『昨天』等原始描述"
    }
  }
}
```

- `fields` 是**可供 AI 挑選的個案資訊候選欄位**，不是必填清單。`{}` 表示一般衛教不一定需要蒐集個人資料。
- JSON **不含**來源索引、規則、風險分數、判斷門檻、樣本資料或臨床必填條件。
- 重複出現在不同類別的欄位，使用同樣的英文 key 與資料型別。
- 問題是否要求個人化判斷，應由上層分類／意圖模組處理；不屬於個案屬性。
- 字串可自行保留 `unknown`／未提供狀態；布林欄位用 `true`、`false`、`null` 區分。

## 與 Context Intake runtime 的差異

本目錄是來源快照，保留 v2 原始欄位名稱。當中 `window_period` 與 `test_result_interpretation` 使用 `last_possible_exposure_date`，而其他暴露相關類別可使用 `exposure_datetime`。Context Intake runtime 會依應用程式契約將同一 Case、同一次暴露事件的時間統一為 `exposure_datetime`，並以 Registry 內容指紋記錄版本；因此 runtime JSON 可以與本快照不同，且不能據此回寫或改稱原始 v2。這項正規化只適用於已確認為同一事件的跨 Category 資料，不代表「最近一次可能暴露」必定是目前 Case 的事件。

其他看似重疊的 `last_test_date`／`test_date`、`hiv_test_result`／`test_result` 不屬於本次正規化範圍，保留各自原義，尚未合併。

## 使用範圍及限制

1. 這是**研究用工程欄位設計**，並非疾管署公布的醫療表單，也未經臨床專家驗證。
2. AI 可依問題選擇欄位、抽取資訊並提出缺漏假設；**不要將 AI 的選擇宣稱為醫學必要性或自動臨床判斷**。
3. 有近期可能暴露、陽性篩檢、用藥或孕產婦等情境時，不應因欄位未收齊而延遲醫療轉介。
4. 年度補助方案、檢驗空窗期與 PrEP／PEP 用藥內容必須再依最新官方規範核對。
5. `partner_gender` 僅沿用先前個管師服務流程作為候選欄位，不能以性別或性傾向當作 HIV 感染風險的代理變數。

原始版本：`https://github.com/v016604z/clinical-warrant-poc/blob/dev/data/tw_cdc_hiv_qa/qa.jsonl`；資料取得快照 2026-11-21。
