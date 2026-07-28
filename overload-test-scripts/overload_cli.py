"""HTTP load test against the codeguard API.

The previous version called os.system("curl ...") from each thread, so most of
what it measured was process creation in the OS, not server latency - and it
reported raw per-thread times with no percentiles. This uses a connection-pooled
client and reports the distribution, which is what actually tells you anything.

Usage:
    python overload_cli.py --requests 200 --concurrency 20
    python overload_cli.py --endpoint /scan --requests 100
"""
import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import requests

PAYLOAD = {"dependencies": ["flask==2.2.2", "requests==2.28.1", "django==3.2.0"]}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:80")
    parser.add_argument("--endpoint", default="/test", choices=["/test", "/scan", "/health"])
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def main():
    args = parse_args()
    target = f"{args.url}{args.endpoint}"

    session = requests.Session()
    session.mount("http://", requests.adapters.HTTPAdapter(
        pool_connections=args.concurrency, pool_maxsize=args.concurrency))

    def one_request(_):
        started = time.perf_counter()
        try:
            if args.endpoint == "/health":
                response = session.get(target, timeout=args.timeout)
            else:
                response = session.post(target, json=PAYLOAD, timeout=args.timeout)
            return time.perf_counter() - started, response.status_code, response.headers
        except requests.RequestException as error:
            return time.perf_counter() - started, str(error), {}

    print(f"{args.requests} requests to {target} at concurrency {args.concurrency}\n")
    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(one_request, range(args.requests)))
    wall = time.perf_counter() - wall_start

    latencies = sorted(r[0] for r in results)
    statuses = {}
    for _, status, _ in results:
        statuses[status] = statuses.get(status, 0) + 1

    def pct(p):
        if not latencies:
            return 0.0
        return latencies[min(len(latencies) - 1, int(len(latencies) * p / 100))]

    ok = statuses.get(200, 0)
    print(f"  wall clock     {wall:.2f}s")
    print(f"  throughput     {args.requests / wall:.1f} req/s")
    print(f"  success        {ok}/{args.requests} ({100 * ok / args.requests:.1f}%)")
    print(f"  latency  min   {latencies[0] * 1000:.0f} ms")
    print(f"           mean  {statistics.mean(latencies) * 1000:.0f} ms")
    print(f"           p50   {pct(50) * 1000:.0f} ms")
    print(f"           p95   {pct(95) * 1000:.0f} ms")
    print(f"           p99   {pct(99) * 1000:.0f} ms")
    print(f"           max   {latencies[-1] * 1000:.0f} ms")
    print("\n  responses:")
    for status, count in sorted(statuses.items(), key=lambda kv: str(kv[0])):
        print(f"    {status}: {count}")


if __name__ == "__main__":
    main()
