"""MongoDB load test against the sharded vulnerability cache.

Fixes two flaws in the previous version: it appended every result to one shared
list from 50 threads (unsynchronised, and it made memory - not Mongo - the
bottleneck), and it reported per-thread times with no aggregate. MongoClient is
already thread safe and pooled, so one client is shared here on purpose.

Usage:
    python mongo_overload.py --queries 500 --concurrency 50
"""
import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

from pymongo import MongoClient


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default="mongodb://127.0.0.1:27017")
    parser.add_argument("--db", default="codeguard")
    parser.add_argument("--collection", default="vulnerability_cache")
    parser.add_argument("--queries", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=50)
    return parser.parse_args()


def main():
    args = parse_args()
    client = MongoClient(args.uri, serverSelectionTimeoutMS=5000,
                         maxPoolSize=args.concurrency)
    collection = client[args.db][args.collection]

    total = collection.count_documents({})
    print(f"{args.queries} queries at concurrency {args.concurrency}")
    print(f"collection holds {total} cached entries\n")

    # Query real keys where possible so the test exercises index lookups
    # rather than always missing.
    sample = [d["_id"] for d in collection.find({}, {"_id": 1}).limit(100)]
    if not sample:
        print("cache is empty - run a scan first, or this measures misses only\n")
        sample = ["PyPI:flask:2.2.2"]

    def one_query(i):
        started = time.perf_counter()
        try:
            collection.find_one({"_id": sample[i % len(sample)]})
            return time.perf_counter() - started, None
        except Exception as error:  # noqa: BLE001
            return time.perf_counter() - started, str(error)

    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(one_query, range(args.queries)))
    wall = time.perf_counter() - wall_start

    latencies = sorted(r[0] for r in results)
    errors = [r[1] for r in results if r[1]]

    def pct(p):
        return latencies[min(len(latencies) - 1, int(len(latencies) * p / 100))]

    print(f"  wall clock   {wall:.2f}s")
    print(f"  throughput   {args.queries / wall:.0f} queries/s")
    print(f"  errors       {len(errors)}")
    print(f"  latency p50  {pct(50) * 1000:.2f} ms")
    print(f"          p95  {pct(95) * 1000:.2f} ms")
    print(f"          p99  {pct(99) * 1000:.2f} ms")
    print(f"          max  {latencies[-1] * 1000:.2f} ms")
    print(f"          mean {statistics.mean(latencies) * 1000:.2f} ms")
    if errors:
        print(f"\n  first error: {errors[0]}")

    client.close()


if __name__ == "__main__":
    main()
