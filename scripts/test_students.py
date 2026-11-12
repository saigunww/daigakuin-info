"""Synthetic roster tests: counting policy, deduplication and public-field boundary."""
import json
import unittest
from unittest.mock import patch
from update_students import ACTIVE, aggregate_students, update_students, validate_student_summary

EXCLUDED = {'休学', '已毕业', '退学'}
ALIASES = {'Example Uni University': 'Example University'}


def record(sid, group='bio', status='在读', school='Example University'):
    return {'student_id': sid, 'group': group, 'status': status, 'school': school}


class StudentTests(unittest.TestCase):
    def summary(self, rows):
        return aggregate_students(rows, ACTIVE, EXCLUDED, ALIASES)

    def test_approved_statuses_missing_school_and_private_fields(self):
        rows = [record('synthetic-a'), record('synthetic-b', status='直考在读'),
                {**record('synthetic-c', 'chem', '待毕业', ''), 'name': 'PRIVATE-NAME', 'email': 'PRIVATE-EMAIL'},
                record('synthetic-d', status='休学'), record('synthetic-e', status='已毕业')]
        data = self.summary(rows)
        self.assertEqual(data['total'], 3)
        self.assertEqual(data['items'], [{'group': 'bio', 'count': 2}, {'group': 'chem', 'count': 1}])
        self.assertEqual(data['schools'], [{'school': 'Example University', 'count': 2}])
        self.assertEqual(data['unknown_school_count'], 1)
        serialized = json.dumps(data)
        for secret in ('synthetic-', 'PRIVATE-', 'student_id', 'email', 'name'):
            self.assertNotIn(secret, serialized)
        validate_student_summary({**data, 'checked_at': '2026-11-12T12:00:00+09:00', 'updated_at': '2026-11-12T12:00:00+09:00'})

    def test_deduplicate_rows_and_cross_subject_enrollment(self):
        rows = [record('synthetic-a'), record('synthetic-a'),
                record('synthetic-a', 'chem', school='Example Uni University'),
                record('synthetic-b', 'chem', school='Example Uni University')]
        data = self.summary(rows)
        self.assertEqual(data['total'], 2)
        self.assertEqual(data['items'], [{'group': 'bio', 'count': 1}, {'group': 'chem', 'count': 2}])
        self.assertEqual(data['schools'], [{'school': 'Example University', 'count': 2}])

    def test_unknown_status_identity_and_conflicts_fail_closed(self):
        cases = [[record('')], [record('synthetic-a', status='unexpected-status')],
                 [record('synthetic-a'), record('synthetic-a', status='休学')],
                 [record('synthetic-a'), record('synthetic-a', 'chem', school='Different University')],
                 [record('synthetic-a', school='Example University\nPRIVATE-NOTE')]]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.summary(rows)

    def test_public_summary_rejects_extra_fields(self):
        data = {**self.summary([record('synthetic-a')]), 'checked_at': '2026-11-12T12:00:00+09:00', 'updated_at': '2026-11-12T12:00:00+09:00'}
        with self.assertRaises(ValueError):
            validate_student_summary({**data, 'student_ids': ['PRIVATE-ID']})
        with self.assertRaises(AssertionError):
            validate_student_summary({**data, 'total': 2})

    def test_second_source_failure_keeps_last_complete_snapshot(self):
        config = {'sources': [{'group': 'bio'}, {'group': 'chem'}], 'active_statuses': list(ACTIVE), 'excluded_statuses': list(EXCLUDED)}
        with patch('update_students.load', return_value=config), patch('update_students.client'), \
                patch('update_students.read_source', side_effect=[[record('synthetic-a')], RuntimeError('Source unavailable')]), \
                patch('update_students.dataset') as publish:
            with self.assertRaises(RuntimeError):
                update_students()
            publish.assert_not_called()


if __name__ == '__main__':
    unittest.main()
