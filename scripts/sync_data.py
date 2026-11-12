"""Refresh independent public feeds; retain the last good file when a source fails."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import argparse
import json
from common import JST, STATE, now, save
from update_google import update_courses, update_honors
from update_admissions import update_admissions
from update_research import update_research
from update_students import update_students

def run(selected=None):
    today = datetime.now(JST).date()
    jobs = {'schedule': update_courses, 'honors': update_honors, 'students': update_students,
            'admissions': lambda: update_admissions(today), 'research': lambda: update_research(today)}
    results = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fn): name for name, fn in jobs.items() if not selected or name in selected}
        for future in as_completed(futures):
            name = futures[future]
            try:
                value = future.result()
                results[name] = {'ok': True, 'items': len(value['items']), 'updated_at': value.get('updated_at')}
            except Exception as exc:
                results[name] = {'ok': False, 'error': type(exc).__name__, 'message': str(exc)[:240]}
            print(json.dumps({name: results[name]}, ensure_ascii=False), flush=True)
    save(STATE / 'last-run.json', {'checked_at': now(), 'feeds': results})
    return results

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--only', nargs='+', choices=['schedule','honors','admissions','research','students'])
    args = parser.parse_args()
    results = run(args.only)
    raise SystemExit(0 if all(r['ok'] for r in results.values()) else 1)
