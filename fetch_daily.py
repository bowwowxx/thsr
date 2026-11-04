#!/usr/bin/env python3
"""THSR 每日全線班次抓取 — 12 站輪詢，結果存 JSON"""

import json
import os
import time
import random
import tempfile
import urllib.request
import urllib.error
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Optional

BASE_URL = (
    "https://tdx.transportdata.tw/api/basic/v2/Rail/THSR"
    "/DailyTimetable/Station/{station_id}/{train_date}?%24format=JSON"
)

HEADERS = {
    "accept": "application/json",
    "accept-language": "zh-TW,zh;q=0.9,en;q=0.8",
    "referer": "https://tdx.transportdata.tw/",
    "origin": "https://tdx.transportdata.tw",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}

# 12 個高鐵車站（由北至南）
STATIONS = [
    ("0990", "NAK", "南港"),
    ("1000", "TPE", "台北"),
    ("1010", "BAC", "板橋"),
    ("1020", "TAY", "桃園"),
    ("1030", "HSC", "新竹"),
    ("1035", "MIL", "苗栗"),
    ("1040", "TAC", "台中"),
    ("1043", "CHA", "彰化"),
    ("1047", "YUL", "雲林"),
    ("1050", "CHY", "嘉義"),
    ("1060", "TNN", "台南"),
    ("1070", "ZUY", "左營"),
]

DELAY_MIN, DELAY_MAX = 4.0, 5.0  # 每站間隔秒數（隨機）


def authenticate():
    """從環境或本機 .env 讀取憑證，取得 Token；不保存 Token。"""
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())
    payload = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["TDX_CLIENT_ID"],
        "client_secret": os.environ["TDX_CLIENT_SECRET"],
    }).encode()
    req = urllib.request.Request(
        "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        token = json.load(resp)["access_token"]
    HEADERS["Authorization"] = f"Bearer {token}"


def fetch_station(station_id: str, train_date: str, retries: int = 3) -> list:
    """抓取單站班次資料，失敗重試"""
    url = BASE_URL.format(station_id=station_id, train_date=train_date)
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
            if b"Valid API Key" in raw:
                raise RuntimeError("API 回傳 Valid API Key Required")
            trains = json.loads(raw)
            if not isinstance(trains, list) or not trains:
                raise ValueError("API 未回傳非空班次陣列")
            if any(t.get("StationID") != station_id or t.get("TrainDate") != train_date
                   for t in trains):
                raise ValueError("API 回傳的車站或日期不符")
            return trains
        except Exception as e:
            print(f"  [{station_id}] attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                wait = 10 * attempt + random.uniform(2, 5)
                print(f"  [{station_id}] backing off {wait:.0f}s...")
                time.sleep(wait)
    raise RuntimeError(f"車站 {station_id} 抓取失敗；不覆寫原檔")


def slim_train(t: dict) -> dict:
    """只保留需要的欄位"""
    return {
        "TrainDate": t["TrainDate"],
        "StationID": t["StationID"],
        "TrainNo": t["TrainNo"],
        "Direction": t["Direction"],
        "StartingStationID": t["StartingStationID"],
        "EndingStationID": t["EndingStationID"],
        "ArrivalTime": t["ArrivalTime"],
        "DepartureTime": t["DepartureTime"],
    }


def run(train_date: Optional[str] = None, output_dir: Optional[Path] = None) -> Path:
    """主程式：抓取全線 12 站班次"""
    authenticate()
    if train_date is None:
        train_date = date.today().isoformat()

    if output_dir is None:
        output_dir = Path(__file__).parent / "timetable"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"抓取 {train_date} 全線 12 站班次\n")

    result = {"train_date": train_date, "stations": {}}
    total = 0

    for i, (sid, code, name) in enumerate(STATIONS):
        trains = fetch_station(sid, train_date)
        if not trains:
            raise RuntimeError(f"車站 {sid} 資料為空；不覆寫原檔")
        slim = [slim_train(t) for t in trains]
        slim.sort(key=lambda x: x["DepartureTime"])
        result["stations"][sid] = {
            "StationCode": code,
            "Name": name,
            "Count": len(slim),
            "Trains": slim,
        }
        total += len(slim)
        print(f"  {name} ({code}): {len(slim)} 班")

        if i < len(STATIONS) - 1:
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    out_path = output_dir / f"{train_date}.json"
    result["total_trains"] = total
    result["fetched_at"] = date.today().isoformat()

    # 全站完成後先寫暫存檔，再原子替換；失敗時保留原檔。
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=output_dir, suffix=".tmp", delete=False) as f:
            temp_path = Path(f.name)
            json.dump(result, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, out_path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    print(f"\n完成 — 共 {total} 班次，存至 {out_path}")

    # 展開成韌機使用的逐站檔（timetable/{date}-station-{id}.json）。
    import prepare_station_daily
    prepare_station_daily.run(train_date)
    return out_path


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else None
    run(d)
