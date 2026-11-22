#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QuizComplete v2.13 答案分布回归测试。"""

import copy
import hashlib
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD_PATH = ROOT / 'build.py'
SPEC = importlib.util.spec_from_file_location('quiz_complete_build', BUILD_PATH)
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)
LETTERS = 'ABCD'


def option_body(option):
    return option[3:] if option[1:3] == '. ' else option


def correct_bodies(question):
    answer = set(question['answer'].replace(' ', '').split('·'))
    return {
        option_body(question['options'][LETTERS.index(letter)])
        for letter in answer
    }


def make_question(qid, qtype, correct_count, *, explanation='', file='fixture'):
    digest = hashlib.sha256(qid.encode()).hexdigest()
    bodies = []
    for idx, letter in enumerate(LETTERS):
        token = hashlib.sha256(('%s-%s' % (qid, letter)).encode()).hexdigest()[:10]
        bodies.append('%s. 材料%s%s' % (letter, digest[idx], token))
    return {
        'id': qid,
        'type': qtype,
        'question': '测试题干 %s' % qid,
        'options': bodies,
        'answer': ' · '.join(LETTERS[:correct_count]),
        'explanation': explanation,
        'tag': '测试标签',
        'file': file,
        'section': '测试章节',
    }


def make_mixed_questions():
    questions = []
    for cardinality, count in {1: 4, 2: 7, 3: 7, 4: 2}.items():
        for idx in range(count):
            questions.append(
                make_question(
                    'mixed-%d-%d' % (cardinality, idx),
                    'multiple',
                    cardinality,
                    file='mixed',
                )
            )
    return questions


def markdown_for(questions):
    blocks = ['# 测试章节', '', '## 一、不定项选择题', '']
    for idx, question in enumerate(questions, 1):
        blocks.extend([
            '### 第 %d 题（不定项选择题）' % idx,
            '',
            question['question'],
            '',
        ])
        blocks.extend(question['options'])
        blocks.extend([
            '',
            '**答案**：%s' % question['answer'],
            '',
            '**解析**：测试解析 %s' % question['id'],
            '',
            '**知识回溯**：测试标签',
            '',
            '---',
            '',
        ])
    return '\n'.join(blocks)


class AnswerDistributionTests(unittest.TestCase):
    def test_single_positions_balanced_and_correct_content_preserved(self):
        questions = [
            make_question('single-%d' % i, 'single', 1, file='single')
            for i in range(8)
        ]
        expected = {q['id']: correct_bodies(q) for q in questions}

        moved, moved_by_type, _skipped, _refs = BUILD.balance_answer_positions(questions)

        counts = BUILD.collections.Counter(q['answer'] for q in questions)
        self.assertEqual(counts, {'A': 2, 'B': 2, 'C': 2, 'D': 2})
        self.assertEqual(moved, 6)
        self.assertEqual(moved_by_type['single'], 6)
        for question in questions:
            self.assertEqual(correct_bodies(question), expected[question['id']])

    def test_single_and_one_answer_multiple_are_balanced_separately(self):
        singles = [
            make_question('mixed-single-%d' % i, 'single', 1, file='single')
            for i in range(23)
        ]
        multis = [
            make_question('mixed-multi-one-%d' % i, 'multiple', 1, file='multi-one')
            for i in range(5)
        ]
        questions = singles + multis

        BUILD.balance_answer_positions(questions)

        single_counts = BUILD.collections.Counter(q['answer'] for q in singles)
        multi_counts = BUILD.collections.Counter(q['answer'] for q in multis)
        self.assertEqual(sorted(single_counts.values()), [5, 6, 6, 6])
        self.assertEqual(sorted(multi_counts.values()), [1, 1, 1, 2])

    def test_multi_three_and_two_answer_patterns_balanced(self):
        questions = []
        for idx in range(56):
            questions.append(
                make_question('three-%02d' % idx, 'multiple', 3, file='three')
            )
        for idx in range(2):
            questions.append(
                make_question('two-%02d' % idx, 'multiple', 2, file='two')
            )
        original_bodies = {
            q['id']: sorted(option_body(option) for option in q['options'])
            for q in questions
        }
        original_correct = {q['id']: correct_bodies(q) for q in questions}

        _moved, moved_by_type, _skipped, _refs = BUILD.balance_answer_positions(questions)

        three = BUILD.collections.Counter(
            q['answer'] for q in questions if q['file'] == 'three'
        )
        two = BUILD.collections.Counter(
            q['answer'] for q in questions if q['file'] == 'two'
        )
        self.assertEqual(
            set(three.values()), {14},
            '三项正确题应均分到 ABC/ABD/ACD/BCD',
        )
        self.assertEqual(set(two.values()), {1})
        self.assertEqual(len(two), 2)
        self.assertEqual(moved_by_type['multiple'], 44)
        for question in questions:
            self.assertEqual(
                sorted(option_body(option) for option in question['options']),
                original_bodies[question['id']],
            )
            self.assertEqual(correct_bodies(question), original_correct[question['id']])

    def test_mixed_cardinality_profile_passes_audit(self):
        questions = make_mixed_questions()
        BUILD.balance_answer_positions(questions)

        stats, warnings = BUILD.quality_audit(questions)

        relevant = [
            warning for warning in warnings
            if '不定项' in warning or '选项正文' in warning
        ]
        self.assertEqual(relevant, [])
        self.assertEqual(stats['multi_cardinality'], {1: 4, 2: 7, 3: 7, 4: 2})

    def test_single_cardinality_structure_is_reported(self):
        questions = []
        for idx in range(56):
            questions.append(
                make_question('single-card-3-%d' % idx, 'multiple', 3)
            )
        for idx in range(2):
            questions.append(
                make_question('single-card-2-%d' % idx, 'multiple', 2)
            )
        BUILD.balance_answer_positions(questions)

        stats, warnings = BUILD.quality_audit(questions)

        self.assertEqual(stats['multi_cardinality'][1], 0)
        self.assertTrue(any('正确项数量结构偏离' in warning for warning in warnings))

    def test_full_select_is_not_changed_and_is_reported(self):
        questions = [
            make_question('full-%d' % idx, 'multiple', 4)
            for idx in range(10)
        ]
        BUILD.balance_answer_positions(questions)

        self.assertTrue(all(q['answer'] == 'A · B · C · D' for q in questions))
        stats, warnings = BUILD.quality_audit(questions)
        self.assertEqual(stats['multi_full'], 10)
        self.assertTrue(any('全选率' in warning for warning in warnings))

    def test_position_sensitive_option_is_skipped(self):
        question = make_question('fixed-option', 'multiple', 2)
        question['options'][3] = 'D. 以上都对'
        original = copy.deepcopy(question)
        questions = [question]

        _moved, moved_by_type, skipped, _refs = BUILD.balance_answer_positions(questions)

        self.assertEqual(moved_by_type['multiple'], 0)
        self.assertEqual(skipped, [question])
        self.assertEqual(question['answer'], original['answer'])
        self.assertEqual(question['options'], original['options'])

    def test_explicit_multi_heading_with_one_answer_letter(self):
        block = '\n'.join([
            '### 第 1 题（不定项选择题）',
            '',
            '只有一项正确的测试题干（ ）',
            '',
            'A. 正确项',
            'B. 错误项一',
            'C. 错误项二',
            'D. 错误项三',
            '',
            '**答案**：A',
            '',
            '**解析**：测试。',
            '',
            '**知识回溯**：测试标签',
        ])

        question = BUILD.parse_question_block(block, 'single-answer-multiple.md')

        self.assertIsNotNone(question)
        self.assertEqual(question['type'], 'multiple')
        self.assertEqual(question['answer'], 'A')

    def test_explanation_letter_references_are_reported(self):
        questions = [
            make_question(
                'letter-ref-%d' % idx,
                'multiple',
                3,
                explanation='A项与B项都正确，C项也正确。',
            )
            for idx in range(8)
        ]

        moved, _moved_by_type, _skipped, refs = BUILD.balance_answer_positions(questions)

        self.assertGreater(moved, 0)
        self.assertTrue(refs)
        self.assertTrue(all(question in refs for question in questions if question['answer'] != 'A · B · C'))

    def test_duplicate_and_similar_options_are_reported(self):
        first = make_question('duplicate-a', 'single', 1, file='duplicate')
        second = make_question('duplicate-b', 'single', 1, file='duplicate')
        first['options'][1] = 'B. 完全相同的干扰项内容'
        second['options'][2] = 'C. 完全相同的干扰项内容'
        first['options'][2] = 'C. 高度相似的干扰项内容甲乙丙丁'
        second['options'][3] = 'D. 高度相似的干扰项内容甲乙丙戊'

        _groups, _count, similar, _examples, _pairs = BUILD._option_similarity_audit(
            [first, second]
        )
        stats, warnings = BUILD.quality_audit([first, second])

        self.assertGreaterEqual(stats['option_duplicate_groups'], 1)
        self.assertGreaterEqual(similar, 1)
        self.assertTrue(any('完全重复' in warning for warning in warnings))
        self.assertTrue(any('高度相似' in warning for warning in warnings))

    def test_balance_result_is_deterministic(self):
        first = make_mixed_questions()
        second = copy.deepcopy(first)

        BUILD.balance_answer_positions(first)
        BUILD.balance_answer_positions(second)

        self.assertEqual(
            [(q['id'], q['options'], q['answer']) for q in first],
            [(q['id'], q['options'], q['answer']) for q in second],
        )

    def test_strict_audit_cli_exit_codes(self):
        with tempfile.TemporaryDirectory(prefix='quiz-complete-v213-') as tmp:
            tmp_path = pathlib.Path(tmp)
            passing = tmp_path / 'passing'
            failing = tmp_path / 'failing'
            passing.mkdir()
            failing.mkdir()
            (passing / 'questions.md').write_text(
                markdown_for(make_mixed_questions()), encoding='utf-8'
            )
            failed_questions = [
                make_question('bad-%d' % idx, 'multiple', 3, file='bad')
                for idx in range(6)
            ]
            (failing / 'questions.md').write_text(
                markdown_for(failed_questions), encoding='utf-8'
            )

            common = [
                sys.executable,
                str(BUILD_PATH),
                '--title',
                '测试',
                '--modes',
                'topic',
                '--strict-audit',
            ]
            pass_run = subprocess.run(
                common + ['--input', str(passing), '--output', str(tmp_path / 'out-pass')],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=60,
            )
            fail_run = subprocess.run(
                common + ['--input', str(failing), '--output', str(tmp_path / 'out-fail')],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=60,
            )

            self.assertEqual(pass_run.returncode, 0, pass_run.stdout + pass_run.stderr)
            self.assertEqual(fail_run.returncode, 2, fail_run.stdout + fail_run.stderr)
            self.assertIn('严格审计未通过', fail_run.stdout)
            output_html = (tmp_path / 'out-pass' / 'index.html').read_text(encoding='utf-8')
            match = re.search(r'const allQuestions = (\[.*?\]);', output_html, re.DOTALL)
            self.assertIsNotNone(match)
            built = json.loads(match.group(1))
            self.assertEqual(
                BUILD.collections.Counter(
                    len(q['answer'].replace(' ', '').split('·')) for q in built
                ),
                {1: 4, 2: 7, 3: 7, 4: 2},
            )


if __name__ == '__main__':
    unittest.main()
