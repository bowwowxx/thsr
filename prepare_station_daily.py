#!/usr/bin/env python3
"""Expand a daily consolidated THSR fetch into per-station raw-format files.

Usage: python3 prepare_station_daily.py YYYY-MM-DD

Reads timetable/YYYY-MM-DD.json (produced by fetch_daily.py) and writes
timetable/YYYY-MM-DD-station-<ID>.json for each of the 12 stations, in the
same flat TDX-array format the firmware downloads. Writes only after every
station validates; original per-date files are left untouched.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Optional
from urllib import error as urllib_error
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
TIMETABLE = ROOT / 'timetable'
STATIONS = ('0990', '1000', '1010', '1020', '1030', '1035', '1040', '1043', '1047', '1050', '1060', '1070')
RAW_URL = 'https://raw.githubusercontent.com/bowwowxx/thsr/main/timetable/{date}-station-{sid}.json'
DATE_RE = re.compile(r'\d{4}-\d{2}-\d{2}')


def catalog_names(date):
    """Latest published per-station station names from the repo's raw files."""
    try:
        with urlopen('https://api.github.com/repos/bowwowxx/thsr/contents/timetable?ref=main', timeout=30) as response:
            entries = json.load(response)
    except Exception as e:
        raise SystemExit(f'GitHub listing fetch failed: {e}')
    if not isinstance(entries, list) or not entries:
        raise SystemExit('GitHub listing empty')
    files = {}
    for entry in entries:
        name = entry.get('name', '')
        match = re.fullmatch(r'(\d{4}-\d{2}-\d{2})-station-(\d{4})\.json', name)
        if match:
            files[match.group(2)] = match.group(1)
    missing = [sid for sid in STATIONS if sid not in files]
    if missing:
        raise SystemExit(f'no published per-station file for station(s) {missing}; run git push first')
    names = {}
    for sid in STATIONS:
        url = f'https://raw.githubusercontent.com/bowwowxx/thsr/main/timetable/{files[sid]}-station-{sid}.json'
        with urlopen(url, timeout=30) as response:
            first = json.load(response)
        if not isinstance(first, list) or not first:
            raise SystemExit(f'raw file for {sid} is empty or not a list')
        station = first[0].get('StationName')
        name = station.get('Zh_tw') if isinstance(station, dict) else None
        if not name:
            raise SystemExit(f'raw file for {sid} lacks StationName.Zh_tw')
        names[sid] = name
    return names


def load_daily(date):
    path = TIMETABLE / f'{date}.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('train_date') != date:
        raise ValueError(f'{path.name}: train_date {data.get("train_date")!r} != {date}')
    stations = data.get('stations')
    if not isinstance(stations, dict):
        raise ValueError(f'{path.name}: missing stations object')
    return stations


def build_station(date, sid, name, trains):
    if not isinstance(trains, list) or not trains:
        raise ValueError(f'{date} station {sid}: empty Trains')
    rows = []
    for t in trains:
        if t.get('TrainDate') != date or t.get('StationID') != sid:
            raise ValueError(f'{date} station {sid}: row date/station mismatch')
        if str(t.get('Direction')) not in ('0', '1'):
            raise ValueError(f'{date} station {sid}: bad Direction {t.get("Direction")!r}')
        terminal = t.get('EndingStationID') == sid
        time = t.get('ArrivalTime') if terminal else t.get('DepartureTime')
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', time or ''):
            raise ValueError(f'{date} station {sid}: bad time {time!r} for train {t.get("TrainNo")!r}')
        for key in ('StartingStationID', 'EndingStationID', 'TrainNo'):
            if not str(t.get(key) or ''):
                raise ValueError(f'{date} station {sid}: missing {key}')
        rows.append({
            'TrainDate': t['TrainDate'],
            'StationID': sid,
            'StationName': {'Zh_tw': name, 'En': '', 'Ja': '', 'Ko': ''},
            'TrainNo': t['TrainNo'],
            'Direction': t['Direction'],
            'StartingStationID': t['StartingStationID'],
            'StartingStationName': {'Zh_tw': '', 'En': '', 'Ja': '', 'Ko': ''},
            'EndingStationID': t['EndingStationID'],
            'EndingStationName': {'Zh_tw': '', 'En': '', 'Ja': '', 'Ko': ''},
            'ArrivalTime': t.get('ArrivalTime') or '',
            'DepartureTime': t.get('DepartureTime') or '',
            'UpdateTime': '',
            'VersionID': 1,
        })
    return rows


def atomic_write(path, text):
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, suffix='.tmp', delete=False) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
            temp = Path(f.name)
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink(missing_ok=True)


def run(train_date: Optional[str] = None) -> None:
    if train_date is None:
        if len(sys.argv) != 2:
            raise SystemExit(__doc__)
        train_date = sys.argv[1]
    if not DATE_RE.fullmatch(train_date):
        raise SystemExit(f'Bad date {train_date!r}; expected YYYY-MM-DD')
    names = catalog_names(train_date)
    stations = load_daily(train_date)
    payloads = {}
    for sid in STATIONS:
        station = stations.get(sid)
        if not isinstance(station, dict):
            raise SystemExit(f'{train_date} station {sid}: missing from daily file')
        rows = build_station(train_date, sid, names[sid], station['Trains'])
        payloads[sid] = (json.dumps(rows, ensure_ascii=False, indent=2) + '\n', len(rows))
    # All 12 stations validated (or exited above); now publish atomically.
    total = 0
    for sid in STATIONS:
        text, count = payloads[sid]
        path = TIMETABLE / f'{train_date}-station-{sid}.json'
        total += count
        atomic_write(path, text)
        print(f'wrote {path.name} ({count} rows, {len(text)} bytes)')
    print(f'{train_date}: published {len(STATIONS)} station files, {total} rows total')


if __name__ == '__main__':
    try:
        run()
    except (SystemExit, ValueError, OSError, json.JSONDecodeError,
            urllib_error.URLError) as e:
        raise SystemExit(str(e))
