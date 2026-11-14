"""Check summary evidence, publication limits and safe failure without network calls."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import copy
import unittest

import research_summaries as summaries
import update_research as research

SUMMARY = {
    'ja': '銀ナノ粒子を用いた測定法を小鼠の血清試料で検証した。機械学習との組合せで二つの実験群を識別した。',
    'zh': '研究在小鼠血清样本中验证了银纳米颗粒检测方法。结合机器学习模型后，可以识别两个实验组的差异。',
    'tw': '研究在小鼠血清樣本中驗證了銀奈米顆粒檢測方法。結合機器學習模型後，可以識別兩個實驗組的差異。',
    'en': 'The model distinguished two groups of mouse serum samples with an AUC of 0.973. These results describe the tested mouse experiment.',
}
TODAY = date(2026, 11, 15)


def paper(number, **changes):
    return {'source': 'MED', 'id': str(number), 'title': 'An experimental paper',
            'doi': f'10.1234/paper{number}', 'firstPublicationDate': '2026-11-14',
            'pubTypeList': {'pubType': ['Journal Article']},
            'abstractText': 'A source abstract describing an experiment and its results. ' * 5,
            **changes}


class Response:
    def __init__(self, rows):
        self.rows = rows

    def raise_for_status(self):
        pass

    def json(self):
        return {'hitCount': len(self.rows), 'resultList': {'result': self.rows}}


class SummaryTests(unittest.TestCase):
    def test_four_languages_two_sentences_and_decimals(self):
        self.assertEqual(summaries.validate_summary(SUMMARY), SUMMARY)
        for change in ({'en': 'Only one sentence is not a valid research summary.'},
                       {'zh': SUMMARY['zh'] + '第三句。'},
                       {'ja': SUMMARY['ja'] + '<script>alert(1)</script>'},
                       {'tw': ''}):
            with self.assertRaises(ValueError):
                summaries.validate_summary({**SUMMARY, **change})
        with self.assertRaises(ValueError):
            summaries.validate_summary({'zh': SUMMARY['zh']})

    def test_cache_is_bound_to_source_abstract(self):
        row = {'doi': '10.1234/cache', 'title': 'A paper', 'abstract': 'Original evidence',
               'source_url': 'https://pubmed.ncbi.nlm.nih.gov/123/'}
        with TemporaryDirectory() as directory, patch.object(summaries, 'STATE', Path(directory)):
            summaries.cache_summary(row, SUMMARY)
            with patch.object(summaries.subprocess, 'run', side_effect=AssertionError('No model call')):
                self.assertEqual(summaries.generate_summaries([row]), {row['doi']: SUMMARY})
            self.assertIsNone(summaries.cached_summary({**row, 'abstract': 'Changed evidence'}))

    def test_generation_request_is_bounded(self):
        for rows in ([], [{}] * 4):
            with self.assertRaises(ValueError):
                summaries.generate_summaries(rows)

    def run_update(self, batches, old=None, generator=None):
        archive = copy.deepcopy(old or {'items': []})
        if generator is None:
            generator = lambda rows: {row['doi']: SUMMARY for row in rows}
        with patch.object(research, 'load', return_value=archive), \
             patch.object(research.requests, 'get', side_effect=[Response(r) for r in batches]) as fetch, \
             patch.object(research, 'generate_summaries', side_effect=generator) as generate, \
             patch.object(research, 'dataset', side_effect=lambda name, data: data) as publish:
            result = research.update_research(TODAY)
        return result, fetch, generate, publish

    def test_selects_three_distinct_papers_before_generation(self):
        result, _, generate, publish = self.run_update([
            [paper(1), paper(4)], [paper(1), paper(2)], [paper(2), paper(3)]])
        rows = result['items']
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({r['id'] for r in rows}), 3)
        self.assertEqual({r['category'] for r in rows}, set(research.TOPICS))
        self.assertEqual(len(generate.call_args.args[0]), 3)
        self.assertTrue(all(r['summary'] == SUMMARY and r['summary_source'].startswith(
            'https://pubmed.ncbi.nlm.nih.gov/') for r in rows))
        publish.assert_called_once()

    def test_skips_missing_abstract_and_preserves_existing_papers(self):
        existing = {'id': 'doi:10.1234/previous', 'added_on': '2026-11-13', 'category': 'biology'}
        result, _, _, _ = self.run_update([
            [paper(1, abstractText=''), paper(2)], [], []], {'items': [existing]})
        self.assertEqual(result['items'][-1], existing)
        self.assertEqual(len(result['items']), 2)
        self.assertEqual(result['items'][0]['doi'], '10.1234/paper2')

    def test_daily_limit_avoids_fetch_and_generation(self):
        old = {'items': [{'id': str(i), 'added_on': TODAY.isoformat()} for i in range(3)]}
        result, fetch, generate, publish = self.run_update([], old)
        self.assertEqual(result, old)
        fetch.assert_not_called()
        generate.assert_not_called()
        publish.assert_not_called()

    def test_generation_failure_or_no_supported_summary_never_publishes(self):
        for effect in (RuntimeError('Unavailable'), lambda rows: {}):
            with self.subTest(effect=effect), \
                 patch.object(research, 'load', return_value={'items': []}), \
                 patch.object(research.requests, 'get', side_effect=[Response([paper(1)])] * 3), \
                 patch.object(research, 'generate_summaries', side_effect=effect), \
                 patch.object(research, 'dataset') as publish:
                with self.assertRaises(RuntimeError):
                    research.update_research(TODAY)
                publish.assert_not_called()


if __name__ == '__main__':
    unittest.main()
