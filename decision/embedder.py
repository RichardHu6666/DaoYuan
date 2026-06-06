from __future__ import annotations

import asyncio
import math
from typing import Any

import httpx

from .config import DecisionConfig


class EmbeddingProvider:
    async def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError

    def close(self) -> None:
        return None


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, config: DecisionConfig):
        self.config = config
        self._client = httpx.Client(
            timeout=self.config.request_timeout_seconds,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def embed_query(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._embed_sync, text)

    def _embed_sync(self, text: str) -> list[float]:
        if not self.config.embedding_api_key:
            raise RuntimeError(
                "Missing embedding API key. Expected it from ~/.bashrc via DECISION_EMBEDDING_API_KEY or OPENAI_API_KEY."
            )
        response = self._client.post(
            f"{self.config.embedding_base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self.config.embedding_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.embedding_model,
                "input": text,
                "dimensions": self.config.embedding_dimensions,
            },
        )
        response.raise_for_status()
        payload = response.json()
        vector = payload["data"][0]["embedding"]
        return _normalize([float(item) for item in vector])

    def close(self) -> None:
        self._client.close()


class LocalBgeM3EmbeddingProvider(EmbeddingProvider):
    def __init__(self, config: DecisionConfig):
        self.config = config
        self._tokenizer = None
        self._model = None
        self._torch = None

    async def embed_query(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._embed_sync, text)

    def _lazy_load(self) -> tuple[Any, Any, Any]:
        if self._tokenizer is not None and self._model is not None and self._torch is not None:
            return self._tokenizer, self._model, self._torch
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "Local BGE-M3 backend requires transformers and torch. "
                "Install them on Jarvis or switch DECISION_EMBEDDING_BACKEND=openai."
            ) from exc
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(self.config.embedding_model)
        self._model = AutoModel.from_pretrained(self.config.embedding_model)
        self._model.eval()
        return self._tokenizer, self._model, self._torch

    def _embed_sync(self, text: str) -> list[float]:
        tokenizer, model, torch = self._lazy_load()
        with torch.no_grad():
            tokens = tokenizer(
                [text],
                padding=True,
                truncation=True,
                max_length=8192,
                return_tensors="pt",
            )
            output = model(**tokens)
            hidden = output.last_hidden_state
            attention = tokens["attention_mask"].unsqueeze(-1).expand(hidden.size()).float()
            pooled = (hidden * attention).sum(dim=1) / attention.sum(dim=1).clamp(min=1e-9)
            arr = pooled[0].detach().cpu().tolist()
        if len(arr) > self.config.embedding_dimensions:
            arr = arr[: self.config.embedding_dimensions]
        elif len(arr) < self.config.embedding_dimensions:
            arr = arr + [0.0] * (self.config.embedding_dimensions - len(arr))
        return _normalize([float(item) for item in arr])


def build_embedding_provider(config: DecisionConfig) -> EmbeddingProvider:
    backend = config.embedding_backend.strip().lower()
    if backend == "openai":
        return OpenAIEmbeddingProvider(config)
    if backend == "local_bge_m3":
        return LocalBgeM3EmbeddingProvider(config)
    raise RuntimeError(f"Unsupported embedding backend: {config.embedding_backend}")


def _normalize(arr: list[float]) -> list[float]:
    norm = math.sqrt(sum(item * item for item in arr))
    if norm == 0:
        return arr
    return [item / norm for item in arr]
