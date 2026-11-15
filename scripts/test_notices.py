"""Exercise content change detection, daily grouping and safe failure."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import copy
import json
import unittest

import update_notices as notices
import sync_data
from common import ROOT

TODAY = date(2026, 11, 15)


class NoticeTests(unittest.TestCase):
    def setUp(self):
        self.sources = {kind: json.loads((ROOT / file).read_text())
                        for kind, (file, _) in notices.SOURCES.items()}

    def baseline(self, today=TODAY):
        return notices.build_notices({}, self.sources, today)

    def test_initial_information_and_exact_repeat(self):
        original = self.baseline()
        self.assertEqual(len(original['items']), 7)
        self.assertTrue(all(row['tag'] == 'info' for row in original['items']))
        self.assertEqual(notices.build_notices(original, self.sources, TODAY), original)
        self.assertEqual(notices.build_notices(original, self.sources, date(2026, 11, 16)), original)

    def test_check_times_status_and_row_order_do_not_create_news(self):
        original = self.baseline()
        for kind, source in self.sources.items():
            source.update(updated_at='2026-11-15T15:17:00+09:00', checked_at='changed')
            if kind != 'course_flow':
                source['items'].reverse()
        self.sources['students']['schools'].reverse()
        for row in self.sources['admissions']['items']:
            row.update(checked_on='2026-11-15', attempted_on='2026-11-15', status='unavailable',
                       changed_on='2026-11-15', fingerprint='irrelevant page-wide change')
            row['notices'].reverse()
            row['application_windows'].reverse()
            row['program_ids'].reverse()
        self.assertEqual(notices.build_notices(original, self.sources, TODAY), original)

    def test_real_change_coalesces_same_day_and_preserves_previous_dates(self):
        first = self.baseline()
        self.sources['research']['items'].append({**self.sources['research']['items'][0], 'id': 'test:1'})
        changed = notices.build_notices(first, self.sources, TODAY)
        self.assertEqual(len(changed['items']), 7)
        current = next(r for r in changed['items'] if r['kind'] == 'research')
        self.assertEqual(current['tag'], 'update')
        self.assertIn(str(len(self.sources['research']['items'])), current['body']['zh'])
        next_date = date(2026, 11, 16)
        self.sources['research']['items'].append({**self.sources['research']['items'][0], 'id': 'test:2'})
        later = notices.build_notices(changed, self.sources, next_date)
        self.assertEqual(len(later['items']), 8)
        self.assertEqual(next(r for r in later['items'] if r['id'] == current['id']), current)
        self.assertEqual(len({r['id'] for r in later['items']}), 8)

    def test_same_total_with_different_content_still_announces(self):
        first = self.baseline()
        self.sources['schedule']['items'][0]['topic'] += '（更新）'
        result = notices.build_notices(first, self.sources, TODAY)
        changed = [kind for kind in notices.SOURCES if result['source_fingerprints'][kind] != first['source_fingerprints'][kind]]
        self.assertEqual(changed, ['schedule'])
        self.assertEqual(next(r for r in result['items'] if r['kind'] == 'schedule')['tag'], 'update')

    def test_january_april_october_term_transitions(self):
        for previous, current, expected in (
            (date(2026, 12, 31), date(2027, 1, 1), '2026年10月—2027年3月 ＋ 2027年1月—2027年9月'),
            (date(2027, 3, 31), date(2027, 4, 1), '2027年1月—2027年9月'),
            (date(2027, 9, 30), date(2027, 10, 1), '2027年10月—2028年3月')):
            with self.subTest(current=current):
                initial = self.baseline(previous)
                changed = notices.build_notices(initial, self.sources, current)
                self.assertNotEqual(initial['source_fingerprints']['schedule'], changed['source_fingerprints']['schedule'])
                row = next(r for r in changed['items'] if r['kind'] == 'schedule' and r['date'] == current.isoformat())
                self.assertIn(expected, row['body']['zh'])

    def test_public_announcements_reject_unexpected_fields_or_targets(self):
        for key, value in (('target', 'https://invalid.example/'), ('kind', 'private'), ('date', '2026-02-30')):
            data = self.baseline()
            data['items'][0][key] = value
            with self.assertRaises(ValueError):
                notices.validate_notices(data)
        data = self.baseline()
        data['items'][0]['student_id'] = 'must never be published'
        with self.assertRaises(ValueError):
            notices.validate_notices(data)

    def test_entrance_year_changes_even_before_source_snapshot_catches_up(self):
        self.sources['course_flow']['entry_year'] = 2027
        previous = self.baseline(date(2027, 3, 31))
        changed = notices.build_notices(previous, self.sources, date(2027, 4, 1))
        row = next(r for r in changed['items'] if r['kind'] == 'course_flow' and r['date'] == '2027-04-01')
        self.assertIn('2028', row['body']['zh'])

    def test_invalid_source_retains_file_and_unchanged_run_preserves_timestamp(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for kind, (file, _) in notices.SOURCES.items():
                (root / file).write_text(json.dumps(self.sources[kind]))
            import common
            with patch.object(notices, 'ROOT', root), patch.object(common, 'ROOT', root):
                notices.update_notices(TODAY)
                saved = (root / 'notices_data.json').read_bytes()
                notices.update_notices(TODAY)
                self.assertEqual(saved, (root / 'notices_data.json').read_bytes())
                (root / 'research_data.json').write_text('{"items":[]}')
                with self.assertRaises(ValueError):
                    notices.update_notices(TODAY)
                self.assertEqual(saved, (root / 'notices_data.json').read_bytes())

    def test_sync_generates_announcements_after_source_has_settled(self):
        calls = []
        def source():
            calls.append('source')
            return {'items': [1]}
        def announce():
            self.assertEqual(calls, ['source'])
            calls.append('notices')
            return {'items': [1]}
        with patch.object(sync_data, 'update_courses', side_effect=source), \
             patch.object(sync_data, 'update_notices', side_effect=announce), patch.object(sync_data, 'save'):
            result = sync_data.run(['schedule'])
        self.assertEqual(calls, ['source', 'notices'])
        self.assertTrue(result['notices']['ok'])


if __name__ == '__main__':
    unittest.main()
