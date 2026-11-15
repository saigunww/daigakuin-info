"""Offline admissions aggregation checks using invented student identities."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import honor_statistics as h


class Response:
    def __init__(self, value):
        self.value = value

    def execute(self, **kwargs):
        return copy.deepcopy(self.value)


class FakeSheets:
    def __init__(self, sources):
        self.sources = sources
        self.calls = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId, **kwargs):
        source = self.sources[spreadsheetId]
        return Response({'sheets': [{'properties': {'sheetId': source['sheet_id'], 'title': '合格',
                                                    'gridProperties': {'rowCount': 100}}}]})

    def batchGet(self, spreadsheetId, ranges, **kwargs):
        self.calls.extend(ranges)
        source = self.sources[spreadsheetId]
        return Response({'valueRanges': [
            {'values': [source['headers']['identity']]}, {'values': [source['headers']['offer']]},
            {'values': [r[0] for r in source['rows']]}, {'values': [r[1] for r in source['rows']]},
        ]})


def offer(student='S001', surname='甲', given='一', year='2027', school='東京大学大学院',
          department='理学系研究科', major='化学専攻', status='合格'):
    return [[student, surname, given], [year, school, department, major, status]]


def poster(image='image-1', name='甲一', year='2027', school='東京大学',
           department='理学系研究科', major='化学専攻', subject='bio', anonymous=False):
    filename = f'合格榜_{name}同学_{school}{department}{major}.png' if anonymous else f'{name}-{school}{department}{major}.png'
    return {'id': image, 'source_path': f'{year}年度/大学院生物/{filename}', 'year': year,
            'subject': subject, 'name': name[:1] + '同学', 'university': school + department + major}


class HonorStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.root = root
        self.config = root / 'private' / 'honor_statistics.json'
        self.review = root / 'private' / 'review.json'
        self.config.parent.mkdir()
        self.patches = [patch.object(h, 'ROOT', root), patch.object(h, 'PRIVATE', self.config.parent),
                        patch.object(h, 'CONFIG', self.config), patch.object(h, 'REVIEW', self.review)]
        for p in self.patches:
            p.start()
        self.sources = {}

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def api(self, rows, extra=None):
        headers = {'identity': ['学籍番号', '姓', '名'],
                   'offer': ['入学年度', '大学院', '研究科', '専攻', '結果']}
        self.sources = {'bio-sheet': {'sheet_id': 1, 'headers': headers, 'rows': rows}}
        config = {'schema_version': 1, 'sources': [
            {'group': 'bio', 'spreadsheet_id': 'bio-sheet', 'sheet_id': 1, 'headers': headers}], 'poster_links': {}}
        if extra is not None:
            self.sources['chem-sheet'] = {'sheet_id': 2, 'headers': headers, 'rows': extra}
            config['sources'].append({'group': 'chem', 'spreadsheet_id': 'chem-sheet', 'sheet_id': 2, 'headers': headers})
        self.config.write_text(json.dumps(config))
        return FakeSheets(self.sources)

    def test_duplicate_source_rows_and_poster_count_once(self):
        result = h.build_statistics(self.api([offer(), offer()]), [poster()])
        self.assertEqual(result['years'][0]['total'], 1)
        self.assertEqual(result['pending_review_total'], 0)

    def test_cross_subject_sources_share_offer_and_memberships(self):
        api = self.api([offer()], extra=[offer()])
        result = h.build_statistics(api, [poster(), poster(subject='chem')])
        year = result['years'][0]
        self.assertEqual(year['total'], 1)
        self.assertEqual(year['by_subject']['bio']['total'], 1)
        self.assertEqual(year['by_subject']['chem']['total'], 1)
        self.assertTrue(h.validate_statistics(result))

    def test_multiple_universities_and_graduate_schools_count_separately(self):
        rows = [offer(), offer(school='京都大学大学院'), offer(department='工学系研究科')]
        result = h.build_statistics(self.api(rows), [poster(), poster(image='second', school='京都大学'),
                                                    poster(image='third', department='工学系研究科')])
        self.assertEqual(result['years'][0]['total'], 3)
        self.assertEqual(result['years'][0]['universities'], [{'name': '東京大学', 'count': 2}, {'name': '京都大学', 'count': 1}])

    def test_multiple_majors_are_distinct_offers(self):
        rows = [offer(), offer(major='生物科学専攻')]
        result = h.build_statistics(self.api(rows), [poster(), poster(image='second', major='生物科学専攻')])
        self.assertEqual(result['years'][0]['total'], 2)

    def test_same_surname_people_are_never_merged(self):
        rows = [offer(), offer(student='S002', given='二')]
        result = h.build_statistics(self.api(rows), [poster(name='甲', anonymous=True)])
        self.assertEqual(result['years'][0]['total'], 2)
        self.assertEqual(result['pending_review_total'], 1)

    def test_surname_plus_unique_program_proves_match(self):
        rows = [offer(), offer(student='S002', given='二', department='工学系研究科')]
        result = h.build_statistics(self.api(rows), [poster(name='甲', anonymous=True)])
        self.assertEqual(result['years'][0]['total'], 2)
        self.assertEqual(result['pending_review_total'], 0)

    def test_same_full_name_different_student_ids_remains_pending(self):
        rows = [offer(), offer(student='S002')]
        result = h.build_statistics(self.api(rows), [poster()])
        self.assertEqual(result['years'][0]['total'], 2)
        self.assertEqual(result['pending_review_total'], 1)

    def test_changed_name_or_program_is_pending_not_extra_offer(self):
        for p in [poster(name='甲二'), poster(major='生化学専攻')]:
            with self.subTest(p=p):
                result = h.build_statistics(self.api([offer()]), [p])
                self.assertEqual(result['years'][0]['total'], 1)
                self.assertEqual(result['years'][0]['pending_review'], 1)

    def test_school_rename_does_not_merge_tokyo_university_of_technology(self):
        rows = [offer(school='東京科学大学大学院'), offer(student='S002', surname='乙', school='東京工科大学大学院')]
        result = h.build_statistics(self.api(rows), [poster(school='東京工業大学')])
        self.assertEqual(result['years'][0]['total'], 2)
        self.assertEqual({r['name'] for r in result['years'][0]['universities']}, {'東京科学大学', '東京工科大学'})
        self.assertEqual(h.university_name('東京医科歯科大学大学院'), '東京科学大学')

    def test_nonaccepted_rows_are_not_counted(self):
        rows = [offer(), offer(student='S002', surname='乙', status='不合格'),
                offer(student='S003', surname='丙', status='結果待ち')]
        result = h.build_statistics(self.api(rows), [])
        self.assertEqual(result['years'][0]['total'], 1)

    def test_nonaccepted_rows_do_not_require_an_identity(self):
        result = h.build_statistics(self.api([offer(), offer(student='', surname='', given='', status='不合格')]), [])
        self.assertEqual(result['years'][0]['total'], 1)

    def test_prefilled_year_only_template_is_not_an_admission_record(self):
        # Real source shape: B-D are empty, I contains a default entrance year,
        # and J-M (school, department, major, result) are empty.
        result = h.build_statistics(self.api([offer(), [[], ['2027']]]), [])
        self.assertEqual(result['years'][0]['total'], 1)
        self.assertEqual(result['pending_review_total'], 0)

    def test_accepted_year_only_row_still_fails_missing_identity(self):
        with self.assertRaises(h.StatisticsError):
            h.build_statistics(self.api([offer(), [[], ['2027', '', '', '', '合格']]]), [])

    def test_unknown_status_is_rejected_even_without_identity(self):
        with self.assertRaises(h.StatisticsError):
            h.build_statistics(self.api([offer(), [[], ['2027', '', '', '', 'unknown status']]]), [])

    def test_missing_accepted_fields_fail_closed(self):
        for patch in [{'student': ''}, {'surname': ''}, {'given': ''}, {'year': ''},
                      {'school': ''}, {'department': ''}, {'major': ''}]:
            with self.subTest(patch=patch):
                with self.assertRaises(h.StatisticsError):
                    h.build_statistics(self.api([offer(**patch)]), [])

    def test_source_year_is_never_inferred_from_dates(self):
        with self.assertRaises(h.StatisticsError):
            h.build_statistics(self.api([offer(year='2026-11-16')]), [poster()])
        result = h.build_statistics(self.api([offer(year='2027年度')]), [])
        self.assertEqual(result['years'][0]['year'], '2027')

    def test_unrecognized_result_status_fails_closed(self):
        with self.assertRaises(h.StatisticsError):
            h.build_statistics(self.api([offer(), offer(student='S002', status='unknown changed status')]), [])

    def test_schema_changes_fail_closed(self):
        api = self.api([offer()])
        self.sources['bio-sheet']['headers'] = {'identity': ['changed', '姓', '名'], 'offer': ['入学年度', '大学院', '研究科', '専攻', '結果']}
        with self.assertRaises(h.StatisticsError):
            h.build_statistics(api, [])

    def test_only_required_columns_are_read(self):
        api = self.api([offer()])
        h.build_statistics(api, [])
        self.assertEqual(api.calls, ["'合格'!B2:D2", "'合格'!I2:M2", "'合格'!B3:D100", "'合格'!I3:M100"])

    def test_api_failure_has_no_private_details(self):
        api = self.api([offer()])
        api.get = lambda **kw: (_ for _ in ()).throw(RuntimeError('SECRET STUDENT 09012345678'))
        with self.assertRaises(h.StatisticsError) as error:
            h.build_statistics(api, [])
        self.assertNotIn('SECRET', str(error.exception))

    def test_duplicate_byte_paths_use_full_identity_and_all_subjects(self):
        first = poster()
        second = poster(name='甲', anonymous=True, subject='chem')
        result = h.build_statistics(self.api([offer()]), [first, second])
        self.assertEqual(result['years'][0]['total'], 1)
        self.assertEqual(result['years'][0]['by_subject']['chem']['total'], 1)

    def test_confirmed_poster_only_offer_counts(self):
        result = h.build_statistics(self.api([offer()]), [poster(name='乙二', school='京都大学')])
        self.assertEqual(result['years'][0]['total'], 2)

    def test_poster_only_duplicate_full_identity_counts_once(self):
        posters = [poster(image='new1', name='乙二', school='京都大学'),
                   poster(image='new2', name='乙二', school='京都大学')]
        result = h.build_statistics(self.api([offer()]), posters)
        self.assertEqual(result['years'][0]['total'], 2)

    def test_poster_only_same_surname_duplicates_are_all_pending(self):
        posters = [poster(image='new1', name='乙', school='京都大学', anonymous=True),
                   poster(image='new2', name='乙', school='京都大学', anonymous=True)]
        result = h.build_statistics(self.api([offer()]), posters)
        self.assertEqual(result['years'][0]['total'], 1)
        self.assertEqual(result['pending_review_total'], 2)

    def test_poster_without_year_is_unassigned(self):
        p = poster(); p['year'] = '未分年度'
        result = h.build_statistics(self.api([offer()]), [p])
        self.assertEqual(result['unassigned_total'], 1)
        self.assertEqual(result['years'][0]['total'], 1)

    def test_reviewed_links_require_a_present_source_offer(self):
        api = self.api([offer()])
        config = json.loads(self.config.read_text())
        config['poster_links'] = {'image-1': {'student_id': 'missing', 'department': '理学系研究科',
                                              'major': '化学専攻', 'basis': 'Invented reviewed correspondence'}}
        self.config.write_text(json.dumps(config))
        result = h.build_statistics(api, [poster(name='甲二')])
        self.assertEqual(result['pending_review_total'], 1)
        self.assertEqual(result['years'][0]['total'], 1)

    def test_private_review_file_has_protected_permissions(self):
        h.build_statistics(self.api([offer()]), [poster(name='甲二')])
        self.assertEqual(self.review.stat().st_mode & 0o777, 0o600)

    def test_public_output_contains_no_source_or_identity_details(self):
        result = h.build_statistics(self.api([offer()]), [poster()])
        serialized = json.dumps(result, ensure_ascii=False)
        for private in ('S001', '甲一', 'source_row', 'source_path', 'bio-sheet', 'student_id', 'department', 'major'):
            self.assertNotIn(private, serialized)

    def test_public_schema_rejects_unknown_fields_at_all_levels(self):
        original = h.build_statistics(self.api([offer()]), [])
        for level in ('root', 'year', 'subject', 'school'):
            result = copy.deepcopy(original)
            target = {'root': result, 'year': result['years'][0],
                      'subject': result['years'][0]['by_subject']['bio'],
                      'school': result['years'][0]['universities'][0]}[level]
            target['student_id'] = 'PRIVATE'
            with self.subTest(level=level), self.assertRaises(h.StatisticsError):
                h.validate_statistics(result)

    def test_public_totals_must_reconcile(self):
        original = h.build_statistics(self.api([offer()]), [])
        for mutation in ('year', 'subject', 'excess', 'missing'):
            result = copy.deepcopy(original)
            y = result['years'][0]
            if mutation == 'year': y['total'] += 1
            elif mutation == 'subject': y['by_subject']['bio']['total'] += 1
            elif mutation == 'excess':
                y['by_subject']['chem'] = {'total': 2, 'universities': [{'name': '東京大学', 'count': 2}]}
            else: y['by_subject']['bio'] = {'total': 0, 'universities': []}
            with self.subTest(mutation=mutation), self.assertRaises(h.StatisticsError):
                h.validate_statistics(result)

    def test_school_fields_reject_contacts_private_notes_and_markup(self):
        for value in ('東京大学 alice@example.com', '東京大学\nPRIVATE', '東京大学:09012345678',
                      '<東京大学>', '東京大学09012345678', '東京大学/PRIVATE', '秘密' * 100 + '大学'):
            with self.subTest(value=value), self.assertRaises(h.StatisticsError):
                h.build_statistics(self.api([offer(school=value)]), [])
        result = h.build_statistics(self.api([offer()]), [])
        result['years'][0]['universities'][0]['name'] = '東京大学 private@contact'
        with self.assertRaises(h.StatisticsError):
            h.validate_statistics(result)

    def test_honors_refresh_failure_preserves_previous_public_bytes(self):
        try:
            import update_google as updater
            from PIL import Image
        except ImportError:
            self.skipTest('Google/Pillow environment required for updater integration')
        site = self.root / 'site'
        site.mkdir()
        previous = b'{"items": [{"id": "previous-complete-feed"}]}\n'
        feed = site / 'honors_data.json'
        feed.write_bytes(previous)
        posters = self.root / 'posters'
        image = posters / '2027年度' / '大学院生物' / '合格榜_甲同学_東京大学理学系研究科.png'
        image.parent.mkdir(parents=True)
        Image.new('RGB', (4, 4), color='#95bdc4').save(image)
        with patch.object(updater, 'ROOT', site), patch.object(updater, 'STATE', self.root / 'state'), \
                patch.object(updater, 'POSTERS', posters), patch.object(updater, 'client', return_value=object()), \
                patch.object(updater, 'drive_tree', return_value=[]), \
                patch.object(h, 'build_statistics', side_effect=h.StatisticsError('Second source unavailable')), \
                patch.object(updater, 'dataset', side_effect=lambda *args: feed.write_bytes(b'CHANGED')) as writer:
            with self.assertRaises(h.StatisticsError):
                updater.update_honors()
            writer.assert_not_called()
        self.assertEqual(feed.read_bytes(), previous)


if __name__ == '__main__':
    unittest.main()
