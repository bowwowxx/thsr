#!/usr/bin/env python3
"""Expand TDX international recurring schedules by operating date, offline."""
import argparse
from collections import defaultdict
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile

WEEKDAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
ROOT = Path(__file__).resolve().parent


def expand(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError('Expected nonempty schedule array')
    days = defaultdict(list)
    seen = set()
    duplicates = 0
    for row in rows:
        start = date.fromisoformat(row['ScheduleStartDate'])
        end = date.fromisoformat(row['ScheduleEndDate'])
        if start > end:
            raise ValueError('Schedule date range is reversed')
        if any(type(row.get(day)) is not bool for day in WEEKDAYS):
            raise ValueError('Expected boolean weekday flags')
        signature = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if signature in seen:
            duplicates += 1
            continue
        seen.add(signature)
        current = start
        while current <= end:
            # Include empty days in the index as well.
            group = days[current.isoformat()]
            if row[WEEKDAYS[current.weekday()]]:
                group.append(dict(row, FlightDate=current.isoformat()))
            current += timedelta(days=1)
    for group in days.values():
        group.sort(key=lambda r: (r['DepartureTime'], r['DepartureAirportID'],
                                  r['FlightNumber'], r['ArrivalAirportID'], r['ArrivalTime']))
    return dict(sorted(days.items())), duplicates


def atomic_json(path, value):
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         suffix='.tmp', delete=False) as stream:
            temp = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?', type=Path,
                        default=ROOT / 'aviation/international/2026-11-03-general-schedule.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'aviation/international/daily')
    args = parser.parse_args()
    raw = args.source.read_bytes()
    rows = json.loads(raw)
    days, duplicates = expand(rows)  # Validate everything before writing.
    args.output.mkdir(parents=True, exist_ok=True)
    index = []
    for day, records in days.items():
        filename = f'{day}.json'
        atomic_json(args.output / filename, records)
        index.append({'date': day, 'file': filename, 'count': len(records)})
    manifest = {'source_file': args.source.name, 'source_sha256': hashlib.sha256(raw).hexdigest(),
                'grouping': 'operating_date_not_arrival_date', 'source_records': len(rows),
                'exact_duplicates_removed': duplicates, 'days': len(index),
                'daily_records': sum(x['count'] for x in index), 'files': index}
    atomic_json(args.output / 'index.json', manifest)
    print(json.dumps({k: v for k, v in manifest.items() if k != 'files'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
