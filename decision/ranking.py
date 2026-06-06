from __future__ import annotations

from .config import DecisionConfig
from .models import RetrievedEvent
from .utils import now_utc, parse_datetime


class RuleRanker:
    def __init__(self, config: DecisionConfig):
        self.config = config

    def rank(self, retrieved: list[RetrievedEvent], *, user: dict | None, filters: dict | None) -> list[RetrievedEvent]:
        filters = filters or {}
        interests = {str(item).strip().lower() for item in (user or {}).get("interest") or [] if str(item).strip()}
        topic_filters = {str(item).strip().lower() for item in filters.get("topics", []) if str(item).strip()}
        now = now_utc()

        ranked: list[RetrievedEvent] = []
        for item in retrieved:
            score = item.similarity
            reasons: list[str] = [f"similarity={item.similarity:.3f}"]

            event_topics = {topic.strip().lower() for topic in item.event.topics if topic.strip()}
            topic_overlap = event_topics & topic_filters
            if topic_overlap:
                bonus = 0.05 * len(topic_overlap)
                score += bonus
                reasons.append(f"topic+{bonus:.2f}")

            interest_overlap = event_topics & interests
            if interest_overlap:
                bonus = 0.04 * len(interest_overlap)
                score += bonus
                reasons.append(f"interest+{bonus:.2f}")

            end_time = parse_datetime(item.event.regis_end_time)
            if end_time:
                if end_time >= now:
                    score += 0.03
                    reasons.append("future_regis+0.03")
                else:
                    score -= 0.08
                    reasons.append("past_regis-0.08")

            activity_time = parse_datetime(item.event.activity_start_time)
            if activity_time and activity_time >= now:
                score += 0.02
                reasons.append("future_activity+0.02")

            item.final_score = score
            item.reasons = reasons
            ranked.append(item)

        ranked.sort(key=lambda item: item.final_score, reverse=True)
        return ranked[: self.config.final_k]
