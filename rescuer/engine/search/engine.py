import re
import shlex

from rescuer.core.database import Database

_SAFE_RE = re.compile(r"[^a-z0-9_.-]")


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _clean_ext(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("."):
        value = value[1:]
    return _SAFE_RE.sub("", value)


def parse_tokens(text: str) -> dict:
    """Parse free text into structured filters.

    Supported key:value tokens: name, ext, path, score, min, max,
    deleted (yes/no), found_by, category. Bare words apply to name/path.
    """
    filters: dict = {"terms": []}
    for token in shlex.split(text):
        if ":" in token and not token.startswith(("http", "www")):
            key, _, value = token.partition(":")
            key = key.strip().lower()
            value = value.strip().strip('"\'')
            if key in ("name", "filename"):
                filters["name"] = value
            elif key in ("ext", "extension", "type"):
                filters["ext"] = _clean_ext(value)
            elif key in ("path", "folder", "dir"):
                filters["path"] = value
            elif key in ("score", "quality", "min", "min_score"):
                try:
                    filters["min_score"] = int(value)
                except ValueError:
                    filters["terms"].append(token)
            elif key == "max":
                try:
                    filters["max_score"] = int(value)
                except ValueError:
                    filters["terms"].append(token)
            elif key in ("deleted", "is_deleted"):
                filters["deleted"] = value.lower() in ("1", "true", "yes", "y")
            elif key in ("found_by", "method", "source"):
                filters["found_by"] = value.lower()
            elif key in ("category", "cat"):
                filters["category"] = value.lower()
            elif key in ("status",):
                filters["status"] = value.lower()
            else:
                filters["terms"].append(token)
        else:
            filters["terms"].append(token)
    return filters


class FileSearch:
    def __init__(self, db: Database) -> None:
        self._db = db

    def search(
        self,
        text: str = "",
        *,
        scan_id: int | None = None,
        ext: str | None = None,
        category: str | None = None,
        deleted: bool | None = None,
        found_by: str | None = None,
        min_score: int = 0,
        max_score: int = 100,
        status: str | None = None,
        sort: str = "score",
        limit: int = 5000,
        sha256: str | None = None,
        min_size: int = 0,
        max_size: int | None = None,
    ) -> list[dict]:
        filters = parse_tokens(text)
        where, params = self.build_where(
            scan_id=scan_id,
            name=filters.get("name"),
            path=filters.get("path"),
            ext=ext or filters.get("ext"),
            category=category or filters.get("category"),
            deleted=filters.get("deleted") if deleted is None else deleted,
            found_by=found_by or filters.get("found_by"),
            min_score=max(min_score, filters.get("min_score", 0)),
            max_score=min(max_score, filters.get("max_score", 100)),
            status=status or filters.get("status"),
            terms=filters.get("terms", []),
            sha256=sha256,
            min_size=min_size,
            max_size=max_size,
        )
        order = self._order_by(sort)
        sql = f"SELECT * FROM files WHERE {where} {order} LIMIT ?"
        rows = self._db.query(sql, params + [limit])
        return [dict(r) for r in rows]

    def build_where(
        self,
        *,
        scan_id: int | None = None,
        name: str | None = None,
        path: str | None = None,
        ext: str | None = None,
        category: str | None = None,
        deleted: bool | None = None,
        found_by: str | None = None,
        min_score: int = 0,
        max_score: int = 100,
        status: str | None = None,
        terms: list[str] | None = None,
        sha256: str | None = None,
        min_size: int = 0,
        max_size: int | None = None,
    ) -> tuple[str, list]:
        clauses: list[str] = []
        params: list = []
        if scan_id is not None:
            clauses.append("scan_id = ?")
            params.append(scan_id)
        if name:
            clauses.append("(name LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\')")
            params += [f"%{_like_escape(name)}%", f"{_like_escape(name)}%"]
        if path:
            clauses.append("path LIKE ? ESCAPE '\\'")
            params.append(f"%{_like_escape(path)}%")
        if ext:
            clauses.append("REPLACE(LOWER(COALESCE(ext,'')), '.', '') = ?")
            params.append(ext.lower().lstrip("."))
        if category:
            clauses.append("category = ?")
            params.append(category.lower())
        if deleted is not None:
            clauses.append("is_deleted = ?")
            params.append(int(deleted))
        if found_by:
            clauses.append("LOWER(COALESCE(found_by,'')) = ?")
            params.append(found_by.lower())
        if min_size > 0:
            clauses.append("COALESCE(size,0) >= ?")
            params.append(min_size * 1024)
        if max_size is not None and max_size > 0:
            clauses.append("COALESCE(size,0) <= ?")
            params.append(max_size * 1024)
        if sha256:
            clauses.append("sha256 = ?")
            params.append(sha256)
        clauses.append("COALESCE(quality_score,0) >= ?")
        params.append(min_score)
        clauses.append("COALESCE(quality_score,0) <= ?")
        params.append(max_score)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if terms:
            like = " OR ".join("(name LIKE ? ESCAPE '\\' OR path LIKE ? ESCAPE '\\')" for _ in terms)
            clauses.append(f"({like})")
            for t in terms:
                params += [f"%{_like_escape(t)}%", f"%{_like_escape(t)}%"]
        if not clauses:
            return "1=1", []
        return " AND ".join(clauses), params

    @staticmethod
    def _order_by(sort: str) -> str:
        mapping = {
            "score": "quality_score DESC",
            "score_asc": "quality_score ASC",
            "size": "size DESC",
            "size_asc": "size ASC",
            "name": "name COLLATE NOCASE ASC",
            "path": "path COLLATE NOCASE ASC",
            "deleted_at": "deleted_at DESC",
        }
        return f"ORDER BY {mapping.get(sort, 'quality_score DESC')}"

    def count(self, text: str = "", **kwargs) -> int:
        filters = parse_tokens(text)
        where, params = self.build_where(terms=filters.get("terms", []), **{
            k: (kwargs.get(k) if k not in filters else filters.get(k))
            for k in ("scan_id", "ext", "category", "deleted", "found_by", "status")
        }, **{
            "min_score": max(kwargs.get("min_score", 0), filters.get("min_score", 0)),
            "max_score": min(kwargs.get("max_score", 100), filters.get("max_score", 100)),
        })
        row = self._db.query_one(f"SELECT COUNT(*) AS n FROM files WHERE {where}", params)
        return int(row["n"]) if row else 0
