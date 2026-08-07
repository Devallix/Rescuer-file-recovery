import os
from dataclasses import dataclass, field

from rescuer.engine.models import FoundFile
from rescuer.engine.quality.verifier import probe_head, verify_content
from rescuer.engine.signatures.registry import Signature


def stars_from_score(score: int) -> int:
    if score >= 90:
        return 5
    if score >= 75:
        return 4
    if score >= 50:
        return 3
    if score >= 25:
        return 2
    return 1


@dataclass
class QualityResult:
    score: int
    stars: int
    confidence: int
    explanation: list[str] = field(default_factory=list)
    checks: dict[str, dict] = field(default_factory=dict)
    duplicate_of: int | None = None

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "stars": self.stars,
            "confidence": self.confidence,
            "explanation": " ".join(self.explanation),
            "duplicate_of": self.duplicate_of,
        }


@dataclass
class _Check:
    earned: float = 0.0
    max: float = 0.0
    note: str = ""


class QualityScorer:
    """Weighted heuristics scoring a FoundFile on a 0-100 scale.

    Weights: detection method 20, integrity 25, size sanity 15,
    name/path 10, parse-test verification 30. Sums to 100.
    """

    def score(
        self,
        found: FoundFile,
        signature: Signature | None = None,
        dup_hashes: set[str] | None = None,
    ) -> QualityResult:
        checks: dict[str, _Check] = {}
        notes: list[str] = []

        checks["detection"] = _Check(*self._detection(found), self._detection_note(found))
        checks["integrity"] = _Check(*self._integrity(found, signature), self._integrity_note(found, signature))
        checks["size"] = _Check(*self._size_sanity(found, signature), self._size_note(found, signature))
        checks["name"] = _Check(*self._name_quality(found), self._name_note(found))
        checks["verify"] = _Check(*self._verify(found), "")

        for c in checks.values():
            if c.note:
                notes.append(c.note)

        total = round(sum(c.earned for c in checks.values()))
        total = max(0, min(100, total))

        duplicate_of = None
        if found.sha256 and dup_hashes and found.sha256 in dup_hashes:
            duplicate_of = -1
            total = max(0, total - 5)
            notes.append("Hash matches a previously recovered file — likely a duplicate.")

        confidence = self._confidence(checks)
        result = QualityResult(
            score=total,
            stars=stars_from_score(total),
            confidence=confidence,
            explanation=notes or ["Recovery looks clean."],
            checks={k: {"earned": v.earned, "max": v.max, "note": v.note} for k, v in checks.items()},
            duplicate_of=duplicate_of,
        )
        return result

    def _detection(self, found: FoundFile) -> tuple[float, float]:
        if found.found_by == "signature":
            return 14, 20
        if found.is_deleted:
            if found.inode is not None and found.size > 0:
                return 18, 20
            return 14, 20
        return 20, 20

    @staticmethod
    def _detection_note(found: FoundFile) -> str:
        if found.found_by == "signature":
            return "Recovered by signature carving — byte-level scan, no filesystem metadata."
        if found.is_deleted:
            return "Filesystem metadata still present (deleted entry) — high reliability."
        return "Intact filesystem entry — live file, no reconstruction needed."

    def _integrity(self, found: FoundFile, sig: Signature | None) -> tuple[float, float]:
        if sig is None:
            return (24, 25) if not found.is_deleted else (20, 25)
        base = {"high": 13, "medium": 9, "low": 6}[sig.confidence]
        if sig.footer:
            earned = base + 11 if found.footer_found else base + 2
        else:
            earned = base + 8
        return min(earned, 25), 25

    @staticmethod
    def _integrity_note(found: FoundFile, sig: Signature | None) -> str:
        if sig is None:
            return "Integrity derived from intact filesystem metadata."
        if sig.footer and not found.footer_found:
            return "No footer found — the last sectors of the file may be missing."
        if sig.footer and found.footer_found:
            return "Signature match ({}), footer found — file appears complete.".format(sig.label)
        return "Signature match ({}) — unbounded format, size capped by scan limits.".format(sig.label)

    def _size_sanity(self, found: FoundFile, sig: Signature | None) -> tuple[float, float]:
        size = found.size
        if size <= 0:
            return 4, 15
        if sig is not None:
            if sig.max_size is not None and size > sig.max_size:
                return 6, 15
            if sig.min_size > 0 and size < sig.min_size:
                return 8, 15
            return 15, 15
        if found.found_by == "signature":
            return 15, 15
        return 15, 15

    @staticmethod
    def _size_note(found: FoundFile, sig: Signature | None) -> str:
        if found.size <= 0:
            return "Reported size is zero — content may be empty."
        if sig is not None and sig.max_size is not None and found.size > sig.max_size:
            return "Recovered size exceeds the signature's expected maximum — possible over-capture."
        if sig is not None and sig.min_size > 0 and found.size < sig.min_size:
            return "Recovered size is below the signature's minimum — possibly truncated."
        return ""

    def _name_quality(self, found: FoundFile) -> tuple[float, float]:
        name = (found.name or "").strip()
        if not name:
            return 3, 10
        lowered = name.lower()
        if name == "recovered" or "recovered." in lowered or lowered.startswith("file"):
            return 5, 10
        if found.found_by == "filesystem":
            return 10, 10
        return 7, 10

    @staticmethod
    def _name_note(found: FoundFile) -> str:
        name = (found.name or "").strip()
        if not name:
            return "No filename available — will be renamed on recovery."
        if found.found_by == "filesystem":
            return "Original filename and path recovered from metadata."
        return "Filename generated from detected signature — original name unavailable."

    def _verify(self, found: FoundFile) -> tuple[float, float]:
        probed = probe_head(found, found.size)
        if probed is None:
            return 15, 30
        head, tail = probed
        try:
            ok, _note = verify_content(found, head, tail)
        except Exception:
            ok = None
        if ok is True:
            return 30, 30
        if ok is False:
            return 6, 30
        return 20, 30

    def _confidence(self, checks: dict[str, _Check]) -> int:
        determined = sum(1 for c in checks.values() if c.earned == c.max or c.max == 0)
        score = 60 + (determined * 8)
        return max(5, min(99, score))


def apply_quality(
    found: FoundFile,
    signature: Signature | None = None,
    dup_hashes: set[str] | None = None,
) -> QualityResult:
    return QualityScorer().score(found, signature, dup_hashes)
