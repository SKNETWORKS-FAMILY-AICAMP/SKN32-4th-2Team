from __future__ import annotations

import unittest

from document_metadata import (
    AUTHORITY_INTERNAL,
    AUTHORITY_STATUTE,
    AUDIENCE_ALL,
    AUDIENCE_FACULTY,
    AUDIENCE_FIXED_TERM_STAFF,
    AUDIENCE_GENERAL_STAFF,
    AUDIENCE_LECTURER_TEMPORARY_TEACHER,
    AUDIENCE_PUBLIC_WORKER,
    AUDIENCE_TECHNICAL_RESEARCHER,
    derive_document_metadata,
    normalize_document_title,
)


class DocumentTitleNormalizationTests(unittest.TestCase):
    def test_path_sequence_pdf_suffix_and_whitespace_are_normalized(self) -> None:
        source = (
            "C:\\documents\\  1. 남녀고용평등과   일ㆍ가정 양립 지원에 관한 "
            "법률(법률) .PDF  "
        )

        self.assertEqual(
            normalize_document_title(source),
            "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률(법률)",
        )

    def test_space_before_extension_is_not_part_of_title(self) -> None:
        self.assertEqual(
            normalize_document_title("유연근무제 운영지침 .pdf"),
            "유연근무제 운영지침",
        )


class DocumentMetadataTests(unittest.TestCase):
    def assertAudience(self, filename: str, expected: list[str]) -> None:
        self.assertEqual(derive_document_metadata(filename)["audience"], expected)

    def test_known_statute_and_subordinate_legislation_are_global(self) -> None:
        for filename in (
            "1.남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률(법률).pdf",
            "2.공공기관의 운영에 관한 법률(시행령).pdf",
            "3.교육공무원법(법률).pdf",
            "4.교육공무원임용령(시행령).pdf",
            "5.근로기준법(법률).pdf",
            "5.근로기준법(시행령).pdf",
            "1.남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률(시행규칙).pdf",
            "6.기간제 및 단시간근로자 보호 등에 관한 법률(법률).pdf",
        ):
            with self.subTest(filename=filename):
                metadata = derive_document_metadata(filename)
                self.assertEqual(metadata["authority"], AUTHORITY_STATUTE)
                self.assertEqual(metadata["audience"], [AUDIENCE_ALL])

    def test_internal_enforcement_rule_is_not_misclassified_as_statute(self) -> None:
        metadata = derive_document_metadata("감사규정시행규칙.pdf")

        self.assertEqual(metadata["authority"], AUTHORITY_INTERNAL)
        self.assertEqual(metadata["audience"], [AUDIENCE_ALL])

    def test_critical_known_audiences_remain_distinct(self) -> None:
        cases = {
            "직원인사규정.pdf": [AUDIENCE_GENERAL_STAFF],
            "기술연구원 인사규정 시행규칙.pdf": [
                AUDIENCE_TECHNICAL_RESEARCHER
            ],
            "강사인사관리 규칙.pdf": [AUDIENCE_LECTURER_TEMPORARY_TEACHER],
            "임시교원인사관리규칙.pdf": [
                AUDIENCE_LECTURER_TEMPORARY_TEACHER
            ],
            "교원인사규정.pdf": [AUDIENCE_FACULTY],
            "공무직 직원 인사 및 보수에 관한 규칙.pdf": [
                AUDIENCE_PUBLIC_WORKER
            ],
            "계약직직원임용지침.pdf": [AUDIENCE_FIXED_TERM_STAFF],
        }

        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                self.assertAudience(filename, expected)

    def test_교직원_expands_to_staff_and_faculty(self) -> None:
        self.assertAudience(
            "교직원 음주운전 비위행위 확인에 관한 지침.pdf",
            [AUDIENCE_GENERAL_STAFF, AUDIENCE_FACULTY],
        )

    def test_ambiguous_special_employee_title_is_not_guessed(self) -> None:
        self.assertAudience(
            "시간선택제 직원에 관한 규칙.pdf",
            [AUDIENCE_ALL],
        )

    def test_unknown_title_remains_global_and_has_only_scope_metadata(self) -> None:
        metadata = derive_document_metadata("새로운 인사 운영 문서.pdf")

        self.assertEqual(
            metadata,
            {
                "document_title": "새로운 인사 운영 문서",
                "authority": AUTHORITY_INTERNAL,
                "audience": [AUDIENCE_ALL],
            },
        )

    def test_audience_list_is_not_shared_between_calls(self) -> None:
        first = derive_document_metadata("직원인사규정.pdf")
        second = derive_document_metadata("직원인사규정.pdf")

        first["audience"].append("변경")
        self.assertEqual(second["audience"], [AUDIENCE_GENERAL_STAFF])


if __name__ == "__main__":
    unittest.main()
