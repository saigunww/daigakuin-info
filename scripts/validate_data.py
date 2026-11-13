"""Validate public data before a commit can be published."""
from datetime import date
from pathlib import Path
from common import ROOT, load, official_url
from update_admissions import PROGRAM_FIELDS
from update_students import validate_student_summary
from course_flow import validate_payload

def validate():
    feeds = {name: load(ROOT / name) for name in ('honors_data.json','schedule_data.json','research_data.json','applications.json','admissions_updates.json','students_data.json','course_flow_data.json')}
    for name, data in feeds.items():
        if not isinstance(data, dict) or not data.get('items') or not data.get('updated_at'):
            raise ValueError('Empty or invalid public feed: '+name)
    validate_student_summary(feeds['students_data.json'])
    validate_payload(feeds['course_flow_data.json'])
    honors=feeds['honors_data.json']['items']
    assert len({r['id'] for r in honors})==len(honors)
    for row in honors:
        assert row['subject'] in ('bio','chem','ai-research','other')
        assert row['image'].startswith('assets/honors/') and '..' not in row['image']
        assert (ROOT/row['image']).is_file()
    for row in feeds['schedule_data.json']['items']:
        date.fromisoformat(row['date'])
        assert set(row)<={'course','date','session','topic','start_time','end_time','format','group','weekday'}
        assert row['group'] in ('bio','chem')
    papers=feeds['research_data.json']['items']
    assert len({r['id'] for r in papers})==len(papers)
    for row in papers:
        assert row['url'].startswith(('https://doi.org/','https://pubmed.ncbi.nlm.nih.gov/'))
        assert date.fromisoformat(row['published_at'])<=date.fromisoformat(row['added_on'])
    programs=feeds['applications.json']['items']
    assert len({r['id'] for r in programs})==len(programs)==100
    for row in programs:
        assert set(row)<=PROGRAM_FIELDS|{'source_checked_on','source_status'}
    for row in feeds['admissions_updates.json']['items']:
        assert official_url(row['url'])
        assert row['status'] in ('ok','unavailable')
        for notice in row['notices']:
            assert official_url(notice['url'])
        for window in row['application_windows']:
            assert official_url(window['url'])
            assert date.fromisoformat(window['s'])<=date.fromisoformat(window['e'])
    return {name:len(data['items']) for name,data in feeds.items()}

if __name__=='__main__':
    print(validate())
