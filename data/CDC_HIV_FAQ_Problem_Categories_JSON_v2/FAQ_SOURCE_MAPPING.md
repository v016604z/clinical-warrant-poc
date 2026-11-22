# 台灣 CDC HIV FAQ：問題類別與個案欄位來源對照（v2）

依據專案內 119 筆 CDC HIV FAQ（2026-11-21 快照）整理；類別與欄位屬於**研究設計**，不是 CDC 官方欄位表或臨床必填要求。

- [原始 QA 資料檔（固定版本）](https://github.com/v016604z/clinical-warrant-poc/blob/940703149f12532eaad0806c6d69b9ac0cdabdcb/data/tw_cdc_hiv_qa/qa.jsonl)
- 各 JSON 只提供「類別＋候選個案欄位」；本 MD 才放來源證據。
- **證據層級**：`官方明確提及` ＝官方 FAQ 討論過相關資訊，但**不等於所有問題都必填**；`依官方內容推導` ＝建模用途；`實務流程` ＝你之前與個管師合作的流程，**非 CDC 規定**。
- 來源內容更新日橫跨 2019–2026；若涉及檢驗標準、預防用藥與補助政策，需重新確認最新版指引。

## 一、問題類別總覽

| 類別 JSON | 問題類別 | 對應原始 FAQ 筆數 | 候選欄位數 |
|---|---|---:|---:|
| `categories/hiv_basics.json` | HIV 基本知識 | 7 | 0 |
| `categories/transmission_education.json` | 傳染與非傳染途徑衛教 | 17 | 6 |
| `categories/personal_exposure_risk.json` | 個人暴露風險 | 11 | 14 |
| `categories/prevention_methods.json` | 預防行為與保護措施 | 7 | 5 |
| `categories/window_period.json` | 篩檢空窗期 | 2 | 6 |
| `categories/screening_recommendation.json` | 篩檢建議與頻率 | 2 | 10 |
| `categories/test_result_interpretation.json` | 篩檢結果與可靠性 | 3 | 8 |
| `categories/symptom_questions.json` | 症狀疑慮 | 2 | 5 |
| `categories/testing_services.json` | 篩檢服務與資源 | 5 | 5 |
| `categories/maternal_child_health.json` | 孕產婦與母子垂直感染 | 12 | 10 |
| `categories/harm_reduction.json` | 藥物使用與針具減害 | 10 | 8 |
| `categories/prep_medication.json` | PrEP 預防性用藥 | 20 | 12 |
| `categories/prep_policy_services.json` | PrEP 公費政策與服務 | 9 | 8 |
| `categories/pep_post_exposure.json` | PEP 暴露後預防性投藥 | 12 | 12 |
| **合計** | **14 類** | **119** | **109（各類欄位出現次數）** |

## 二、各類別與候選欄位的代表性來源

### HIV 基本知識 (`hiv_basics`)

一般知識問題不需要個案資料，因此 `fields: {}`。

**沒有個案欄位。** CDC 原始問題如 [什麼是 HIV？](https://www.cdc.gov.tw/Category/QAPage/SpEUrQI64Q_EV_DI8NsYTw#heading5477)、[什麼是 AIDS？](https://www.cdc.gov.tw/Category/QAPage/SpEUrQI64Q_EV_DI8NsYTw#heading5476)。

### 傳染與非傳染途徑衛教 (`transmission_education`)

一般傳染途徑問答通常可以直接衛教；以下僅是使用者若描述個別接觸事件時可抽取的背景，不代表一律要求補問。

| JSON 欄位 | 欄位說明 | 依據性質 | 代表性 CDC 原文／來源說明 |
|---|---|---|---|
| `contact_setting` | 接觸發生的場景，例如一般生活接觸或醫療器具接觸 | 依官方內容推導 | [HIV 的傳染途徑](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5480)、[共用馬桶與洗衣設備是否傳染？](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5508)、[與 HIV 感染者聊天會傳染嗎？](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5507) |
| `contact_material` | 接觸的物質或物品，例如血液、汗水或門把 | 官方明確提及 | [HIV 的傳染途徑](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5480)、[共用馬桶與洗衣設備是否傳染？](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5508)、[接吻及唾液、淚水、汗水接觸](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5504) |
| `blood_present` | 接觸情境是否涉及可見血液 | 官方明確提及 | [觸碰沾有血液的鈔票是否傳染？](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5505)、[接吻及唾液、淚水、汗水接觸](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5504)、[協助流血傷者的暴露風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5491) |
| `has_wound` | 接觸部位皮膚是否有傷口 | 官方明確提及 | [HIV 的傳染途徑](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5480)、[接吻及唾液、淚水、汗水接觸](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5504)、[協助流血傷者的暴露風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5491) |
| `mucosal_contact` | 是否有黏膜直接接觸 | 官方明確提及 | [HIV 的傳染途徑](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5480)、[接吻及唾液、淚水、汗水接觸](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5504)、[協助流血傷者的暴露風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5491) |
| `source_hiv_status` | 接觸來源者的 HIV 感染狀態（可為未知） | 官方明確提及 | [固定伴侶與感染前提](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5498)、[協助流血傷者的暴露風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5491)、[與 HIV 感染者無套性行為的風險因素](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5483) |

### 個人暴露風險 (`personal_exposure_risk`)

以實際暴露行為、接觸方式及保護措施為主。性別不直接代表 HIV 感染風險。

| JSON 欄位 | 欄位說明 | 依據性質 | 代表性 CDC 原文／來源說明 |
|---|---|---|---|
| `exposure_route` | 暴露方式，例如性行為、共用針具或血液／體液接觸 | 官方明確提及 | [拔牙、針灸或穿耳洞是否可能傳染？](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5481)、[共用牙刷及刮鬍刀的風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5494)、[協助流血傷者的暴露風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5491) |
| `exposure_datetime` | 可能暴露的發生時間，可保留「昨天」等原始描述 | 官方明確提及 | [HIV 檢驗空窗期與檢驗方式](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5511)、[何時應到醫院接受 PEP 評估？](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5569)、[血液或體液暴露後應如何處理？](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5568) |
| `sexual_activity_type` | 實際性行為方式，例如口交、陰道交或肛交 | 官方明確提及 | [未戴套但部分進入陰道的性行為](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5486)、[不同性行為方式及角色的 HIV 風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5485)、[與 HIV 感染者無套性行為的風險因素](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5483) |
| `sexual_role` | 該次性行為的插入者／接受者等角色 | 官方明確提及 | [不同性行為方式及角色的 HIV 風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5485)、[與 HIV 感染者無套性行為的風險因素](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5483) |
| `condom_use` | 該次行為是否全程使用保險套 | 官方明確提及 | [未戴套但部分進入陰道的性行為](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5486)、[不同性行為方式及角色的 HIV 風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5485)、[與 HIV 感染者無套性行為的風險因素](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5483) |
| `condom_integrity` | 保險套有無破裂、滑落等情況 | 依官方內容推導 | [保險套能否預防所有性病？](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5487)、[保險套與不同潤滑液](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading6408)、[保險套放在皮夾保存的問題](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading6406) |
| `lubricant_type` | 該次行為使用的潤滑液類型 | 官方明確提及 | [不同性行為方式及角色的 HIV 風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5485)、[保險套與不同潤滑液](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading6408) |
| `needle_sharing` | 是否共用針頭、針筒或稀釋液 | 官方明確提及 | [HIV 的傳染途徑](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5480)、[哪些人需要接受 HIV 篩檢？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83069)、[成癮性藥物與相關風險](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5528) |
| `blood_or_body_fluid_contact` | 是否接觸血液或可能相關體液 | 官方明確提及 | [拔牙、針灸或穿耳洞是否可能傳染？](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5481)、[協助流血傷者的暴露風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5491)、[CPR 口對口人工呼吸的暴露情形](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5490) |
| `has_wound` | 接觸部位皮膚是否有傷口 | 官方明確提及 | [協助流血傷者的暴露風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5491)、[被咬傷是否可能傳染？](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5503)、[指交是否傳染 HIV？](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5497) |
| `mucosal_contact` | 是否有黏膜直接接觸 | 官方明確提及 | [協助流血傷者的暴露風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5491)、[HIV 的傳染途徑](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5480)、[接吻及唾液、淚水、汗水接觸](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5504) |
| `source_hiv_status` | 接觸來源者的 HIV 感染狀態（可為未知） | 官方明確提及 | [協助流血傷者的暴露風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5491)、[與 HIV 感染者無套性行為的風險因素](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5483)、[固定伴侶與感染前提](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5498) |
| `partner_viral_load_status` | 如已知，伴侶病毒量或病毒抑制情況 | 官方明確提及 | [與 HIV 感染者無套性行為的風險因素](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5483) |
| `partner_gender` | 對象性別（僅依個管服務需求記錄，不作為 HIV 風險判斷依據） | 實務流程（非官方必要欄位） | **來自先前個管師服務流程；CDC 並未將此訂為判斷風險的必要欄位。** 參見 [性傾向與傳染方式](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5499) |

### 預防行為與保護措施 (`prevention_methods`)

一般防護知識可直接衛教；若問題包含具體行為才視需要讀取相關欄位。

| JSON 欄位 | 欄位說明 | 依據性質 | 代表性 CDC 原文／來源說明 |
|---|---|---|---|
| `sexual_activity_type` | 實際性行為方式，例如口交、陰道交或肛交 | 官方明確提及 | [HIV 的傳染途徑](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5480)、[未戴套但部分進入陰道的性行為](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5486)、[不同性行為方式及角色的 HIV 風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5485) |
| `condom_use` | 該次行為是否全程使用保險套 | 官方明確提及 | [保險套能否預防所有性病？](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5487)、[口交與保險套使用](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading6409)、[未戴套但部分進入陰道的性行為](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5486) |
| `condom_integrity` | 保險套有無破裂、滑落等情況 | 依官方內容推導 | [保險套能否預防所有性病？](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5487)、[保險套與不同潤滑液](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading6408)、[保險套放在皮夾保存的問題](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading6406) |
| `lubricant_type` | 該次行為使用的潤滑液類型 | 官方明確提及 | [保險套與不同潤滑液](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading6408)、[不同性行為方式及角色的 HIV 風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5485) |
| `sexual_role` | 該次性行為的插入者／接受者等角色 | 官方明確提及 | [不同性行為方式及角色的 HIV 風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5485)、[與 HIV 感染者無套性行為的風險因素](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5483) |

### 篩檢空窗期 (`window_period`)

空窗期應由暴露時間、檢驗日期與檢驗方式理解，不內建最新臨床時間門檻。

| JSON 欄位 | 欄位說明 | 依據性質 | 代表性 CDC 原文／來源說明 |
|---|---|---|---|
| `last_possible_exposure_date` | 最近一次可能暴露的日期或時間 | 依官方內容推導 | [HIV 檢驗空窗期與檢驗方式](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5511)、[空窗期後檢驗結果的可靠性](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5509)、[陰性結果、伴侶情況與不安全性行為](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83062) |
| `test_date` | 進行 HIV 檢驗的日期 | 依官方內容推導 | [HIV 檢驗空窗期與檢驗方式](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5511)、[空窗期後檢驗結果的可靠性](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5509)、[RT-PCR 陰性、檢驗時間與藥物影響](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83064) |
| `test_method` | 採用的 HIV 檢驗方法 | 官方明確提及 | [HIV 檢驗空窗期與檢驗方式](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5511)、[RT-PCR 陰性、檢驗時間與藥物影響](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83064) |
| `test_result` | HIV 檢驗結果（如陰性、初步陽性、未知） | 官方明確提及 | [空窗期後檢驗結果的可靠性](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5509)、[RT-PCR 陰性、檢驗時間與藥物影響](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83064)、[陰性結果、伴侶情況與不安全性行為](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83062) |
| `further_exposure_after_test` | 在上次篩檢後是否有新的可能暴露 | 依官方內容推導 | [空窗期後檢驗結果的可靠性](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5509)、[固定伴侶與定期 HIV 檢驗](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83063)、[陰性結果、伴侶情況與不安全性行為](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83062) |
| `antiretroviral_use` | 檢驗前後是否使用相關抗病毒藥物 | 官方明確提及 | [RT-PCR 陰性、檢驗時間與藥物影響](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83064) |

### 篩檢建議與頻率 (`screening_recommendation`)

篩檢動機是先前個管師服務流程的保留資訊，不能說是 CDC 規定必填。

| JSON 欄位 | 欄位說明 | 依據性質 | 代表性 CDC 原文／來源說明 |
|---|---|---|---|
| `screening_motivation` | 希望篩檢的原因（個管服務流程保留，並非一律必問） | 實務流程（非官方必要欄位） | **來自先前個管師服務流程。** 官方僅呈現篩檢需求例子：[哪些人需要接受 HIV 篩檢？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83069)、[免費匿名篩檢管道](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83067)、[注射用藥或藥愛者如何接受檢驗？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83061) |
| `ever_tested` | 過去是否曾接受 HIV 篩檢 | 依官方內容推導 | [固定伴侶與定期 HIV 檢驗](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83063)、[陰性結果、伴侶情況與不安全性行為](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83062)、[孕期新暴露後是否需再次篩檢？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5517) |
| `last_test_date` | 最近一次 HIV 篩檢日期 | 依官方內容推導 | [固定伴侶與定期 HIV 檢驗](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83063)、[空窗期後檢驗結果的可靠性](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5509)、[陰性結果、伴侶情況與不安全性行為](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83062) |
| `new_exposure` | 近期是否有新的可能暴露 | 官方明確提及 | [固定伴侶與定期 HIV 檢驗](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83063)、[陰性結果、伴侶情況與不安全性行為](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83062)、[孕期新暴露後是否需再次篩檢？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5517) |
| `sexual_exposure_pattern` | 近期性行為或暴露概況 | 官方明確提及 | [哪些人需要接受 HIV 篩檢？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83069)、[固定伴侶與定期 HIV 檢驗](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83063)、[陰性結果、伴侶情況與不安全性行為](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83062) |
| `condom_use` | 該次行為是否全程使用保險套 | 官方明確提及 | [固定伴侶與定期 HIV 檢驗](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83063)、[保險套能否預防所有性病？](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5487)、[口交與保險套使用](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading6409) |
| `sti_history` | 是否曾有其他性傳染病史 | 官方明確提及 | [哪些人需要接受 HIV 篩檢？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83069)、[固定伴侶與定期 HIV 檢驗](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83063)、[孕期新暴露後是否需再次篩檢？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5517) |
| `multiple_partners` | 是否涉及多重性伴侶的情境 | 官方明確提及 | [哪些人需要接受 HIV 篩檢？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83069)、[固定伴侶與定期 HIV 檢驗](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83063)、[孕期新暴露後是否需再次篩檢？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5517) |
| `needle_sharing` | 是否共用針頭、針筒或稀釋液 | 官方明確提及 | [哪些人需要接受 HIV 篩檢？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83069)、[HIV 的傳染途徑](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5480)、[成癮性藥物與相關風險](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5528) |
| `partner_hiv_status` | 性伴侶的 HIV 感染狀態（可為未知） | 官方明確提及 | [與 HIV 感染者無套性行為的風險因素](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5483)、[陰性結果、伴侶情況與不安全性行為](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83062)、[哪些人適合接受 PrEP 評估？](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5542) |

### 篩檢結果與可靠性 (`test_result_interpretation`)

篩檢結果不等於確診；陽性結果的確認程序需由醫療端處理。

| JSON 欄位 | 欄位說明 | 依據性質 | 代表性 CDC 原文／來源說明 |
|---|---|---|---|
| `test_method` | 採用的 HIV 檢驗方法 | 官方明確提及 | [RT-PCR 陰性、檢驗時間與藥物影響](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83064)、[HIV 檢驗空窗期與檢驗方式](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5511) |
| `test_date` | 進行 HIV 檢驗的日期 | 依官方內容推導 | [RT-PCR 陰性、檢驗時間與藥物影響](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83064)、[陰性結果、伴侶情況與不安全性行為](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83062)、[HIV 檢驗空窗期與檢驗方式](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5511) |
| `test_result` | HIV 檢驗結果（如陰性、初步陽性、未知） | 官方明確提及 | [RT-PCR 陰性、檢驗時間與藥物影響](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83064)、[陰性結果、伴侶情況與不安全性行為](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83062)、[空窗期後檢驗結果的可靠性](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5509) |
| `test_stage` | 檢驗階段，例如初步篩檢或確認檢驗 | 官方明確提及 | [空窗期後檢驗結果的可靠性](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5509)、[孕婦篩檢與確認檢驗](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5516)、[孕婦初步篩檢陽性後的處置](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading6176) |
| `confirmatory_test_status` | 是否已接受或完成確認檢驗 | 官方明確提及 | [空窗期後檢驗結果的可靠性](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5509)、[孕婦篩檢與確認檢驗](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5516)、[孕婦初步篩檢陽性後的處置](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading6176) |
| `last_possible_exposure_date` | 最近一次可能暴露的日期或時間 | 依官方內容推導 | [陰性結果、伴侶情況與不安全性行為](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83062)、[HIV 檢驗空窗期與檢驗方式](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5511)、[空窗期後檢驗結果的可靠性](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5509) |
| `further_exposure_after_test` | 在上次篩檢後是否有新的可能暴露 | 依官方內容推導 | [陰性結果、伴侶情況與不安全性行為](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83062)、[空窗期後檢驗結果的可靠性](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5509)、[固定伴侶與定期 HIV 檢驗](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83063) |
| `antiretroviral_use` | 檢驗前後是否使用相關抗病毒藥物 | 官方明確提及 | [RT-PCR 陰性、檢驗時間與藥物影響](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83064) |

### 症狀疑慮 (`symptom_questions`)

症狀本身不能用來確診或排除 HIV；相關問題需提示適當篩檢及就醫。

| JSON 欄位 | 欄位說明 | 依據性質 | 代表性 CDC 原文／來源說明 |
|---|---|---|---|
| `symptoms` | 目前自述症狀 | 官方明確提及 | [HIV 可能出現哪些症狀？](https://www.cdc.gov.tw/Category/QAPage/fV5yD36S7dZuzHVcqFgQ-Q#heading5478)、[不安全性行為後出現紅疹是否感染？](https://www.cdc.gov.tw/Category/QAPage/fV5yD36S7dZuzHVcqFgQ-Q#heading5479) |
| `symptom_onset` | 症狀開始或持續的時間 | 依官方內容推導 | [HIV 可能出現哪些症狀？](https://www.cdc.gov.tw/Category/QAPage/fV5yD36S7dZuzHVcqFgQ-Q#heading5478)、[不安全性行為後出現紅疹是否感染？](https://www.cdc.gov.tw/Category/QAPage/fV5yD36S7dZuzHVcqFgQ-Q#heading5479) |
| `possible_exposure_event` | 是否提到可能暴露事件 | 官方明確提及 | [不安全性行為後出現紅疹是否感染？](https://www.cdc.gov.tw/Category/QAPage/fV5yD36S7dZuzHVcqFgQ-Q#heading5479) |
| `exposure_datetime` | 可能暴露的發生時間，可保留「昨天」等原始描述 | 官方明確提及 | [HIV 檢驗空窗期與檢驗方式](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5511)、[何時應到醫院接受 PEP 評估？](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5569)、[血液或體液暴露後應如何處理？](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5568) |
| `test_history` | 過去 HIV 檢驗歷程 | 依官方內容推導 | [不安全性行為後出現紅疹是否感染？](https://www.cdc.gov.tw/Category/QAPage/fV5yD36S7dZuzHVcqFgQ-Q#heading5479)、[RT-PCR 陰性、檢驗時間與藥物影響](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83064) |

### 篩檢服務與資源 (`testing_services`)

查找附近服務通常只需縣市或區域，不應為一般服務查詢要求完整病歷。

| JSON 欄位 | 欄位說明 | 依據性質 | 代表性 CDC 原文／來源說明 |
|---|---|---|---|
| `service_area` | 希望查詢服務的縣市或區域（不需要精確地址） | 依官方內容推導 | [可以在哪裡接受 HIV 檢驗？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83068)、[免費匿名篩檢管道](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83067)、[注射用藥者取得清潔針具](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5527) |
| `anonymous_testing_preference` | 是否希望使用匿名篩檢 | 官方明確提及 | [可以在哪裡接受 HIV 檢驗？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83068)、[免費匿名篩檢管道](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83067)、[匿名篩檢是否免費？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83066) |
| `self_testing_preference` | 是否希望使用自我篩檢 | 官方明確提及 | [可以在哪裡接受 HIV 檢驗？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83068)、[如何取得居家 HIV 自我篩檢試劑？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83065) |
| `service_type` | 希望取得的篩檢服務類型 | 依官方內容推導 | [可以在哪裡接受 HIV 檢驗？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83068)、[免費匿名篩檢管道](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83067)、[匿名篩檢是否免費？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83066) |
| `screening_motivation` | 希望篩檢的原因（個管服務流程保留，並非一律必問） | 實務流程（非官方必要欄位） | **來自先前個管師服務流程。** 官方僅呈現篩檢需求例子：[免費匿名篩檢管道](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83067)、[注射用藥或藥愛者如何接受檢驗？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83061)、[哪些人需要接受 HIV 篩檢？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83069) |

### 孕產婦與母子垂直感染 (`maternal_child_health`)

孕產婦用藥、分娩及新生兒處置應由醫師個別評估。

| JSON 欄位 | 欄位說明 | 依據性質 | 代表性 CDC 原文／來源說明 |
|---|---|---|---|
| `pregnancy_status` | 是否涉及懷孕、產後或孕產婦情境 | 官方明確提及 | [孕婦為什麼需要 HIV 篩檢？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5522)、[固定伴侶的孕婦是否需要檢驗？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5521)、[孕婦免費 HIV 篩檢地點](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5520) |
| `pregnancy_stage` | 懷孕週數或孕期階段 | 官方明確提及 | [孕期新暴露後是否需再次篩檢？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5517)、[HIV 感染孕婦是否需要終止妊娠？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5515)、[孕婦初步篩檢陽性後的處置](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading6176) |
| `antenatal_hiv_test_history` | 孕期 HIV 篩檢歷程 | 官方明確提及 | [孕婦為什麼需要 HIV 篩檢？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5522)、[孕期新暴露後是否需再次篩檢？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5517)、[孕婦篩檢與確認檢驗](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5516) |
| `new_exposure_during_pregnancy` | 孕期是否發生新的可能暴露 | 官方明確提及 | [孕期新暴露後是否需再次篩檢？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5517) |
| `maternal_hiv_status` | 孕產婦已知的 HIV 感染狀態 | 官方明確提及 | [HIV 感染孕婦是否需要終止妊娠？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5515)、[孕婦初步篩檢陽性後的處置](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading6176)、[HIV 感染孕婦如何減少母嬰傳染？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5514) |
| `maternal_viral_load` | 如已知，孕產婦的病毒量狀態 | 官方明確提及 | [孕婦為什麼需要 HIV 篩檢？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5522)、[HIV 感染孕婦的分娩方式](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5513) |
| `maternal_treatment_status` | 是否正在接受相關治療及服藥 | 官方明確提及 | [孕婦為什麼需要 HIV 篩檢？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5522)、[母子垂直感染的預防服務](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5518)、[HIV 感染孕婦如何減少母嬰傳染？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5514) |
| `delivery_context` | 分娩階段或預期分娩情境 | 官方明確提及 | [孕婦為什麼需要 HIV 篩檢？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5522)、[HIV 感染孕婦如何減少母嬰傳染？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5514)、[HIV 感染孕婦的分娩方式](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5513) |
| `infant_context` | 新生兒或嬰幼兒相關照護背景 | 官方明確提及 | [母子垂直感染的預防服務](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5518)、[HIV 感染嬰兒的照護](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5512) |
| `infant_feeding_type` | 嬰兒哺餵方式 | 官方明確提及 | [孕婦為什麼需要 HIV 篩檢？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5522)、[母子垂直感染的預防服務](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5518)、[HIV 感染孕婦如何減少母嬰傳染？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5514) |

### 藥物使用與針具減害 (`harm_reduction`)

物質使用方式與共用針具有關；戒癮協助與資源查詢應避免污名化。

| JSON 欄位 | 欄位說明 | 依據性質 | 代表性 CDC 原文／來源說明 |
|---|---|---|---|
| `substance_use_context` | 使用成癮性物質的背景情境 | 官方明確提及 | [成癮性藥物與相關風險](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5528)、[藥愛、共用針具與不安全性行為](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading6300)、[成癮性藥物與 HIV 治療交互作用](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading6301) |
| `administration_route` | 物質的使用方式，例如注射或吸食 | 官方明確提及 | [成癮性藥物與相關風險](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5528)、[藥愛、共用針具與不安全性行為](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading6300) |
| `needle_sharing` | 是否共用針頭、針筒或稀釋液 | 官方明確提及 | [成癮性藥物與相關風險](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5528)、[注射用藥者取得清潔針具](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5527)、[藥愛、共用針具與不安全性行為](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading6300) |
| `chemsex_context` | 是否涉及以藥助性（chemsex） | 官方明確提及 | [成癮性藥物與相關風險](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5528)、[藥愛、共用針具與不安全性行為](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading6300)、[注射用藥或藥愛者如何接受檢驗？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83061) |
| `concurrent_medications` | 同時使用的其他藥物 | 官方明確提及 | [美沙冬副作用](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5524)、[成癮性藥物與 HIV 治療交互作用](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading6301) |
| `substance_treatment_need` | 是否希望取得戒癮或減害服務 | 依官方內容推導 | [注射用藥者取得清潔針具](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5527)、[藥癮戒治就醫機構](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5526)、[替代治療的醫療資源](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5525) |
| `service_area` | 希望查詢服務的縣市或區域（不需要精確地址） | 依官方內容推導 | [注射用藥者取得清潔針具](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5527)、[藥癮戒治就醫機構](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5526)、[替代治療的醫療資源](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5525) |
| `current_hiv_treatment` | 目前是否正在接受 HIV 治療 | 官方明確提及 | [成癮性藥物與 HIV 治療交互作用](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading6301)、[HIV 感染者的戒癮轉介服務](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading6302) |

### PrEP 預防性用藥 (`prep_medication`)

PrEP 是否適用及用藥調整仍由醫師決定，欄位只是供 AI 辨識問題情境。

| JSON 欄位 | 欄位說明 | 依據性質 | 代表性 CDC 原文／來源說明 |
|---|---|---|---|
| `hiv_test_result` | 最近一次 HIV 篩檢結果 | 官方明確提及 | [什麼是 PrEP？](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5548)、[哪些人適合接受 PrEP 評估？](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5542)、[HIV 已感染者是否可以使用 PrEP？](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5536) |
| `hiv_status` | 目前已知的 HIV 感染狀態 | 官方明確提及 | [什麼是 PrEP？](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5548)、[哪些人適合接受 PrEP 評估？](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5542)、[HIV 已感染者是否可以使用 PrEP？](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5536) |
| `prep_current_use` | 目前是否使用 PrEP | 官方明確提及 | [PrEP 是否能完全預防 HIV？](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5544)、[PrEP 的服藥方式](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5539)、[PrEP 漏服時的處理](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5538) |
| `prep_dosing_pattern` | 目前 PrEP 的服藥模式 | 官方明確提及 | [PrEP 的服藥方式](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5539)、[PrEP 漏服時的處理](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5538) |
| `prep_adherence` | 自述 PrEP 服藥遵從情形 | 官方明確提及 | [PrEP 漏服時的處理](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5538)、[哪些情況應與醫師討論停用 PrEP？](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5533)、[PrEP 使用與抗藥性](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5530) |
| `exposure_pattern` | 近期可能暴露的型態或頻率 | 官方明確提及 | [PrEP 預防效果與對象](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5545)、[哪些人適合接受 PrEP 評估？](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5542)、[PrEP 使用禁忌與腎功能等因素](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5541) |
| `renal_function_context` | 如已知，腎功能檢查或相關病史 | 官方明確提及 | [PrEP 使用禁忌與腎功能等因素](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5541)、[PrEP 的可能副作用](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5537)、[開始 PrEP 前的檢查項目](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5532) |
| `hepatitis_b_context` | 如已知，B 型肝炎相關狀況 | 官方明確提及 | [PrEP、B 型肝炎與停藥影響](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5534)、[開始 PrEP 前的檢查項目](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5532) |
| `pregnancy_status` | 是否涉及懷孕、產後或孕產婦情境 | 官方明確提及 | [孕婦使用 PrEP 的考量](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5540)、[孕婦為什麼需要 HIV 篩檢？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5522)、[固定伴侶的孕婦是否需要檢驗？](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5521) |
| `other_medications` | 其他目前使用的藥物 | 官方明確提及 | [美沙冬副作用](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5524)、[成癮性藥物與 HIV 治療交互作用](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading6301)、[PEP 副作用與其他藥物交互作用](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5564) |
| `adverse_effects` | 目前是否有疑似用藥副作用 | 官方明確提及 | [PrEP 漏服時的處理](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5538)、[PrEP 的可能副作用](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5537)、[哪些情況應與醫師討論停用 PrEP？](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5533) |
| `planned_prep_change` | 是否打算開始、更改或停止 PrEP | 官方明確提及 | [PrEP 的服藥方式](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5539)、[哪些情況應與醫師討論停用 PrEP？](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5533)、[開始 PrEP 前的檢查項目](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5532) |

### PrEP 公費政策與服務 (`prep_policy_services`)

補助計畫及資格可能逐年變更，欄位不代表自動審核資格。

| JSON 欄位 | 欄位說明 | 依據性質 | 代表性 CDC 原文／來源說明 |
|---|---|---|---|
| `program_year` | 欲查詢的 PrEP 公費計畫年度 | 依官方內容推導 | [PrEP 計畫年度與期限](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5556)、[PrEP 公費補助對象](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5555) |
| `age_years` | 年齡（歲） | 官方明確提及 | [PrEP 公費補助對象](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5555)、[PrEP 補助政策的對象考量](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5551) |
| `citizenship_context` | 與當年度補助資格相關的國籍或居留狀態 | 官方明確提及 | [PrEP 公費補助對象](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5555) |
| `hiv_test_result` | 最近一次 HIV 篩檢結果 | 官方明確提及 | [PrEP 公費補助對象](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5555)、[什麼是 PrEP？](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5548)、[哪些人適合接受 PrEP 評估？](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5542) |
| `partner_hiv_status` | 性伴侶的 HIV 感染狀態（可為未知） | 官方明確提及 | [PrEP 公費補助對象](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5555)、[與 HIV 感染者無套性行為的風險因素](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5483)、[陰性結果、伴侶情況與不安全性行為](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83062) |
| `risk_assessment_status` | 是否經醫療人員進行相關適用性評估 | 官方明確提及 | [PrEP 公費計畫的服務內容](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5557)、[PrEP 公費補助對象](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5555)、[不符合公費資格如何取得 PrEP？](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5549) |
| `service_area` | 希望查詢服務的縣市或區域（不需要精確地址） | 依官方內容推導 | [PrEP 服務醫療院所](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5550)、[可以在哪裡接受 HIV 檢驗？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83068)、[免費匿名篩檢管道](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83067) |
| `program_participation_context` | 與公費計畫資格有關的個案情況 | 依官方內容推導 | [PrEP 公費補助對象](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5555)、[PrEP 補助政策的對象考量](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5551) |

### PEP 暴露後預防性投藥 (`pep_post_exposure`)

近期疑似暴露須優先建議盡速由醫師評估，不能等候完整問卷才提醒就醫。

| JSON 欄位 | 欄位說明 | 依據性質 | 代表性 CDC 原文／來源說明 |
|---|---|---|---|
| `exposure_datetime` | 可能暴露的發生時間，可保留「昨天」等原始描述 | 官方明確提及 | [何時應到醫院接受 PEP 評估？](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5569)、[血液或體液暴露後應如何處理？](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5568)、[暴露後超過 72 小時的 PEP 問題](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5567) |
| `exposure_route` | 暴露方式，例如性行為、共用針具或血液／體液接觸 | 官方明確提及 | [不同暴露途徑的 HIV 風險](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5570)、[何時應到醫院接受 PEP 評估？](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5569)、[HIV 的傳染途徑](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5480) |
| `source_hiv_status` | 接觸來源者的 HIV 感染狀態（可為未知） | 官方明確提及 | [何時應到醫院接受 PEP 評估？](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5569)、[協助流血傷者的暴露風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5491)、[與 HIV 感染者無套性行為的風險因素](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5483) |
| `blood_or_body_fluid_contact` | 是否接觸血液或可能相關體液 | 官方明確提及 | [不同暴露途徑的 HIV 風險](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5570)、[血液或體液暴露後應如何處理？](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5568)、[HIV 的傳染途徑](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5480) |
| `needle_sharing` | 是否共用針頭、針筒或稀釋液 | 官方明確提及 | [何時應到醫院接受 PEP 評估？](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5569)、[HIV 的傳染途徑](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5480)、[哪些人需要接受 HIV 篩檢？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83069) |
| `has_wound` | 接觸部位皮膚是否有傷口 | 官方明確提及 | [HIV 的傳染途徑](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5480)、[協助流血傷者的暴露風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5491)、[接吻及唾液、淚水、汗水接觸](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5504) |
| `mucosal_contact` | 是否有黏膜直接接觸 | 官方明確提及 | [不同暴露途徑的 HIV 風險](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5570)、[HIV 的傳染途徑](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5480)、[協助流血傷者的暴露風險](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5491) |
| `occupational_exposure` | 是否為執行職務時的暴露事件 | 官方明確提及 | [職業暴露、檢測同意與費用補助](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5560) |
| `medical_evaluation_status` | 是否已接受醫師評估 | 官方明確提及 | [什麼是 PEP？](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5571)、[何時應到醫院接受 PEP 評估？](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5569)、[血液或體液暴露後應如何處理？](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5568) |
| `pep_use_status` | 是否已接受或開始 PEP | 官方明確提及 | [暴露後超過 72 小時的 PEP 問題](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5567)、[PEP 一般用藥療程](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5565)、[PEP 副作用與其他藥物交互作用](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5564) |
| `other_medications` | 其他目前使用的藥物 | 官方明確提及 | [PEP 副作用與其他藥物交互作用](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5564)、[美沙冬副作用](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5524)、[成癮性藥物與 HIV 治療交互作用](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading6301) |
| `service_area` | 希望查詢服務的縣市或區域（不需要精確地址） | 依官方內容推導 | [PEP 就醫科別與醫院](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5561)、[可以在哪裡接受 HIV 檢驗？](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83068)、[免費匿名篩檢管道](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83067) |

## 三、119 筆 FAQ 的類別來源對照

下表用 **原始資料中的排序序號** 方便查找，並附原始 CDC 網址；序號不是 CDC 官方識別碼。題目文字為簡短摘要，請以連結中的原文為準。

| 序號 | 問題摘要（非逐字原文） | 本次歸類 | 原始 CDC 問題 | CDC 頁面標示更新日 |
|---:|---|---|---|---|
| 1 | HIV 病因、起源與全球感染分布 | HIV 基本知識 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/SpEUrQI64Q_EV_DI8NsYTw#heading5471) | 2021-03-06 |
| 2 | 台灣 HIV 感染人數統計 | HIV 基本知識 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/SpEUrQI64Q_EV_DI8NsYTw#heading5472) | 2019-07-26 |
| 3 | 什麼是 HIV 病毒？ | HIV 基本知識 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/SpEUrQI64Q_EV_DI8NsYTw#heading5477) | 2019-07-26 |
| 4 | 什麼是 AIDS？ | HIV 基本知識 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/SpEUrQI64Q_EV_DI8NsYTw#heading5476) | 2019-08-13 |
| 5 | HIV 在人體的生命週期 | HIV 基本知識 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/SpEUrQI64Q_EV_DI8NsYTw#heading5475) | 2019-07-26 |
| 6 | HIV 需要多少病毒量才會傳染？ | HIV 基本知識 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/SpEUrQI64Q_EV_DI8NsYTw#heading5474) | 2019-07-26 |
| 7 | HIV 如何影響免疫系統？ | HIV 基本知識 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/SpEUrQI64Q_EV_DI8NsYTw#heading5473) | 2019-08-13 |
| 8 | HIV 的傳染途徑 | 傳染與非傳染途徑衛教 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5480) | 2019-08-13 |
| 9 | 拔牙、針灸或穿耳洞是否可能傳染？ | 個人暴露風險 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5481) | 2019-08-13 |
| 10 | 共用牙刷及刮鬍刀的風險 | 個人暴露風險 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5494) | 2019-08-13 |
| 11 | 輸血是否可能傳染 HIV？ | 傳染與非傳染途徑衛教 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5493) | 2021-03-06 |
| 12 | 血友病患者的歷史感染原因 | 傳染與非傳染途徑衛教 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5492) | 2019-08-13 |
| 13 | 協助流血傷者的暴露風險 | 個人暴露風險 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5491) | 2019-08-13 |
| 14 | CPR 口對口人工呼吸的暴露情形 | 個人暴露風險 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5490) | 2019-08-13 |
| 15 | 三溫暖場所與風險行為 | 個人暴露風險 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5489) | 2019-08-13 |
| 16 | 性交易與 HIV 風險 | 個人暴露風險 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5488) | 2019-08-13 |
| 17 | 保險套能否預防所有性病？ | 預防行為與保護措施 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5487) | 2022-03-14 |
| 18 | 保險套與不同潤滑液 | 預防行為與保護措施 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading6408) | 2021-06-25 |
| 19 | 保險套放在皮夾保存的問題 | 預防行為與保護措施 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading6406) | 2021-06-25 |
| 20 | 戴兩層保險套是否更安全？ | 預防行為與保護措施 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading6407) | 2021-06-25 |
| 21 | 口交與保險套使用 | 預防行為與保護措施 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading6409) | 2021-06-25 |
| 22 | 過期保險套是否能使用？ | 預防行為與保護措施 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading6410) | 2021-06-25 |
| 23 | 未戴套但部分進入陰道的性行為 | 個人暴露風險 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5486) | 2019-08-13 |
| 24 | 女用保險套的供應資訊 | 預防行為與保護措施 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading6411) | 2021-06-25 |
| 25 | 不同性行為方式及角色的 HIV 風險 | 個人暴露風險 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5485) | 2019-08-13 |
| 26 | 肛交、陰道交與口交的風險差異 | 傳染與非傳染途徑衛教 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5484) | 2019-08-13 |
| 27 | 與 HIV 感染者無套性行為的風險因素 | 個人暴露風險 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5483) | 2022-03-14 |
| 28 | 哺乳與母子感染途徑 | 傳染與非傳染途徑衛教 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/YXJ9H8_nDgSuviJ6pA7_aA#heading5482) | 2019-08-13 |
| 29 | 共用馬桶與洗衣設備是否傳染？ | 傳染與非傳染途徑衛教 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5508) | 2019-08-13 |
| 30 | 與 HIV 感染者聊天會傳染嗎？ | 傳染與非傳染途徑衛教 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5507) | 2019-08-13 |
| 31 | 游泳與公共浴池是否傳染？ | 傳染與非傳染途徑衛教 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5506) | 2019-08-13 |
| 32 | 觸碰沾有血液的鈔票是否傳染？ | 傳染與非傳染途徑衛教 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5505) | 2019-08-13 |
| 33 | 接吻及唾液、淚水、汗水接觸 | 傳染與非傳染途徑衛教 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5504) | 2019-08-13 |
| 34 | 被咬傷是否可能傳染？ | 個人暴露風險 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5503) | 2019-08-13 |
| 35 | 共用門把與桌面是否傳染？ | 傳染與非傳染途徑衛教 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5502) | 2019-08-13 |
| 36 | 共用 3D 眼鏡是否傳染？ | 傳染與非傳染途徑衛教 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5501) | 2019-08-13 |
| 37 | 蚊子叮咬是否傳染 HIV？ | 傳染與非傳染途徑衛教 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5500) | 2019-08-13 |
| 38 | 性傾向、自慰與傳染方式 | 傳染與非傳染途徑衛教 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5499) | 2019-08-13 |
| 39 | 固定伴侶與感染前提 | 傳染與非傳染途徑衛教 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5498) | 2019-08-13 |
| 40 | 指交是否傳染 HIV？ | 個人暴露風險 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5497) | 2019-07-28 |
| 41 | 舔乳頭是否傳染 HIV？ | 傳染與非傳染途徑衛教 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5496) | 2019-07-28 |
| 42 | 醫療器械的滅菌與消毒 | 傳染與非傳染途徑衛教 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/tN3OCfprezBUk9jVnWC8Yg#heading5495) | 2019-08-16 |
| 43 | HIV 檢驗空窗期與檢驗方式 | 篩檢空窗期 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5511) | 2021-03-06 |
| 44 | 染髮是否影響 HIV 檢驗？ | 篩檢結果與可靠性 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5510) | 2021-03-06 |
| 45 | 空窗期後檢驗結果的可靠性 | 篩檢空窗期 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/My0uZvjAFs11NWjujWXvBg#heading5509) | 2021-03-06 |
| 46 | HIV 可能出現哪些症狀？ | 症狀疑慮 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/fV5yD36S7dZuzHVcqFgQ-Q#heading5478) | 2019-07-26 |
| 47 | 不安全性行為後出現紅疹是否感染？ | 症狀疑慮 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/fV5yD36S7dZuzHVcqFgQ-Q#heading5479) | 2021-03-06 |
| 48 | 哪些人需要接受 HIV 篩檢？ | 篩檢建議與頻率 | [查看原文](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83069) | 2024-02-20 |
| 49 | 可以在哪裡接受 HIV 檢驗？ | 篩檢服務與資源 | [查看原文](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83068) | 2019-07-28 |
| 50 | 免費匿名篩檢管道 | 篩檢服務與資源 | [查看原文](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83067) | 2019-07-28 |
| 51 | 匿名篩檢是否免費？ | 篩檢服務與資源 | [查看原文](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83066) | 2019-07-28 |
| 52 | 如何取得居家 HIV 自我篩檢試劑？ | 篩檢服務與資源 | [查看原文](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83065) | 2026-05-06 |
| 53 | RT-PCR 陰性、檢驗時間與藥物影響 | 篩檢結果與可靠性 | [查看原文](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83064) | 2019-07-28 |
| 54 | 固定伴侶與定期 HIV 檢驗 | 篩檢建議與頻率 | [查看原文](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83063) | 2024-02-20 |
| 55 | 陰性結果、伴侶情況與不安全性行為 | 篩檢結果與可靠性 | [查看原文](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83062) | 2024-02-20 |
| 56 | 注射用藥或藥愛者如何接受檢驗？ | 篩檢服務與資源 | [查看原文](https://www.cdc.gov.tw/Category/MPage/Y4wiJu8wKZ_zDKN5efu9KQ#headingOne83061) | 2019-07-28 |
| 57 | 孕婦為什麼需要 HIV 篩檢？ | 孕產婦與母子垂直感染 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5522) | 2021-03-06 |
| 58 | 固定伴侶的孕婦是否需要檢驗？ | 孕產婦與母子垂直感染 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5521) | 2021-03-06 |
| 59 | 孕婦免費 HIV 篩檢地點 | 孕產婦與母子垂直感染 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5520) | 2021-03-06 |
| 60 | 孕婦篩檢的服務資格 | 孕產婦與母子垂直感染 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5519) | 2021-03-06 |
| 61 | 母子垂直感染的預防服務 | 孕產婦與母子垂直感染 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5518) | 2021-03-06 |
| 62 | 孕期新暴露後是否需再次篩檢？ | 孕產婦與母子垂直感染 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5517) | 2021-03-06 |
| 63 | 孕婦篩檢與確認檢驗 | 孕產婦與母子垂直感染 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5516) | 2021-03-06 |
| 64 | HIV 感染孕婦是否需要終止妊娠？ | 孕產婦與母子垂直感染 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5515) | 2019-08-13 |
| 65 | 孕婦初步篩檢陽性後的處置 | 孕產婦與母子垂直感染 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading6176) | 2020-12-03 |
| 66 | HIV 感染孕婦如何減少母嬰傳染？ | 孕產婦與母子垂直感染 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5514) | 2020-12-03 |
| 67 | HIV 感染孕婦的分娩方式 | 孕產婦與母子垂直感染 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5513) | 2019-08-13 |
| 68 | HIV 感染嬰兒的照護 | 孕產婦與母子垂直感染 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/qcdRrymODh9YF69ewsA5Qw#heading5512) | 2019-08-13 |
| 69 | 成癮性藥物與相關風險 | 藥物使用與針具減害 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5528) | 2019-08-13 |
| 70 | 注射用藥者取得清潔針具 | 藥物使用與針具減害 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5527) | 2021-03-06 |
| 71 | 藥癮戒治就醫機構 | 藥物使用與針具減害 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5526) | 2023-05-19 |
| 72 | 替代治療的醫療資源 | 藥物使用與針具減害 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5525) | 2019-08-13 |
| 73 | 美沙冬副作用 | 藥物使用與針具減害 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5524) | 2019-08-13 |
| 74 | HIV 感染者替代治療的費用 | 藥物使用與針具減害 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading5523) | 2021-03-06 |
| 75 | 藥愛、共用針具與不安全性行為 | 藥物使用與針具減害 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading6300) | 2021-03-06 |
| 76 | 成癮性藥物與 HIV 治療交互作用 | 藥物使用與針具減害 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading6301) | 2021-03-06 |
| 77 | HIV 感染者的戒癮轉介服務 | 藥物使用與針具減害 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading6302) | 2021-03-06 |
| 78 | 藥癮戒治資源 | 藥物使用與針具減害 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/NmDr6gAiK-xPxaejvJ-Lqw#heading6303) | 2023-05-19 |
| 79 | 什麼是 PrEP？ | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5548) | 2021-03-23 |
| 80 | PrEP 與 PEP 的差異 | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5547) | 2022-03-16 |
| 81 | PrEP 是否為疫苗？ | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5546) | 2021-02-08 |
| 82 | PrEP 預防效果與對象 | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5545) | 2021-02-08 |
| 83 | PrEP 是否能完全預防 HIV？ | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5544) | 2021-02-08 |
| 84 | PrEP 是否預防其他性病？ | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5543) | 2021-02-08 |
| 85 | 哪些人適合接受 PrEP 評估？ | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5542) | 2021-02-08 |
| 86 | PrEP 使用禁忌與腎功能等因素 | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5541) | 2021-02-08 |
| 87 | 孕婦使用 PrEP 的考量 | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5540) | 2021-02-08 |
| 88 | PrEP 的服藥方式 | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5539) | 2021-02-08 |
| 89 | PrEP 漏服時的處理 | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5538) | 2021-02-08 |
| 90 | PrEP 的可能副作用 | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5537) | 2021-02-08 |
| 91 | HIV 已感染者是否可以使用 PrEP？ | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5536) | 2021-02-08 |
| 92 | PrEP 就診地點 | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5535) | 2021-02-08 |
| 93 | PrEP、B 型肝炎與停藥影響 | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5534) | 2021-02-08 |
| 94 | 哪些情況應與醫師討論停用 PrEP？ | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5533) | 2021-02-08 |
| 95 | 開始 PrEP 前的檢查項目 | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5532) | 2021-02-08 |
| 96 | PrEP 是否需終身服用？ | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5531) | 2021-02-08 |
| 97 | PrEP 使用與抗藥性 | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5530) | 2021-02-08 |
| 98 | PrEP 服藥後仍可能感染嗎？ | PrEP 預防性用藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/PGwKHMNjHuzGO9hgvJKK4w#heading5529) | 2021-03-23 |
| 99 | PrEP 政策推動與成效評估 | PrEP 公費政策與服務 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5559) | 2023-01-16 |
| 100 | 為什麼推動 PrEP 政策？ | PrEP 公費政策與服務 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5558) | 2023-01-13 |
| 101 | PrEP 公費計畫的服務內容 | PrEP 公費政策與服務 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5557) | 2023-01-13 |
| 102 | PrEP 計畫年度與期限 | PrEP 公費政策與服務 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5556) | 2024-12-31 |
| 103 | PrEP 公費補助對象 | PrEP 公費政策與服務 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5555) | 2025-01-06 |
| 104 | PrEP 補助政策的對象考量 | PrEP 公費政策與服務 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5551) | 2025-01-06 |
| 105 | PrEP 計畫補助內容 | PrEP 公費政策與服務 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5554) | 2023-01-13 |
| 106 | PrEP 服務醫療院所 | PrEP 公費政策與服務 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5550) | 2023-01-13 |
| 107 | 不符合公費資格如何取得 PrEP？ | PrEP 公費政策與服務 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/pzjkJa4dgVjdk6emQjM-3g#heading5549) | 2023-01-13 |
| 108 | 什麼是 PEP？ | PEP 暴露後預防性投藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5571) | 2020-09-30 |
| 109 | 不同暴露途徑的 HIV 風險 | PEP 暴露後預防性投藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5570) | 2019-08-13 |
| 110 | 何時應到醫院接受 PEP 評估？ | PEP 暴露後預防性投藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5569) | 2019-08-13 |
| 111 | 血液或體液暴露後應如何處理？ | PEP 暴露後預防性投藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5568) | 2019-08-13 |
| 112 | 暴露後超過 72 小時的 PEP 問題 | PEP 暴露後預防性投藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5567) | 2021-03-06 |
| 113 | 被公共場所棄置針頭扎傷 | PEP 暴露後預防性投藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5566) | 2019-08-13 |
| 114 | PEP 一般用藥療程 | PEP 暴露後預防性投藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5565) | 2021-03-06 |
| 115 | PEP 副作用與其他藥物交互作用 | PEP 暴露後預防性投藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5564) | 2019-08-13 |
| 116 | 反覆暴露與多次使用 PEP | PEP 暴露後預防性投藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5563) | 2019-08-13 |
| 117 | PEP 的費用 | PEP 暴露後預防性投藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5562) | 2019-08-13 |
| 118 | PEP 就醫科別與醫院 | PEP 暴露後預防性投藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5561) | 2019-08-13 |
| 119 | 職業暴露、檢測同意與費用補助 | PEP 暴露後預防性投藥 | [查看原文](https://www.cdc.gov.tw/Category/QAPage/JQc1_rTZWlHX9-hw4U_4yg#heading5560) | 2021-03-06 |

## 四、研究使用限制

1. JSON 中全部是**候選欄位**，不設必填、條件式必填、臨床風險分數或直接結論；AI 可以提出選用理由，但不能把自身推論當成醫學黃金標準。
2. `personal_exposure_risk` 的 `partner_gender` 是為了保留你曾使用的實務欄位；請勿用對象性別或性傾向取代實際暴露方式與保護狀態。
3. `hiv_basics` 的 `fields` 為空，並非每個問題都需要追問個資。
4. 涉及近期可能暴露、陽性篩檢、PrEP/PEP 個人化用藥、孕產婦處置等，應優先提示就醫／醫療專業評估，不應因問卷欄位不齊而延遲。
5. 所有代表性來源只證明「此因素在 FAQ 中被討論或可合理推導」；**不是每題一定需要該欄位的證據**。

