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

流程：`fetch_daily.py` 抓 TDX 當日 12 站（自動呼叫 `prepare_station_daily.py` 展開成逐站檔）→ git commit → push。失敗時排程發通知，不會靜默漏跑。手動重跑用 `python3 fetch_daily.py YYYY-MM-DD`（見下方）。

## 更新資料

將 TDX 憑證填入本機 `.env`（不提交 Git），執行：

```sh
python3 fetch_daily.py 2026-11-03
```

程式產生 `timetable/YYYY-MM-DD.json` 全站彙整檔；12 站全部成功且非空才以暫存檔原子替換舊檔。此指令不會更新各站獨立 JSON。每站間隔 4～5 秒，遇到錯誤會退避重試；來源 IP 若同時有其他程式請求，仍須共同控制頻率。

抓取完成後執行：

```sh
python3 prepare_station_daily.py 2026-11-03
```

程式把彙整檔展開成 `timetable/YYYY-MM-DD-station-站碼.json`（12 個逐站檔，TDX 原始欄位格式，站名從 repo 已發布檔補齊），12 站全部通過驗證才原子寫入；站名欄位為空的行仍可用，但終到站名會顯示為站碼。此指令不呼叫 TDX。

兩支指令完成後，把新增的 `timetable/` 檔 commit 並 push（每日排程自動做；手動時）：

```sh
git add timetable/ && git commit -m "Daily THSR timetable YYYY-MM-DD" && git push
```

## 航空資料

桃園出入境表定時刻已依日期及方向分頁，每頁最多 32 筆／16 KiB。裝置先讀取 [航空入口索引](https://raw.githubusercontent.com/bowwowxx/thsr/main/aviation/esp32/index.json)，再取固定版本的當日分頁。完整規格見 [航空讀取說明](aviation/esp32/README.md)。

2026-11-03 新增更新按鈕，會完整驗證當日出入境後保存至 Flash，失敗保留舊資料。登機門與即時狀態不在此資料來源內。原始航空 17 MB 檔及全欄位每日大檔保留本機，不在此儲存庫。轉換工具需自行提供原始 JSON；`prepare_aviation_esp32.py` 可傳入來源路徑。
