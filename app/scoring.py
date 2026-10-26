"""Turns raw per-person ratings into a ranking.

Score of a house, always on 0-10:

1. Each person's stars: weighted average of their topics (Ubicación counts double by
   default). A topic they haven't rated yet counts as a neutral 5, so a half-rated house
   can't look perfect.
2. Everyone's opinion together: halfway between the average and the lowest opinion, so a
   house only ranks high when all raters like it.
3. Questions: share of the importance-weighted questions answered Yes ("No sé" is half,
   No is zero), worth QUESTIONS_SHARE of the final score.

Only 10 stars on every topic from everyone plus Yes to every question gives 10.0.
"""
from .db import AMENITIES, FEATURES, TOPICS, get_setting

IMPORTANCE = (0, 1, 2)
DEFAULT_WEIGHTS = {"ubicacion": 2.0}  # topics not listed weigh 1
QUESTIONS_SHARE = 15  # % of the final score that comes from the Yes/No questions
NEUTRAL = 5  # value of a topic a person hasn't rated yet
ANSWER_CREDIT = {1: 1.0, None: 0.5, 0: 0.0}


def weights(conn) -> dict[str, float]:
    """Topic weights keyed by topic, question importance keyed by "q:<question>", "share" in %."""
    out = {}
    for t in TOPICS:
        default = DEFAULT_WEIGHTS.get(t, 1.0)
        try:
            out[t] = max(0.0, float(get_setting(conn, f"weight_{t}", f"{default:g}")))
        except ValueError:
            out[t] = default
    for f in FEATURES:
        value = get_setting(conn, f"importance_{f}", "1")
        out[f"q:{f}"] = int(value) if value.isdigit() and int(value) in IMPORTANCE else 1
    value = get_setting(conn, "questions_share", str(QUESTIONS_SHARE))
    out["share"] = min(50, int(value)) if value.isdigit() else QUESTIONS_SHARE
    return out


def topic_shares(w: dict) -> dict[str, float]:
    """How much of the stars part each topic is worth, in % (for the Settings page)."""
    total = sum(w[t] for t in TOPICS) or 1
    return {t: 100 * w[t] / total for t in TOPICS}


def _avg(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def person_score(rating, w: dict) -> float | None:
    """One person's stars on 0-10, or None if they haven't rated any topic."""
    if rating is None or all(rating[t] is None for t in TOPICS):
        return None
    total = sum(w[t] for t in TOPICS)
    if not total:
        return None
    return sum(w[t] * (rating[t] if rating[t] is not None else NEUTRAL) for t in TOPICS) / total


def together(scores: list[float]) -> float | None:
    """Everyone's opinion in one number: halfway between the average and the lowest one."""
    if not scores:
        return None
    return (sum(scores) / len(scores) + min(scores)) / 2


def questions_score(house, w: dict) -> float | None:
    """Yes/No/unknown answers on 0-10, weighted by importance. None if nothing matters."""
    total = sum(w[f"q:{f}"] for f in FEATURES)
    if not total:
        return None
    return 10 * sum(w[f"q:{f}"] * ANSWER_CREDIT.get(house[f], 0.5) for f in FEATURES) / total


def house_scores(house, ratings, w: dict) -> dict:
    """ratings: rows for this house (one per person)."""
    people = {r["user_id"]: s for r in ratings if (s := person_score(r, w)) is not None}
    stars = together(list(people.values()))
    questions = questions_score(house, w)
    share = w["share"] / 100 if questions is not None else 0
    overall = None if stars is None else (1 - share) * stars + share * (questions or 0)
    return {
        "topics": {t: _avg([r[t] for r in ratings]) for t in TOPICS},
        "people": people,
        "base": stars,
        "questions": questions,
        "overall": overall,
        "amenities_yes": sum(1 for a in AMENITIES if house[a] == 1),
        "amenities_total": len(AMENITIES),
        "rated_by": len(people),
        "ratings": {r["user_id"]: r for r in ratings},
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
