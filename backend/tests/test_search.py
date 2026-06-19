"""Tests for GET /api/search response shape and pagination behavior."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from find_api.core.database import get_db
from find_api.main import app


def _mock_search(client, fake_rows, *, params=None, total_count=None):
    """Call /api/search with mocked embeddings and paginated DB responses."""
    response, _mock_db = _mock_search_with_db(
        client, fake_rows, params=params, total_count=total_count
    )
    return response


def _mock_search_with_db(client, fake_rows, *, params=None, total_count=None):
    """Call /api/search and return the mocked DB for SQL assertions."""
    mock_embedder = MagicMock()
    mock_embedder.embed_text.return_value = [0.0] * 768

    mock_db = MagicMock()
    count_result = MagicMock()
    count_result.scalar.return_value = (
        len(fake_rows) if total_count is None else total_count
    )
    mock_db.execute.side_effect = [count_result, iter(fake_rows)]

    def _override():
        yield mock_db

    app.dependency_overrides[get_db] = _override

    try:
        with (
            patch(
                "find_api.routers.search.settings",
                ML_MODE="mock",
                EMBEDDING_DIM=768,
            ),
            patch(
                "find_api.ml.mock_embedder.get_mock_embedder",
                return_value=mock_embedder,
            ),
        ):
            response = client.get(
                "/api/search", params={"q": "sunset", **(params or {})}
            )
            return response, mock_db
    finally:
        app.dependency_overrides.pop(get_db, None)


class TestSearchResponseShape:
    """Search response shape with mocked data."""

    def test_search_result_shape(self, client):
        fake_row = MagicMock(
            id=1,
            filename="beach.jpg",
            minio_key="images/ab/abc.jpg",
            thumbnail_key="thumbnails/ab/abc.webp",
            thumbnail_content_type="image/webp",
            thumbnail_size=512,
            thumbnail_width=256,
            thumbnail_height=144,
            status="indexed",
            liked=False,
            width=1920,
            height=1080,
            cluster_id=None,
            similarity=0.82,
            metadata_json='{"caption": "a beach", "objects": ["sand"]}',
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        response = _mock_search(client, [fake_row])

        assert response.status_code == 200
        body = response.json()
        assert body["query"] == "sunset"
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["limit"] == 24
        assert body["skip"] == 0
        assert body["has_more"] is False
        assert "results" in body

        result = body["results"][0]
        assert "media_id" in result
        assert "similarity" in result
        assert isinstance(result["similarity"], float)

        meta = result["metadata"]
        expected = {
            "id",
            "filename",
            "minio_key",
            "thumbnail_key",
            "thumbnail_content_type",
            "thumbnail_size",
            "thumbnail_width",
            "thumbnail_height",
            "thumbnail_url",
            "status",
            "liked",
            "width",
            "height",
            "cluster_id",
            "created_at",
            "caption",
            "objects",
            "url",
            "thumbnail_url",
        }
        assert expected.issubset(meta.keys())
        assert meta["thumbnail_url"] == "/api/image/1/thumbnail"

    def test_empty_results(self, client):
        response = _mock_search(client, [])

        assert response.status_code == 200
        body = response.json()
        assert body["results"] == []
        assert body["total"] == 0
        assert body["has_more"] is False

    def test_search_pagination_metadata(self, client):
        fake_rows = [
            MagicMock(
                id=101,
                filename="photo-101.jpg",
                minio_key="images/10/101.jpg",
                thumbnail_key="thumbnails/10/101.webp",
                thumbnail_content_type="image/webp",
                thumbnail_size=256,
                thumbnail_width=128,
                thumbnail_height=72,
                status="indexed",
                liked=False,
                width=1920,
                height=1080,
                cluster_id=None,
                similarity=0.8,
                metadata_json="{}",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            MagicMock(
                id=102,
                filename="photo-102.jpg",
                minio_key="images/10/102.jpg",
                thumbnail_key="thumbnails/10/102.webp",
                thumbnail_content_type="image/webp",
                thumbnail_size=256,
                thumbnail_width=128,
                thumbnail_height=72,
                status="indexed",
                liked=False,
                width=1920,
                height=1080,
                cluster_id=None,
                similarity=0.79,
                metadata_json="{}",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        ]

        response = _mock_search(
            client,
            fake_rows,
            params={"limit": 2, "skip": 2},
            total_count=5,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 5
        assert body["limit"] == 2
        assert body["skip"] == 2
        assert body["page"] == 2
        assert body["has_more"] is True
        assert [row["media_id"] for row in body["results"]] == [101, 102]

    def test_missing_query_returns_422(self, client):
        response = client.get("/api/search")
        assert response.status_code == 422

    def test_no_feedback_search_uses_zero_boost_fallback(self, client):
        response, mock_db = _mock_search_with_db(client, [])

        assert response.status_code == 200
        search_sql = str(mock_db.execute.call_args_list[1].args[0])
        assert "COALESCE(ranking_boost, 0) as ranking_boost" in search_sql
        assert "+ COALESCE(ranking_boost, 0)" in search_sql

    def test_search_orders_by_boosted_score_but_filters_by_similarity(self, client):
        response, mock_db = _mock_search_with_db(client, [])

        assert response.status_code == 200
        search_sql = str(mock_db.execute.call_args_list[1].args[0])
        assert "WHERE similarity > :threshold AND is_hidden = false" in search_sql
        assert "ORDER BY final_score DESC, similarity DESC, id ASC" in search_sql
