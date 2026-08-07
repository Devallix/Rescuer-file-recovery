from dataclasses import dataclass, field

from rescuer.exceptions import ConfigurationError


@dataclass(frozen=True)
class HeaderSpec:
    data: bytes
    offset: int = 0


@dataclass(frozen=True)
class FooterSpec:
    data: bytes
    max_gap: int = 1_048_576


@dataclass
class Signature:
    id: str
    extensions: list[str]
    mime: str
    category: str
    label: str
    preview: str
    headers: list[HeaderSpec]
    footer: FooterSpec | None = None
    min_size: int = 0
    max_size: int | None = None
    carve: bool = True

    @property
    def primary_pattern(self) -> bytes:
        return min(self.headers, key=lambda h: len(h.data)).data

    @property
    def confidence(self) -> str:
        length = min(len(h.data) for h in self.headers)
        if length >= 8:
            return "high"
        if length >= 4:
            return "medium"
        return "low"

    def matches_buffer(self, buffer: bytes, base_offset: int) -> bool:
        for h in self.headers:
            pos = base_offset + h.offset
            if pos < 0 or pos + len(h.data) > len(buffer):
                return False
            if buffer[pos:pos + len(h.data)] != h.data:
                return False
        return True


class SignatureRegistry:
    def __init__(self, signatures: list[Signature], categories: dict[str, dict]) -> None:
        self.signatures = signatures
        self.categories = categories
        self._by_id: dict[str, Signature] = {s.id: s for s in signatures}

    @classmethod
    def load(cls, path: str | None = None, custom_dir: str | None = None) -> "SignatureRegistry":
        import json
        from pathlib import Path

        default = Path(__file__).resolve().parent.parent.parent / "data" / "signatures.json"
        p = Path(path) if path else default
        if not p.exists():
            raise ConfigurationError(f"Signature database not found: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        signatures: list[Signature] = []
        for raw in data.get("signatures", []):
            headers = [HeaderSpec(bytes.fromhex(h["bytes"]), h.get("offset", 0))
                       for h in raw.get("headers", [])]
            footer_raw = raw.get("footer")
            footer = FooterSpec(
                bytes.fromhex(footer_raw["bytes"]),
                footer_raw.get("max_gap", 1_048_576),
            ) if footer_raw else None
            signatures.append(
                Signature(
                    id=raw["id"],
                    extensions=raw.get("extensions", []),
                    mime=raw.get("mime", ""),
                    category=raw.get("category", "other"),
                    label=raw.get("label", raw["id"]),
                    preview=raw.get("preview", "binary"),
                    headers=headers,
                    footer=footer,
                    min_size=raw.get("min_size", 0),
                    max_size=raw.get("max_size"),
                    carve=raw.get("carve", True),
                )
            )
        if custom_dir:
            custom_path = Path(custom_dir)
            if custom_path.exists() and custom_path.is_dir():
                for fp in custom_path.glob("*.json"):
                    try:
                        extra = json.loads(fp.read_text(encoding="utf-8"))
                        for raw in extra.get("signatures", []):
                            headers = [HeaderSpec(bytes.fromhex(h["bytes"]), h.get("offset", 0))
                                       for h in raw.get("headers", [])]
                            footer_raw = raw.get("footer")
                            footer = FooterSpec(
                                bytes.fromhex(footer_raw["bytes"]),
                                footer_raw.get("max_gap", 1_048_576),
                            ) if footer_raw else None
                            signatures.append(
                                Signature(
                                    id=raw["id"],
                                    extensions=raw.get("extensions", []),
                                    mime=raw.get("mime", ""),
                                    category=raw.get("category", "other"),
                                    label=raw.get("label", raw["id"]),
                                    preview=raw.get("preview", "binary"),
                                    headers=headers,
                                    footer=footer,
                                    min_size=raw.get("min_size", 0),
                                    max_size=raw.get("max_size"),
                                    carve=raw.get("carve", True),
                                )
                            )
                    except Exception:
                        pass
        return cls(signatures, data.get("categories", {}))

    def get(self, signature_id: str) -> Signature | None:
        return self._by_id.get(signature_id)

    def carveable(self) -> list[Signature]:
        return [s for s in self.signatures if s.carve]

    def find_sig(self, signature_id: str) -> Signature:
        sig = self._by_id.get(signature_id)
        if sig is None:
            raise ConfigurationError(f"Unknown signature id: {signature_id}")
        return sig
