import sys
import unittest
from datetime import date
from admission_dates import extract_ranges
from update_google import parse_courses
from update_research import candidate, normalize_doi
from update_admissions import public_program, active_windows
from common import official_url

class SyncTests(unittest.TestCase):
    def test_explicit_japanese_year(self):
        rows=extract_ranges('<p>出願期間 令和9年3月1日～3月15日</p>')
        self.assertEqual([(r['s'],r['e']) for r in rows],[('2027-03-01','2027-03-15')])

    def test_never_infer_year_or_roll_over(self):
        for text in ('2027年度 出願期間 3月1日〜3月15日','出願期間 2027年12月20日〜1月10日','出願期間 2027年2月29日〜3月1日','出願期間未定 試験日 2027年3月1日〜3月2日'):
            self.assertEqual(extract_ranges('<p>'+text+'</p>'),[],text)

    def test_program_directory_excludes_legacy_material(self):
        source={'status':'ok','checked_on':'2026-11-12'}
        program={'id':1,'u':'東京大学','m':'医科学専攻','url':'https://www.u-tokyo.ac.jp/',
                 'refE':'2025-06-30','e':'2025-06-30','exReq':'old requirements','appDoc':'old documents'}
        self.assertEqual(public_program(program,source),{
            'id':1,'u':'東京大学','m':'医科学専攻','url':'https://www.u-tokyo.ac.jp/',
            'source_checked_on':'2026-11-12','source_status':'ok'})

    def test_deadline_today_is_still_displayed(self):
        rows=[{'e':'2026-11-11'},{'e':'2026-11-12'},{'e':'2026-11-13'}]
        self.assertEqual(active_windows(rows,date(2026,11,12)),rows[1:])

    def test_sheet_header_and_private_columns(self):
        rows=[['title'],['授業名','授業日','授業内容','担当先生','備考'],['生化学','2026/11/12','酵素','private teacher','private note'],['bad','2026/02/30','bad']]
        result=parse_courses(rows,'bio')
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['date'],'2026-11-12')
        self.assertNotIn('private',str(result))
        with self.assertRaises(ValueError):parse_courses([['changed header']], 'bio')

    def test_paper_date_type_and_doi(self):
        raw={'source':'MED','id':'123','title':'<i>Gene</i> study','doi':'https://doi.org/10.1234/ABC','firstPublicationDate':'2026-11-11','pubTypeList':{'pubType':['Journal Article']}}
        row=candidate(raw,'biology',date(2026,9,1),date(2026,11,12))
        self.assertEqual(row['id'],'doi:10.1234/abc')
        self.assertEqual(row['title'],'Gene study')
        for patch in ({'firstPublicationDate':'2027-01-01'},{'pubTypeList':{'pubType':['Review']}},{'source':'PPR'}):
            self.assertIsNone(candidate({**raw,**patch},'biology',date(2026,9,1),date(2026,11,12)))

    def test_official_domain_boundary(self):
        self.assertTrue(official_url('https://www.waseda.jp/fsci/'))
        for url in ('https://university.ac.jp.evil.example/','https://evilwaseda.jp/','file:///etc/passwd','https://user:pass@www.sci.kyoto-u.ac.jp/'):
            self.assertFalse(official_url(url))

if __name__=='__main__':unittest.main()
