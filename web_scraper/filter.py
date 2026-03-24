"""
URL relevance filter.

Scores each URL returned by the search engine and keeps only those likely
to contain useful content.  Scoring is based on:
  - Presence of known "bad" path patterns  (blog, cart, login …)
  - Presence of known "good" path patterns (product, shop, item …)
  - Keyword overlap between query and URL / title
  - Optional trusted-domain bonus

The filter also learns dynamically: URL path patterns that appear frequently
in a result set are recorded as rules and reused in subsequent calls.
"""

import logging
import re
from collections import Counter, defaultdict
from typing import Dict, List, Tuple
from urllib.parse import urlparse

from web_scraper.models import FilterRule

logger = logging.getLogger(__name__)


# ── Query analysis helpers ─────────────────────────────────────────────────────

def _extract_query_intent(query: str) -> Dict[str, float]:
    intent_signals = {
        "product":     ["mg", "capsules", "tablets", "bottle", "price", "buy", "order", "supplement"],
        "information": ["what is", "how to", "benefits", "side effects", "guide", "learn"],
        "comparison":  ["vs", "versus", "compare", "best", "top", "review"],
        "technical":   ["dosage", "research", "study", "clinical", "mechanism"],
        "shopping":    ["store", "shop", "purchase", "discount", "coupon"],
    }
    q = query.lower()
    return {
        intent: sum(1 for kw in kws if kw in q) / len(kws)
        for intent, kws in intent_signals.items()
        if any(kw in q for kw in kws)
    }


def _extract_keywords(query: str) -> List[str]:
    stop = {"the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by"}
    cleaned = re.sub(r"[^\w\s-]", " ", query.lower())
    words = [w for w in cleaned.split() if len(w) > 2 and w not in stop]
    compound = re.findall(r"\b\w+[-_]\w+\b", query.lower())
    return list(set(words + compound))


def _url_info(url: str) -> Dict:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    return {
        "domain":          parsed.netloc,
        "path_depth":      len(parts),
        "has_product_id":  any(p.isdigit() for p in parts),
        "has_params":      bool(parsed.query),
        "path_keywords":   parts,
    }


def _keyword_relevance(keywords: List[str], url: str, title: str) -> float:
    if not keywords:
        return 0.0
    url_l, title_l = url.lower(), title.lower()
    score = 0.0
    for kw in keywords:
        kw_l = kw.lower()
        if kw_l in url_l:
            score += 0.4
        elif kw_l in title_l:
            score += 0.3
        elif len(kw_l) > 4 and any(kw_l in word for word in (url_l + " " + title_l).split()):
            score += 0.1
    return min(1.0, score / len(keywords))


def _generate_dynamic_rules(query: str, results: List[Dict]) -> List[FilterRule]:
    intent = _extract_query_intent(query)
    url_patterns: Counter = Counter()
    for item in results:
        for part in _url_info(item.get("url", ""))["path_keywords"]:
            url_patterns[part] += 1
    total = len(results) or 1
    rules = []
    for pattern, count in url_patterns.most_common(5):
        freq = count / total
        if freq > 0.3:
            confidence = 0.7 if "product" in intent else 0.3
            rules.append(FilterRule(
                pattern=pattern,
                rule_type="url",
                confidence=confidence,
                context_tags=set(intent.keys()),
            ))
    return rules


# ── Main filter class ──────────────────────────────────────────────────────────

class ContentFilter:
    """
    General-purpose URL relevance filter.

    Pass ``unwanted_patterns`` / ``product_indicators`` / ``trusted_domains``
    to customise it for any domain — or leave the defaults for generic use.
    """

    DEFAULT_UNWANTED = [
        "/blog/", "/article/", "/news/", "/press/",
        "/about", "/contact", "/support", "/help",
        "/terms", "/privacy", "/shipping", "/returns",
        "/account", "/login", "/register", "/checkout",
        "/policy", "/warranty", "/footer", "/header",
        "/cart", "/wishlist", "/pdf",
    ]

    DEFAULT_PRODUCT_INDICATORS = [
        "/product/", "/products/", "/p/", "/item/",
        "/pr/", "/shop/", "/store/", "/buy/",
        "/dp/", "/pd/", "/sku/",
    ]

    def __init__(
        self,
        unwanted_patterns: List[str] = None,
        product_indicators: List[str] = None,
        trusted_domains: List[str] = None,
    ):
        self.unwanted_patterns = unwanted_patterns or self.DEFAULT_UNWANTED
        self.product_indicators = product_indicators or self.DEFAULT_PRODUCT_INDICATORS
        self.trusted_domains = trusted_domains or []
        self.learned_rules: List[FilterRule] = []
        self.domain_profiles: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

    # ── Private helpers ────────────────────────────────────────────────────────

    def _is_unwanted(self, url: str) -> bool:
        u = url.lower()
        return any(p in u for p in self.unwanted_patterns)

    def _has_product_indicator(self, url: str) -> bool:
        u = url.lower()
        return any(p in u for p in self.product_indicators)

    def _is_trusted(self, url: str) -> bool:
        domain = urlparse(url).netloc.lower()
        return any(t in domain for t in self.trusted_domains)

    def _score(self, item: Dict, keywords: List[str]) -> float:
        url = item.get("url", "")
        title = item.get("title", "") or ""
        info = _url_info(url)
        score = 0.0

        if self._is_unwanted(url):
            score -= 0.8
        if self._has_product_indicator(url):
            score += 0.6
        if keywords:
            score += _keyword_relevance(keywords, url, title) * 1.2
        if self._is_trusted(url):
            score += 0.3
        if info["has_product_id"] and self._has_product_indicator(url):
            score += 0.2

        domain = info["domain"]
        score += self.domain_profiles[domain].get("quality", 0.0) * 0.2

        return max(0.0, min(1.0, score))

    # ── Public API ─────────────────────────────────────────────────────────────

    def apply(
        self,
        query: str,
        results: List[Dict],
        learning_mode: bool = True,
    ) -> Tuple[List[Dict], Dict]:
        """
        Score, filter, and sort ``results``.

        Returns ``(filtered_results, stats)``.
        """
        intent = _extract_query_intent(query)
        keywords = _extract_keywords(query)

        if learning_mode:
            new_rules = _generate_dynamic_rules(query, results)
            self.learned_rules.extend(new_rules)

        threshold = 0.2
        if intent.get("product", 0) > 0.5:
            threshold = 0.3
        elif "information" in intent:
            threshold = 0.15
        if len(keywords) > 2:
            threshold += 0.1

        stats = {
            "total_input": len(results),
            "intent": intent,
            "keywords": keywords,
            "threshold": threshold,
            "filtered_out": 0,
        }

        scored = []
        for item in results:
            base_score = self._score(item, keywords)
            rule_bonus = sum(
                rule.confidence * 0.1
                for rule in self.learned_rules
                if (
                    any(tag in intent for tag in rule.context_tags)
                    and rule.rule_type == "url"
                    and rule.pattern in item.get("url", "").lower()
                )
            )
            final = base_score + rule_bonus

            if final >= threshold and "pdf" not in item.get("url", "").lower():
                item["_relevance_score"] = final
                scored.append(item)
            else:
                stats["filtered_out"] += 1
                logger.debug(
                    "Filtered (score=%.3f threshold=%.3f): %s",
                    final, threshold, item.get("url", ""),
                )

        scored.sort(key=lambda x: x.get("_relevance_score", 0), reverse=True)
        stats["kept"] = len(scored)
        return scored, stats
