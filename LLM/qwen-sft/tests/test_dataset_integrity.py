from __future__ import annotations

import unittest

from prepare_dataset import find_pii, normalize, similarity, validate_and_convert


SYSTEM = "반드시 한국어로 답변하세요."
HOLDOUT = [
    {"id": "test-a", "group": "held-out-intent", "question": "연차는 며칠인가요?"}
]


def candidate(**overrides):
    row = {
        "id": "train-a",
        "split": "train",
        "intent_group": "new-intent",
        "category": "기타",
        "case_type": "no_context",
        "question": "주차 위치를 알려주세요.",
        "answer": "제공된 규정 문서에서 해당 내용을 찾을 수 없습니다. 담당 부서에 문의해 주세요.",
        "evidence": [],
        "approved": True,
        "reviewer": "reviewer",
    }
    row.update(overrides)
    return row


class DatasetIntegrityTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize(" 연차-일수? "), "연차일수")

    def test_holdout_paraphrase_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "홀드아웃"):
            validate_and_convert(
                [candidate(question="연차는 며칠인가요")], HOLDOUT, SYSTEM
            )

    def test_split_group_overlap_is_rejected(self):
        rows = [candidate(), candidate(id="valid-a", split="valid")]
        with self.assertRaisesRegex(ValueError, "intent_group 중복"):
            validate_and_convert(rows, HOLDOUT, SYSTEM)

    def test_pii_is_rejected(self):
        self.assertIn("이메일", find_pii("문의 주소는 user@example.com 입니다"))

    def test_invalid_evidence_reports_validation_error_not_key_error(self):
        row = candidate(
            case_type="grounded",
            evidence=[{"source_file": "복무규정.pdf"}],
        )
        with self.assertRaisesRegex(ValueError, "evidence"):
            validate_and_convert([row], HOLDOUT, SYSTEM)

    def test_medium_similarity_requires_manual_overlap_review(self):
        row = candidate(question="연차는 며칠인지")
        score = similarity(row["question"], HOLDOUT[0]["question"])
        self.assertGreaterEqual(score, 0.60)
        self.assertLess(score, 0.85)
        with self.assertRaisesRegex(ValueError, "중간 유사도"):
            validate_and_convert([row], HOLDOUT, SYSTEM)

    def test_valid_rows_become_messages(self):
        train, valid, report = validate_and_convert([candidate()], HOLDOUT, SYSTEM)
        self.assertEqual(len(train), 1)
        self.assertEqual(valid, [])
        self.assertEqual([m["role"] for m in train[0]["messages"]], ["system", "user", "assistant"])
        self.assertEqual(report["pii_findings"], 0)

    def test_personal_data_guard_may_have_no_document_context(self):
        row = candidate(
            case_type="personal_data",
            question="제 개인 교육 이수 내역을 확인해 주세요.",
            answer=(
                "현재 대화에서는 개인 교육 이수 기록을 조회할 수 없습니다. "
                "사내 교육 시스템에서 직접 확인해 주세요. "
                "조회가 어렵다면 담당 부서에 문의해 주세요."
            ),
        )
        train, _, _ = validate_and_convert([row], HOLDOUT, SYSTEM)
        self.assertEqual(len(train), 1)

    def test_similarity_is_high_for_spacing_variant(self):
        self.assertGreater(similarity("연차는 며칠인가요", "연차 는 며칠 인가요?"), 0.95)


if __name__ == "__main__":
    unittest.main()
