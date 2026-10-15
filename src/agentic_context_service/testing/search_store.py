"""A read-only, in-memory stand-in for the OpenSearch context store.

It holds documents in the same shape the indexer writes to OpenSearch and decides visibility
with the OpenSearch adapter's own permission check, so tenant, collection, classification and
purpose rules are identical. Ranking is plain word overlap (no vectors), which is enough for
the offline demo and for consumer tests. Assistant memory is not supported.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Final

from agentic_context_service.adapters.opensearch import (
    SearchHit,
    SearchRequest,
    TombstoneRequest,
    UpsertRequest,
    _is_permitted,
)

_WORD: Final = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_TITLE_WEIGHT: Final = 2.0
_STOP_WORDS: Final = frozenset(
    {"a", "an", "and", "are", "can", "do", "for", "how", "is", "it", "of", "on", "or", "the"}
    | {"to", "what", "when", "which", "who", "with", "may", "be", "at", "in", "our", "we"}
)


class ReadOnlyStoreError(RuntimeError):
    """The in-memory store holds a fixed set of records and accepts no writes."""


class InMemorySearchStore:
    """Search a fixed list of indexed documents with the production visibility rules."""

    def __init__(self, documents: Iterable[dict[str, Any]]) -> None:
        self._documents = tuple(documents)

    async def search(self, request: SearchRequest) -> list[SearchHit]:
        """Return permitted documents that share words with the question, best first."""
        ranked = sorted(self._matches(request), key=_best_first)[: request.limit]
        return [_hit(document, score, rank) for rank, (score, document) in enumerate(ranked, 1)]

    def _matches(self, request: SearchRequest) -> list[tuple[float, dict[str, Any]]]:
        wanted = _words(request.text)
        scored = [(_score(doc, wanted), doc) for doc in self._permitted(request)]
        return [(score, doc) for score, doc in scored if score > 0]

    def _permitted(self, request: SearchRequest) -> list[dict[str, Any]]:
        return [doc for doc in self._documents if _is_permitted(doc, request)]

    async def get(self, *, tenant_id: str, document_id: str) -> dict[str, Any] | None:
        """This store holds no assistant memories."""
        del tenant_id, document_id
        return None

    async def upsert(self, request: UpsertRequest) -> None:
        """Refuse writes: the records are fixed when the store is created."""
        raise ReadOnlyStoreError(f"cannot store {request.document_id}: the store is read-only")

    async def tombstone(self, request: TombstoneRequest) -> None:
        """Refuse deletes: the records are fixed when the store is created."""
        raise ReadOnlyStoreError(f"cannot delete {request.document_id}: the store is read-only")

    async def freshness(self, *, tenant_id: str, source: str) -> dict[str, Any]:
        """Count the live records one source system has for one tenant."""
        live = [
            doc
            for doc in self._documents
            if doc["tenant_id"] == tenant_id
            and doc["source"]["system"] == source
            and not doc["validity"]["is_deleted"]
        ]
        return {"source": source, "live_documents": len(live)}

    async def ready(self) -> bool:
        """Always ready: everything is already in memory."""
        return True


def _words(text: str) -> frozenset[str]:
    return frozenset(_WORD.findall(text.lower())) - _STOP_WORDS


def _score(document: dict[str, Any], wanted: frozenset[str]) -> float:
    title = _words(str(document["title"]))
    body = _words(f"{document['content']} {' '.join(document['keywords'])}")
    return _TITLE_WEIGHT * len(wanted & title) + len(wanted & body)


def _best_first(pair: tuple[float, dict[str, Any]]) -> tuple[float, str]:
    score, document = pair
    return (-score, str(document["document_id"]))


def _hit(document: dict[str, Any], score: float, rank: int) -> SearchHit:
    return SearchHit(str(document["document_id"]), document, score, lexical_rank=rank)
