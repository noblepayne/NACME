# NACME Dev Log

This is a chronological developer journal for the NACME project — tracking decisions, progress, gotchas, iterations, test notes, and rationale.  
Unlike `architecture.md` (which stays high-level and stable), this log is living, messy, and time-stamped. Entries are added as we go.

### 2026-01-17 – Initial Implementation Sprint (Server, Client, Flake)

**Summary**  
Kicked off the real MVP coding after several rounds of architecture discussion. Goal was to get to a working add-flow end-to-end as fast as possible so we can validate the core idea: shared-secret onboarding that feels closer to Tailscale than manual `nebula-cert`. Achieved a single-file server + simple client + minimal flake for dev shell.

**Key Decisions & Trade-offs**

- **Single-file server** (`nacme_server.py`)  
  - Pros: Extremely fast iteration — everything in one place, easy to grep/edit/run.  
  - Cons: Will get ugly fast once we add renew/history/UI hooks → plan to refactor into modules later (e.g. `api/`, `db/`, `cert/`).  
  - Two uvicorn servers in one process via `asyncio.gather` — works surprisingly well for our use case, keeps Docker simple (one container, two ports). Avoided multi-process or separate containers for now.

- **Env vars everywhere**  
  - Made `NACME_SUBNET_CIDR` required + validated (via pydantic + ipaddress). No more hardcoded 10.100.0.0/24.  
  - `NACME_MASTER_KEY` is env-only (no DB storage) — simplest secure bootstrap.  
  - Client also env-driven with CLI overrides → easy for systemd oneshot or testing.

- **DB choices**  
  - Stuck with SQLite + WAL + busy_timeout — concurrency is fine for our workload (infrequent writes).  
  - Plain SQL + aiosqlite — no ORM, no query builder. Keeps queries readable and debuggable with sqlite3 CLI.  
  - Seeding from config on first run → idempotent startup.

- **Cert generation**  
  - plumbum for `nebula-cert sign` — much nicer than subprocess.run.  
  - Temp dir for output files → read into memory → client writes atomically.  
  - IP suffix pulled dynamically from subnet prefixlen (not hardcoded /24).

- **Client** (`nacme_client.py`)  
  - Idempotent skip-if-files-exist → perfect for systemd pre-start or boot hooks.  
  - Atomic writes + chmod 600 on key → basic security hygiene.  
  - Minimal deps (requests + pydantic) — easy to package or run standalone.

- **Flake.nix**  
  - No flake-utils, pure x86_64-linux hardcode — keeps it tiny.  
  - Includes `nebula` package (so `nebula-cert` is available) + sqlite3 CLI + curl/jq for manual testing.  
  - Helpful shellHook with reminders → reduces onboarding friction when entering the shell.

**Quick Wins & Validation Plan**

- Run server → set env vars → curl admin /keys to create API key → curl public /add → get bundle → manually write files → success!  
- Then run client → see it skip or onboard → validate idempotence.  
- Next test: boot-like scenario (delete host files → run client → files reappear).

**Known Rough Edges / TODOs (short-term)**

- No /renew yet — that's the next big piece (verify current key, re-sign same params, archive old cert).  
- Nebula-cert can fail silently or with weird exit codes — need better plumbum error capture/logging.  
- No HTTPS on servers yet (self-signed or mkcert in dev) — add later for realism.  
- Client doesn't parse/validate returned certs (e.g. expiry) — add cryptography lib later for renew trigger.  
- DB schema lacks `cert_history` table — add when renew lands.

**Current State (as of 2026-01-17 evening)**  
- Server boots, DB initializes, keys can be created via admin API.  
- /add works end-to-end (allocates IP/hostname, signs cert, stores lease).  
- Client idempotently onboards or skips.  
- Dev shell ready → `nix develop` → everything in PATH.

Feeling validated on the core loop — shared secret → auto cert → files on disk.  
Next: add /renew + client-side expiry check → then we have a real "set it and forget it" helper.

— Wes, 2026-01-17 17:45 PST (Seattle)

### 2026-01-17 – Pydantic v1 to v2 Migration & Pytest Setup

**Summary**
Migrated the Pydantic configuration models in both `nacme/server.py` and `nacme/client.py` from Pydantic v1 to v2 syntax. This involved updating `BaseModel` to `BaseSettings` (for server), using `SettingsConfigDict` for configuration, replacing `@validator` with `@field_validator`, and refining environment variable loading for both applications. Also, added `pytest` and `pytest-asyncio` to `flake.nix` to enable proper testing as per `AGENTS.md`.

**Key Decisions & Trade-offs**
- Server (`nacme/server.py`): Adopted `pydantic-settings.BaseSettings` for robust, explicit environment variable management. This aligns with Pydantic v2's recommended approach for settings.
- Client (`nacme/client.py`): Maintained `pydantic.BaseModel` but refactored the `load_config` function to manually handle environment variables and CLI arguments before model instantiation. This allows CLI args to override env vars, providing flexibility for `systemd oneshot` or manual testing, while still benefiting from Pydantic's validation.
- Flake: Added `pytest` and `pytest-asyncio` to the `pythonEnv` in `flake.nix` to prepare the development environment for unit and integration testing of async code.

**Gotchas / Notes**
- The `env=` parameter in `Field` is deprecated in Pydantic v2; replaced with `SettingsConfigDict(env_prefix="...")` for `BaseSettings` or manual environment variable fetching for `BaseModel`.
- The `validator(..., pre=True)` was replaced by `field_validator(..., mode="before")`.
- `HttpUrl` moved from top-level `pydantic` to `pydantic.networks` but still accessible from top level `pydantic`. The existing import structure worked without change.
- The `ensure_dir` validator in `nacme/client.py` was made more resilient to `PermissionError` when creating output directories, providing a warning instead of a hard crash if running as a non-root user.

**Next Steps**
- Write comprehensive tests for both server and client, utilizing `pytest` and `pytest-asyncio`.
- Verify full functionality with the updated configuration loading.

— Gemini, 2026-01-17 PST (Seattle)

### 2026-01-17 – Import Style Refactoring

**Summary**
Enforced Clojure-style namespaced imports across the codebase as specified in AGENTS.md. Updated both `nacme/server.py` and `nacme/client.py` to use namespaced imports (e.g., `import pathlib.Path` → `import pathlib`, then `pathlib.Path`) and added explicit import style guidelines to AGENTS.md.

**Key Changes**
- Added import style guidelines to AGENTS.md: "Clojure-style namespaced imports only. No `from x import y` except in tests or tightly coupled APIs. Always maintain at least one level of namespacing. No `import *` allowed."
- Updated `nacme/server.py`: Converted all imports to namespaced style, including `pydantic`, `fastapi`, `pathlib`, `contextlib`, `typing`, `ipaddress`, and `plumbum`.
- Updated `nacme/client.py`: Converted imports to namespaced style, including `pydantic`, `pathlib`, and `time`.
- Fixed all resulting references throughout both files to use the full namespaced paths.
- Resolved database method calls to use proper aiosqlite cursor patterns with `execute()` + `fetchone()` instead of non-existent `fetchval()`/`fetchrow()` methods.

**Gotchas / Notes**
- aiosqlite doesn't have `fetchval()` or `fetchrow()` methods like some other async DB libraries - had to use `execute()` + `fetchone()` pattern instead.
- Fixed potential None access issues in database queries by adding proper null checks.
- Both files still compile and pass syntax validation after the refactoring.

**Next Steps**
- Write tests to validate the import changes don't break functionality.
- Consider adding a linting rule to enforce the namespaced import style automatically.

— OpenCode, 2026-01-17 PST (Seattle)

### 2026-01-17 – Add basic smoke tests
- Created `tests/` directory structure for the project
- Added `tests/test_smoke.py` with three basic smoke tests:
  - `test_server_import_missing_env_vars`: Verifies server fails on missing required env vars (SystemExit)
  - `test_client_import`: Confirms client module imports successfully without env vars
  - `test_server_import_with_env_vars`: Tests server imports successfully with minimal required env vars set
- All tests pass, confirming basic import behavior works as expected
- Tests handle the server's `sys.exit(1)` behavior when config validation fails

— OpenCode, 2026-01-17 UTC-5

### 2026-01-17 – Session Continuation & Project State Verification

**Summary**
Picked up from previous session to continue work on httpx to requests migration, but discovered this was already completed in prior work. Verified current project state, ran tests to ensure functionality, and confirmed httpx is properly implemented throughout the codebase.

**Key Actions**
- Confirmed httpx is already implemented in `nacme/client.py` (lines 10, 107, 138, 143)
- Ran pytest suite: all 3 smoke tests pass
- Verified project structure and dependencies are correct
- Confirmed dev environment is properly set up via flake.nix

**Current State Verification**
- Server boots and handles configuration correctly
- Client uses httpx for HTTP requests with proper error handling
- Tests validate import behavior and basic functionality
- Project follows AGENTS.md specifications for imports and structure

**Next Steps**
- Continue with next development priorities (renew functionality, HTTPS, etc.)
- Maintain existing httpx implementation as intended

— OpenCode, 2026-01-17 PST (Seattle)

### 2026-01-17 – End-to-End Test Implementation

**Summary**
Successfully implemented a comprehensive end-to-end test that validates the complete NACME onboarding flow. The test starts the server in a subprocess, creates an API key, runs the client, and validates all output files and certificates.

**Key Implementation Details**
- Created `tests/test_e2e.py` with `test_end_to_end_onboarding` test
- Uses subprocess management to isolate server and client execution
- Validates file creation, permissions, certificate content, and client output
- Test PKI infrastructure in `tests/fixtures/` with CA cert/key
- Uses separate test ports (18000/19000) to avoid conflicts
- Tests complete flow: server startup → API key creation → client onboarding → file verification

**Issues Resolved**
- Fixed double slash URL issue with pydantic HttpUrl adding trailing slash
- Corrected nebula-cert duration format from days to hours (`365d` → `8760h`)
- Created long-lasting test CA (10 years) to accommodate certificate expiry validation
- Fixed server health check to use `/docs` endpoint instead of non-existent `/health`
- Updated AGENTS.md to reflect preference for e2e/blackbox/integration tests over unit tests

**Test Coverage**
- Server startup and API responsiveness
- API key creation via admin endpoint
- Client execution and successful onboarding
- File creation (ca.crt, host.crt, host.key) with proper permissions
- Certificate format validation (Nebula V2 format)
- Client output validation (success message and metadata)

**Current Status**
- All tests pass including the new e2e test
- Complete end-to-end validation achieved
- Ready for additional property-based and contract testing using hypothesis and icontract

— OpenCode, 2026-01-17 PST (Seattle)

### 2026-01-22 – Core Algorithm Robustness & Error Handling Improvements

**Summary**
Major robustness pass to make NACME "demo ready" for manual network testing. Fixed IP allocation reliability at high utilization, added concurrency safety, implemented startup validation, and enhanced nebula-cert error handling. All tests passing and core is now solid for real-world testing.

**Core Algorithm Fixes**

**IP Allocation Overhaul**
Replaced fixed-retry random allocation with hybrid strategy:
- Networks < 100k addresses: sequential scan from random start (handles 99%+ utilization)  
- Networks ≥ 100k addresses: random selection (collision negligible in large spaces)
- Typical /24 homelab uses sequential (254 addresses)
- Future IPv6 support via random (e.g., /64 = 18 quintillion addresses)

Math: In a /24 at 80% utilization, old approach needed ~5+ attempts per allocation and could fail. New approach is deterministic single pass.

**Transaction Safety & Concurrency**
Added optimistic locking pattern for simultaneous `/add` requests:
- Retry loop (max 10 attempts) wraps allocation + cert generation + insertion
- UNIQUE constraints on IP/hostname act as atomic locks
- Graceful retry on collision instead of failing request
- SQLite transaction boundary via existing get_db() context manager
- Structured logging for retry attempts and collisions

**Performance Optimization**
Cached runtime config in memory (eliminates 2-3 DB queries per request):
- CIDR subnet
- Expiry days  
- Hostname suffix length
- Config loaded once at startup, cached in `_RUNTIME_CONFIG`

**Startup Validation**
Added pre-flight checks before server starts:
- CA cert/key files exist and readable
- nebula-cert binary available in PATH
- DB directory writable
- Fail fast with clear errors instead of mysterious failures on first request
- Comprehensive structured logging for validation failures

**Enhanced Error Handling**
Improved nebula-cert failure handling with specific error analysis:
- Distinguish missing binary vs permission issues vs invalid files
- Better user messages for IP format, groups format, CA file problems
- Validate output files exist and are non-empty
- Verify Nebula certificate and private key formats
- Separate handling for expected vs unexpected errors

**Testing Improvements**
- Added comprehensive database persistence test (`tests/test_database_persistence.py`)
- Tests server restart, data preservation, continued operations across restarts
- Validates unique IP/hostname allocation across server lifecycle
- All 5 tests passing (smoke, e2e, persistence)

**Code Quality**
- Maintained Clojure-style namespaced imports throughout
- Added detailed comments explaining IPv6 threshold choice (100k addresses)
- Type hints and structured logging for all new functionality
- Proper exception handling with specific error categorization

**IPv6 Notes**
MVP stays focused on IPv4 (v1 certs, typical /24 deployments) but algorithm is ready for IPv6 when needed. The 100k threshold naturally switches strategies at the right point.

**Performance Impact**
- Config caching: eliminates 2-3 DB queries per request
- Sequential IP allocation: deterministic even at 99%+ utilization
- Collision retry: maximum 10 attempts only when concurrent requests collide
- Overall: faster, more reliable, better user experience

**Next Steps**
Core is solid and robust. Ready for manual network testing and eventually deployment layer (README, systemd examples, container image).

— OpenCode, 2026-01-22 PST (Seattle)

### 2026-01-22 – Code Style Refinement & URL Handling Robustness

**Summary**
Updated code style guidance to be more pragmatic, fixed double-slash URL handling in client, and added comprehensive test coverage for URL edge cases. Maintains focus on readability over dogmatic constraints while ensuring robust URL construction.

**Code Style Updates**
Refined AGENTS.md guidance to be more pragmatic:
- Type hints: "Use where they help clarity, but avoid over-engineering. `dict[str, str]` is often clearer than complex generics."
- Simplified typing in server code: `typing.Dict[str, str]` → `dict[str, str]`
- Relaxed import language: "Clojure-style preferred" instead of "only"
- Added focus on "readability over strict typing dogma"
- Emphasized pragmatic approach over prescriptive rules

**URL Handling Fix**
Fixed double-slash issue in client URL construction:
- Problem: `f"{str(config.server_url).rstrip('/')}/add"` still problematic with edge cases
- Solution: `urllib.parse.urljoin(str(config.server_url), "/add")` handles all URL formats correctly
- Added `urllib.parse` import to client
- Maintains backward compatibility with existing URL formats

**Test Enhancement**
Added comprehensive URL variant testing:
- New test `test_url_handling_variants` in existing e2e test file
- Tests: no slash, single slash, double slash, with path, with path+slash
- Reuses existing test infrastructure (server_process, api_key fixtures)
- All URL formats now resolve correctly to `/add` endpoint
- Both original e2e and new URL tests pass

**Testing Philosophy Applied**
Followed existing test patterns rather than creating new unit test:
- Extended existing e2e infrastructure for consistency
- reused subprocess testing pattern from other tests
- Maintained focus on integration over unit testing
- Validated real client behavior with different URL inputs

**Rationale for Single-File Server**
Confirmed decision to keep server single-file for now:
- Extremely fast iteration with everything in one place
- Easy to grep/edit/run for MVP development
- Will refactor to modules only when it becomes painful (>800-1000 LOC)
- Current approach optimal for rapid development cycle

**Runtime Config Cache Validation**
Runtime config cache implementation working well:
- Eliminates 2-3 DB queries per request
- Stores CIDR subnet, expiry days, hostname suffix length in memory
- Loaded once at startup, cached in `_RUNTIME_CONFIG` dict
- Significant performance improvement for frequent operations

**Next Steps**
Ready for manual network testing and eventual deployment considerations. Core functionality is robust with improved URL handling and pragmatic code approach.

— OpenCode, 2026-01-22 PST (Seattle)