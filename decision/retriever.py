from __future__ import annotations

import math
import struct

from .config import DecisionConfig
from .db_gateway import DecisionDBGateway
from .embedder import EmbeddingProvider
from .models import RetrievedEvent


class VectorRetriever:
    def __init__(self, *, config: DecisionConfig, gateway: DecisionDBGateway, embedder: EmbeddingProvider):
        self.config = config
        self.gateway = gateway
        self.embedder = embedder

    async def retrieve(self, *, query: str, filters: dict | None = None) -> list[RetrievedEvent]:
        results, _trace = await self.retrieve_with_trace(query=query, filters=filters)
        return results

    async def retrieve_with_trace(self, *, query: str, filters: dict | None = None) -> tuple[list[RetrievedEvent], dict]:
        candidates = await self.gateway.list_candidate_events(filters or {})
        fallback_to_unfiltered = False
        if not candidates and filters:
            candidates = await self.gateway.list_candidate_events({})
            fallback_to_unfiltered = True
        if not candidates:
            return [], {
                "candidate_count_before_vector": 0,
                "fallback_to_unfiltered": fallback_to_unfiltered,
                "vector_scored_count": 0,
                "invalid_vector_count": 0,
                "query_vector_dim": 0,
            }

        query_vector = await self.embedder.embed_query(query)
        results: list[RetrievedEvent] = []
        invalid_vector_count = 0
        for event in candidates:
            vector = _decode_vector(event.embedded_summary, expected_dim=len(query_vector))
            if vector is None:
                invalid_vector_count += 1
                continue
            similarity = sum(left * right for left, right in zip(query_vector, vector))
            results.append(RetrievedEvent(event=event, similarity=similarity))
        results.sort(key=lambda item: item.similarity, reverse=True)
        limited = results[: self.config.recall_k]
        return limited, {
            "candidate_count_before_vector": len(candidates),
            "fallback_to_unfiltered": fallback_to_unfiltered,
            "vector_scored_count": len(results),
            "invalid_vector_count": invalid_vector_count,
            "query_vector_dim": len(query_vector),
        }


def _decode_vector(blob: bytes | None, *, expected_dim: int) -> list[float] | None:
    if not blob:
        return None
    try:
        if len(blob) % 4 != 0:
            return None
        vector = [item[0] for item in struct.iter_unpack("<f", blob)]
    except struct.error:
        return None
    if len(vector) != expected_dim:
        return None
    norm = math.sqrt(sum(item * item for item in vector))
    if norm == 0:
        return None
    return [item / norm for item in vector]
