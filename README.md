# 台灣高鐵時刻資料

各站完整原始 JSON 位於 `timetable/YYYY-MM-DD-station-站碼.json`，未設定 `$top` 限制。

桃園（1020）範例，ESP32 可透過 HTTPS GET 下載：

https://raw.githubusercontent.com/bowwowxx/thsr/main/timetable/2026-11-03-station-1020.json

站碼對照見 `stations.json`。檔名含日期，目前資料為 2026-11-03，尚未設定自動更新。

## 更新資料

將 TDX 憑證填入本機 `.env`（不提交 Git），執行：

```sh
python3 fetch_daily.py 2026-11-03
```

程式產生 `timetable/YYYY-MM-DD.json` 全站彙整檔；12 站全部成功且非空才以暫存檔原子替換舊檔。此指令不會更新各站獨立 JSON。每站間隔 4～5 秒，遇到錯誤會退避重試；來源 IP 若同時有其他程式請求，仍須共同控制頻率。
