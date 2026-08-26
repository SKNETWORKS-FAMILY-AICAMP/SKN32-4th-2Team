from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from rag_pipeline import DocumentLike, normalize_search_query, search_across_vector_stores


class FakeEmbeddingModel:
    def __init__(self) -> None:
        self.queries = []

    def embed_query(self, query: str):
        self.queries.append(query)
        return [0.1, 0.2]


class RecordingReranker:
    def __init__(self) -> None:
        self.pairs = []

    def predict(self, pairs):
        self.pairs = list(pairs)
        return [1.0 if "육아휴직" in candidate else 0.1 for _query, candidate in self.pairs]


class FakeStore:
    def __init__(self, documents) -> None:
        self.documents = documents
        self.requested_k = []

    def similarity_search_with_score_by_vector(self, query_embedding, *, k: int):
        self.requested_k.append(k)
        return self.documents[:k]


def _fake_stores(*, lexical_index: int | None = None):
    stores = {}
    for store_index in range(10):
        documents = []
        for local_index in range(3):
            candidate_index = (store_index * 3) + local_index
            if candidate_index == lexical_index:
                content = "육아휴직 육아휴직 적용 대상과 기간"
            else:
                content = f"일반 후보 문서 번호 {candidate_index}"
            document = DocumentLike(
                page_content=content,
                metadata={
                    "source_file": f"source-{candidate_index}.pdf",
                    "article": f"제{candidate_index}조(테스트)",
                    "section_type": "main",
                },
            )
            documents.append((document, float(candidate_index)))
        stores[f"doc-{store_index:02d}"] = FakeStore(documents)
    return stores


class RetrievalCandidatePoolTests(unittest.TestCase):
    def test_annual_leave_spacing_variants_are_normalized(self) -> None:
        for query in (
            "연차사용 가능일수는 며칠이야?",
            "연차 사용가능일수는 며칠이야?",
            "연차 사용 가능 일수는 며칠이야?",
        ):
            with self.subTest(query=query):
                normalized = normalize_search_query(query)
                self.assertTrue(normalized.startswith(query))
                self.assertTrue(
                    normalized.endswith(
                        "복무규정 연차휴가 사용 가능 일수 재직기간 출근율"
                    )
                )

    def test_normalized_query_is_used_for_embedding_and_reranking(self) -> None:
        stores = _fake_stores()

        _results, embedding, reranker = self._search(
            "연차사용 가능일수는 며칠이야?", stores
        )

        expected = (
            "연차사용 가능일수는 며칠이야? "
            "복무규정 연차휴가 사용 가능 일수 재직기간 출근율"
        )
        self.assertEqual(embedding.queries, [expected])
        self.assertTrue(all(query == expected for query, _candidate in reranker.pairs))

    def test_annual_leave_allowance_query_is_not_expanded_as_leave_days(self) -> None:
        query = "연차수당은 며칠까지 지급되나요?"
        self.assertEqual(normalize_search_query(query), query)

    def _search(self, query: str, stores: dict[str, FakeStore]):
        embedding = FakeEmbeddingModel()
        reranker = RecordingReranker()

        def load_store(vector_path: str, _embedding_model):
            return stores[os.path.basename(vector_path)]

        with patch("rag_pipeline.os.listdir", return_value=list(stores)), patch(
            "rag_pipeline.os.path.isdir", return_value=True
        ), patch("rag_pipeline.load_vector_store_cached", side_effect=load_store):
            results = search_across_vector_stores(
                "질문" if query is None else query,
                "C:\\fake-vector-root",
                embedding,
                reranker,
                top_k=5,
                initial_candidates=20,
            )

        return results, embedding, reranker

    def test_lexical_only_candidate_outside_dense_top_twenty_reaches_reranker(self) -> None:
        stores = _fake_stores(lexical_index=29)

        results, embedding, reranker = self._search("육아휴직", stores)

        self.assertEqual(embedding.queries, ["육아휴직"])
        self.assertEqual(len(reranker.pairs), 20)
        reranker_texts = [candidate for _query, candidate in reranker.pairs]
        lexical_text = next(text for text in reranker_texts if "육아휴직 적용 대상과 기간" in text)
        self.assertIn("source=source-29.pdf", lexical_text)
        self.assertIn("article=제29조(테스트)", lexical_text)
        self.assertIn("section=main", lexical_text)

        self.assertEqual(len(results), 5)
        self.assertIn("육아휴직", results[0]["content"])
        self.assertEqual(
            set(results[0]),
            {
                "doc_id",
                "content",
                "metadata",
                "score",
                "rerank_score",
                "bm25_score",
                "faiss_score",
            },
        )

    def test_all_zero_bm25_keeps_original_dense_top_twenty_order(self) -> None:
        stores = _fake_stores()

        results, _embedding, reranker = self._search("존재하지않는검색어", stores)

        self.assertEqual(len(reranker.pairs), 20)
        candidate_contents = [
            candidate.rsplit("\n", 1)[-1] for _query, candidate in reranker.pairs
        ]
        self.assertEqual(
            candidate_contents,
            [f"일반 후보 문서 번호 {index}" for index in range(20)],
        )
        self.assertEqual(len(results), 5)
        self.assertTrue(all(result["bm25_score"] == 0.0 for result in results))

    def test_each_store_still_fetches_three_and_reranker_pool_is_capped_at_twenty(self) -> None:
        stores = _fake_stores(lexical_index=29)

        _results, _embedding, reranker = self._search("육아휴직", stores)

        self.assertEqual(len(reranker.pairs), 20)
        self.assertTrue(all(store.requested_k == [3] for store in stores.values()))


if __name__ == "__main__":
    unittest.main()
