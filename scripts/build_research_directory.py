"""Build the reviewed laboratory directory; independent of the daily paper feed."""
from collections import Counter
from html import escape
from pathlib import Path
import argparse
import json
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ('ja', 'zh', 'tw', 'en')
START = '<!-- RESEARCH DIRECTORY START -->'
END = '<!-- RESEARCH DIRECTORY END -->'


def lang(values):
    assert set(LANGUAGES) <= set(values)
    return ''.join('<span class="lang-text" data-lang="' + key + '"' +
                   ('' if key == 'ja' else ' style="display:none"') + '>' +
                   escape(values[key]) + '</span>' for key in LANGUAGES)


def localized(zh, tw, ja, en):
    return lang(dict(zh=zh, tw=tw, ja=ja, en=en))


def valid_url(value):
    parsed = urlsplit(value)
    assert parsed.scheme in ('http', 'https') and parsed.hostname, value
    assert not parsed.username and not parsed.password, value
    return escape(value, quote=True)


def load_catalog():
    data = json.loads((ROOT / 'config/research_labs.json').read_text())
    fields, labs = data['fields'], data['labs']
    assert re.fullmatch(r'\d{4}-\d{2}-\d{2}', data['checked_at'])
    field_ids = [f['id'] for f in fields]
    assert len(set(field_ids)) == len(field_ids)
    assert set(f['subject'] for f in fields) == {'bio', 'chem'}
    for f in fields:
        assert re.fullmatch(r'[a-z][a-z_]*', f['id'])
        for key in ('label', 'description'):
            assert all(f[key].get(code) for code in LANGUAGES), f
    seen = set()
    for row in labs:
        assert row['field'] in field_ids
        assert all(row.get(k) for k in ('id', 'university', 'department', 'lab', 'pi', 'url', 'references', 'keywords'))
        # Each lab keeps the date its official sources were checked; the catalog date is the latest.
        assert re.fullmatch(r'\d{4}-\d{2}-\d{2}', row['checked_at']) and row['checked_at'] <= data['checked_at']
        identity = (row['university'], re.sub(r'\s+', '', row['pi']))
        assert identity not in seen, ('Duplicate lab', identity)
        seen.add(identity)
        for code in LANGUAGES:
            assert row.get('theme_' + code) and row.get('summary_' + code), (row['id'], code)
        valid_url(row['url'])
        for ref in row['references']:
            valid_url(ref['url'])
            assert ref['evidence']
    counts = Counter(row['field'] for row in labs)
    assert set(counts) == set(field_ids)
    assert min(counts.values()) >= 2
    assert len({row['id'] for row in labs}) == len(labs)
    return data


def render(data):
    fields, labs = data['fields'], data['labs']
    checked = data['checked_at']
    counts = Counter(row['field'] for row in labs)
    universities = len({row['university'] for row in labs})
    n, f = len(labs), len(fields)
    out = [START, '<div class="section" id="research">', '<div class="section-hero"><h2>' +
           localized('日本大学研究室 · 按领域查询', '日本大學研究室 · 按領域查詢',
                     '日本の大学研究室・分野別ガイド', 'Japanese University Labs by Research Field') + '</h2></div>']
    out += ['<div class="research-directory-intro">' +
            localized('按生物、化学常见研究领域，概述日本各大学代表性研究室的研究问题与方法。可先选领域，再比较研究主题；也可搜索大学、研究室或关键词。',
                      '按生物、化學常見研究領域，概述日本各大學代表性研究室的研究問題與方法。可先選領域，再比較研究主題；也可搜尋大學、研究室或關鍵詞。',
                      '生物・化学の主要分野ごとに、日本の大学の代表的な研究室と研究課題・手法を紹介します。分野を選んで比較するほか、大学・研究室・キーワードでも検索できます。',
                      'Explore representative Japanese university labs by biology and chemistry research field. Compare their questions and methods, or search by university, lab and keyword.') + '</div>',
            '<p class="research-directory-meta">' +
            localized(f'{f}个领域 · {n}个研究室 · {universities}所大学 · 官网信息核查：{checked}',
                      f'{f}個領域 · {n}個研究室 · {universities}所大學 · 官網資訊核查：{checked}',
                      f'{f}分野・{n}研究室・{universities}大学｜公式情報確認：{checked}',
                      f'{f} fields · {n} labs · {universities} universities · Official sources checked: {checked}') + '</p>',
            '<p class="research-directory-scope">' +
            localized('本目录为代表性研究室导览，并非全日本完整名录。所属及研究内容依据所列官网整理，招生安排请查看各研究室与研究科的最新通知。',
                      '本目錄為代表性研究室導覽，並非全日本完整名錄。所屬及研究內容依據所列官網整理，招生安排請查看各研究室與研究科的最新通知。',
                      '代表的な研究室を紹介するガイドであり、全国の全研究室を網羅するものではありません。所属・研究内容は掲載の公式情報に基づきます。募集状況は研究室・研究科の最新案内をご確認ください。',
                      'This is a representative guide, not a complete national directory. Affiliations and summaries are based on the linked official sources. Check current lab and graduate-school notices for admissions.') + '</p>',
            '<div class="research-directory-search"><label for="research-lab-query">' +
            localized('搜索全部研究室', '搜尋全部研究室', '全研究室を検索', 'Search all labs') +
            '</label><input type="search" id="research-lab-query" autocomplete="off" placeholder="大学 / 研究室 / RNA / AI">',
            '<p id="research-match-count" aria-live="polite"></p></div>',
            '<div id="research-main-tabs" role="group">']
    subject_labels = {
        'bio': dict(ja='🧬 生物系', zh='🧬 生物', tw='🧬 生物', en='🧬 Biology'),
        'chem': dict(ja='⚗️ 化学系', zh='⚗️ 化学', tw='⚗️ 化學', en='⚗️ Chemistry'),
    }
    first = {subject: next(f['id'] for f in fields if f['subject'] == subject) for subject in subject_labels}
    for subject, labels in subject_labels.items():
        out.append(f'<button type="button" class="research-main-tab{" active" if subject == "bio" else ""}" data-rmt="{subject}" onclick="switchResearchMain(\'{subject}\')">{lang(labels)}</button>')
    out.append('</div>')
    for subject in subject_labels:
        out.append(f'<div class="research-filter" id="research-{subject}-filters"' + ('' if subject == 'bio' else ' style="display:none"') + '>')
        for field in fields:
            if field['subject'] != subject:
                continue
            key = field['id']
            out.append(f'<button type="button" class="research-filter-btn{" active" if key == first[subject] else ""}" data-rf="{key}" onclick="filterResearch(\'{key}\')">{lang(field["label"])} <span class="research-field-count">{counts[key]}</span></button>')
        out.append('</div>')
    out.append('<p id="research-empty" style="display:none" role="status">' + localized('没有找到匹配的研究室，请更换大学名称或关键词。', '沒有找到匹配的研究室，請更換大學名稱或關鍵詞。', '該当する研究室がありません。大学名やキーワードを変更してください。', 'No labs match. Try another university name or keyword.') + '</p>')
    out.append('<div class="research-section" id="research-content">')
    for field in fields:
        key, subject = field['id'], field['subject']
        style = '' if key == first['bio'] else ' style="display:none"'
        out.append(f'<div class="research-field" id="research-{key}" data-field="{key}" data-subject="{subject}"{style}>')
        out.append('<h3 class="research-field-title">' + lang(field['label']) + '</h3>')
        out.append('<p class="research-field-desc">' + lang(field['description']) + '</p>')
        for row in labs:
            if row['field'] != key:
                continue
            out.append('<article class="research-card" id="lab-' + escape(row['id'], quote=True) + '" data-lab-id="' + escape(row['id'], quote=True) + '" data-search="' + escape(' '.join(row.get('aliases', [])), quote=True) + '">')
            out.append('<div class="research-card-uni">' + escape(row['university'] + ' ｜ ' + row['department']) + '</div>')
            out.append('<h4 class="research-card-lab">' + escape(row['lab']) + '</h4>')
            out.append('<div class="research-card-prof">' + localized('负责人：', '負責人：', '研究代表者：', 'Research lead: ') + escape(row['pi']) + '</div>')
            out.append('<div class="research-card-theme">' + lang({code: row['theme_' + code] for code in LANGUAGES}) + '</div>')
            out.append('<p class="research-card-desc">' + lang({code: row['summary_' + code] for code in LANGUAGES}) + '</p>')
            out.append('<div class="research-card-tags">' + ''.join('<span class="research-card-tag">' + escape(word) + '</span>' for word in row['keywords']) + '</div>')
            out.append('<a class="research-card-link" href="' + valid_url(row['url']) + '" target="_blank" rel="noopener noreferrer">' + localized('研究室／大学官网 ↗', '研究室／大學官網 ↗', '研究室・大学公式サイト ↗', 'Official lab / university page ↗') + '</a>')
            out.append('<details class="research-card-sources"><summary>' + localized('官方依据与核查日期', '官方依據與核查日期', '公式情報と確認日', 'Official sources and review date') + '</summary><p>' + escape(row['checked_at']) + '</p><ul>')
            for i, ref in enumerate(row['references'], 1):
                out.append('<li><a href="' + valid_url(ref['url']) + '" target="_blank" rel="noopener noreferrer">' + localized(f'官方来源 {i}', f'官方來源 {i}', f'公式出典 {i}', f'Official source {i}') + ' · ' + escape(urlsplit(ref['url']).hostname) + '</a></li>')
            out.append('</ul>')
            if row.get('source_note'):
                out.append('<p class="research-source-note">' + lang(row['source_note']) + '</p>')
            out.append('</details></article>')
        out.append('</div>')
    out.extend(['</div></div>', END])
    return '\n'.join(out)


def build(check=False):
    data = load_catalog()
    generated = render(data)
    path = ROOT / 'index.html'
    source = path.read_text()
    if START in source:
        a, b = source.index(START), source.index(END) + len(END)
    else:
        a = source.index('<div class="section" id="research">')
        b = source.index('<div class="section" id="daily-research">', a)
    result = source[:a] + generated + source[b:]
    if check:
        assert result == source, 'Run scripts/build_research_directory.py to refresh static cards'
    else:
        path.write_text(result)
    return {'fields': len(data['fields']), 'labs': len(data['labs']), 'universities': len({r['university'] for r in data['labs']}), 'checked_at': data['checked_at']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    print(json.dumps(build(args.check), ensure_ascii=False))
