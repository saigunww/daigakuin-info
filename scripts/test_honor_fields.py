"""Offline academic-field classification and admissions reconciliation checks."""
from __future__ import annotations

import copy
import json
import unittest

import honor_fields as f
import honor_statistics as h
import test_honor_statistics as fixtures

offer, poster = fixtures.offer, fixtures.poster


class AcademicFieldClassificationTests(unittest.TestCase):
    def test_explicit_major_wins_over_combined_school(self):
        for department, major, expected in [
            ('医歯薬学総合研究科', '薬科学専攻', 'pharmacy'),
            ('医歯薬学研究科', '歯学専攻', 'dentistry'),
            ('医工農学総合教育部', '生命環境学専攻', 'agriculture-environment'),
            ('医学系研究科', '生命医科学専攻', 'life-sciences'),
            ('理工情報生命学術院', '化学学位プログラム', 'chemistry'),
            ('新領域創成科学研究科', 'メディカル情報生命専攻', 'life-sciences'),
            ('工学系研究科', '化学システム工学専攻', 'chemical-systems'),
            ('農学生命科学研究科', '応用生命化学専攻', 'life-sciences'),
            ('物質理工学院', '応用化学系', 'applied-chemistry'),
            ('工学研究科', '工業化学専攻', 'applied-chemistry'),
            ('総合化学院', '総合化学専攻', 'chemistry'),
            ('新領域創成科学研究科', '物質系専攻', 'materials'),
            ('経営管理研究科', '経営管理専攻', 'business'),
            ('保健医療科学研究科', '保健医療科学専攻', 'medicine'),
            ('理工情報生命学術院', '数理物質科学研究群', 'interdisciplinary'),
        ]:
            with self.subTest(major=major):
                self.assertEqual(f.classify_program(department, major), expected)

    def test_broad_school_does_not_guess_a_discipline(self):
        for department in ('医歯薬学研究科', '理学系研究科', '工学系研究科', '理工学部',
                           '理工情報生命学術院', '新領域創成科学研究科', '物質理工学院'):
            with self.subTest(department=department):
                self.assertEqual(f.classify_program(department), 'unconfirmed')

    def test_wide_programs_remain_broad_until_a_specific_course_is_proven(self):
        self.assertEqual(f.classify_program('総合文化研究科', '広域科学専攻'), 'interdisciplinary')
        self.assertEqual(f.classify_program('融合理工学府', '先進理化学専攻'), 'interdisciplinary')
        self.assertEqual(f.classify_program('先進理化学専攻 化学コース'), 'chemistry')

    def test_combined_poster_program_is_split_before_school_fallback(self):
        for full, expected in [
            ('九州大学生物資源環境科学府生命機能科学専攻', 'life-sciences'),
            ('京都大学農学研究科応用生命科学専攻', 'life-sciences'),
            ('生命科学部応用化学科', 'applied-chemistry'),
            ('理工学部機能分子・生命化学科', 'chemistry'),
        ]:
            with self.subTest(program=full):
                self.assertEqual(f.classify_program(full), expected)

    def test_specific_evidence_refines_a_broad_program(self):
        self.assertEqual(f.resolve_fields(['interdisciplinary', 'chemistry', 'unconfirmed']), ('chemistry', False))
        self.assertEqual(f.resolve_fields(['chemistry', 'pharmacy']), ('unconfirmed', True))

    def test_catalog_is_fixed_and_returned_as_a_copy(self):
        catalog = f.public_fields()
        self.assertEqual(len(catalog), 12)
        self.assertEqual(set(catalog[0]['labels']), {'ja', 'zh', 'tw', 'en'})
        catalog[0]['labels']['zh'] = 'changed'
        self.assertEqual(f.public_fields()[0]['labels']['zh'], '医学与医疗')

    def test_reviewed_override_accepts_only_public_academic_evidence(self):
        good = {'schema_version': 1, 'posters': {'a' * 64: {'field': 'chemistry', 'program': '化学学位プログラム'}}}
        self.assertEqual(f.validate_overrides(good), good['posters'])
        for mutation in ('id', 'private', 'mismatch', 'identity', 'extra'):
            value = copy.deepcopy(good)
            if mutation == 'id':
                value['posters']['private source path'] = value['posters'].pop('a' * 64)
            elif mutation == 'private':
                value['posters']['a' * 64]['program'] = '化学 alice@example.com'
            elif mutation == 'mismatch':
                value['posters']['a' * 64]['field'] = 'pharmacy'
            elif mutation == 'identity':
                value['posters']['a' * 64]['program'] = '化学 20270101'
            else:
                value['posters']['a' * 64]['student_id'] = 'PRIVATE'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                f.validate_overrides(value)


class AcademicFieldAggregationTests(unittest.TestCase):
    """Reuse the invented-record fixture without repeating unrelated checks."""

    setUp = fixtures.HonorStatisticsTests.setUp
    tearDown = fixtures.HonorStatisticsTests.tearDown
    api = fixtures.HonorStatisticsTests.api

    def test_same_offer_cross_subjects_has_one_primary_field(self):
        fields = {}
        result = h.build_statistics(self.api([offer()], extra=[offer()]),
                                    [poster(subject='bio'), poster(subject='chem')], fields)
        year = result['years'][0]
        self.assertEqual(result['schema_version'], 2)
        self.assertEqual(year['by_field']['chemistry']['total'], 1)
        self.assertEqual(year['by_field']['chemistry']['by_subject']['bio']['total'], 1)
        self.assertEqual(year['by_field']['chemistry']['by_subject']['chem']['total'], 1)
        self.assertEqual(sum(g['total'] for g in year['by_field'].values()), year['total'])
        self.assertEqual(fields, {'image-1': 'chemistry'})

    def test_verified_source_major_classifies_broad_poster(self):
        fields = {}
        api = self.api([offer(department='工学系研究科', major='化学システム工学専攻')])
        p = poster(department='工学系研究科', major='')
        h.build_statistics(api, [p], fields)
        self.assertEqual(fields['image-1'], 'chemical-systems')

    def test_poster_can_refine_verified_broad_source_with_reviewed_public_program(self):
        image_id = 'b' * 64
        fields = {}
        api = self.api([offer(department='理工情報生命学術院', major='数理物質科学研究群')])
        config = json.loads(self.config.read_text())
        config['poster_links'][image_id] = {'student_id': 'S001', 'department': '理工情報生命学術院',
                                            'major': '数理物質科学研究群', 'basis': 'Invented reviewed proof'}
        self.config.write_text(json.dumps(config))
        (self.root / 'config').mkdir(exist_ok=True)
        (self.root / 'config/honor_fields.json').write_text(json.dumps({'schema_version': 1, 'posters': {
            image_id: {'field': 'chemistry', 'program': '化学学位プログラム'}}}))
        result = h.build_statistics(api, [poster(image=image_id, department='理工情報生命学術院', major='')], fields)
        self.assertEqual(result['years'][0]['total'], 1)
        self.assertEqual(result['years'][0]['by_field']['chemistry']['total'], 1)
        self.assertEqual(fields[image_id], 'chemistry')

    def test_conflict_is_unconfirmed_without_changing_offer_total(self):
        api = self.api([offer()])
        config = json.loads(self.config.read_text())
        config['poster_links']['image-1'] = {'student_id': 'S001', 'department': '理学系研究科',
                                            'major': '化学専攻', 'basis': 'Invented reviewed proof'}
        self.config.write_text(json.dumps(config))
        fields = {}
        result = h.build_statistics(api, [poster(department='薬学系研究科', major='薬科学専攻')], fields)
        self.assertEqual(result['years'][0]['total'], 1)
        self.assertEqual(result['years'][0]['by_field']['unconfirmed']['total'], 1)
        self.assertEqual(result['pending_review_total'], 0)
        self.assertEqual(fields['image-1'], 'unconfirmed')
        review = json.loads(self.review.read_text())
        self.assertEqual(review['field_pending_count'], 1)
        self.assertIn('conflicting', review['field_issues'][0]['reason'])

    def test_pending_poster_has_field_but_never_adds_an_offer(self):
        fields = {}
        result = h.build_statistics(self.api([offer()]), [poster(name='甲二')], fields)
        self.assertEqual(result['pending_review_total'], 1)
        self.assertEqual(result['years'][0]['total'], 1)
        self.assertEqual(result['years'][0]['by_field']['chemistry']['total'], 1)
        self.assertEqual(fields['image-1'], 'chemistry')

    def test_unconfirmed_offer_is_not_inferred_from_course_source(self):
        fields = {}
        result = h.build_statistics(self.api([offer(major='未記載', department='理学系研究科')]), [], fields)
        self.assertEqual(result['years'][0]['by_field']['unconfirmed']['total'], 1)
        self.assertEqual(result['years'][0]['by_field']['life-sciences']['total'], 0)

    def test_field_export_rejects_unknown_keys_and_mismatched_totals(self):
        original = h.build_statistics(self.api([offer()]), [])
        for mutation in ('extra', 'total', 'subject', 'catalog', 'field'):
            data = copy.deepcopy(original)
            group = data['years'][0]['by_field']['chemistry']
            if mutation == 'extra': group['student_id'] = 'PRIVATE'
            elif mutation == 'total': group['total'] += 1
            elif mutation == 'subject': group['by_subject']['bio']['universities'][0]['count'] += 1
            elif mutation == 'catalog': data['fields'][0]['labels']['zh'] = 'PRIVATE'
            else: data['years'][0]['by_field']['invented'] = group
            with self.subTest(mutation=mutation), self.assertRaises(h.StatisticsError):
                h.validate_statistics(data)

    def test_poster_bindings_are_not_changed_on_source_failure(self):
        fields = {'previous': 'medicine'}
        with self.assertRaises(h.StatisticsError):
            h.build_statistics(self.api([offer(major='')]), [poster()], fields)
        self.assertEqual(fields, {'previous': 'medicine'})


if __name__ == '__main__':
    unittest.main()
