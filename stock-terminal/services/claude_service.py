import re
import json
from typing import Optional, List
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, logger
from services.sentiment import classify_sentiment, EXCLUDE_KEYWORDS, HIGH_IMPORTANCE, CAT_KEYWORDS


def _make_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ---------------------------------------------------------------------------
# News filter
# ---------------------------------------------------------------------------

def _keyword_filter(articles: list[dict]) -> list[dict]:
    """Fallback filter used when ANTHROPIC_API_KEY is not set."""
    results = []
    for a in articles:
        text = (a["title"] + " " + a["summary"]).lower()
        if any(kw in text for kw in EXCLUDE_KEYWORDS):
            continue
        high_hits = sum(1 for kw in HIGH_IMPORTANCE if kw in text)
        cat_hits  = sum(1 for kws in CAT_KEYWORDS.values() for kw in kws if kw in text)
        is_fed = any(kw in text for kw in [
            "federal reserve", "fomc", "powell", "fed meeting",
            "rate decision", "rate hike", "rate cut", "fed statement",
            "ecb", "bank of england", "bank of japan", "central bank",
            "hawkish", "dovish", "basis points", "bps",
        ])
        if not is_fed and high_hits == 0 and cat_hits < 2:
            continue
        if is_fed:
            score = 9 if high_hits >= 2 else 8
        elif high_hits >= 2 or cat_hits >= 5:
            score = 9
        elif high_hits == 1 or cat_hits >= 3:
            score = 8
        else:
            score = 7

        from services.sentiment import classify_category
        results.append({
            **a,
            "importance_score": score,
            "category":         classify_category(text),
            "market_impact":    "",
            "sentiment":        classify_sentiment(text),
        })
    results.sort(key=lambda x: x["importance_score"], reverse=True)
    return results[:25]


def claude_filter(articles: list[dict]) -> list[dict]:
    """Filter + score news articles. Falls back to keyword filter if no API key."""
    if not articles:
        return []
    if not ANTHROPIC_API_KEY:
        return _keyword_filter(articles)

    batch_text = "\n".join(
        f'[{i}] TITLE: {a["title"]}\nSUMMARY: {a["summary"]}'
        for i, a in enumerate(articles)
    )
    system = (
        "You are a financial news filter for a professional equity trading terminal.\n"
        "Your job: identify macro-relevant, market-moving news articles.\n\n"
        "INCLUDE: Fed/central bank decisions, inflation data, jobs reports, GDP surprises, "
        "geopolitical conflicts, oil/gas disruptions, wars, sanctions, major AI regulation, "
        "systemic financial risk, sovereign events, major elections or political instability.\n"
        "EXCLUDE: individual company earnings (unless systemic), crypto minor moves, "
        "sports, lifestyle, celebrity, regional politics with no macro impact, "
        "routine data exactly in-line with forecasts.\n\n"
        "Return a JSON array. Each passing article must have:\n"
        "  id            — original index (integer)\n"
        "  importance_score — 1-10 (10 = market-moving event; only include >= 7)\n"
        "  category      — one of: Fed/Monetary Policy, Geopolitics, Commodities, Tech/AI, Markets, Macro Economy\n"
        "  market_impact — 2 sentences explaining the potential equity market impact, written for a trader\n"
        "Return only a valid JSON array. No markdown, no extra text."
    )
    try:
        client = _make_client()
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": batch_text}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        scored = json.loads(raw)
    except Exception:
        logger.warning("Claude news filter failed, falling back to keyword filter", exc_info=True)
        return _keyword_filter(articles)

    enriched = []
    for item in scored:
        idx = item.get("id")
        if idx is None or not isinstance(idx, int) or idx >= len(articles):
            continue
        score = item.get("importance_score", 0)
        if score < 7:
            continue
        art = dict(articles[idx])
        art["importance_score"] = score
        art["category"]         = item.get("category", "Markets")
        art["market_impact"]    = item.get("market_impact", "")
        art["sentiment"] = classify_sentiment(
            (art.get("title", "") + " " + art.get("summary", "")).lower()
        )
        enriched.append(art)

    enriched.sort(key=lambda x: x["importance_score"], reverse=True)
    return enriched[:20]


# ---------------------------------------------------------------------------
# Portfolio impact (Claude path)
# ---------------------------------------------------------------------------

def claude_portfolio_impact(tickers: list, articles: list) -> Optional[dict]:
    """
    Returns {"impacts": [...]} if Claude is available, None otherwise
    (caller falls back to keyword engine).
    """
    if not ANTHROPIC_API_KEY:
        return None

    def _ticker_label(t) -> str:
        if isinstance(t, dict):
            sym = t.get("ticker", "").upper()
            sec = t.get("sector", "")
            return f"{sym} ({sec})" if sec else sym
        return str(t).upper()

    tickers_str  = ", ".join(_ticker_label(t) for t in tickers[:25])
    articles_text = "\n\n".join(
        f'[{a["id"]}] {a.get("title", "")}\n{a.get("summary", "")[:250]}'
        for a in articles[:25]
    )
    system = (
        f"An equity investor holds: {tickers_str}.\n"
        "Read each numbered news article and identify which holdings are meaningfully affected.\n"
        "Consider: direct mentions, sector-wide impact, macro factor specific to the business.\n\n"
        "Return a JSON array where each entry is:\n"
        '  {"article_id": <int>, "ticker": "<SYMBOL>", '
        '"direction": "Positive"|"Negative"|"Mixed", '
        '"note": "<one sentence: how this news specifically impacts this holding>"}\n\n'
        "Rules:\n"
        "- Only include entries with a specific, genuine connection — not vague macro.\n"
        "- Be concrete: 'Tariff on chips raises NVDA input costs' beats 'may affect markets'.\n"
        "- If an article affects multiple holdings, emit one entry per holding.\n"
        "- Return only a valid JSON array. No markdown, no preamble."
    )
    try:
        client = _make_client()
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": articles_text}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        return {"impacts": json.loads(raw)}
    except Exception:
        logger.warning("Claude portfolio impact failed, falling back to keyword engine", exc_info=True)
        return None
