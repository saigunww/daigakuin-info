"""Offline contract tests for authenticated, complete Rooms schedule imports."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

import update_rooms as rooms

CONFIG = {'subjects': {'233': {'name':'院生物学','code':'Y17','group':'bio'},
                       '234': {'name':'院化学','code':'Y18','group':'chem'}},
          'public_course_suffixes': {'bio':['必修课程'],'chem':['必修课程']}}
EXPECTED = {'q[subject_subject_category_id_in][]':['2'], 'q[subject_id_in][]':['233','234'],
            'q[start_time_gteq]':['2026-10-01 00:00'], 'q[finish_time_lteq]':['2027-03-31 23:59']}


def row(identifier, title='26年10月期生物学 必修课程', tags=''):
    cells = [f'<a href="/lectures/{identifier}?locale=ja">詳細</a>', '編集用の名前', '院生物学',
             f'<a href="/klass_subjects/999">(TK26Y17XX9999) 院生物学[{title}]</a>',
             'STAFF_PRIVATE', '2026/11/28 18:00 - 21:00', 'MEETING_PRIVATE',
             'STUDENT_PRIVATE', 'ATTENDANCE_PRIVATE', tags, 'REMARK_PRIVATE', 'LOG_PRIVATE', '承認']
    return '<tr>'+''.join('<td>'+value+'</td>' for value in cells)+'</tr>'


def page(ids, total=None, page_number=1, next_page=False, expected=None, **kwargs):
    expected = expected or EXPECTED
    fields = ''
    for name, values in expected.items():
        if 'time_' in name:
            value=values[0].replace('-', '/')
            fields+=f'<input name="{name}" value="{value}">'
        else:
            fields+=f'<select name="{name}" multiple>'+''.join(f'<option value="{v}" selected>{v}</option>' for v in values)+'</select>'
    rows=''.join(row(i, **kwargs) for i in ids)
    count=f'<p>{(page_number-1)*50+1} - {(page_number-1)*50+len(ids)} / {total if total is not None else len(ids)} 件</p>' if ids else '<p>授業が見つかりませんでした</p>'
    pagination=''
    if next_page:
        from urllib.parse import urlencode
        query=[('page',str(page_number+1))]+[(k,v) for k,values in expected.items() for v in values]
        pagination='<ul class="pagination"><a rel="next" href="/lectures?'+urlencode(query)+'">次</a></ul>'
    return '<a href="/users/sign_out">Logout</a><form>'+fields+'</form>'+count+'<table><thead><tr>'+''.join('<th>'+h+'</th>' for h in rooms.HEADERS)+'</tr></thead><tbody>'+rows+'</tbody></table>'+pagination


class RoomsTests(unittest.TestCase):
    def test_japan_display_coverage(self):
        self.assertEqual(rooms.coverage(date(2027,1,1)),(date(2026,10,1),date(2027,10,1)))
        self.assertEqual(rooms.coverage(date(2027,4,1)),(date(2027,1,1),date(2027,10,1)))
        self.assertEqual(rooms.coverage(date(2027,10,1)),(date(2027,10,1),date(2028,4,1)))

    def test_public_projection_and_private_class_exclusion(self):
        html=page([1],tags='時間変更中')
        rows,total,nxt=rooms.parse_page(html,EXPECTED,1,CONFIG)
        self.assertEqual((total,nxt),(1,None))
        self.assertEqual(rows[0]['status'],'rescheduling')
        public,cache=rooms.project(rows,set(),[],{},date(2026,10,1),date(2027,4,1))
        self.assertEqual(public[0]['course'],'26年10月期生物学 必修课程')
        self.assertNotIn('PRIVATE',json.dumps(public))
        self.assertNotIn('id',public[0])
        rows,_,_=rooms.parse_page(page([1],title='学生甲签约班'),EXPECTED,1,CONFIG)
        self.assertEqual(rooms.project(rows,set(),[],{},date(2026,10,1),date(2027,4,1))[0],[])

    def test_complete_pagination_and_cancellation(self):
        with patch.object(rooms,'request_page',side_effect=[page(list(range(1,51)),53,next_page=True),page([51,52,53],53,2)]):
            rows=rooms.fetch_lectures(None,date(2026,10,1),date(2027,4,1),CONFIG)
        self.assertEqual(len(rows),53)
        public,_=rooms.project(rows,{'53'},[],{},date(2026,10,1),date(2027,4,1))
        self.assertEqual(len(public),52)

    def test_page_two_failure_or_missing_page_rejected(self):
        for second in [RuntimeError('offline'),page([50,51,52],53,2),page([51,52,53],54,2)]:
            with self.subTest(second=type(second).__name__):
                with patch.object(rooms,'request_page',side_effect=[page(list(range(1,51)),53,next_page=True),second]):
                    with self.assertRaises(RuntimeError):rooms.fetch_lectures(None,date(2026,10,1),date(2027,4,1),CONFIG)
        with self.assertRaises(RuntimeError):
            with patch.object(rooms,'request_page',return_value=page([1],53)):
                rooms.fetch_lectures(None,date(2026,10,1),date(2027,4,1),CONFIG)

    def test_login_schema_and_filter_failure(self):
        variants=[page([1]).replace('/users/sign_out','/'),
                  page([1]).replace('名称','NEW_HEADER'),
                  page([1]).replace('value="233" selected','value="233"'),
                  page([1]).replace('2026/10/01 00:00','2026/11/01 00:00')]
        for html in variants:
            with self.assertRaises(RuntimeError):rooms.parse_page(html,EXPECTED,1,CONFIG)

    def test_verified_empty_cancellation_result(self):
        expected={**EXPECTED,'q[canceled_status_in][]':list(rooms.CANCELLED)}
        self.assertEqual(rooms.parse_page(page([],expected=expected),expected,1,CONFIG),([],0,None))
        with self.assertRaises(RuntimeError):rooms.parse_page(page([]).replace('授業が見つかりませんでした',''),EXPECTED,1,CONFIG)

    def test_unique_metadata_and_cache_identity(self):
        rows,_,_=rooms.parse_page(page([1]),EXPECTED,1,CONFIG)
        baseline=[{**rows[0],'session':'4','topic':'Verified topic','format':'対面'}]
        public,cache=rooms.project(rows,set(),baseline,{},date(2026,10,1),date(2027,4,1))
        self.assertEqual(public[0]['session'],'4')
        moved=[{**rows[0],'date':'2026-11-29'}]
        public,_=rooms.project(moved,set(),baseline,cache,date(2026,10,1),date(2027,4,1))
        self.assertEqual(public[0]['topic'],'Verified topic')
        public,_=rooms.project(moved,set(),baseline,{**cache,'1':{**cache['1'],'curriculum_id':'another'}},date(2026,10,1),date(2027,4,1))
        self.assertEqual(public[0]['topic'],'')
        public,_=rooms.project(rows,set(),baseline*2,{},date(2026,10,1),date(2027,4,1))
        self.assertEqual(public[0]['topic'],'')
        self.assertEqual(rooms.project([],set(),baseline,cache,date(2026,10,1),date(2027,4,1))[0],[])

    def test_import_failure_retains_last_success_and_all_rows(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir()
            (root/'config/schedule_source.json').write_text(json.dumps(CONFIG))
            original={'source_type':'rooms_schedule','updated_at':'2026-11-26T12:00:00+09:00',
                'last_success_at':'2026-11-26T12:00:00+09:00','items':[{'course':'Complete previous feed'}]}
            (root/'schedule_data.json').write_text(json.dumps(original))
            with patch.object(rooms,'ROOT',root),patch.object(rooms,'STATE',root/'.sync-state'),patch.object(rooms,'session_client',side_effect=RuntimeError('Expired')):
                with self.assertRaises(RuntimeError):rooms.update_rooms(date(2026,11,27))
            saved=json.loads((root/'schedule_data.json').read_text())
            self.assertEqual(saved['items'],original['items'])
            self.assertEqual(saved['last_success_at'],original['last_success_at'])
            self.assertEqual(saved['updated_at'],original['updated_at'])
            self.assertEqual(saved['sync_status'],'error')


if __name__=='__main__':unittest.main()
