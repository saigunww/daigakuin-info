"""Check PDF fidelity, entry-year semantics, timezone boundaries and stable writes."""
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unicodedata
import unittest
from unittest.mock import patch

import common
from course_flow import (ROOT, entry_year_for_date, load_template, make_payload,
                         timing_text, update_course_flow, validate_payload)


class CourseFlowTests(unittest.TestCase):
    def test_2027_means_prior_summer_and_same_year_winter(self):
        data = make_payload(date(2026, 11, 13))
        self.assertEqual(data['entry_year'], 2027)
        expected = {
            'summer': ['2025年9月～2025年10月', '2025年10月下旬～2026年4月',
                       '2025年11月～2026年5月', '2026年6月', '2026年8月', '2026年9月'],
            'winter': ['2026年7月～2026年9月', '2026年9月下旬～2026年10月',
                       '2026年10月～2026年11月', '2026年11月', '2027年1月', '2027年2月']}
        for cycle in data['items']:
            actual = [timing_text(step['timing'], 2027)['ja'] for step in cycle['stages']]
            self.assertEqual(actual, expected[cycle['id']])

    def test_tokyo_boundary_leap_day_and_year_change(self):
        cases = [('2026-11-13T09:00:00+09:00', 2027),
                 ('2027-03-31T14:59:59+00:00', 2027),
                 ('2027-03-31T15:00:00+00:00', 2028),
                 ('2027-12-31T15:00:00+00:00', 2028),
                 ('2028-02-29T00:00:00+09:00', 2028),
                 ('2028-03-31T15:00:00+00:00', 2029)]
        for instant, expected in cases:
            with self.subTest(instant=instant):
                self.assertEqual(entry_year_for_date(datetime.fromisoformat(instant)), expected)
        with self.assertRaises(ValueError):
            entry_year_for_date(datetime(2027, 4, 1))

    def test_rollover_preserves_source_text_months_and_baseline(self):
        first = make_payload(date(2026, 11, 13))
        next_year = make_payload(date(2027, 4, 1))
        self.assertEqual(next_year['entry_year'], 2028)
        for key in ('items', 'source_documents', 'base_entry_year', 'rollover'):
            self.assertEqual(first[key], next_year[key], key)
        summer = next_year['items'][0]['stages']
        self.assertEqual(timing_text(summer[0]['timing'], 2028)['ja'], '2026年9月～2026年10月')
        self.assertEqual(timing_text(summer[4]['timing'], 2028)['ja'], '2027年8月')

    def test_unchanged_year_does_not_write_timestamp_or_file(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(common, 'ROOT', Path(folder)), \
                patch.object(common, 'now', side_effect=['2026-11-13T10:00:00+09:00',
                                                       '2027-04-01T00:00:00+09:00']) as clock:
            original = update_course_flow(date(2026, 11, 13))
            path = Path(folder) / 'course_flow_data.json'
            before = path.read_bytes(), path.stat().st_mtime_ns
            repeated = update_course_flow(date(2026, 12, 1))
            self.assertEqual(repeated, original)
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
            self.assertEqual(clock.call_count, 1)
            newer = update_course_flow(date(2027, 4, 1))
            self.assertEqual(newer['entry_year'], 2028)
            self.assertNotEqual(newer['updated_at'], original['updated_at'])

    def test_full_japanese_details_and_source_hashes_match_both_pdfs(self):
        template = load_template()
        self.assertEqual([len(step['details']) for step in template['steps']], [4, 2, 2, 2, 2, 2])
        normalize = lambda text: re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))
        for source in template['source_documents'].values():
            path = ROOT.parent / '课程介绍' / source['file']
            if not path.exists():
                self.skipTest('Source PDFs are stored only on the production server')
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source['sha256'])
            # Raw content order preserves each diagram text box; layout mode
            # interleaves adjacent columns before a wrapped sentence completes.
            pages = subprocess.run(['pdftotext', '-raw', str(path), '-'],
                                   check=True, capture_output=True, text=True).stdout.split('\f')
            for page_number in (8, 9):
                text = normalize(pages[page_number - 1])
                for step in template['steps']:
                    for detail in step['details']:
                        self.assertIn(normalize(detail['ja']), text, (source['file'], page_number, detail['ja']))

    def test_feed_validation_and_publish_scope(self):
        from sync_and_publish import generated
        data = make_payload(date(2026, 11, 13))
        validate_payload(data)
        self.assertTrue(generated('course_flow_data.json'))
        self.assertFalse(generated('index.html'))
        self.assertFalse(generated('config/course_flow.json'))
        broken = deepcopy(data)
        broken['items'][0]['stages'].pop()
        with self.assertRaises(AssertionError):
            validate_payload(broken)


if __name__ == '__main__':
    unittest.main()
