from fastapi import FastAPI, Query
from pathlib import Path
from typing import Optional

from boss import load_data

base = Path(__file__).parent
rows, stats = load_data(base)

app = FastAPI(title="RxNorm BoSS API")


def match_row(row: dict, q: str) -> bool:
    if not q:
        return True
    q = q.lower()
    hay = [
        row["parent"].get("rxcui"), row["parent"].get("str"), row["parent"].get("tty"),
        row["scdc"].get("rxcui"), row["scdc"].get("str"), row["scdc"].get("tty"),
    ]
    for x in row.get("ai", []):
        hay.extend([x.get("rxcui"), x.get("str"), x.get("kind")])
    for x in row.get("am", []):
        hay.extend([x.get("rxcui"), x.get("str"), x.get("kind")])
    hay.extend(row.get("boss_from", []))
    hay = [(s or "").lower() for s in hay]
    return any(q in s for s in hay)


@app.get("/groups")
def get_groups(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    q: Optional[str] = None,
):
    filtered = [r for r in rows if match_row(r, q)] if q else rows
    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "results": filtered[start:end],
    }


@app.get("/stats")
def get_stats():
    return stats
