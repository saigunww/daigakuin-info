"""Contracts for stable, reviewed Excel session bindings and cache fallback."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import course_metadata as excel
import update_rooms as rooms
from common import save, load


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.row = {'id':'1', 'curriculum_id':'class1', 'course':'26年10月期生物学 必修课程',
                    'group':'bio', 'date':'2026-12-26', 'start_time':'18:00', 'end_time':'21:00'}
        self.source = {'course':'26年10月期生物学必修课程', 'group':'bio', 'session':'4',
                       'date':'2026-11-07', 'start_time':'14:00', 'end_time':'17:00',
                       'topic':'糖質、脂質の構造', 'format':'対面'}
        self.binding = {key:self.row[key] for key in ('course','group','curriculum_id')}
        self.binding.update(source_course=self.source['course'], source_session='4', basis='plan_estimate')

    def project(self, source=None, rows=None, cache=None, binding=None):
        return rooms.project(rows or [self.row], set(), source if source is not None else [self.source],
                             cache or {}, date(2026,10,1), date(2027,4,1),
                             {'1':self.binding if binding is None else binding})

    def test_moved_lesson_uses_reviewed_session_and_fresh_topic(self):
        public, cache = self.project()
        self.assertEqual((public[0]['date'], public[0]['start_time']), ('2026-12-26','18:00'))
        self.assertEqual((public[0]['session'], public[0]['topic']), ('4','糖質、脂質の構造'))
        self.assertEqual(public[0]['metadata_basis'], 'plan_estimate')
        fresh = {**self.source, 'topic':'Updated Excel content', 'date':'2027-01-01'}
        public, _ = self.project(source=[fresh], cache=cache)
        self.assertEqual(public[0]['topic'], 'Updated Excel content')
        self.assertNotIn('source_course', public[0])
        self.assertNotIn('id', public[0])

    def test_missing_duplicate_and_changed_identity_clear_old_fields(self):
        _, cache = self.project()
        variants = [([], self.binding), ([self.source,self.source], self.binding),
                    ([self.source], {**self.binding,'curriculum_id':'other'}),
                    ([self.source], {**self.binding,'group':'chem'}),
                    ([{**self.source,'course':'27年10月期生物学必修课程'}], self.binding)]
        for source, binding in variants:
            with self.subTest(source=len(source), binding=binding):
                public, updated = self.project(source=source, cache=cache, binding=binding)
                self.assertEqual(public[0]['session'], '')
                self.assertEqual(public[0]['topic'], '')
                self.assertNotIn('metadata_basis', public[0])
                self.assertNotIn('metadata_basis', updated['1'])

    def test_unreviewed_new_id_cannot_claim_existing_excel_session(self):
        # Recreating a lecture at an original date does not prove its session.
        new = {**self.row, **{k:self.source[k] for k in ('date','start_time','end_time')}, 'id':'2'}
        public, _ = self.project(rows=[self.row,new])
        self.assertEqual(sum(bool(r['session']) for r in public), 1)

    def test_read_failure_uses_complete_cache_not_partial_source(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            previous={'checked_at':'2026-11-26T12:00:00+09:00','items':[self.source]}
            save(root/'excel-metadata.json', previous)
            with patch.object(excel,'read_excel_metadata',side_effect=RuntimeError('PRIVATE_RESPONSE')):
                value,status=excel.load_excel_metadata(root, [])
            self.assertEqual((value,status), (previous,'cached'))
            self.assertEqual(load(root/'excel-last-error.json')['error'], 'RuntimeError')
            self.assertNotIn('PRIVATE_RESPONSE',(root/'excel-last-error.json').read_text())

    def test_only_explicit_source_merges_are_filled(self):
        columns={'course':[['Course'],[],[],['Separate']],
                 'session':[['1'],['2'],['3'],['4']],
                 'topic':[['A'],['B'],['C'],['D']],
                 'date':[['2026/10/01']]*4}
        merges=[{'startColumnIndex':2,'endColumnIndex':3,'startRowIndex':3,'endRowIndex':5}]
        rows=excel.public_columns(columns, {'course':2,'session':6,'topic':7,'date':4}, merges, 2,'bio','生物')
        self.assertEqual([r['source_row'] for r in rows],[4,5,7])
        self.assertEqual([r['session'] for r in rows],['1','2','4'])
        self.assertEqual(rows[1]['course'],'Course')


if __name__=='__main__':unittest.main()
