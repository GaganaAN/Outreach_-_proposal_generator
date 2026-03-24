"""
Quick diagnostic script — run from the project root to see exactly what
the scraper extracts from a URL and whether the LLM would classify it.

Usage:
    python debug_scraper.py                        # scrape default test URL
    python debug_scraper.py <url>                  # scrape a specific URL
    python debug_scraper.py <url> <kw1,kw2,...>   # scrape + keyword filter
"""
import sys
import asyncio
import os
from dotenv import load_dotenv
load_dotenv()  # load .env FIRST before anything else

# ── 1. Which URL to test ───────────────────────────────────────────────────────
url = sys.argv[1] if len(sys.argv) > 1 else "https://www.linkedin.com/jobs/search/?keywords=Python+data+engineer"
raw_keywords = sys.argv[2] if len(sys.argv) > 2 else "data,python,cloud,AWS,engineer,RFP,procurement"
keywords = [k.strip() for k in raw_keywords.split(",") if k.strip()]

print(f"\n{'='*70}")
print(f"URL:      {url}")
print(f"Keywords: {keywords}")
print(f"{'='*70}\n")


# ── 2. Try crawl4ai (stealth browser) first ───────────────────────────────────
async def crawl_with_playwright(url: str) -> str:
    try:
        from web_scraper.crawler import Crawler
        print("[Crawler] Trying crawl4ai stealth browser...")
        result = await Crawler().crawl(url)
        if result.success and result.content:
            print(f"[Crawler] ✓ crawl4ai success — {len(result.content)} chars")
            return result.content
        else:
            print(f"[Crawler] ✗ crawl4ai failed: {result.error}")
            return ""
    except ImportError:
        print("[Crawler] ✗ web_scraper/crawl4ai not available")
        return ""
    except Exception as e:
        print(f"[Crawler] ✗ crawl4ai error: {e}")
        return ""


def crawl_with_requests(url: str) -> str:
    try:
        import requests
        from bs4 import BeautifulSoup
        print("[Crawler] Trying requests + BeautifulSoup fallback...")
        headers = {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"}
        resp = requests.get(url, timeout=20, headers=headers)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        text = "\n".join(line.strip() for line in text.splitlines() if len(line.strip()) > 30)
        print(f"[Crawler] ✓ requests success — {len(text)} chars")
        return text
    except Exception as e:
        print(f"[Crawler] ✗ requests failed: {e}")
        return ""


# ── 3. Keyword matching ────────────────────────────────────────────────────────
def find_snippets(text: str, keywords: list) -> list:
    lower_kws = [k.lower() for k in keywords]
    paras = [p.strip() for p in text.split("\n") if len(p.strip()) > 60]
    if not keywords:
        return paras[:5]
    matched = [p for p in paras if any(kw in p.lower() for kw in lower_kws)]
    return matched


# ── 4. Run ─────────────────────────────────────────────────────────────────────
async def main():
    # Try playwright first, then fallback
    content = await crawl_with_playwright(url)
    if not content:
        content = crawl_with_requests(url)

    if not content:
        print("\n[RESULT] No content extracted — the URL may require JavaScript rendering.")
        print("         Try a simpler/static page URL instead.")
        return

    print(f"\n[Content] First 500 chars:")
    print("-" * 60)
    print(content[:500])
    print("-" * 60)

    snippets = find_snippets(content, keywords)
    print(f"\n[Keyword Filter] {len(snippets)} matching snippet(s) found (keywords: {keywords})")

    if not snippets:
        all_paras = [p.strip() for p in content.split("\n") if len(p.strip()) > 60]
        print(f"  (Total paragraphs in page: {len(all_paras)})")
        print("  ← No paragraphs matched your keywords. Either the page is empty")
        print("    (JS-rendered), or the keywords don't appear in the text.")
        print("\n  First 3 paragraphs found (regardless of keywords):")
        for i, p in enumerate(all_paras[:3], 1):
            print(f"  {i}. {p[:120]}")
        return

    print("\nTop 3 matching snippets:")
    for i, s in enumerate(snippets[:3], 1):
        print(f"\n  [{i}] {s[:200]}")

    # ── 5. Test LLM classification on first snippet ────────────────────────────
    print("\n" + "="*70)
    print("[LLM] Testing signal classification on first snippet...")
    print("="*70)
    try:
        sys.path.insert(0, ".")
        from app.services.signal_classifier import get_signal_classifier
        classifier = get_signal_classifier()
        result = classifier.classify(snippets[0], source_url=url)
        print(f"\n  signal_type:     {result.signal_type}")
        print(f"  company_name:    {result.company_name}")
        print(f"  confidence:      {result.confidence_score:.2f}  (threshold: 0.60)")
        print(f"  detected_skills: {result.detected_skills[:5]}")
        print(f"  reasoning:       {result.reasoning}")

        if result.signal_type == "other":
            print("\n  → Signal type is 'other' — this snippet will NOT be saved.")
            print("    Tip: Use a URL/keywords with clearer RFP / job hiring language.")
        elif result.confidence_score < 0.6:
            print(f"\n  → Confidence {result.confidence_score:.2f} is below threshold 0.60 — NOT saved.")
        else:
            print(f"\n  ✓ Would be saved as a {result.signal_type} signal!")
    except Exception as e:
        print(f"  [LLM] Skipped (GROQ_API_KEY not set or error): {e}")


asyncio.run(main())
