from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any

from card_parser import CardIdentity
from listing_classifier import ListingClassification
from text_safety import safe_text


@dataclass(frozen=True)
class GradingEstimate:
    grading_candidate: bool
    grading_signal_score: int
    confidence: str
    reasons: tuple[str, ...]
    warning: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = "; ".join(self.reasons)
        return data


def estimate_grading_candidate(
    title: str,
    condition: str,
    classification: ListingClassification,
    identity: CardIdentity,
) -> GradingEstimate:
    text = f"{safe_text(title)} {safe_text(condition)}".lower()
    reasons: list[str] = []
    score = 0

    if classification.actionable and classification.raw:
        score += 30
        reasons.append("raw single-card listing")
    else:
        reasons.append("not an eligible raw single card")

    if identity.parallel:
        score += 15
        reasons.append(f"parallel: {identity.parallel}")
    if identity.print_run is not None:
        score += 20 if identity.print_run <= 99 else 8
        reasons.append(f"serial numbered to {identity.print_run}")
    if identity.rookie:
        score += 12
        reasons.append("rookie designation")
    if identity.autograph:
        score += 10
        reasons.append("autograph designation")
    if re.search(r"\b(?:mint|gem|sharp|clean|pack fresh|well centered|centered)\b", text):
        score += 8
        reasons.append("positive condition language")
    if re.search(r"\b(?:damage|damaged|crease|creased|scratch|scratched|print line|off center|oc|dent|dimple|stain)\b", text):
        score -= 45
        reasons.append("negative condition language")
    if classification.graded or classification.damaged:
        score = min(score, 10)

    score = max(0, min(score, 100))
    candidate = classification.actionable and score >= 35
    confidence = "HIGH" if score >= 70 else "MEDIUM" if score >= 45 else "LOW"
    warning = (
        "Title-based estimate only. Review front/back photos, centering, corners, edges, "
        "surface, authenticity, and seller return terms before buying or grading."
    )
    return GradingEstimate(candidate, score, confidence, tuple(reasons), warning)
