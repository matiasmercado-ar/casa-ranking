"""Turns raw per-person ratings into a ranking."""
from .db import AMENITIES, TOPICS, get_setting


def weights(conn) -> dict[str, float]:
    out = {}
    for t in TOPICS:
        try:
            out[t] = max(0.0, float(get_setting(conn, f"weight_{t}", "1")))
        except ValueError:
            out[t] = 1.0
    return out


def _avg(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def house_scores(house, ratings, w: dict[str, float]) -> dict:
    """ratings: rows for this house (one per person). Unrated topics are ignored, not zero."""
    topic_avg = {t: _avg([r[t] for r in ratings]) for t in TOPICS}
    num = sum(topic_avg[t] * w[t] for t in TOPICS if topic_avg[t] is not None)
    den = sum(w[t] for t in TOPICS if topic_avg[t] is not None)
    yes = sum(1 for a in AMENITIES if house[a] == 1)
    return {
        "topics": topic_avg,
        "overall": num / den if den else None,
        "amenities_yes": yes,
        "amenities_total": len(AMENITIES),
        "rated_by": sum(1 for r in ratings if any(r[t] is not None for t in TOPICS)),
    }


def ranking(conn, include_discarded: bool = False) -> list[dict]:
    w = weights(conn)
    houses = conn.execute("SELECT * FROM houses ORDER BY created_at").fetchall()
    by_house: dict[int, list] = {}
    for r in conn.execute("SELECT * FROM ratings"):
        by_house.setdefault(r["house_id"], []).append(r)
    rows = []
    for h in houses:
        if h["status"] == "descartada" and not include_discarded:
            continue
        rows.append({"house": h, **house_scores(h, by_house.get(h["id"], []), w)})
    # Rated houses first by score, then amenities; unrated last; discarded at the very end.
    rows.sort(
        key=lambda r: (
            r["house"]["status"] == "descartada",
            r["overall"] is None,
            -(r["overall"] or 0),
            -r["amenities_yes"],
        )
    )
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows
