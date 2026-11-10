## 高鐵資料

各站完整原始 JSON 位於 `timetable/YYYY-MM-DD-station-站碼.json`，未設定 `$top` 限制。

桃園（1020）範例，ESP32 可透過 HTTPS GET 下載：

https://raw.githubusercontent.com/bowwowxx/thsr/main/timetable/2026-11-03-station-1020.json

站碼對照見 `stations.json`。檔名含日期，每日由排程自動更新（見下方「每日自動發布」）。

## 每日自動發布

本倉庫由高鐵每日排程自動維護（Hermes cron，Mac mini 每天 06:30 觸發）：

```sh
~/.hermes/scripts/thsr-daily.sh
```

流程：`fetch_daily.py` 沿用原本 TDX 認證與 12 站下載 → 在記憶體驗證完整資料 → 產生彙整檔、ESP32 逐站檔、routes 檔 → 同一支程式執行 git commit 與 push。Hermes 排程只呼叫此程式，不再重複提交／推送。失敗時回傳非零狀態，排程發通知，不會靜默漏跑。

## 更新資料

將 TDX 憑證填入本機 `.env`（不提交 Git），執行：

```sh
python3 fetch_daily.py 2026-11-03
```

每次執行同時產生：

- `timetable/YYYY-MM-DD.json`：保留原本的全站彙整格式與全部停站紀錄。
- `timetable/YYYY-MM-DD-station-站碼.json`：沿用 `prepare_station_daily.py` 的 12 站拆檔格式與舊站檔清理規則，ESP32 讀取格式不變。
- `routes/YYYY-MM-DD.json`：從同一份已下載資料依車次彙整，不新增 TDX 請求。

下載仍為每站間隔 4～5 秒及原有退避重試。完整 12 站、各站 Count、total_trains、日期、車次字串、同車次的方向／起訖站、重複停站、端點存在及到發時間順序皆通過後，才開始寫檔；任何驗證失敗不覆寫既有輸出。每個檔案使用暫存檔原子替換，routes 最後寫入，所有輸出與清理都成功才提交／推送。這是逐檔原子替換，不是跨檔案交易；若遇到 I/O 失敗，修正後重跑，不會推送半套結果。

提交只包含當日的三種資料與此次清除的舊站檔，不會加入程式碼、航空檔或其他工作檔。若已有其他暫存變更會先停止；不會 stash、reset、pull 或強制推送。無資料變更時不建立空提交，但仍嘗試推送，讓前次推送失敗的提交可以重試。

只產生本機資料、暫不提交或推送：

```sh
python3 fetch_daily.py 2026-11-03 --no-push
```

離線重建與測試既有資料（不讀 TDX 憑證、不呼叫 API、不提交推送）：

```sh
python3 fetch_daily.py 2026-11-10 --offline --no-push
python3 -m unittest discover -s tests -v
```

`prepare_station_daily.py YYYY-MM-DD` 仍可單獨使用，格式與行為相容；日常更新無須再另外執行。

## routes 格式

JSON 使用 UTF-8 精簡編碼，不重複保存車次、日期、站名或可由停站紀錄取得的起訖時間。結構示意：

```json
{"schema":1,"date":"2026-11-10","routes":{"0109":{"direction":0,"origin":"0990","destination":"1070","stops":[["0990","07:20","07:20"],["1000","07:28","07:31"],["1010","07:38","07:39"],["1040","08:18","08:20"],["1070","09:05","09:05"]]}}}
```

`routes` 的 key 是原始 `TrainNo` 字串，例如 `0817`，保留前置零。方向 0 是南下、1 是北上；`origin`／`destination` 為起訖 StationID。每個 `stops` 元素依序是 `[StationID, ArrivalTime, DepartureTime]`，只收錄來源實際出現的停靠站，南下由南港往左營排列，北上反向；區間車從自己的起點到終點，不補齊未停靠站。時刻原樣保留 `HH:MM`，跨午夜只允許一次時間回繞，讀取端可依旅程順序判斷隔日，不把跳站推算成已停站。

資料完整性以現有來源能提供的資訊為限：若來源悄悄遺漏中途一筆停站，且連 Count／total_trains 也同步變成一致，又沒有提供預期停站清單，就無法區分漏列與合法跳站；程式不猜測補站，也不額外呼叫 API。

2026-11-10 離線實測：12 站、1,254 筆停站紀錄、149 車次（南下 74、北上 75），routes 檔 **41,824 bytes（約 40.84 KiB）**；完整檔與 12 個 ESP32 站別檔逐位元相同。19 項測試全數通過，包含既有航空測試、禁止網路的離線重建、寫檔失敗不推送，以及本機 bare Git remote 的提交／推送、失敗重試與未變更重跑。

## 航空資料

桃園出入境表定時刻已依日期及方向分頁，每頁最多 32 筆／16 KiB。裝置先讀取 [航空入口索引](https://raw.githubusercontent.com/bowwowxx/thsr/main/aviation/esp32/index.json)，再取固定版本的當日分頁。完整規格見 [航空讀取說明](aviation/esp32/README.md)。

2026-11-03 新增更新按鈕，會完整驗證當日出入境後保存至 Flash，失敗保留舊資料。登機門與即時狀態不在此資料來源內。原始航空 17 MB 檔及全欄位每日大檔保留本機，不在此儲存庫。轉換工具需自行提供原始 JSON；`prepare_aviation_esp32.py` 可傳入來源路徑。
