"""The offline store applies the same visibility rules as the OpenSearch adapter."""

from __future__ import annotations

from typing import Any

import pytest

from agentic_context_service.adapters.opensearch import (
    SearchRequest,
    TombstoneRequest,
    UpsertRequest,
)
from agentic_context_service.testing.search_store import (
    InMemorySearchStore,
    ReadOnlyStoreError,
)


def _document(record_id: str, text: str, **changes: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "document_id": record_id,
        "chunk_id": f"{record_id}#0",
        "tenant_id": "demo-retail",
        "domain": "pricing",
        "entity_type": "pricing_rule",
        "title": f"Rule {record_id}",
        "content": text,
        "keywords": [record_id],
        "source": {
            "system": "catalog",
            "record_id": record_id,
            "uri": "postgres://x",
            "version": "1",
        },
        "validity": {"source_updated_at": "2026-09-24T12:00:00Z", "is_deleted": False},
        "governance": {
            "classification": "internal",
            "allowed_purposes": ["pricing-analysis"],
            "region": "US",
        },
    }
    document.update(changes)
    return document


def _request(text: str, **changes: Any) -> SearchRequest:
    values: dict[str, Any] = {
        "tenant_id": "demo-retail",
        "text": text,
        "corpora": ("pricing",),
        "classifications": ("internal",),
        "purpose": "pricing-analysis",
        "mode": "lexical",
    }
    values.update(changes)
    return SearchRequest(**values)


@pytest.mark.asyncio
async def test_should_rank_by_matching_words_when_several_records_match() -> None:
    # Given
    store = InMemorySearchStore(
        [
            _document("NS-100", "NS-100 may be discounted at most 20 percent."),
            _document("NS-205", "Discounts above 15 percent need approval."),
            _document("NS-300", "Unrelated shipping note."),
        ]
    )

    # When
    hits = await store.search(_request("discount limit for NS-100"))

    # Then
    assert [hit.document_id for hit in hits] == ["NS-100"]
    assert hits[0].lexical_rank == 1
    assert hits[0].score is not None
    assert hits[0].score > 0


@pytest.mark.asyncio
async def test_should_order_better_matches_first_when_scores_differ() -> None:
    # Given
    store = InMemorySearchStore(
        [
            _document("A", "approval needed"),
            _document("B", "approval needed for discounts above the limit"),
        ]
    )

    # When
    hits = await store.search(_request("approval discounts limit"))

    # Then
    assert [hit.document_id for hit in hits] == ["B", "A"]
    assert [hit.lexical_rank for hit in hits] == [1, 2]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hidden",
    [
        {"tenant_id": "other-retailer"},
        {"domain": "support"},
        {"governance": {"classification": "restricted", "allowed_purposes": ["pricing-analysis"]}},
        {"governance": {"classification": "internal", "allowed_purposes": ["finance-review"]}},
        {"validity": {"source_updated_at": "2026-09-24T12:00:00Z", "is_deleted": True}},
    ],
)
async def test_should_hide_a_record_when_the_request_may_not_see_it(
    hidden: dict[str, Any],
) -> None:
    # Given
    store = InMemorySearchStore([_document("NS-100", "NS-100 discount", **hidden)])

    # When
    hits = await store.search(_request("NS-100 discount"))

    # Then
    assert hits == []


@pytest.mark.asyncio
async def test_should_cap_results_when_more_records_match_than_the_limit() -> None:
    # Given
    store = InMemorySearchStore([_document(f"R-{n}", "discount rule") for n in range(5)])

    # When
    hits = await store.search(_request("discount", limit=2))

    # Then
    assert len(hits) == 2


@pytest.mark.asyncio
async def test_should_count_live_records_per_source_when_asked_for_freshness() -> None:
    # Given
    store = InMemorySearchStore([_document("A", "a"), _document("B", "b")])

    # When
    freshness = await store.freshness(tenant_id="demo-retail", source="catalog")

    # Then
    assert freshness == {"source": "catalog", "live_documents": 2}
    assert await store.ready()


@pytest.mark.asyncio
async def test_should_hold_no_memories_when_asked_for_one() -> None:
    # Given / When / Then
    assert await InMemorySearchStore([]).get(tenant_id="demo-retail", document_id="m") is None


@pytest.mark.asyncio
async def test_should_refuse_writes_when_records_are_fixed() -> None:
    # Given
    store = InMemorySearchStore([])
    upsert = UpsertRequest("demo-retail", "m", "memory", "ns", "memory", {}, 1)
    tombstone = TombstoneRequest("demo-retail", "m", "memory", 1)

    # When / Then
    with pytest.raises(ReadOnlyStoreError):
        await store.upsert(upsert)
    with pytest.raises(ReadOnlyStoreError):
        await store.tombstone(tombstone)
