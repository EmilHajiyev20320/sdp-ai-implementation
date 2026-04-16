"""
Test the pipeline with real sources (RSS + NewsData) or seeded bundles.
Usage:
  # Real sources flow (recommended):
  python scripts/test_pipeline.py --fetch --create --generate

  # Seeded bundles (quick smoke test):
  python scripts/test_pipeline.py --seed --generate

  # Options:
  python scripts/test_pipeline.py --fetch --create --generate --topic technology
  python scripts/test_pipeline.py --generate --bundles bundle_xxx bundle_yyy
"""
import argparse
import subprocess
import sys
from pathlib import Path

# Add project root for imports
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

API_BASE = "http://127.0.0.1:8000"
TEST_BUNDLE_IDS = ["test_bundle_explainer", "test_bundle_global", "test_bundle_az_tech"]
DEFAULT_MODES = ["explainer", "global_news", "az_tech"]


def run_seed():
    """Run seed_test_bundles.py."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "seed_test_bundles.py")],
        cwd=str(ROOT),
    )
    return result.returncode == 0


def fetch_sources(topic: str = "technology") -> bool:
    """Fetch from RSS and NewsData into sources collection."""
    import requests
    ok = True
    # 1) RSS (no API key needed)
    print(f"  Fetching RSS (topic={topic})...", end=" ")
    try:
        r = requests.post(
            f"{API_BASE}/admin/sources/fetch-rss",
            json={
                "topic": topic,
                "max_entries": 20,
                "random_feeds": True,
                "random_feed_count": 3,
            },
            timeout=90,
        )
        data = r.json()
        if data.get("ok"):
            print(f"saved={data.get('saved', 0)}, skipped={data.get('skipped', 0)}")
        else:
            print(f"FAIL: {data.get('error', 'unknown')}")
            ok = False
    except Exception as e:
        print(f"FAIL: {e}")
        ok = False

    # 2) NewsData (requires NEWSDATA_API_KEY)
    print(f"  Fetching NewsData (topic={topic})...", end=" ")
    try:
        r = requests.post(
            f"{API_BASE}/admin/sources/fetch-newsdata",
            json={"topic": topic, "max_sources": 10, "randomize": True},
            timeout=60,
        )
        data = r.json()
        if data.get("ok"):
            print(f"saved={data.get('saved', 0)}, skipped={data.get('skipped', 0)}")
        else:
            print(f"FAIL: {data.get('error', 'unknown')} (API key may be missing)")
            # Don't fail overall - RSS may have enough
    except Exception as e:
        print(f"FAIL: {e}")

    # 3) NewsAPI (requires NEWSAPI_API_KEY)
    print(f"  Fetching NewsAPI (topic={topic})...", end=" ")
    try:
        r = requests.post(
            f"{API_BASE}/admin/sources/fetch-newsapi",
            json={"topic": topic, "max_sources": 10, "randomize": True},
            timeout=60,
        )
        data = r.json()
        if data.get("ok"):
            print(f"saved={data.get('saved', 0)}, skipped={data.get('skipped', 0)}")
        else:
            print(f"FAIL: {data.get('error', 'unknown')} (API key may be missing)")
            # Don't fail overall - other sources may have enough
    except Exception as e:
        print(f"FAIL: {e}")

    return ok


def create_bundles_from_sources(topic: str, modes: list[str]) -> list[str]:
    """Create bundles from stored sources, one per mode. Returns bundle_ids."""
    import requests
    bundle_ids = []
    for mode in modes:
        print(f"  Creating bundle (mode={mode}, topic={topic})...", end=" ")
        try:
            r = requests.post(
                f"{API_BASE}/admin/bundles/create",
                json={"topic": topic, "mode": mode, "max_sources": 5, "min_sources": 3},
                timeout=30,
            )
            data = r.json()
            if data.get("ok"):
                bid = data.get("bundle_id", "")
                bundle_ids.append(bid)
                print(f"OK -> {bid}")
            else:
                print(f"FAIL: {data.get('error', 'unknown')}")
        except Exception as e:
            print(f"FAIL: {e}")
    return bundle_ids


def get_bundle_ids_from_api():
    """Fetch bundle IDs from GET /admin/bundles. Fallback: use test IDs."""
    try:
        import requests
        r = requests.get(f"{API_BASE}/admin/bundles", params={"limit": 50}, timeout=10)
        if r.ok:
            data = r.json()
            return [b["bundle_id"] for b in data.get("bundles", [])]
    except Exception:
        pass
    return TEST_BUNDLE_IDS


def generate_for_bundle(bundle_id: str) -> dict:
    """Call POST /admin/generate for a bundle."""
    try:
        import requests
        r = requests.post(
            f"{API_BASE}/admin/generate",
            json={"bundle_id": bundle_id},
            timeout=300,
        )
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Test pipeline with real or seeded sources")
    parser.add_argument("--seed", action="store_true", help="Seed test bundles (mock data)")
    parser.add_argument("--fetch", action="store_true", help="Fetch real sources from RSS + NewsData")
    parser.add_argument("--create", action="store_true", help="Create bundles from sources collection")
    parser.add_argument("--generate", action="store_true", help="Generate articles for bundles")
    parser.add_argument("--topic", default="technology", help="Topic for fetch/create (default: technology)")
    parser.add_argument(
        "--modes",
        nargs="*",
        default=DEFAULT_MODES,
        help=f"Modes for bundle creation (default: {DEFAULT_MODES})",
    )
    parser.add_argument(
        "--bundles",
        nargs="*",
        default=None,
        help="Bundle IDs to generate (default: list from API)",
    )
    args = parser.parse_args()

    if not any([args.seed, args.fetch, args.create, args.generate]):
        parser.print_help()
        print("\nExample (real sources): python scripts/test_pipeline.py --fetch --create --generate")
        print("Example (seeded):       python scripts/test_pipeline.py --seed --generate")
        return 1

    created_bundle_ids = []

    if args.seed:
        print("Seeding test bundles...")
        if not run_seed():
            print("Seed failed")
            return 1
        print()

    if args.fetch:
        print("Fetching sources from RSS + NewsData...")
        if not fetch_sources(args.topic):
            print("Fetch failed (RSS is required)")
            return 1
        print()

    if args.create:
        print("Creating bundles from sources...")
        created_bundle_ids = create_bundles_from_sources(args.topic, args.modes)
        if not created_bundle_ids:
            print("No bundles created. Ensure sources exist (run --fetch first).")
            return 1
        print()

    if args.generate:
        # Prefer newly created bundles if we just created them
        bundle_ids = (
            args.bundles
            if args.bundles
            else (created_bundle_ids if created_bundle_ids else get_bundle_ids_from_api())
        )
        print(f"Generating articles for {len(bundle_ids)} bundles...")
        for bid in bundle_ids:
            print(f"  {bid}...", end=" ")
            result = generate_for_bundle(bid)
            if result.get("ok"):
                print(f"OK -> {result.get('article_id', '?')}")
                flags = result.get("quality_flags", {})
                if flags:
                    print(f"       word_count_en={flags.get('word_count_en')}, word_count_az={flags.get('word_count_az')}")
            else:
                print(f"FAIL: {result.get('error', 'unknown')}")
                if result.get("validation_errors"):
                    for e in result["validation_errors"]:
                        print(f"       - {e}")
        print("Done.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
