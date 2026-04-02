"""Full pipeline test: search -> validate -> report."""
import logging, sys, time, os
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
from services.search_engine import collect_validated_sources, format_validated_report
from services.data_fetcher import fetch_match_analysis_data, FootballFetcher

print("=" * 60)
print("TEST: Full pipeline -- Las Palmas vs Granada (football)")
print("=" * 60)

start = time.time()
result = fetch_match_analysis_data(
    "Las Palmas vs Granada",
    FootballFetcher(),
    "fetch_team_info",
    "[F]",
    match_context={"date": "2026-04-02", "league": "LaLiga2"},
)
elapsed = time.time() - start

print(f"\nTime: {elapsed:.1f}s")
print(f"Result length: {len(result)} chars")
print(f"Has 'validated': {'validated' in result.lower()}")
has_sources = "sources" in result.lower() or "источник" in result.lower()
print(f"Has sources info: {has_sources}")

# Show ASCII-safe portion
safe = result.encode('ascii', 'replace').decode('ascii')
print(f"\n--- First 1200 chars ---")
print(safe[:1200])
print("---")
