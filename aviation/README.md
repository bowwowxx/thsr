# 航空資料

與高鐵 `timetable/` 分開存放。

- `international/2026-11-03-general-schedule.json`：TDX 國際航空定期時刻表原始完整回應，42,343 筆，未加 `$top`、未篩選機場。
- 同名 `.meta.json`：來源網址、擷取時間、HTTP 狀態、筆數、大小及 SHA-256。

來源：TDX `/api/basic/v2/Air/GeneralSchedule/International?health=false&%24format=JSON`。

回應含適用起訖日期、星期一至星期日營運欄位、出發／抵達機場及時間等；屬定期時刻表，不能作為即時航班狀態。時間可能有 `+1` 跨日標記，後續顯示須保留並處理。原始檔約 17 MB，供 ESP32 使用前宜另製依機場與日期篩選的小檔。

## 每日檔

`international/daily/YYYY-MM-DD.json` 依適用日期（包含起訖日）與營運星期展開，每筆保留原欄位並新增 `FlightDate`。共 147 天，2026-11-02～2027-03-28；2026-11-03 有 1,264 筆。`daily/index.json` 列出每日檔名、筆數與原始檔雜湊。

刪除 21 筆完全相同的原始紀錄；相同航班的不同時刻／不同班表紀錄仍保留，不擅自合併。每日檔以班表營運日歸類，非抵達日清單；`ArrivalTime` 的 `+1` 等標記保持原樣，未作時區換算。未篩選機場；後續裝置可另取桃園 TPE 出發或抵達的子集。

離線重新產生：`python3 split_aviation_daily.py`。完整驗證輸入後才開始寫入，每個檔案採暫存檔完成後替換；原始 JSON 不變。
