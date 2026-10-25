"""Turns raw per-person ratings into a ranking."""
from .db import AMENITIES, FEATURES, TOPICS, get_setting

# Each Yes adds, each No subtracts, BONUS_STEP x the question's importance (0, 1 or 2).
BONUS_STEP = 0.3
IMPORTANCE = (0, 1, 2)


def weights(conn) -> dict[str, float]:
    """Topic weights keyed by topic, question importance keyed by "q:<question>"."""
    out = {}
    for t in TOPICS:
        try:
            out[t] = max(0.0, float(get_setting(conn, f"weight_{t}", "1")))
        except ValueError:
            out[t] = 1.0
    for f in FEATURES:
        value = get_setting(conn, f"importance_{f}", "1")
        out[f"q:{f}"] = int(value) if value.isdigit() and int(value) in IMPORTANCE else 1
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
    sign = {1: 1, 0: -1}
    bonus = round(sum(BONUS_STEP * w[f"q:{f}"] * sign.get(house[f], 0) for f in FEATURES), 2)
    base = num / den if den else None
    # The questions only adjust a house that has stars; the score stays on the 0-10 scale,
    # "raw" (unclamped) is kept for sorting so ties at the edges still order correctly.
    raw = base + bonus if base is not None else None
    return {
        "topics": topic_avg,
        "base": base,
        "bonus": bonus,
        "raw": raw,
        "overall": min(10.0, max(0.0, raw)) if raw is not None else None,
        "amenities_yes": yes,
        "amenities_total": len(AMENITIES),
        "rated_by": sum(1 for r in ratings if any(r[t] is not None for t in TOPICS)),
        "ratings": {r["user_id"]: r for r in ratings},
    }


def ranking(conn, include_discarded: bool = False, visited: str = "") -> list[dict]:
    """visited: "" = all, "si" = only visited, "no" = only not visited."""
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
            -(r["raw"] or 0),
            -r["amenities_yes"],
        )
    )
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    # Filter after numbering so a house keeps its overall position.
    if visited:
        rows = [r for r in rows if bool(r["house"]["visitada"]) == (visited == "si")]
    return rows
