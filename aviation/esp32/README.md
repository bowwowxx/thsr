# ESP32 桃園航班小檔

資料為表定時刻，沒有即時誤點／取消／登機狀態。所有檔案採 UTF-8 JSON。

## 裝置讀取順序

1. GET `aviation/esp32/index.json`，取得 `date_index_template`。
2. 將 `{date}` 換成台灣當日日期（例如 `2026-11-03`），從 `aviation/esp32/` 起算讀取該日期索引。
3. 日期索引的 `departures.index` 或 `arrivals.index` 也是從 `aviation/esp32/` 起算的路徑。讀取它取得頁碼、檔名、筆數、時間範圍及 SHA-256。
4. 各頁 `file` 是相對於該方向索引所在目錄。從 `000.json` 起依需要下載；列表要完整則讀取所有頁。下一班查找可利用 `first_time`／`last_time` 挑選頁面，時間相同時可能跨頁。

每頁最多 32 筆、最多 16 KiB；目前最大 4,779 bytes。索引中的 `pages` 完整列出所有頁，沒有 top 截斷。空方向 `count=0, pages=[]`。HTTP 404 代表該日期尚未提供，不能自行替換成其他日期。分頁採來源內容版本目錄，讀取期間請固定同一版本；生成器最後才發布根索引。

## 每筆欄位

| 欄位 | 用途 |
|---|---|
| `time` | 桃園端表定時間 HH:MM；依外層 date 顯示 |
| `flight` | 完整航班編號 |
| `airline` | 航空公司代碼 |
| `airport` | 出境目的地／入境出發地機場代碼 |
| `name_zh`, `name_en` | 既有專案名稱對照；未收錄者使用機場代碼 |
| `terminal` | 原始 Terminal 值，未另外推測 |
| `service_date` | 原班表營運日，供追查跨日班次 |

頁面的 `direction` 為 departures（出境）或 arrivals（入境）；`timezone=Asia/Taipei`，`scheduled_only=true`。桃園出境依 DepartureTime，入境依 ArrivalTime；依原始時間後綴 +1／+2／-1 調整事件日期後分組，再去掉後綴成 HH:MM。此處只使用桃園端時間，不對外站時間額外做時區換算。相同顯示紀錄才合併，不把不同時間／航廈的同號航班任意合併。

名稱對照取自既有 ESP32 專案的離線機場標籤，目前只涵蓋少數機場；可補齊 `aviation/airport_names.json` 後重新生成。登機門缺資料應顯示 --，狀態顯示「表定」，不可填成準點。航廈照來源保留，實機使用前仍應抽查桃園入境／出境資料是否正確。

## 離線重新生成

```sh
python3 prepare_aviation_esp32.py
python3 -m unittest discover -s tests -v
```

原始檔與全欄位每日檔均保留。尚未修改 ESP32 航空頁的 HTTP／解析程式；本目錄先提供裝置可分次讀取的格式。尚未上傳 GitHub，所以目前不存在公開 raw 下載網址。
