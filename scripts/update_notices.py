"""Announce changes to public content, ignoring routine source-check timestamps."""
from datetime import date, datetime
import hashlib
import json
import re

from common import JST, ROOT, dataset, load
from course_flow import entry_year_for_date

LANGUAGES = ('ja', 'zh', 'tw', 'en')
SOURCES = {
    'research': ('research_data.json', 'daily-research'),
    'admissions': ('admissions_updates.json', 'application'),
    'honors': ('honors_data.json', 'honor'),
    'schedule': ('schedule_data.json', 'schedule'),
    'students': ('students_data.json', 'students'),
    'course_flow': ('course_flow_data.json', 'intro'),
}
TARGETS = {'home', *(target for _, target in SOURCES.values())}


def translated(ja, zh, tw, en):
    return dict(zip(LANGUAGES, (ja, zh, tw, en), strict=True))


def ordered(rows):
    return sorted(rows, key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))


def select(row, fields):
    return {key: row[key] for key in fields if key in row}


def terms(today):
    year = today.year
    winter = (year if today.month >= 10 else year - 1, 10,
              year + 1 if today.month >= 10 else year, 3)
    january = (year, 1, year, 9)
    return [winter] if today.month >= 10 else [january] if today.month >= 4 else [winter, january]


def content(kind, data, today):
    """Only published business fields participate in change detection."""
    rows = data['items']
    if not isinstance(rows, list) or not rows:
        raise ValueError('Missing public source; retaining prior announcements')
    if kind == 'schedule':
        return {'terms': terms(today), 'items': ordered([select(r, (
            'course', 'date', 'start_time', 'end_time', 'session', 'topic', 'format', 'group')) for r in rows])}
    if kind == 'honors':
        return ordered([select(r, ('id', 'name', 'university', 'year', 'subject', 'image')) for r in rows])
    if kind == 'research':
        return ordered([select(r, ('id', 'title', 'summary', 'source', 'published_at', 'url',
                                  'category', 'summary_source')) for r in rows])
    if kind == 'students':
        return {**select(data, ('total', 'unknown_school_count', 'counting_basis')),
                'items': ordered(rows), 'schools': ordered(data['schools'])}
    if kind == 'admissions':
        # A failed fetch retains the source's last public notices; status, page-wide
        # fingerprints, checked_on and attempted_on must never become news.
        return ordered([{
            'url': r['url'], 'program_ids': sorted(r['program_ids']),
            'notices': ordered([select(n, ('title', 'url')) for n in r['notices']]),
            'windows': ordered([select(w, ('s', 'e', 'heading', 'evidence', 'url'))
                                for w in r['application_windows']]),
        } for r in rows])
    if kind == 'course_flow':
        payload = select(data, ('entry_year', 'items', 'rollover', 'source_documents'))
        payload['entry_year'] = max(data['entry_year'], entry_year_for_date(today))
        return payload
    raise ValueError('Unknown announcement source')


def announcement(kind, data, today, initial):
    count = len(data['items'])
    titles = {
        'research': translated('研究論文のご紹介' if initial else '研究論文紹介を更新しました',
            '每日研究论文汇总' if initial else '每日研究已更新',
            '每日研究論文彙總' if initial else '每日研究已更新',
            'Research paper collection' if initial else 'Research papers updated'),
        'admissions': translated('出願情報のご案内' if initial else '出願情報を更新しました',
            '大学官网出愿信息' if initial else '出愿信息已更新',
            '大學官網出願資訊' if initial else '出願資訊已更新',
            'University admissions information' if initial else 'Admissions information updated'),
        'honors': translated('合格実績のご紹介' if initial else '合格実績を更新しました',
            '合格榜汇总' if initial else '合格榜已更新', '合格榜彙總' if initial else '合格榜已更新',
            'Admission results' if initial else 'Admission results updated'),
        'schedule': translated('授業時間割のご案内' if initial else '授業時間割を更新しました',
            '当前课程表' if initial else '课程表已更新', '目前課程表' if initial else '課程表已更新',
            'Current timetable' if initial else 'Timetable updated'),
        'students': translated('在籍者数のご案内' if initial else '在籍者数を更新しました',
            '在籍学生人数' if initial else '在籍人数统计已更新',
            '在籍學生人數' if initial else '在籍人數統計已更新',
            'Enrolled students' if initial else 'Enrollment summary updated'),
        'course_flow': translated('大学院入試準備の流れ' if initial else '大学院入試準備の流れを更新しました',
            '大学院入试准备流程' if initial else '大学院入试准备流程已更新',
            '大學院入試準備流程' if initial else '大學院入試準備流程已更新',
            'Graduate entrance preparation' if initial else 'Entrance preparation plan updated'),
    }
    if kind == 'research':
        body = translated(f'生物・化学・AI生命科学の論文を計{count}件掲載しています。各論文に2文の成果紹介と原文リンクがあります。',
            f'现收录{count}篇生物、化学与AI生命科学论文，每篇附两句话的成果介绍及原文链接。',
            f'現收錄{count}篇生物、化學與AI生命科學論文，每篇附兩句話的成果介紹及原文連結。',
            f'The collection contains {count} papers in biology, chemistry and AI for life sciences, with two-sentence findings and original paper links.')
    elif kind == 'admissions':
        body = translated('大学公式サイトの通知・募集要項と、期限内の出願日程を確認できます。専攻・入試区分ごとの条件は原文をご確認ください。',
            '可查看大学官网通知、募集要项及未过期的出愿日程，具体专攻、批次与要求请核对官网原文。',
            '可查看大學官網通知、募集要項及未過期的出願日程，具體專攻、批次與要求請核對官網原文。',
            'View official university notices, guidelines and unexpired application windows. Check the source for each program and admission round.')
    elif kind == 'honors':
        body = translated(f'合格実績ポスターを計{count}件掲載しています。年度・科目別に絞り込めます。',
            f'合格榜现有{count}张海报，可按年度与科目筛选查看。',
            f'合格榜現有{count}張海報，可按年度與科目篩選查看。',
            f'The gallery contains {count} admission posters, with filters for year and subject.')
    elif kind == 'schedule':
        periods = terms(today)
        labels = [' ＋ '.join(f'{a}年{b}月—{c}年{d}月' for a, b, c, d in periods),
                  ' + '.join(f'{a}-{b:02d} to {c}-{d:02d}' for a, b, c, d in periods)]
        body = translated(f'表示期間は{labels[0]}です。1〜3月は両期を併せて表示し、後日の授業変更は先生の連絡をご確認ください。',
            f'当前展示{labels[0]}的初次排课表；1—3月同时显示两期课程，后续调课请以老师通知为准。',
            f'目前展示{labels[0]}的初次排課表；1—3月同時顯示兩期課程，後續調課請以老師通知為準。',
            f'The initial timetable covers {labels[1]}. Both terms appear in January–March; check instructor notices for later changes.')
    elif kind == 'students':
        total = data['total']
        body = translated(f'現在の在籍学生は{total}名です。卒業予定を含み、休学中を除いた人数と出身校の集計を掲載しています。',
            f'当前在籍学生共{total}人，含待毕业、不含休学；页面仅展示人数及出身校汇总。',
            f'目前在籍學生共{total}人，含待畢業、不含休學；頁面僅展示人數及出身校彙總。',
            f'There are {total} enrolled students, including those awaiting graduation and excluding students on leave. Only counts and origin-school aggregates are published.')
    else:
        year = max(data['entry_year'], entry_year_for_date(today))
        body = translated(f'{year}年度入学に向けた夏・冬の準備手順を掲載しています。大学公式の出願日程は出願情報で別途ご確認ください。',
            f'展示{year}年度入学的夏季、冬季入试准备步骤，大学官网出愿日程请另行查看出愿信息。',
            f'展示{year}年度入學的夏季、冬季入試準備步驟，大學官網出願日程請另行查看出願資訊。',
            f'View summer and winter preparation steps for {year} entry. Consult the admissions section separately for official university application dates.')
    return {'id': f'auto:{kind}:{today.isoformat()}', 'date': today.isoformat(),
            'kind': kind, 'tag': 'info' if initial else 'update',
            'target': SOURCES[kind][1], 'title': titles[kind], 'body': body}


def validate_notices(data):
    if set(data) - {'items', 'source_fingerprints', 'updated_at'}:
        raise ValueError('Unexpected announcement fields')
    fingerprints = data['source_fingerprints']
    if set(fingerprints) != set(SOURCES) or not all(re.fullmatch(r'[a-f0-9]{64}', v) for v in fingerprints.values()):
        raise ValueError('Invalid announcement source fingerprints')
    rows = data['items']
    if not rows or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Empty or duplicate announcements')
    for row in rows:
        if set(row) != {'id', 'date', 'kind', 'tag', 'target', 'title', 'body'}:
            raise ValueError('Unexpected announcement fields')
        date.fromisoformat(row['date'])
        if row['tag'] not in ('info', 'update') or row['target'] not in TARGETS:
            raise ValueError('Invalid announcement destination')
        if row['kind'] not in {*SOURCES, 'system'}:
            raise ValueError('Invalid announcement kind')
        for key in ('title', 'body'):
            if set(row[key]) != set(LANGUAGES) or not all(
                isinstance(value, str) and 1 <= len(value) <= 800 and '<' not in value
                for value in row[key].values()):
                raise ValueError('Invalid localized announcement')
    return data


def build_notices(previous, sources, today):
    """One notice per source and JST date; keep all prior dates and originals."""
    fingerprints = {}
    additions = []
    for kind in SOURCES:
        digest = hashlib.sha256(json.dumps(content(kind, sources[kind], today),
            ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        fingerprints[kind] = digest
        prior = previous.get('source_fingerprints', {}).get(kind)
        if digest != prior:
            additions.append(announcement(kind, sources[kind], today, initial=prior is None))
    records = {row['id']: row for row in previous.get('items', [])}
    for row in additions:
        records[row['id']] = row
    enabled = 'auto:system:enabled'
    if enabled not in records:
        records[enabled] = {
            'id': enabled, 'date': today.isoformat(), 'kind': 'system', 'tag': 'info', 'target': 'home',
            'title': translated('お知らせの自動更新を開始しました', '通知公告已接入自动更新',
                                '通知公告已接入自動更新', 'Announcements now update automatically'),
            'body': translated('各ページの公開内容を毎時確認し、変更がある場合にお知らせを更新します。同日・同項目はまとめ、過去のお知らせも残します。',
                '每小时检查各栏目公开内容，有实际变化时更新公告；同日同栏目合并展示，历史公告继续保留。',
                '每小時檢查各欄目公開內容，有實際變化時更新公告；同日同欄目合併展示，歷史公告繼續保留。',
                'Published content is checked hourly. Changes generate announcements, grouped by section and date, while earlier notices are retained.'),
        }
    # Stable ordering within a date; the activation notice is first on launch day.
    rows = sorted(records.values(), key=lambda r: (r['date'], r['id'] == enabled), reverse=True)
    return validate_notices({'items': rows, 'source_fingerprints': fingerprints})


def update_notices(today=None):
    today = today or datetime.now(JST).date()
    previous = load(ROOT / 'notices_data.json', {})
    if previous:
        validate_notices(previous)
    sources = {kind: load(ROOT / file) for kind, (file, _) in SOURCES.items()}
    payload = build_notices(previous, sources, today)
    return dataset('notices_data.json', payload)


if __name__ == '__main__':
    print(json.dumps({'items': len(update_notices()['items'])}))
