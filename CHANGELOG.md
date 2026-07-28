# Changelog

## [2.1.0] — 2026-07-28

Hardening and packaging on top of 2.0.0.

### Added
- **MongoDB authentication.** Keyfile internal auth on every node plus SCRAM
  users. The backend authenticates as an application user with `readWrite` on
  `codeguard` only — it cannot administer the cluster.
- **`install.sh`** — checks prerequisites, generates random credentials into
  `.env` (mode 600), builds and starts the cluster, runs a smoke scan and
  installs the CLI. `--cli-only`, `--no-cli` and `--uninstall` supported.
- **`Makefile`** — `up`, `down`, `status`, `logs`, `shell`, `test`,
  `failover-test`, `lint`, `scale`, `autoscale`, `load-test`, `clean`.
- **Recorded demos** (VHS) for scanning, autoscaling and leader failover,
  embedded in the README.
- **TTL index** on the cache so MongoDB expires entries nobody scans any more.
- **Release tooling** (`scripts/release.sh`, `make release` / `make publish`):
  builds the standalone CLI, a reproducible source tarball generated from the
  tag, and `SHA256SUMS` covering both, then creates the GitHub release.
- `.env.example`, `CHANGELOG.md`.

### Changed
- CLI self-update downloads the published `codeguard` asset and verifies it
  against `SHA256SUMS` before replacing the installed file. It **refuses to
  install** when a release publishes no checksums, and does not checksum
  GitHub's auto-generated source archives (those are not byte-stable).
- CVE lists in the report are capped at three ids so no line exceeds the
  74-column report width.
- The autoscaler scales to *demand* rather than blindly doubling, so a spike
  from one replica reaches capacity in a single step.
- Failover test output is colourised and scales the cluster up first (the
  default of one replica has nothing to fail over to).
- `mongos` is published to loopback only and now requires credentials.

### Fixed
- **Scaling was broken by the dependency chain.** `docker compose up --scale`
  re-ran the one-shot Mongo init containers on every scaling action; once auth
  was enabled those failed, taking the whole command down. All scaling paths
  now pass `--no-deps`.
- **Replica-set init was not idempotent under auth.** A second `docker compose
  up` tried to re-initiate and failed, because the localhost exception closes
  permanently once a user exists. The scripts now detect an existing replica
  set via `hello` (which needs no authentication) and exit cleanly.
- Git commit SHAs from OSV `GIT` ranges no longer leak into the "fixed in"
  list — only ecosystem versions are shown.

---

## [2.0.0] — 2026-07-28

Rebuild of the scanning core, the coordination layer and the deployment.

### Added
- **OSV.dev as the primary source**: version-aware matching, batched queries,
  no API key. Findings carry CVE ids, severity and the fixing version.
- **ZooKeeper coordination that actually runs**: a three-node ensemble, leader
  election wired to a real job (cache refresh), and a shared outbound rate
  budget held as a token bucket in a znode.
- **Automatic cluster bootstrap**: replica sets, `addShard`, `enableSharding`
  and `shardCollection` all run idempotently on `docker compose up`.
- **Autoscaling**: the backend is one replicated service discovered by HAProxy
  over Docker DNS; `scripts/autoscale.sh` grows and shrinks it with load.
- 57 unit tests, a failover integration test, and CI covering unit tests,
  shellcheck, cluster topology, scanning, scaling and failover.
- `/health` and `/ready` endpoints; HAProxy active health checks.

### Changed
- `gunicorn` replaces the Flask development server; containers run as non-root.
- MongoDB 8.0 LTS, ZooKeeper 3.9.5, HAProxy 3.0, Python 3.11, pinned
  dependencies actually installed from `requirements.txt`.
- WiredTiger cache and the ZooKeeper heap are capped — four mongod instances
  each claiming ~50% of host RAM caused OOM kills.
- The CLI exits `0` clean / `1` findings / `2` scan failed, and no longer
  overwrites the user's `requirements.txt`.
- HAProxy: `default_backend`, longer server timeout, authenticated stats page.

### Fixed
- **Cross-dependency contamination**: a result list shared across loop
  iterations made every dependency after the first match report as vulnerable.
- **Fail-open scanning**: a failed scan returned `404 []`, indistinguishable
  from a clean result. It now returns `503` with an explicit "unknown".
- **The NVD fallback crashed the scan** by returning `None`, which the caller
  passed to `len()`.
- `number_of_found_vulnerabilities` was hardcoded to `1`.
- `MongoClient` was constructed per request, discarding connection pooling.
- `pipreqs --force >nul` created a junk file named `nul` on Unix.

### Removed
- 15 MB of committed WiredTiger database files, orphaned `.pyc` files and
  `.DS_Store` — the cluster now builds itself from nothing in ~45 seconds.
