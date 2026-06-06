from __future__ import annotations

from .models import ManualReviewItem
from .state_store import StateStore


class ManualQueue:
    def __init__(self, state_store: StateStore):
        self.state_store = state_store

    def enqueue(self, item: ManualReviewItem) -> None:
        self.state_store.enqueue_manual_review(item)

    def list_pending(self) -> list[dict]:
        return self.state_store.list_manual_review(status="pending")

    def get(self, review_id: str) -> dict | None:
        return self.state_store.get_manual_review(review_id)

    def mark_resolved(self, review_id: str) -> None:
        self.state_store.update_manual_review_status(review_id, "resolved")
