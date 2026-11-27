"""Validate public data before a commit can be published."""
from datetime import date
from pathlib import Path
from common import ROOT, load, official_url
from update_admissions import PROGRAM_FIELDS
from update_students import validate_student_summary
from course_flow import validate_payload
from research_summaries import validate_summary
from update_notices import validate_notices
from honor_statistics import validate_statistics

def validate():
    feeds = {name: load(ROOT / name) for name in ('honors_data.json','schedule_data.json','research_data.json','applications.json','admissions_updates.json','students_data.json','course_flow_data.json','notices_data.json')}
    for name, data in feeds.items():
        empty_schedule = name == 'schedule_data.json' and isinstance(data, dict) and data.get('source_type') == 'rooms_schedule' and isinstance(data.get('items'), list)
        if not isinstance(data, dict) or (not data.get('items') and not empty_schedule) or not data.get('updated_at'):
            raise ValueError('Empty or invalid public feed: '+name)
    validate_student_summary(feeds['students_data.json'])
    validate_payload(feeds['course_flow_data.json'])
    validate_notices(feeds['notices_data.json'])
    honors=feeds['honors_data.json']['items']
    validate_statistics(feeds['honors_data.json'].get('statistics'))
    fields = {row['id'] for row in feeds['honors_data.json']['statistics']['fields']}
    assert len({r['id'] for r in honors})==len(honors)
    for row in honors:
        assert row['subject'] in ('bio','chem','ai-research','other')
        assert row['field'] in fields
        assert row['image'].startswith('assets/honors/') and '..' not in row['image']
        assert (ROOT/row['image']).is_file()
    for row in feeds['schedule_data.json']['items']:
        date.fromisoformat(row['date'])
        assert set(row)<={'course','date','session','topic','start_time','end_time','format','group','weekday','status','metadata_basis'}
        assert row['group'] in ('bio','chem')
        assert row.get('status', 'scheduled') in ('scheduled','rescheduling')
        assert row.get('metadata_basis', 'excel') in ('excel','plan_estimate')
    schedule = feeds['schedule_data.json']
    if schedule.get('source_type') == 'rooms_schedule':
        assert schedule['sync_status'] in ('ok','error')
        assert schedule['sync_interval_minutes'] == 60
        assert date.fromisoformat(schedule['coverage_start']) < date.fromisoformat(schedule['coverage_end'])
        assert schedule['last_success_at'] and schedule['last_attempt_at']
        assert all(schedule['coverage_start'] <= row['date'] < schedule['coverage_end'] for row in schedule['items'])
    papers=feeds['research_data.json']['items']
    assert len({r['id'] for r in papers})==len(papers)
    for row in papers:
        assert row['url'].startswith(('https://doi.org/','https://pubmed.ncbi.nlm.nih.gov/'))
        assert date.fromisoformat(row['published_at'])<=date.fromisoformat(row['added_on'])
        validate_summary(row['summary'])
        assert row['summary_source'].startswith('https://pubmed.ncbi.nlm.nih.gov/')
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
