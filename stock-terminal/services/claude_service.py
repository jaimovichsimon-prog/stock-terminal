import re
import json
from typing import Optional, List
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, logger
from services.sentiment import EXCLUDE_KEYWORDS, HIGH_IMPORTANCE, CAT_KEYWORDS, classify_category


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

        results.append({
            **a,
            "importance_score": score,
            "category":         classify_category(text),
            "market_impact":    "",
            "reasoning":        "",
        })
    results.sort(key=lambda x: x["importance_score"], reverse=True)
    return results[:40]


def claude_filter(articles: list[dict]) -> list[dict]:
    """Filter + score news articles. Falls back to keyword filter if no API key."""
    if not articles:
        return []
    if not ANTHROPIC_API_KEY:
        return _keyword_filter(articles)

    batch_text = "\n\n".join(
        '[{}] TITLE: {}\nSOURCE: {}\nSUMMARY: {}'.format(
            i, a["title"], a.get("source", ""), (a.get("summary") or "")[:600]
        )
        for i, a in enumerate(articles[:120])
    )

    system = "\n".join([
        "You are a senior macro analyst filtering news for a professional equity trading terminal.",
        "Your job: read every article and return ALL that are relevant to macro markets and equities.",
        "Be GENEROUS -- include anything touching monetary policy, geopolitics, commodities,",
        "tech regulation, or macro economy. Only exclude pure sports, celebrity, lifestyle,",
        "recipes, entertainment, or local news with zero macro relevance.",
        "",
        "IMPORTANCE SCORING -- use the full range, not just 7:",
        "  10: Systemic shock -- Fed emergency rate move, major war declaration, nuclear threat,",
        "      global financial crisis, sovereign default",
        "  9:  Highly market-moving -- Fed rate decision, CPI/PCE beat or miss, NFP blowout or miss,",
        "      active conflict escalation, major sanctions package, OPEC supply announcement",
        "  8:  Significant macro -- GDP release, central bank speech with clear signal,",
        "      major election result, notable tariff announcement, commodity move >3%,",
        "      systemic bank stress, major AI regulation",
        "  7:  Relevant macro -- Fed official commentary, trade policy updates, geopolitical tensions,",
        "      commodity price trends, economic indicator releases (PMI, retail sales, etc.)",
        "  6:  Notable but lower-impact -- analyst macro calls, policy discussions, market technicals,",
        "      sector-wide trends, preliminary data",
        "",
        "Include articles scoring 7 and above. Use the FULL scale -- do not compress into 7.",
        "",
        "CATEGORY DEFINITIONS -- assign the best fit:",
        "  Fed/Monetary Policy: central bank decisions, interest rates, inflation policy,",
        "      Fed/ECB/BOJ/BOE speeches and minutes, quantitative easing/tightening",
        "  Geopolitics: wars, military conflicts, sanctions, diplomatic crises, elections with",
        "      geopolitical consequences, NATO, territorial disputes",
        "  Commodities: oil, gas, gold, copper, agricultural prices, OPEC, energy supply/demand",
        "  Tech/AI: artificial intelligence regulation or breakthroughs, semiconductors,",
        "      big tech antitrust, chip exports, data centers",
        "  Markets: stock market moves, bond yields, credit spreads, IPOs, M&A, hedge funds,",
        "      dollar/FX, market volatility, sector rallies or selloffs",
        "  Macro Economy: GDP growth/contraction, recession signals, jobs/unemployment/payrolls,",
        "      consumer spending, retail sales, housing data, PMI/ISM, trade balances,",
        "      tariffs as economic policy, inflation data (CPI/PCE as economic readings),",
        "      fiscal policy, government spending, debt, cost of living",
        "",
        "Tariff and trade stories go in Macro Economy unless primarily a geopolitical conflict.",
        "GDP, jobs, and inflation data releases always go in Macro Economy.",
        "",
        "Return a JSON array. Each passing article must have these exact fields:",
        "  id               - original index (integer)",
        "  importance_score - integer 7-10",
        "  category         - one of: Fed/Monetary Policy, Geopolitics, Commodities, Tech/AI, Markets, Macro Economy",
        "  reasoning        - 1-2 sentences: what is happening and why it matters to markets",
        "  market_impact    - 2 sentences of equity market impact written for a trader",
        "",
        "Return ONLY a valid JSON array. No markdown, no extra text.",
    ])

    try:
        client = _make_client()
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=6000,
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
        art["reasoning"]        = item.get("reasoning", "")
        enriched.append(art)

    enriched.sort(key=lambda x: x["importance_score"], reverse=True)
    return enriched[:40]


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
