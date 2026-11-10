#!/usr/bin/env python3
"""Expand a daily consolidated THSR fetch into per-station raw-format files.

Usage: python3 prepare_station_daily.py YYYY-MM-DD

Reads timetable/YYYY-MM-DD.json (produced by fetch_daily.py) and writes
timetable/YYYY-MM-DD-station-<ID>.json for each of the 12 stations, in the
same flat TDX-array format the firmware downloads. Writes only after every
station validates. After all 12 writes succeed, remove older station files;
original consolidated per-date files are left untouched.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
TIMETABLE = ROOT / 'timetable'
STATIONS = ('0990', '1000', '1010', '1020', '1030', '1035', '1040', '1043', '1047', '1050', '1060', '1070')
DATE_RE = re.compile(r'\d{4}-\d{2}-\d{2}')


def catalog_names(stations):
    """Read Chinese station names from the consolidated daily file."""
    names = {}
    for sid in STATIONS:
        station = stations.get(sid)
        name = station.get('Name') if isinstance(station, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f'station {sid}: missing Name in daily file')
        names[sid] = name
    return names


def station_name(name):
    """Use the Chinese name for every language, matching the ESP32 files."""
    return {lang: name for lang in ('Zh_tw', 'En', 'Ja', 'Ko')}


def load_daily(date):
    path = TIMETABLE / f'{date}.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('train_date') != date:
        raise ValueError(f'{path.name}: train_date {data.get("train_date")!r} != {date}')
    stations = data.get('stations')
    if not isinstance(stations, dict):
        raise ValueError(f'{path.name}: missing stations object')
    return stations


def build_station(date, sid, names, trains):
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
        for key in ('StartingStationID', 'EndingStationID'):
            if t[key] not in names:
                raise ValueError(f'{date} station {sid}: unknown {key} {t[key]!r}')
        rows.append({
            'TrainDate': t['TrainDate'],
            'StationID': sid,
            'StationName': station_name(names[sid]),
            'TrainNo': t['TrainNo'],
            'Direction': t['Direction'],
            'StartingStationID': t['StartingStationID'],
            'StartingStationName': station_name(names[t['StartingStationID']]),
            'EndingStationID': t['EndingStationID'],
            'EndingStationName': station_name(names[t['EndingStationID']]),
            'ArrivalTime': t.get('ArrivalTime') or '',
            'DepartureTime': t.get('DepartureTime') or '',
            'UpdateTime': t.get('UpdateTime') or date,
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


def build_payloads(train_date, stations):
    """Validate all stations in memory before any output is replaced."""
    names = catalog_names(stations)
    payloads = {}
    for sid in STATIONS:
        station = stations.get(sid)
        if not isinstance(station, dict):
            raise SystemExit(f'{train_date} station {sid}: missing from daily file')
        rows = build_station(train_date, sid, names, station['Trains'])
        payloads[sid] = (json.dumps(rows, ensure_ascii=False, indent=2) + '\n', len(rows))
    return payloads


def publish_station_files(train_date, payloads, output_dir):
    """Keep the existing ESP32 format and old-station-file retention policy."""
    # All 12 stations validated (or exited above); now publish atomically.
    total = 0
    removed = []
    for sid in STATIONS:
        text, count = payloads[sid]
        path = output_dir / f'{train_date}-station-{sid}.json'
        total += count
        atomic_write(path, text)
        print(f'wrote {path.name} ({count} rows, {len(text)} bytes)')
    # Delete older station files only after every current station write succeeds.
    for path in sorted(output_dir.iterdir()):
        match = re.fullmatch(r'(\d{4}-\d{2}-\d{2})-station-(\d{4})\.json', path.name)
        if (match and match.group(1) < train_date
                and match.group(2) in STATIONS and path.is_file()):
            path.unlink()
            removed.append(path)
            print(f'removed {path.name}')
    print(f'{train_date}: published {len(STATIONS)} station files, {total} rows total')
    return removed


def run(train_date: Optional[str] = None) -> None:
    if train_date is None:
        if len(sys.argv) != 2:
            raise SystemExit(__doc__)
        train_date = sys.argv[1]
    if not DATE_RE.fullmatch(train_date):
        raise SystemExit(f'Bad date {train_date!r}; expected YYYY-MM-DD')
    stations = load_daily(train_date)
    payloads = build_payloads(train_date, stations)
    publish_station_files(train_date, payloads, TIMETABLE)


if __name__ == '__main__':
    try:
        run()
    except (SystemExit, ValueError, OSError, json.JSONDecodeError) as e:
        raise SystemExit(str(e))
