"""Conservative document-level metadata derived from a PDF filename.

This module deliberately classifies only document scope.  It does not infer
substantive HR rules, eligibility, durations, rates, or other policy facts.
Unknown or ambiguous audiences remain ``전체`` so retrieval can ask for
clarification instead of silently excluding a potentially relevant document.
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Final


AUTHORITY_STATUTE: Final = "statute"
AUTHORITY_INTERNAL: Final = "internal"

AUDIENCE_ALL: Final = "전체"
AUDIENCE_GENERAL_STAFF: Final = "일반 직원"
AUDIENCE_TECHNICAL_RESEARCHER: Final = "기술연구원"
AUDIENCE_LECTURER_TEMPORARY_TEACHER: Final = "강사·임시교원"
AUDIENCE_FACULTY: Final = "교원"
AUDIENCE_PUBLIC_WORKER: Final = "공무직"
AUDIENCE_FIXED_TERM_STAFF: Final = "기간제 직원"


_LEADING_SEQUENCE_RE = re.compile(r"^\s*\d+\s*[.．]\s*")
_PDF_SUFFIX_RE = re.compile(r"\s*\.pdf\s*$", re.IGNORECASE)
_STATUTE_KIND_SUFFIX_RE = re.compile(r"\s*\((?:법률|시행령|시행규칙)\)\s*$")

# These are the statute families shipped with the current corpus.  Requiring a
# known family avoids treating an internal file such as ``감사규정시행규칙``
# as a statute merely because its title contains "시행규칙".
_KNOWN_STATUTE_TITLES: Final = frozenset(
    {
        "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률",
        "공공기관의 운영에 관한 법률",
        "교육공무원법",
        "교육공무원임용령",
        "근로기준법",
        "기간제 및 단시간근로자 보호 등에 관한 법률",
    }
)

# Exact current-corpus names are kept for the categories where a broad keyword
# would be unsafe (for example, "시간선택제 직원" is not assumed to mean the
# same thing as a general employee).
_EXACT_AUDIENCES: Final = {
    "직원인사규정": (AUDIENCE_GENERAL_STAFF,),
    "직원인사규정시행규칙": (AUDIENCE_GENERAL_STAFF,),
    "직원채용에관한지침": (AUDIENCE_GENERAL_STAFF,),
    "직원승진시험시행지침": (AUDIENCE_GENERAL_STAFF,),
    "기술연구원인사규정": (AUDIENCE_TECHNICAL_RESEARCHER,),
    "기술연구원인사규정시행규칙": (AUDIENCE_TECHNICAL_RESEARCHER,),
    "기술연구원성과급적연봉제운영규칙": (AUDIENCE_TECHNICAL_RESEARCHER,),
    "강사인사관리규칙": (AUDIENCE_LECTURER_TEMPORARY_TEACHER,),
    "임시교원인사관리규칙": (AUDIENCE_LECTURER_TEMPORARY_TEACHER,),
    "교원인사규정": (AUDIENCE_FACULTY,),
    "교원연구제에관한규칙": (AUDIENCE_FACULTY,),
    "교원호봉확정지침": (AUDIENCE_FACULTY,),
    "비정년트랙전임교원운영에관한규칙": (AUDIENCE_FACULTY,),
    "정년보장교원호봉승급지침": (AUDIENCE_FACULTY,),
    "공무직직원인사및보수에관한규칙": (AUDIENCE_PUBLIC_WORKER,),
    "계약직직원임용지침": (AUDIENCE_FIXED_TERM_STAFF,),
}


def normalize_document_title(filename: str | os.PathLike[str]) -> str:
    """Return a stable human-readable title from a path or PDF filename.

    Only mechanical normalization is performed: Unicode composition,
    basename extraction, PDF/sequence removal, and whitespace collapsing.
    Meaningful punctuation and parenthetical statute kinds are preserved.
    """

    # NFC composes ordinary Hangul without rewriting the meaningful Korean
    # middle-dot-like character ``ㆍ`` (NFKC would change it to an archaic
    # Hangul code point and break exact statute-family matching).
    raw = unicodedata.normalize("NFC", os.fspath(filename))
    basename = re.split(r"[\\/]", raw)[-1]
    without_suffix = _PDF_SUFFIX_RE.sub("", basename)
    without_sequence = _LEADING_SEQUENCE_RE.sub("", without_suffix)
    return " ".join(without_sequence.split()).strip()


def _compact_title(title: str) -> str:
    return re.sub(r"\s+", "", title)


def infer_authority(document_title: str) -> str:
    """Classify a known statute family; otherwise treat it as internal."""

    base_title = _STATUTE_KIND_SUFFIX_RE.sub("", document_title).strip()
    return (
        AUTHORITY_STATUTE
        if base_title in _KNOWN_STATUTE_TITLES
        else AUTHORITY_INTERNAL
    )


def infer_audience(document_title: str, authority: str | None = None) -> list[str]:
    """Infer a conservative document audience from its title.

    The returned list is ordered and newly allocated.  Statutes and titles
    without a safe classification use ``["전체"]``.
    """

    resolved_authority = authority or infer_authority(document_title)
    if resolved_authority == AUTHORITY_STATUTE:
        return [AUDIENCE_ALL]

    compact = _compact_title(document_title)
    exact = _EXACT_AUDIENCES.get(compact)
    if exact is not None:
        return list(exact)

    # Ordered from the most specific composite/specialized labels to broader
    # ones.  In particular, 교직원 must never collapse to only 직원 or 교원.
    if "교직원" in compact:
        return [AUDIENCE_GENERAL_STAFF, AUDIENCE_FACULTY]
    if "기술연구원" in compact:
        return [AUDIENCE_TECHNICAL_RESEARCHER]
    if "임시교원" in compact or compact.startswith("강사"):
        return [AUDIENCE_LECTURER_TEMPORARY_TEACHER]
    if "공무직" in compact:
        return [AUDIENCE_PUBLIC_WORKER]
    if "계약직직원" in compact or "기간제직원" in compact:
        return [AUDIENCE_FIXED_TERM_STAFF]
    if compact.startswith("교원"):
        return [AUDIENCE_FACULTY]
    if compact.startswith("직원"):
        return [AUDIENCE_GENERAL_STAFF]
    return [AUDIENCE_ALL]


def derive_document_metadata(
    filename: str | os.PathLike[str],
) -> dict[str, str | list[str]]:
    """Build filename-derived metadata suitable for attaching to all chunks."""

    document_title = normalize_document_title(filename)
    authority = infer_authority(document_title)
    return {
        "document_title": document_title,
        "authority": authority,
        "audience": infer_audience(document_title, authority),
    }


__all__ = [
    "AUTHORITY_INTERNAL",
    "AUTHORITY_STATUTE",
    "AUDIENCE_ALL",
    "AUDIENCE_FACULTY",
    "AUDIENCE_FIXED_TERM_STAFF",
    "AUDIENCE_GENERAL_STAFF",
    "AUDIENCE_LECTURER_TEMPORARY_TEACHER",
    "AUDIENCE_PUBLIC_WORKER",
    "AUDIENCE_TECHNICAL_RESEARCHER",
    "derive_document_metadata",
    "infer_audience",
    "infer_authority",
    "normalize_document_title",
]
