"""Offline route generation and local-only Git publication tests."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fetch_daily as daily
import prepare_station_daily as station

DATE = '2026-11-10'
FIXTURE = ROOT / 'timetable' / f'{DATE}.json'
STATIONS = [sid for sid, _, _ in daily.STATIONS]


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.no_network = mock.patch('urllib.request.urlopen', side_effect=AssertionError('TDX/network forbidden'))
        self.no_network.start()
        self.addCleanup(self.no_network.stop)

    def row(self, sid, train, data=None):
        source = self.data if data is None else data
        return next(t for t in source['stations'][sid]['Trains'] if t['TrainNo'] == train)

    def remove(self, sid, train):
        source = self.data['stations'][sid]
        source['Trains'].remove(self.row(sid, train))
        source['Count'] -= 1
        self.data['total_trains'] -= 1

    def test_fast_south_skips_non_stops_and_keeps_endpoint_times(self):
        route = daily.build_routes(self.data, DATE)['routes']['0109']
        self.assertEqual(route['direction'], 0)
        self.assertEqual((route['origin'], route['destination']), ('0990', '1070'))
        self.assertEqual([s[0] for s in route['stops']], ['0990', '1000', '1010', '1040', '1070'])
        self.assertEqual(route['stops'][0], ['0990', '07:20', '07:20'])
        self.assertEqual(route['stops'][-1], ['1070', '09:05', '09:05'])
        self.assertNotIn('1020', [s[0] for s in route['stops']])

    def test_all_stops_south_and_leading_zero(self):
        routes = daily.build_routes(self.data, DATE)['routes']
        self.assertIn('0817', routes)
        self.assertNotIn('817', routes)
        self.assertEqual([s[0] for s in routes['0817']['stops']], STATIONS)
        self.assertEqual(routes['0817']['stops'][0], ['0990', '10:00', '10:00'])
        self.assertEqual(routes['0817']['stops'][-1], ['1070', '12:25', '12:25'])

    def test_fast_north_order_and_endpoint_times(self):
        route = daily.build_routes(self.data, DATE)['routes']['0108']
        self.assertEqual(route['direction'], 1)
        self.assertEqual((route['origin'], route['destination']), ('1070', '0990'))
        self.assertEqual([s[0] for s in route['stops']], ['1070', '1040', '1010', '1000', '0990'])
        self.assertEqual(route['stops'][0], ['1070', '07:55', '07:55'])
        self.assertEqual(route['stops'][-1], ['0990', '09:40', '09:40'])

    def test_all_stops_north_and_short_working(self):
        routes = daily.build_routes(self.data, DATE)['routes']
        self.assertEqual([s[0] for s in routes['0802']['stops']], STATIONS[::-1])
        self.assertEqual(routes['0802']['stops'][0], ['1070', '06:15', '06:15'])
        self.assertEqual(routes['0802']['stops'][-1], ['0990', '08:40', '08:40'])
        self.assertEqual(routes['0502']['stops'][0], ['1040', '06:05', '06:05'])
        self.assertEqual(routes['0502']['stops'][-1], ['0990', '07:20', '07:20'])
        self.assertEqual(len(routes['0502']['stops']), 7)

    def test_all_real_records_round_trip_without_mutating_source(self):
        before = copy.deepcopy(self.data)
        doc = daily.build_routes(self.data, DATE)
        self.assertEqual(self.data, before)
        self.assertEqual((doc['schema'], doc['date']), (1, DATE))
        routes = doc['routes']
        self.assertEqual(len(routes), 149)
        self.assertEqual(sum(r['direction'] == 0 for r in routes.values()), 74)
        self.assertEqual(sum(len(r['stops']) for r in routes.values()), 1254)
        for sid, data in self.data['stations'].items():
            for row in data['Trains']:
                route = routes[row['TrainNo']]
                self.assertEqual(route['direction'], row['Direction'])
                self.assertEqual(route['origin'], row['StartingStationID'])
                self.assertEqual(route['destination'], row['EndingStationID'])
                self.assertIn([sid, row['ArrivalTime'], row['DepartureTime']], route['stops'])

    def test_reject_incomplete_stations_dates_counts_and_malformed_records(self):
        cases = {
            'missing station': lambda d: d['stations'].pop('1035'),
            'unknown station': lambda d: d['stations'].__setitem__('9999', d['stations']['1035']),
            'empty station': lambda d: d['stations']['1035'].__setitem__('Trains', []),
            'count mismatch': lambda d: d['stations']['1035'].__setitem__('Count', 999),
            'missing interior record': lambda d: d['stations']['1035']['Trains'].pop(),
            'total mismatch': lambda d: d.__setitem__('total_trains', 1),
            'top date': lambda d: d.__setitem__('train_date', '2026-11-09'),
            'row date': lambda d: d['stations']['1035']['Trains'][0].__setitem__('TrainDate', '2026-11-09'),
            'row station': lambda d: d['stations']['1035']['Trains'][0].__setitem__('StationID', '1040'),
            'bad station object': lambda d: d['stations'].__setitem__('1035', []),
            'bad record': lambda d: d['stations']['1035']['Trains'].__setitem__(0, None),
            'numeric TrainNo': lambda d: d['stations']['1035']['Trains'][0].__setitem__('TrainNo', 817),
            'blank TrainNo': lambda d: d['stations']['1035']['Trains'][0].__setitem__('TrainNo', ''),
            'bool direction': lambda d: d['stations']['1035']['Trains'][0].__setitem__('Direction', True),
            'unknown endpoint': lambda d: d['stations']['1035']['Trains'][0].__setitem__('EndingStationID', '9999'),
            'bad time': lambda d: d['stations']['1035']['Trains'][0].__setitem__('ArrivalTime', '24:00'),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                data = copy.deepcopy(self.data)
                mutate(data)
                with self.assertRaises(ValueError):
                    daily.build_routes(data, DATE)

    def test_reject_duplicates_missing_endpoints_and_train_inconsistency(self):
        cases = ('duplicate', 'missing origin', 'missing destination', 'direction', 'origin', 'outside route')
        for label in cases:
            with self.subTest(label=label):
                self.data = json.loads(FIXTURE.read_text(encoding='utf-8'))
                if label == 'duplicate':
                    self.data['stations']['1040']['Trains'].append(copy.deepcopy(self.row('1040', '0109')))
                    self.data['stations']['1040']['Count'] += 1
                    self.data['total_trains'] += 1
                elif label == 'missing origin': self.remove('0990', '0109')
                elif label == 'missing destination': self.remove('1070', '0109')
                elif label == 'direction': self.row('1040', '0109')['Direction'] = 1
                elif label == 'origin': self.row('1040', '0109')['StartingStationID'] = '1000'
                else: self.row('0990', '0109')['StartingStationID'] = '1000'
                with self.assertRaises(ValueError): daily.build_routes(self.data, DATE)

    def test_reject_backwards_arrival_departure_and_allow_midnight(self):
        self.row('1040', '0109')['DepartureTime'] = '08:17'
        with self.assertRaises(ValueError): daily.build_routes(self.data, DATE)
        self.row('1040', '0109')['DepartureTime'] = '08:20'
        self.row('1040', '0109')['ArrivalTime'] = '07:38'
        with self.assertRaises(ValueError): daily.build_routes(self.data, DATE)
        for sid, value in zip(('0990', '1000', '1010', '1040', '1070'), ('23:00', '23:15', '23:25', '23:50', '00:35')):
            row = self.row(sid, '0109')
            row['ArrivalTime'] = row['DepartureTime'] = value
        route = daily.build_routes(self.data, DATE)['routes']['0109']
        self.assertEqual(route['stops'][-1], ['1070', '00:35', '00:35'])

    def test_offline_run_is_byte_compatible_and_compact(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            table = Path(tmp) / 'timetable'
            table.mkdir()
            source = table / f'{DATE}.json'
            source.write_bytes(FIXTURE.read_bytes())
            with mock.patch.object(daily, 'authenticate', side_effect=AssertionError('no auth')), \
                 mock.patch.object(daily, 'fetch_station', side_effect=AssertionError('no fetch')), \
                 mock.patch.object(daily, 'publish_to_git', side_effect=AssertionError('no push')):
                daily.run(DATE, table, offline=True, publish=False)
            self.assertEqual(source.read_bytes(), FIXTURE.read_bytes())
            for sid in STATIONS:
                name = f'{DATE}-station-{sid}.json'
                self.assertEqual((table / name).read_bytes(), (ROOT / 'timetable' / name).read_bytes())
            encoded = (Path(tmp) / 'routes' / f'{DATE}.json').read_bytes()
            expected = daily.build_routes(self.data, DATE)
            self.assertEqual(json.loads(encoded), expected)
            self.assertEqual(encoded, (json.dumps(expected, ensure_ascii=False, separators=(',', ':')) + '\n').encode())

    def test_validation_failure_preserves_all_previous_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'timetable').mkdir()
            (root / 'routes').mkdir()
            full = root / 'timetable' / f'{DATE}.json'
            route = root / 'routes' / f'{DATE}.json'
            existing = root / 'timetable' / f'{DATE}-station-1020.json'
            for path in (full, route, existing): path.write_text('previous')
            for error in ('route', 'station'):
                with self.subTest(error=error):
                    bad = copy.deepcopy(self.data)
                    if error == 'route': bad['total_trains'] = 0
                    else: bad['stations']['1020']['Name'] = ''
                    with self.assertRaises(ValueError):
                        daily.write_daily(bad, DATE, root / 'timetable', root / 'routes')
                    self.assertEqual([p.read_text() for p in (full, route, existing)], ['previous'] * 3)

    def test_invalid_date_does_not_authenticate_or_fetch(self):
        for value in ('2026-02-30', '../bad', '2026-1-01'):
            with mock.patch.object(daily, 'authenticate') as auth, self.assertRaises(ValueError):
                daily.run(value, publish=False)
            auth.assert_not_called()

    def test_station_write_failure_preserves_routes_and_skips_git(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            table = root / 'timetable'
            table.mkdir()
            (table / f'{DATE}.json').write_bytes(FIXTURE.read_bytes())
            (root / 'routes').mkdir()
            route = root / 'routes' / f'{DATE}.json'
            route.write_text('previous routes')
            original = station.atomic_write
            def fail_station(path, text):
                if path.name == f'{DATE}-station-1020.json': raise OSError('mock storage failure')
                return original(path, text)
            with mock.patch.object(daily, 'git_ready', return_value=root), \
                 mock.patch.object(station, 'atomic_write', side_effect=fail_station), \
                 mock.patch.object(daily, 'publish_to_git') as publish, self.assertRaises(OSError):
                daily.run(DATE, table, offline=True)
            publish.assert_not_called()
            self.assertEqual(route.read_text(), 'previous routes')

    def test_normal_fetch_calls_exactly_the_existing_twelve_station_requests(self):
        def response(request, timeout):
            sid = request.full_url.split('/Station/')[1].split('/')[0]
            self.assertEqual(timeout, 15)
            return io.BytesIO(json.dumps(self.data['stations'][sid]['Trains']).encode())
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()), \
             mock.patch.object(daily, 'authenticate') as auth, \
             mock.patch('urllib.request.urlopen', side_effect=response) as request, \
             mock.patch.object(daily.time, 'sleep') as sleep:
            daily.run(DATE, Path(tmp) / 'timetable', publish=False)
            auth.assert_called_once()
            self.assertEqual(request.call_count, 12)
            self.assertEqual(sleep.call_count, 11)
            self.assertEqual(json.loads((Path(tmp) / 'routes' / f'{DATE}.json').read_text()), daily.build_routes(self.data, DATE))


class GitPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / 'repo'
        self.repo.mkdir()
        self.remote = Path(self.tmp.name) / 'remote.git'
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Offline test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.table = self.repo / 'timetable'
        self.table.mkdir()
        (self.table / f'{DATE}.json').write_bytes(FIXTURE.read_bytes())
        (self.table / '2026-11-09-station-1020.json').write_text('old')
        (self.repo / 'unrelated.txt').write_text('baseline')
        self.git('add', '.')
        self.git('commit', '-m', 'baseline')
        subprocess.run(['git', 'init', '--bare', str(self.remote)], check=True, capture_output=True)
        self.git('remote', 'add', 'origin', str(self.remote))
        self.root_patch = mock.patch.object(daily, 'ROOT', self.repo)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def test_local_commit_push_retry_noop_and_unrelated_file_protection(self):
        (self.repo / 'unrelated.txt').write_text('user work')
        original_git = daily._git
        def reject_push(repo, *args):
            if args[0] == 'push': raise subprocess.CalledProcessError(1, ['git', *args], stderr='mock rejection')
            return original_git(repo, *args)
        with contextlib.redirect_stdout(io.StringIO()), mock.patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')):
            with mock.patch.object(daily, '_git', side_effect=reject_push), self.assertRaises(subprocess.CalledProcessError):
                daily.run(DATE, self.table, offline=True)
            committed = self.git('rev-parse', 'HEAD')
            self.assertIn(f'routes/{DATE}.json', self.git('show', '--pretty=', '--name-only', 'HEAD'))
            self.assertNotIn('unrelated.txt', self.git('show', '--pretty=', '--name-only', 'HEAD'))
            self.assertIn('2026-11-09-station-1020.json', self.git('show', '--pretty=', '--name-only', 'HEAD'))
            daily.run(DATE, self.table, offline=True)
            self.assertEqual(self.git('rev-parse', 'HEAD'), committed)
            self.assertEqual(self.git('rev-parse', 'origin/main'), committed)
            # Only a local bare remote is used, never GitHub or TDX.
            remote_data = subprocess.run(['git', '--git-dir', str(self.remote), 'show', f'main:routes/{DATE}.json'], check=True, capture_output=True).stdout
            self.assertEqual(remote_data, (self.repo / 'routes' / f'{DATE}.json').read_bytes())
            daily.run(DATE, self.table, offline=True)
            self.assertEqual(self.git('rev-parse', 'HEAD'), committed)
            self.assertEqual((self.repo / 'unrelated.txt').read_text(), 'user work')

    def test_unrelated_staged_changes_stop_before_fetch(self):
        (self.repo / 'unrelated.txt').write_text('staged work')
        self.git('add', 'unrelated.txt')
        with mock.patch.object(daily, 'authenticate') as auth, self.assertRaises(RuntimeError):
            daily.run(DATE, self.table)
        auth.assert_not_called()
        self.assertFalse((self.repo / 'routes').exists())


if __name__ == '__main__':
    unittest.main()
