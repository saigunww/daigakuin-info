"""Build public admission-offer counts; identities never leave private memory.

An offer is one student, entrance year, university and graduate-program pair.
The caller supplies a read-only Sheets client and verified poster metadata.
Uncertain posters are held for private review without adding extra offers;
source failures preserve the previous dataset by raising a sanitized error.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import re
import unicodedata

from common import ROOT, clean, load, save

PRIVATE = ROOT.parent / '同步私有配置'
CONFIG = PRIVATE / 'honor_statistics.json'
REVIEW = PRIVATE / 'honor_statistics_review.json'
SUBJECTS = ('bio', 'chem', 'ai-research', 'other')
YEAR = re.compile(r'20\d{2}')
CHARACTERS = str.maketrans({
    '許': '许', '張': '张', '劉': '刘', '喬': '乔', '陳': '陈', '鄧': '邓',
    '吳': '吴', '呉': '吴', '錢': '钱', '馮': '冯', '楊': '杨', '趙': '赵',
    '黃': '黄', '馬': '马', '羅': '罗', '尧': '堯', '學': '学', '專': '専',
})
UNIVERSITY_ALIASES = {
    '东京大学': '東京大学', '京都大學': '京都大学',
    '东京科学大学': '東京科学大学', '東京工業大学': '東京科学大学',
    '东京工业大学': '東京科学大学', '東京医科歯科大学': '東京科学大学',
    '东京医科齿科大学': '東京科学大学', '东京工科大学': '東京工科大学',
    '早稻田大学': '早稲田大学', '庆应义塾大学': '慶應義塾大学',
    '庆応义塾大学': '慶應義塾大学', '北海道大學': '北海道大学',
    '东京理科大学': '東京理科大学', '东京农工大学': '東京農工大学',
    '顺天堂大学': '順天堂大学', '关西大学': '関西大学',
}
NOT_ACCEPTED = {
    '', '不合格', '未受験', '未受验', '受験予定', '受验予定', '受験中',
    '出願予定', '出願済', '出願済み', '結果待ち', '結果待', '未定',
    '辞退', '受験辞退', '受验辞退', '補欠', '補欠合格', '取下げ', '取消',
}


class StatisticsError(ValueError):
    """A short error safe for logs published by the synchronization service."""


def normalized(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or '')))


def person_name(value):
    return normalized(value).translate(CHARACTERS)


def university_name(value):
    raw = str(value or '')
    if (len(raw) > 100 or any(c in raw for c in ('\n', '\r', '@', ':', '<', '>', '/', '\\'))
            or re.search(r'\d{5,}', raw)):
        raise StatisticsError('Admission university field is missing or invalid')
    text = normalized(raw).replace('大學', '大学')
    found = re.fullmatch(r'([A-Za-z\u3400-\u9fff\u3040-\u30ffー・]{1,55}?大学)(?:大学院)?', text)
    if not found:
        raise StatisticsError('Admission university field is missing or invalid')
    name = found.group(1)
    return UNIVERSITY_ALIASES.get(name, name)


def program_name(value):
    text = normalized(value).translate(CHARACTERS).replace('大学院', '')
    text = text.replace('医歯薬学総合研究科', '医歯薬学研究科')
    text = text.replace('先端生命科学専攻', '先端生命専攻')
    return re.sub(r'[・･,，、/／_—–\-()（）]', '', text)


def entrance_year(value):
    text = normalized(value)
    if text.endswith('年度'):
        text = text[:-2]
    if not YEAR.fullmatch(text):
        raise StatisticsError('Admission entrance year is missing or invalid')
    return text


def university_program(value):
    text = normalized(value).replace('大學', '大学')
    found = re.match(r'^(.+?大学)(.*)$', text)
    if not found:
        raise StatisticsError('Poster university metadata is missing or invalid')
    return university_name(found.group(1)), program_name(found.group(2))


def _source_records(api, config):
    sources = config.get('sources')
    if not isinstance(sources, list) or not sources:
        raise StatisticsError('Admission statistics source configuration is missing')
    result = []
    for source in sources:
        try:
            group, sid, gid = source['group'], source['spreadsheet_id'], source['sheet_id']
            if group not in ('bio', 'chem') or not isinstance(sid, str) or not isinstance(gid, int):
                raise ValueError
            expected = source['headers']
            if (set(expected) != {'identity', 'offer'} or len(expected['identity']) != 3
                    or len(expected['offer']) != 5 or any(not clean(v) for a in expected.values() for v in a)):
                raise ValueError
            metadata = api.spreadsheets().get(spreadsheetId=sid, fields='sheets.properties').execute(num_retries=2)
            matches = [x['properties'] for x in metadata['sheets'] if x['properties']['sheetId'] == gid]
            if len(matches) != 1:
                raise ValueError
            properties = matches[0]
            limit = properties['gridProperties']['rowCount']
            if not isinstance(limit, int) or not 3 <= limit <= 10000:
                raise ValueError
            title = "'" + properties['title'].replace("'", "''") + "'"
            response = api.spreadsheets().values().batchGet(
                spreadsheetId=sid,
                ranges=[f'{title}!B2:D2', f'{title}!I2:M2', f'{title}!B3:D{limit}', f'{title}!I3:M{limit}'],
                valueRenderOption='FORMATTED_VALUE',
            ).execute(num_retries=2)
            ranges = response.get('valueRanges', [])
            if len(ranges) != 4:
                raise ValueError
            headers = [r.get('values', []) for r in ranges[:2]]
            for actual, key in zip(headers, ('identity', 'offer')):
                if len(actual) != 1 or [clean(v) for v in actual[0]] != [clean(v) for v in expected[key]]:
                    raise ValueError
            identities, offers = [r.get('values', []) for r in ranges[2:]]
        except StatisticsError:
            raise
        except Exception:
            raise StatisticsError('Admission source unavailable or source schema changed') from None
        valid_rows = 0
        for index in range(max(len(identities), len(offers))):
            identity = identities[index] if index < len(identities) else []
            offer = offers[index] if index < len(offers) else []
            if len(identity) > 3 or len(offer) > 5:
                raise StatisticsError('Admission source schema changed')
            identity = [clean(v) for v in (identity + [''] * 3)[:3]]
            offer = [clean(v) for v in (offer + [''] * 5)[:5]]
            if not any(identity + offer):
                continue
            status = offer[4]
            if status != '合格':
                if status not in NOT_ACCEPTED:
                    raise StatisticsError('Admission result contains an unrecognized status')
                # The source sheets contain prefilled entrance-year/template
                # rows with no student yet. Empty or explicit nonaccepted
                # results are never offers, so no identity is inferred for them.
                continue
            student_id, surname, given_name = identity
            if not all((student_id, surname, given_name)):
                raise StatisticsError('An accepted admission record is missing its required identity fields')
            year, school, department, major, _ = offer
            if not all((student_id, surname, given_name, department, major)):
                raise StatisticsError('An accepted offer is missing required fields')
            result.append({
                'person': student_id, 'full_name': person_name(surname + given_name),
                'surname': person_name(surname), 'year': entrance_year(year),
                'university': university_name(school), 'department': program_name(department),
                'major': program_name(major), 'subject': group,
                'source_row': index + 3,
            })
            valid_rows += 1
        if not valid_rows:
            raise StatisticsError('An admission source has no validated accepted offers')
    return result


def _poster_identity(poster, metadata):
    source = poster.get('source_path')
    if not isinstance(source, str) or not source or '\\' in source or '..' in Path(source).parts:
        raise StatisticsError('Poster source metadata is missing or invalid')
    filename = Path(source).name
    stem = Path(filename).stem
    explicit = ''
    if stem.startswith('合格榜_'):
        fields = stem.split('_', 2)
        if len(fields) != 3:
            raise StatisticsError('Poster identity metadata is missing or invalid')
        explicit = fields[1]
    else:
        curated = clean(metadata.get(filename, {}).get('name', ''))
        if len(person_name(curated)) >= 2 and not re.search(r'同[学學]$', curated):
            explicit = curated
        prefix = re.split(r'[-_]', stem, maxsplit=1)[0]
        prefix = re.sub(r'(?:东大|東大|东科|東科|京大|北海道|东北大|東北大|冈山|岡山|筑波|早大|九大|金泽大|金沢大)$', '', prefix)
        if not explicit and re.search(r'[\u3400-\u9fffぁ-ゖァ-ヺ]', prefix) and not re.fullmatch(r'[0-9a-fA-F]{20,}', prefix):
            explicit = prefix
        if not explicit:
            explicit = metadata.get(filename, {}).get('name', '')
    if not explicit:
        explicit = poster.get('name', '')
    anonymous = bool(re.search(r'同[学學]$', explicit))
    if anonymous:
        explicit = re.sub(r'同[学學]$', '', explicit)
    name = person_name(explicit)
    if not name:
        raise StatisticsError('Poster identity metadata is missing or invalid')
    return name, anonymous or len(name) == 1


def _program_matches(poster_program, record):
    department, major = record['department'], record['major']
    if not poster_program:
        return False
    # A short major must never match a suffix inside a different major (for
    # example 化学専攻 inside 生化学専攻). Only explicit full-field equality is
    # proof; the degree labels below do not alter the graduate program.
    for label in ('博士前期課程', '博士後期課程', '修士課程', '博士課程'):
        poster_program = poster_program.replace(label, '')
    return poster_program in (department + major, department, major)


def _offer_key(record):
    return tuple(record[k] for k in ('person', 'year', 'university', 'department', 'major'))


def _write_review(issues):
    try:
        PRIVATE.mkdir(parents=True, exist_ok=True)
        temporary = REVIEW.with_suffix('.json.tmp')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump({'schema_version': 1, 'pending_count': len(issues), 'issues': issues}, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush(); os.fsync(handle.fileno())
        temporary.replace(REVIEW)
    except OSError:
        raise StatisticsError('Cannot save the private statistics review list') from None


def build_statistics(api, poster_records):
    config = load(CONFIG, {})
    if config.get('schema_version') != 1:
        raise StatisticsError('Admission statistics source configuration is missing or invalid')
    records = _source_records(api, config)
    metadata = load(ROOT / 'config/honor_metadata.json', {})
    person_names = defaultdict(set)
    name_people = defaultdict(set)
    for record in records:
        person_names[record['person']].add(record['full_name'])
        name_people[record['full_name']].add(record['person'])
    if any(len(names) != 1 for names in person_names.values()):
        raise StatisticsError('Conflicting admission identities require private review')
    entries = {}
    for record in records:
        key = _offer_key(record)
        entry = entries.setdefault(key, {'year': record['year'], 'university': record['university'], 'subjects': set()})
        entry['subjects'].add(record['subject'])
    by_image = defaultdict(list)
    for poster in poster_records:
        if not isinstance(poster, dict) or not isinstance(poster.get('id'), str) or not poster['id']:
            raise StatisticsError('Poster identity metadata is missing or invalid')
        by_image[poster['id']].append(poster)
    issues, unassigned = [], 0
    poster_only = defaultdict(list)
    links = config.get('poster_links', {})
    for image_id, copies in by_image.items():
        candidates = []
        path_descriptions = []
        for poster in copies:
            year_raw = clean(poster.get('year'))
            if year_raw in ('', '未分年度'):
                continue
            year = entrance_year(year_raw)
            school, program = university_program(poster.get('university'))
            subject = poster.get('subject')
            if subject not in SUBJECTS:
                raise StatisticsError('Poster subject metadata is invalid')
            identity, anonymous = _poster_identity(poster, metadata)
            path_descriptions.append((year, school, program, identity, anonymous, subject))
        if not path_descriptions:
            unassigned += 1
            continue
        descriptions = {(a, b, c) for a, b, c, _, _, _ in path_descriptions}
        if len(descriptions) != 1:
            issues.append({'poster_id': image_id, 'reason': 'Conflicting metadata for duplicate poster bytes'})
            continue
        year, school, program = next(iter(descriptions))
        full_names = {d[3] for d in path_descriptions if not d[4]}
        if len(full_names) > 1:
            issues.append({'poster_id': image_id, 'year': year, 'reason': 'Duplicate poster bytes have conflicting full names'})
            continue
        if full_names:
            identity, anonymous = next(iter(full_names)), False
        else:
            short_names = {d[3] for d in path_descriptions}
            if len(short_names) != 1:
                issues.append({'poster_id': image_id, 'year': year, 'reason': 'Duplicate poster bytes have conflicting anonymous labels'})
                continue
            identity, anonymous = next(iter(short_names)), True
        subjects = {d[5] for d in path_descriptions}
        same_school = [r for r in records if r['year'] == year and r['university'] == school]
        link = links.get(image_id)
        if link is not None:
            if not isinstance(link, dict) or not clean(link.get('basis')):
                raise StatisticsError('Reviewed poster correspondence configuration is invalid')
            target = [r for r in same_school if r['person'] == clean(link.get('student_id'))
                      and r['department'] == program_name(link.get('department'))
                      and r['major'] == program_name(link.get('major'))]
            if not target:
                issues.append({'poster_id': image_id, 'year': year, 'reason': 'Reviewed correspondence no longer matches the source'})
                continue
            candidates = target
        else:
            identity_candidates = [r for r in same_school if
                (r['surname'] == identity if anonymous else r['full_name'] == identity)]
            candidates = [r for r in identity_candidates if _program_matches(program, r)]
            if not candidates and identity_candidates:
                issues.append({'poster_id': image_id, 'year': year, 'reason': 'Identity overlaps a source, but the program is not proven',
                               'candidate_count': len({_offer_key(r) for r in identity_candidates})})
                continue
            if not candidates and not anonymous:
                surname_candidates = [r for r in same_school if identity.startswith(r['surname'])
                                      and _program_matches(program, r)]
                if surname_candidates:
                    issues.append({'poster_id': image_id, 'year': year,
                                   'reason': 'A source has a similar name and the same program; no identity match is assumed',
                                   'candidate_count': len({_offer_key(r) for r in surname_candidates})})
                    continue
            if not candidates and anonymous:
                # A surname-only poster may be a genuine extra offer. Its full
                # program is required to keep future duplicate checks meaningful.
                if not program:
                    issues.append({'poster_id': image_id, 'year': year, 'reason': 'Anonymous poster lacks a graduate-program identity'})
                    continue
        keys = {_offer_key(r) for r in candidates}
        if len(keys) > 1:
            issues.append({'poster_id': image_id, 'year': year, 'reason': 'Poster correspondence is ambiguous', 'candidate_count': len(keys)})
            continue
        if keys:
            entry = entries[next(iter(keys))]
            entry['subjects'].update(subjects)
            continue
        if anonymous:
            person = 'anonymous:' + identity
        elif len(name_people.get(identity, set())) == 1:
            person = next(iter(name_people[identity]))
        elif len(name_people.get(identity, set())) > 1:
            issues.append({'poster_id': image_id, 'year': year, 'reason': 'Full name refers to multiple source identities'})
            continue
        else:
            person = 'name:' + identity
        descriptor = (person, year, school, program)
        poster_only[descriptor].append((image_id, anonymous))
        # One descriptive program field is sufficient for poster-only records;
        # source-linked records retain the authoritative department/major pair.
        key = (person, year, school, program, '')
        entry = entries.setdefault(key, {'year': year, 'university': school, 'subjects': set()})
        entry['subjects'].update(subjects)
    for descriptor, images in poster_only.items():
        if len(images) > 1 and any(anonymous for _, anonymous in images):
            key = (descriptor[0], descriptor[1], descriptor[2], descriptor[3], '')
            entries.pop(key, None)
            for image_id, _ in images:
                issues.append({'poster_id': image_id, 'year': descriptor[1],
                               'reason': 'Same-surname poster-only records require identity confirmation'})
    _write_review(issues)
    # Uncertain posters do not contribute extra offers. Confirmed source records
    # remain counted; there is no implied identity correspondence for a pending
    # poster. Source errors above still abort the entire refresh.
    pending_years = Counter()
    for issue in issues:
        if issue.get('year'):
            pending_years[issue['year']] += 1
    years = []
    for year in sorted({v['year'] for v in entries.values()} | set(pending_years), reverse=True):
        year_entries = [e for e in entries.values() if e['year'] == year]
        universities = _counts(year_entries)
        by_subject = {}
        for subject in SUBJECTS:
            subject_entries = [e for e in year_entries if subject in e['subjects']]
            by_subject[subject] = {'total': len(subject_entries), 'universities': _counts(subject_entries)}
        years.append({'year': year, 'total': len(year_entries), 'universities': universities,
                      'by_subject': by_subject, 'pending_review': pending_years[year]})
    output = {'schema_version': 1, 'counting_unit': 'offers', 'years': years,
              'unassigned_total': unassigned, 'pending_review_total': len(issues)}
    validate_statistics(output)
    return output


def _counts(entries):
    counts = Counter(e['university'] for e in entries)
    return [{'name': name, 'count': count} for name, count in sorted(counts.items(), key=lambda p: (-p[1], p[0]))]


def validate_statistics(statistics):
    """Reject private fields, malformed types and totals that do not reconcile."""
    def integer(value):
        return type(value) is int and value >= 0

    def counts(rows, total):
        if not isinstance(rows, list) or not integer(total):
            raise StatisticsError('Invalid public admission statistics')
        seen, previous, accumulated = set(), None, 0
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {'name', 'count'}
                    or not isinstance(row['name'], str) or not row['name'] or not integer(row['count']) or row['count'] == 0):
                raise StatisticsError('Invalid public admission statistics')
            if row['name'] != university_name(row['name']) or row['name'] in seen:
                raise StatisticsError('Invalid public admission statistics')
            order = (-row['count'], row['name'])
            if previous is not None and order < previous:
                raise StatisticsError('Invalid public admission statistics')
            seen.add(row['name']); previous = order; accumulated += row['count']
        if accumulated != total:
            raise StatisticsError('Admission university totals do not reconcile')
        return {r['name']: r['count'] for r in rows}

    if (not isinstance(statistics, dict)
            or set(statistics) != {'schema_version', 'counting_unit', 'years', 'unassigned_total', 'pending_review_total'}
            or type(statistics['schema_version']) is not int or statistics['schema_version'] != 1
            or statistics['counting_unit'] != 'offers' or not isinstance(statistics['years'], list)
            or not integer(statistics['unassigned_total']) or not integer(statistics['pending_review_total'])):
        raise StatisticsError('Invalid public admission statistics')
    seen_years, previous_year = set(), None
    for year in statistics['years']:
        if (not isinstance(year, dict)
                or set(year) != {'year', 'total', 'universities', 'by_subject', 'pending_review'}
                or not integer(year['pending_review'])):
            raise StatisticsError('Invalid public admission statistics')
        value = year['year']
        if (not isinstance(value, str) or not YEAR.fullmatch(value) or value in seen_years
                or previous_year is not None and value > previous_year):
            raise StatisticsError('Invalid public admission statistics')
        seen_years.add(value); previous_year = value
        school_totals = counts(year['universities'], year['total'])
        groups = year['by_subject']
        if not isinstance(groups, dict) or set(groups) != set(SUBJECTS):
            raise StatisticsError('Invalid public admission statistics')
        summed_memberships = Counter()
        for subject in SUBJECTS:
            group = groups[subject]
            if not isinstance(group, dict) or set(group) != {'total', 'universities'}:
                raise StatisticsError('Invalid public admission statistics')
            group_counts = counts(group['universities'], group['total'])
            for school, value in group_counts.items():
                if value > school_totals.get(school, 0):
                    raise StatisticsError('Admission subject totals exceed the combined total')
                summed_memberships[school] += value
        if any(summed_memberships[school] < value for school, value in school_totals.items()):
            raise StatisticsError('Admission subject membership is incomplete')
    if sum(y['pending_review'] for y in statistics['years']) > statistics['pending_review_total']:
        raise StatisticsError('Admission pending-review totals do not reconcile')
    return True
