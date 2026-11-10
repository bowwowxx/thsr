#!/usr/bin/env python3
"""THSR 每日全線班次：一次抓取，產生彙整／站別／路線，最後提交推送。"""

import argparse
import json
import os
import re
import subprocess
import time
import random
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
ROOT = Path(__file__).resolve().parent
TIME_RE = re.compile(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]')


def validate_date(train_date):
    if not isinstance(train_date, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', train_date):
        raise ValueError('日期格式須為 YYYY-MM-DD')
    date.fromisoformat(train_date)
    return train_date


def build_routes(daily, train_date):
    """Only use this fetch's complete in-memory data; never perform I/O here.

    stops entries are [StationID, ArrivalTime, DepartureTime] in travel order.
    One midnight rollover is allowed; small backwards time jumps are rejected.
    """
    validate_date(train_date)
    if not isinstance(daily, dict) or daily.get('train_date') != train_date:
        raise ValueError('彙整檔日期不符')
    stations = daily.get('stations')
    rank = {sid: i for i, (sid, _, _) in enumerate(STATIONS)}
    if not isinstance(stations, dict) or set(stations) != set(rank):
        raise ValueError('必須包含完整 12 站，且不可包含未知車站')
    routes = {}
    total = 0
    for sid, _, _ in STATIONS:
        station = stations[sid]
        if not isinstance(station, dict):
            raise ValueError(f'{sid}: 車站資料格式錯誤')
        rows = station.get('Trains')
        if not isinstance(rows, list) or not rows:
            raise ValueError(f'{sid}: 車站資料為空')
        if type(station.get('Count')) is not int or station['Count'] != len(rows):
            raise ValueError(f'{sid}: Count 與資料筆數不符')
        total += len(rows)
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or row.get('TrainDate') != train_date or row.get('StationID') != sid:
                raise ValueError(f'{sid}: 車次日期或車站不符')
            train = row.get('TrainNo')
            if not isinstance(train, str) or not re.fullmatch(r'[0-9]+', train):
                raise ValueError(f'{sid}: TrainNo 必須是保留前置零的數字字串')
            if train in seen:
                raise ValueError(f'{sid}: 重複車次 {train}')
            seen.add(train)
            direction, origin, destination = (row.get(k) for k in ('Direction', 'StartingStationID', 'EndingStationID'))
            if type(direction) is not int or direction not in (0, 1):
                raise ValueError(f'{train}: Direction 必須是 0 或 1')
            if any(not isinstance(s, str) or s not in rank for s in (origin, destination)):
                raise ValueError(f'{train}: 起訖站不合法')
            if not (rank[origin] < rank[destination] if direction == 0 else rank[origin] > rank[destination]):
                raise ValueError(f'{train}: 起訖站與方向不符')
            if not min(rank[origin], rank[destination]) <= rank[sid] <= max(rank[origin], rank[destination]):
                raise ValueError(f'{train}: 停靠站超出起訖範圍')
            times = [row.get('ArrivalTime'), row.get('DepartureTime')]
            if any(not isinstance(t, str) or not TIME_RE.fullmatch(t) for t in times):
                raise ValueError(f'{train}/{sid}: 到發時間格式錯誤')
            route = routes.setdefault(train, {'direction': direction, 'origin': origin, 'destination': destination, 'stops': []})
            if (route['direction'], route['origin'], route['destination']) != (direction, origin, destination):
                raise ValueError(f'{train}: 各站方向或起訖站不一致')
            route['stops'].append([sid, *times])
    if type(daily.get('total_trains')) is not int or daily['total_trains'] != total:
        raise ValueError('total_trains 與全站筆數不符')
    for train, route in routes.items():
        stops = route['stops']
        stops.sort(key=lambda s: rank[s[0]], reverse=route['direction'] == 1)
        if stops[0][0] != route['origin'] or stops[-1][0] != route['destination']:
            raise ValueError(f'{train}: 缺少起點或終點停站紀錄')
        previous = first = None
        day_offset = 0
        for sid, arrival, departure in stops:
            for index, value in enumerate((arrival, departure)):
                hour, minute = map(int, value.split(':'))
                current = hour * 60 + minute + day_offset
                if previous is not None and current < previous:
                    if day_offset or previous - current <= 12 * 60:
                        raise ValueError(f'{train}/{sid}: 行車時間倒退')
                    day_offset = 24 * 60
                    current += day_offset
                if first is None:
                    first = current
                if current - first >= 24 * 60 or (index == 0 and previous is not None and current <= previous):
                    raise ValueError(f'{train}/{sid}: 行車時間不合理')
                previous = current
    return {'schema': 1, 'date': train_date, 'routes': dict(sorted(routes.items()))}


def _git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, check=True, text=True, capture_output=True).stdout.strip()


def git_ready(output_dir, routes_dir):
    """Refuse unrelated staged changes; never stash, reset, pull or force-push."""
    repo = Path(_git(ROOT, 'rev-parse', '--show-toplevel')).resolve()
    for path in (output_dir, routes_dir):
        path.resolve().relative_to(repo)
    if _git(repo, 'diff', '--cached', '--name-only'):
        raise RuntimeError('Git 已有暫存變更；請先處理，避免混入每日資料提交')
    _git(repo, 'symbolic-ref', '--short', 'HEAD')
    _git(repo, 'remote', 'get-url', 'origin')
    return repo


def publish_to_git(repo, train_date, output_dir, routes_dir, removed):
    if _git(repo, 'diff', '--cached', '--name-only'):
        raise RuntimeError('Git 暫存區在產生資料期間被修改；停止提交以免混入其他變更')
    relative = lambda path: path.resolve().relative_to(repo).as_posix()
    paths = [relative(output_dir / f'{train_date}.json'), relative(routes_dir / f'{train_date}.json')]
    paths.extend(relative(output_dir / f'{train_date}-station-{sid}.json') for sid, _, _ in STATIONS)
    if removed:
        tracked = _git(repo, 'ls-files', '-z', '--', *(relative(p) for p in removed))
        paths.extend(p for p in tracked.split('\0') if p)
    _git(repo, 'add', '-A', '--', *paths)
    if _git(repo, 'diff', '--cached', '--name-only'):
        _git(repo, 'commit', '-m', f'Daily THSR timetable and routes {train_date}')
        print('已提交今日彙整、站別與 routes 資料')
    else:
        print('資料未變更，略過建立提交')
    branch = _git(repo, 'symbolic-ref', '--short', 'HEAD')
    # Retry a previous failed push even if this run did not create another commit.
    _git(repo, 'push', 'origin', branch)
    print(f'已推送 origin/{branch}')


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


def collect_daily(train_date):
    """Keep the existing TDX station requests, delay, retries and full JSON shape."""
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

    result["total_trains"] = total
    result["fetched_at"] = date.today().isoformat()
    return result


def write_daily(result, train_date, output_dir, routes_dir):
    """Validate all outputs first; publish routes last, with per-file atomic writes."""
    import prepare_station_daily

    routes = build_routes(result, train_date)
    payloads = prepare_station_daily.build_payloads(train_date, result['stations'])
    full_text = json.dumps(result, ensure_ascii=False, indent=2)
    route_text = json.dumps(routes, ensure_ascii=False, separators=(',', ':')) + '\n'
    output_dir.mkdir(parents=True, exist_ok=True)
    routes_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f'{train_date}.json'
    prepare_station_daily.atomic_write(out_path, full_text)
    removed = prepare_station_daily.publish_station_files(train_date, payloads, output_dir)
    route_path = routes_dir / f'{train_date}.json'
    prepare_station_daily.atomic_write(route_path, route_text)
    print(f'完成 — {result["total_trains"]} 筆停站紀錄，{len(routes["routes"])} 車次；'
          f'{route_path} ({len(route_text.encode("utf-8"))} bytes)')
    return out_path, removed


def run(train_date: Optional[str] = None, output_dir: Optional[Path] = None,
        *, offline: bool = False, publish: bool = True) -> Path:
    """One command produces all three formats and then commits/pushes daily data."""
    train_date = validate_date(train_date if train_date is not None else date.today().isoformat())
    output_dir = Path(output_dir) if output_dir is not None else ROOT / 'timetable'
    routes_dir = output_dir.parent / 'routes'
    repo = git_ready(output_dir, routes_dir) if publish else None
    if offline:
        print('離線模式：只讀取既有彙整檔，不驗證 TDX 憑證、不呼叫 API')
        result = json.loads((output_dir / f'{train_date}.json').read_text(encoding='utf-8'))
    else:
        authenticate()
        result = collect_daily(train_date)
    out_path, removed = write_daily(result, train_date, output_dir, routes_dir)
    if publish:
        publish_to_git(repo, train_date, output_dir, routes_dir, removed)
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('date', nargs='?', help='YYYY-MM-DD，預設今天')
    parser.add_argument('--offline', action='store_true', help='使用既有彙整檔，不連 TDX')
    parser.add_argument('--no-push', action='store_true', help='只產生資料，不提交或推送 Git')
    args = parser.parse_args()
    try:
        run(args.date, offline=args.offline, publish=not args.no_push)
    except subprocess.CalledProcessError as exc:
        parser.exit(1, f'Git 命令失敗；資料保留，可修正後重跑：{exc.stderr or exc}\n')
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f'{exc}\n')
