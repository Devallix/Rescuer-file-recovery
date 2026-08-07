import re
from dataclasses import dataclass, field

from rescuer.engine.search.engine import FileSearch

_INTENT_PATTERNS: list[tuple[re.Pattern, str, dict]] = [
    (re.compile(r"\b(pdf|documents?)\b", re.I), "documents", {"category": "documents"}),
    (re.compile(r"\b(photo|photos?|image|images?|pictures?|pics?)\b", re.I), "photos", {"category": "photos"}),
    (re.compile(r"\b(video|videos|footage)\b", re.I), "videos", {"category": "videos"}),
    (re.compile(r"\b(audio|music|songs?|mp3)\b", re.I), "audio", {"category": "audio"}),
    (re.compile(r"\b(archive|archives?|zip|compressed)\b", re.I), "archives", {"category": "archives"}),
    (re.compile(r"\b(database|db)\b", re.I), "databases", {"category": "databases"}),
    (re.compile(r"\b(deleted|removed|gone|trashed|recycled?)\b", re.I), "deleted", {"deleted": True}),
    (re.compile(r"\b(existing|live|current|not deleted)\b", re.I), "live", {"deleted": False}),
    (re.compile(r"\b(carved?|signature|raw)\b", re.I), "carved", {"found_by": "signature"}),
    (re.compile(r"\b(excel|spreadsheet|xlsx?)\b", re.I), "spreadsheets", {"category": "spreadsheets"}),
    (re.compile(r"\b(word|docx?|report)\b", re.I), "word documents", {"category": "documents"}),
    (re.compile(r"\b(cad|autocad|dwg)\b", re.I), "cad", {"category": "cad"}),
    (re.compile(r"\b(emails?|outlook|pst|ost)\b", re.I), "emails", {"category": "emails"}),
]

_QUALITY_HINTS = [
    (re.compile(r"\b(best|excellent|top|highest)\b", re.I), 90, "Excellent recoveries (90+):"),
    (re.compile(r"\b(good)\b", re.I), 75, "Good recoveries (75+):"),
    (re.compile(r"\b(partial|damaged|broken|corrupt)\b", re.I), 0, "At-risk recoveries (below 50):", True),
]


@dataclass
class AssistantSuggestion:
    label: str
    filters: dict = field(default_factory=dict)
    query: str = ""
    hint: str = ""


class SmartAssistant:
    def __init__(self, search: FileSearch) -> None:
        self._search = search

    def interpret(self, text: str) -> AssistantSuggestion:
        suggestion = AssistantSuggestion(label="", filters={}, query=text)
        lowered = text.strip().lower()
        if not lowered:
            return suggestion

        matched: list[tuple[str, dict]] = []
        for pattern, label, filters in _INTENT_PATTERNS:
            if pattern.search(text):
                matched.append((label, dict(filters)))

        if matched:
            merged: dict = {}
            for _label, filters in matched:
                merged.update(filters)
            labels = ", ".join(label for label, _ in matched[:3])
            suggestion = AssistantSuggestion(
                label=labels,
                filters=merged,
                query=text,
                hint=self._describe(merged),
            )

        score_bounds: dict | None = None
        for pattern, threshold, label, *invert in _QUALITY_HINTS:
            if pattern.search(text):
                if invert and invert[0]:
                    score_bounds = {"max_score": 49}
                else:
                    score_bounds = {"min_score": threshold}
                suggestion.hint = label
                break

        if score_bounds:
            suggestion.filters.update(score_bounds)

        suggestion.query = self._build_query(suggestion.filters)
        return suggestion

    def suggest(self, text: str, top_n: int = 3) -> list[AssistantSuggestion]:
        """Return ranked suggestions for a partial query string."""
        if not text.strip():
            return []
        results = []
        for pattern, label, filters in _INTENT_PATTERNS:
            if pattern.search(text):
                results.append(
                    AssistantSuggestion(label=f"Filter: {label}", filters=filters,
                                        query=self._build_query(filters), hint=self._describe(filters))
                )
        return results[:top_n]

    def _build_query(self, filters: dict) -> str:
        parts = []
        for key, value in filters.items():
            if key == "deleted":
                parts.append(f"deleted:{'yes' if value else 'no'}")
            elif key == "min_score":
                parts.append(f"min:{value}")
            elif key == "max_score":
                parts.append(f"max:{value}")
            elif key == "found_by":
                parts.append(f"found_by:{value}")
            elif key in ("category",):
                parts.append(f"category:{value}")
            else:
                parts.append(f"{key}:{value}")
        return " ".join(parts)

    def _describe(self, filters: dict) -> str:
        bits = []
        for key, value in filters.items():
            if key == "deleted":
                bits.append("deleted files" if value else "live files")
            elif key == "min_score":
                bits.append(f"quality at least {value}")
            elif key == "max_score":
                bits.append(f"quality below {value}")
            elif key == "found_by":
                bits.append(f"found by {value} scan")
            elif key == "category":
                bits.append(f"{value} category")
            else:
                bits.append(f"{key}={value}")
        return " and ".join(bits) if bits else "no special filters"

    def apply(self, text: str, **base_filters) -> list[dict]:
        suggestion = self.interpret(text)
        return self._search.search(
            suggestion.query,
            **{**base_filters, **{k: v for k, v in suggestion.filters.items() if k not in ("min_score", "max_score")}},
            min_score=base_filters.get("min_score", suggestion.filters.get("min_score", 0)),
            max_score=base_filters.get("max_score", suggestion.filters.get("max_score", 100)),
        )
