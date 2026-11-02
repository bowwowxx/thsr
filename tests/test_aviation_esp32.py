import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_aviation_esp32 import convert, event_time, paginate, encode, PAGE_BYTES, PAGE_RECORDS
from split_aviation_daily import WEEKDAYS


def flight(**kwargs):
    row=dict(ScheduleStartDate='2026-11-02',ScheduleEndDate='2026-11-03',
             DepartureAirportID='MNL',ArrivalAirportID='TPE',DepartureTime='23:35',
             ArrivalTime='02:00+1',AirlineID='5J',FlightNumber='5J310',Terminal='1')
    row.update(dict.fromkeys(WEEKDAYS,True));row.update(kwargs)
    return row


class DailyPages(unittest.TestCase):
    def test_time_offsets(self):
        self.assertEqual(event_time('2026-12-31','02:00+1'),('2027-01-01','02:00'))
        self.assertEqual(event_time('2026-11-03','01:00-1'),('2026-11-02','01:00'))
        self.assertEqual(event_time('2026-11-03','01:00+2'),('2026-11-05','01:00'))
        for value in ('24:00','25:30','02:60','bad'):
            with self.assertRaises(ValueError): event_time('2026-11-03',value)

    def test_arrival_day_and_weekdays(self):
        r=flight(Tuesday=False)
        groups,duplicates,unknown=convert([r,r],{})
        self.assertEqual(duplicates,1)
        self.assertEqual(groups[('2026-11-02','arrivals')],[])
        arrivals=groups[('2026-11-03','arrivals')]
        self.assertEqual(len(arrivals),1)
        self.assertEqual(arrivals[0]['service_date'],'2026-11-02')
        self.assertEqual(arrivals[0]['time'],'02:00')
        self.assertEqual(arrivals[0]['name_zh'],'MNL')
        self.assertEqual(groups[('2026-11-03','departures')],[])
        self.assertNotIn(('2026-11-04','arrivals'),groups)

    def test_departure_offset_and_direction(self):
        r=flight(DepartureAirportID='TPE',ArrivalAirportID='NRT',DepartureTime='00:30+1')
        groups,_,_=convert([r],{'NRT':{'zh':'東京','en':'Narita'}})
        item=groups[('2026-11-04','departures')][0]
        self.assertEqual(item['airport'],'NRT')
        self.assertEqual(item['name_zh'],'東京')
        self.assertFalse(any(items for (day,direction),items in groups.items() if direction=='arrivals'))

    def test_no_truncation_and_limits(self):
        item=dict(time='12:00',flight='CI100',airport='NRT',name_zh='東京'*100)
        items=[dict(item,flight=str(i)) for i in range(101)]
        pages=paginate('2026-11-03','departures',items)
        self.assertEqual([r for page in pages for r in page['items']],items)
        for page in pages:
            self.assertLessEqual(len(page['items']),PAGE_RECORDS)
            self.assertLessEqual(len(encode(page)),PAGE_BYTES)
        self.assertEqual(paginate('2026-11-03','departures',[]),[])


if __name__=='__main__': unittest.main()
