#!/usr/bin/env python3
"""Build small TPE schedule pages by local event date for ESP32 (offline)."""
import argparse
from collections import defaultdict
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re
from split_aviation_daily import ROOT, expand, atomic_json

PAGE_RECORDS = 32
PAGE_BYTES = 16384


def event_time(service_date, value):
    match = re.fullmatch(r'([0-2]\d:[0-5]\d)([+-]\d+)?', value)
    if not match or int(match[1][:2]) > 23:
        raise ValueError(f'Invalid schedule time: {value!r}')
    return (date.fromisoformat(service_date) + timedelta(days=int(match[2] or 0))).isoformat(), match[1]


def convert(rows, names):
    daily, duplicates = expand(rows)
    groups = defaultdict(list)
    unknown = set()
    seen = set()
    for service_date, flights in daily.items():
        # Include empty directions in every source calendar day.
        groups[(service_date, 'departures')]
        groups[(service_date, 'arrivals')]
        for flight in flights:
            for direction, field, peer in (
                ('departures', 'DepartureTime', 'ArrivalAirportID'),
                ('arrivals', 'ArrivalTime', 'DepartureAirportID'),
            ):
                local_airport = 'DepartureAirportID' if direction == 'departures' else 'ArrivalAirportID'
                if flight[local_airport] != 'TPE':
                    continue
                event_date, time = event_time(service_date, flight[field])
                airport = flight[peer]
                label = names.get(airport, {})
                if not label:
                    unknown.add(airport)
                item = dict(time=time, flight=flight['FlightNumber'], airline=flight['AirlineID'],
                            airport=airport, name_zh=label.get('zh') or airport,
                            name_en=label.get('en') or airport, terminal=flight.get('Terminal') or '',
                            service_date=service_date)
                # Collapse identical display records only; distinct times/terminals remain.
                signature = (event_date, direction, json.dumps(item, sort_keys=True, ensure_ascii=False))
                if signature in seen:
                    continue
                seen.add(signature)
                groups[(event_date, direction)].append(item)
    for items in groups.values():
        items.sort(key=lambda r: (r['time'], r['flight'], r['airport'], r['terminal'], r['service_date']))
    return dict(sorted(groups.items())), duplicates, sorted(unknown)


def payload(day, direction, page, items):
    return dict(schema=1, airport='TPE', date=day, direction=direction, page=page,
                timezone='Asia/Taipei', scheduled_only=True, items=items)


def encode(obj):
    return (json.dumps(obj, ensure_ascii=False, separators=(',', ':'))+'\n').encode()


def paginate(day, direction, items):
    pages = []
    current = []
    for item in items:
        trial = current + [item]
        if len(trial)>PAGE_RECORDS or len(encode(payload(day,direction,len(pages),trial)))>PAGE_BYTES:
            if not current:
                raise ValueError('Single record exceeds page limit')
            pages.append(payload(day,direction,len(pages),current))
            current = [item]
        else:
            current = trial
        if len(encode(payload(day,direction,len(pages),current)))>PAGE_BYTES:
            raise ValueError('Single record exceeds page limit')
    if current:
        pages.append(payload(day,direction,len(pages),current))
    return pages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?', type=Path,
                        default=ROOT/'aviation/international/2026-11-03-general-schedule.json')
    parser.add_argument('--output', type=Path, default=ROOT/'aviation/esp32')
    args = parser.parse_args()
    raw = args.source.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    names = json.loads((ROOT/'aviation/airport_names.json').read_text())
    groups, duplicates, unknown = convert(json.loads(raw), names)
    # Immutable content-versioned directory; publish root index only after all pages are done.
    version = hashlib.sha256(raw+encode(names)+Path(__file__).read_bytes()).hexdigest()[:16]
    base = args.output/'versions'/version
    calendar = defaultdict(dict)
    total=0; largest=0; page_count=0
    for (day, direction), items in groups.items():
        folder = base/day/direction
        folder.mkdir(parents=True, exist_ok=True)
        entries=[]
        for page in paginate(day,direction,items):
            filename=f'{page["page"]:03d}.json'
            content=encode(page)
            path=folder/filename
            # Reuse atomic writer while keeping output compact.
            import os, tempfile
            with tempfile.NamedTemporaryFile(dir=folder,delete=False) as f:
                temp=Path(f.name)
                try:
                    f.write(content); f.flush(); os.fsync(f.fileno())
                except BaseException:
                    temp.unlink(missing_ok=True); raise
            try:
                os.replace(temp,path)
            finally:
                temp.unlink(missing_ok=True)
            entries.append(dict(file=filename,count=len(page['items']),bytes=len(content),
                                first_time=page['items'][0]['time'],last_time=page['items'][-1]['time'],
                                sha256=hashlib.sha256(content).hexdigest()))
            largest=max(largest,len(content));page_count+=1
        atomic_json(folder/'index.json',dict(schema=1,date=day,direction=direction,airport='TPE',
                    timezone='Asia/Taipei',scheduled_only=True,count=len(items),pages=entries))
        calendar[day][direction]=dict(index=f'versions/{version}/{day}/{direction}/index.json',count=len(items))
        total+=len(items)
    args.output.mkdir(parents=True,exist_ok=True)
    for day, directions in calendar.items():
        atomic_json(base/day/'index.json',dict(schema=1,date=day,airport='TPE',timezone='Asia/Taipei',scheduled_only=True,**directions))
    manifest=dict(schema=1,airport='TPE',timezone='Asia/Taipei',scheduled_only=True,
                  version=version,date_index_template=f'versions/{version}/{{date}}/index.json',
                  first_date=min(calendar),last_date=max(calendar),day_count=len(calendar),source_file=args.source.name,source_sha256=source_hash,
                  page_record_limit=PAGE_RECORDS,page_byte_limit=PAGE_BYTES,
                  exact_source_duplicates_removed=duplicates,missing_airport_names=unknown,
                  airport_names_file='../airport_names.json')
    atomic_json(args.output/'index.json',manifest)
    print(json.dumps(dict(version=version,days=len(calendar),records=total,pages=page_count,
                          largest_page_bytes=largest,missing_airport_names=unknown),ensure_ascii=False))


if __name__=='__main__':
    main()
