"""Deterministic adapters for consumer tests and local examples."""

from agentic_context_service.testing.embedding import InMemoryEmbeddingCache
from agentic_context_service.testing.memory import (
    FixedClock,
    InMemoryContextStore,
    InMemoryMemoryRepository,
)
from agentic_context_service.testing.policy import StaticPolicy
from agentic_context_service.testing.search_store import InMemorySearchStore

__all__ = [
    "FixedClock",
    "InMemoryContextStore",
    "InMemoryEmbeddingCache",
    "InMemoryMemoryRepository",
    "InMemorySearchStore",
    "StaticPolicy",
]
