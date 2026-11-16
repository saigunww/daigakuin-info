"""A single public academic field per admission, independent of course source.

The dictionary contains public academic labels only.  Source identities are never
accepted here; callers provide graduate school and major text.  A broad graduate
school is not evidence for a particular discipline inside it.
"""
from __future__ import annotations

import copy
import re
import unicodedata


FIELDS = [
    {'id': 'medicine', 'labels': {'ja': '医学・医療', 'zh': '医学与医疗', 'tw': '醫學與醫療', 'en': 'Medicine & Health'}},
    {'id': 'pharmacy', 'labels': {'ja': '薬学', 'zh': '药学', 'tw': '藥學', 'en': 'Pharmacy'}},
    {'id': 'dentistry', 'labels': {'ja': '歯学', 'zh': '齿学', 'tw': '齒學', 'en': 'Dentistry'}},
    {'id': 'life-sciences', 'labels': {'ja': '生命科学', 'zh': '生命科学', 'tw': '生命科學', 'en': 'Life Sciences'}},
    {'id': 'applied-chemistry', 'labels': {'ja': '応用化学', 'zh': '应用化学', 'tw': '應用化學', 'en': 'Applied Chemistry'}},
    {'id': 'chemical-systems', 'labels': {'ja': '化学システム工学', 'zh': '化学系统工程', 'tw': '化學系統工程', 'en': 'Chemical Systems Engineering'}},
    {'id': 'chemistry', 'labels': {'ja': '化学', 'zh': '化学', 'tw': '化學', 'en': 'Chemistry'}},
    {'id': 'materials', 'labels': {'ja': '材料・物質科学', 'zh': '材料与物质科学', 'tw': '材料與物質科學', 'en': 'Materials Science'}},
    {'id': 'agriculture-environment', 'labels': {'ja': '農学・環境', 'zh': '农学与环境', 'tw': '農學與環境', 'en': 'Agriculture & Environment'}},
    {'id': 'interdisciplinary', 'labels': {'ja': '総合・広域科学', 'zh': '综合与广域科学', 'tw': '綜合與廣域科學', 'en': 'Interdisciplinary Sciences'}},
    {'id': 'unconfirmed', 'labels': {'ja': '専攻確認中', 'zh': '专业待确认', 'tw': '專業待確認', 'en': 'Field to Be Confirmed'}},
]
FIELD_IDS = tuple(row['id'] for row in FIELDS)
# Keep recognition for deliberate exclusion from the public results.  Excluded
# fields remain available to the updater so future posters can also be omitted.
EXCLUDED_FIELDS = frozenset({'business'})
INTERNAL_FIELD_IDS = frozenset(FIELD_IDS) | EXCLUDED_FIELDS
FLEXIBLE = frozenset(('interdisciplinary', 'unconfirmed'))


def public_fields():
    return copy.deepcopy(FIELDS)


def _text(value):
    text = re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or '')))
    return text.translate(str.maketrans({'學': '学', '藥': '薬', '药': '薬', '齒': '歯', '齿': '歯',
                                        '醫': '医', '农': '農', '环': '環', '營': '営', '营': '営',
                                        '濟': '済', '济': '済', '應': '応', '应': '応', '綜': '総',
                                        '综': '総', '經': '経', '经': '経'}))


def _discipline(value):
    """Recognize explicit programs, leaving broad mixed institutes unresolved."""
    text = _text(value)
    if not text:
        return None
    # Combined schools contain several independent disciplines.  Remove that
    # common umbrella before interpreting any more specific text that follows.
    for broad in ('医歯薬学総合研究科', '医歯薬学研究科', '医工農学総合教育部',
                  '理工情報生命学術院', '物質理工学院', '環境社会理工学院',
                  '環境・社会理工学院', '新領域創成科学研究科', '先進理工学研究科'):
        text = text.replace(broad, '')
    if not text:
        return None
    if re.search(r'化学システム|化学系統|化学系统', text):
        return 'chemical-systems'
    if re.search(r'経済|経営|経管|商学', text):
        return 'business'
    if re.search(r'応用化学|工業化学', text):
        return 'applied-chemistry'
    if re.search(r'機能分子[・･]?生命化学', text):
        return 'chemistry'
    if re.search(r'薬科学|薬学|創成薬', text):
        return 'pharmacy'
    if '歯学' in text:
        return 'dentistry'
    # These are explicit environmental programs, not unspecified biological
    # disciplines inferred merely from the word 生物 or 生命 in an institute.
    if re.search(r'生物[・･]?環境工学|自然環境|生命環境|農学専攻|農学府|農学研究科|環境科学', text):
        return 'agriculture-environment'
    if re.search(r'生命|生物|バイオ|水圏', text):
        return 'life-sciences'
    if re.search(r'医学|医科学|医療|保健', text):
        return 'medicine'
    if re.search(r'広域科学|総合文化|融合理工|システム創成|数理物質', text):
        return 'interdisciplinary'
    # 先進理化学 alone covers both physics and chemistry.  A stated chemistry
    # course/program is more specific evidence and can be confirmed separately.
    if '理化学' in text and not re.search(r'化学(?:コース|学位プログラム)', text):
        return 'interdisciplinary'
    if re.search(r'材料|物質系|物質科学', text):
        return 'materials'
    if '化学' in text:
        return 'chemistry'
    return None


def classify_program(department='', major=''):
    """Use the program and its agricultural-school affiliation consistently."""
    if not major:
        # Public poster metadata often joins university, graduate school and
        # major into one string.  Split a stated major before applying fallback
        # rules so a joined poster description and a two-column source agree.
        combined = _text(department)
        match = re.match(r'^(.*?(?:研究科|学術院|学院|学府|教育部|学部))(.+)$', combined)
        if match:
            department, major = match.groups()
    specific = _discipline(major)
    # Agriculture schools include biological programs under agricultural
    # admissions.  Keep those programs together rather than splitting them
    # between Life Sciences and Agriculture based on the word 生命 alone.
    # Explicit narrower disciplines (chemistry, pharmacy, business, ...) keep
    # their existing precedence.  Combined medical/engineering/agriculture
    # schools do not establish agricultural affiliation by themselves.
    agriculture_school = re.search(
        r'農学生命科学研究科|農学研究科|農学府|生物資源環境科学府', _text(department))
    if agriculture_school and specific in (None, 'life-sciences'):
        return 'agriculture-environment'
    if specific is not None:
        return specific
    return _discipline(department) or 'unconfirmed'


def resolve_fields(evidence):
    """Refine broad fields, but do not choose between conflicting disciplines."""
    fields = set(evidence)
    if not fields <= INTERNAL_FIELD_IDS:
        raise ValueError('Invalid admission academic field')
    concrete = fields - FLEXIBLE
    if len(concrete) > 1:
        return 'unconfirmed', True
    if concrete:
        return next(iter(concrete)), False
    if 'interdisciplinary' in fields:
        return 'interdisciplinary', False
    return 'unconfirmed', False


def validate_overrides(value):
    """Allow only reviewed public poster IDs and academic program evidence."""
    if value is None:
        return {}
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'posters'}
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or not isinstance(value['posters'], dict)):
        raise ValueError('Reviewed academic field configuration is invalid')
    for poster_id, row in value['posters'].items():
        if (not isinstance(poster_id, str) or not re.fullmatch(r'[a-f0-9]{64}', poster_id)
                or not isinstance(row, dict) or set(row) != {'field', 'program'}
                or row['field'] not in INTERNAL_FIELD_IDS or not isinstance(row['program'], str)
                or not 1 <= len(row['program']) <= 120
                or re.search(r'[\n\r@:<>{}/\\]|\d{4,}', row['program'])
                or classify_program(row['program']) != row['field']):
            raise ValueError('Reviewed academic field configuration is invalid')
    return copy.deepcopy(value['posters'])
