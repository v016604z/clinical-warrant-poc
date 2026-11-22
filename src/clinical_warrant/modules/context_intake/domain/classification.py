"""Typed result contract for the Context Intake classifier."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class IntakeClassificationResult:
    top1_category_id: str
    top1_similarity: float
    top2_category_id: str
    top2_similarity: float
    is_unknown: bool
    model_id: str
    model_revision: str
    catalog_version: str

    def __post_init__(self) -> None:
        for name in ("top1_category_id", "top2_category_id", "model_id", "model_revision", "catalog_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.top1_category_id == self.top2_category_id:
            raise ValueError("Top-1 and Top-2 category IDs must differ")
        for name in ("top1_similarity", "top2_similarity"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number between -1 and 1")
            if not math.isfinite(value) or not -1 <= value <= 1:
                raise ValueError(f"{name} must be a finite number between -1 and 1")
        if self.top1_similarity < self.top2_similarity:
            raise ValueError("Top-1 similarity must be greater than or equal to Top-2 similarity")
        if not isinstance(self.is_unknown, bool):
            raise ValueError("is_unknown must be a boolean")


@dataclass(frozen=True)
class IntakePrototypeCategory:
    category_id: str
    prototypes: tuple[str, ...]
