# NACME Dev Log
### 2026-01-30 – Added Suggested IP Feature for Lighthouse Nodes

**Summary**
Implemented optional IP suggestion for clients (particularly useful for lighthouse nodes and NixOS declarative configurations). Followed full TDD approach with 10 comprehensive tests covering validation, fallback, race conditions, and client integration.

**Key Decisions & Trade-offs**

- **Validation strategy**: IP must be in configured subnet and cannot be network/broadcast address
  - Added `validate_ip_in_subnet()` helper function for reusable validation
  - Pydantic validator handles format validation, helper handles subnet/reserved checks
  - IPv4-specific broadcast check (IPv6 has no broadcast address)

- **Fallback behavior**: If suggested IP is already taken, silently fall back to auto-allocation
  - Rationale: Better UX than failing - client gets *an* IP even if not their preferred one
  - Logged as warning for debugging but request succeeds
  - Prevents denial-of-service via exhausting suggested IPs

- **Authorization model**: Available to all API keys (no special permission needed)
  - Simpler than role-based access for MVP
  - Validation provides sufficient security (subnet enforcement)
  - Can add permission flags later if needed

- **Client integration**: Both `--ip` CLI flag and `NACME_SUGGESTED_IP` env var supported
  - CLI flag takes precedence over env var (standard priority)
  - Env var useful for systemd units or declarative configs
  - Client shows "Suggesting IP: x.x.x.x" message for transparency

**Implementation Details**

Server changes (`nacme/server.py`):
- Added optional `suggested_ip: str | None = None` field to `AddRequest` model
- Pydantic validator for IP format (using `ipaddress.ip_address()`)
- Helper function `validate_ip_in_subnet()` checks subnet membership and reserved addresses
- Updated `/add` endpoint with conditional IP allocation logic:
  1. If suggested_ip provided → validate → check availability → use or fallback
  2. If not provided → auto-allocate (backward compatible)
- Return 422 error for invalid suggestions (out of subnet, reserved addresses)
- Structured logging for acceptance, fallback, and validation failures

Client changes (`nacme/client.py`):
- Added `suggested_ip: str | None = None` field to `ClientConfig`
- Added `--ip` argument to CLI parser
- Added `NACME_SUGGESTED_IP` environment variable support
- Pass suggested_ip in request payload if provided
- User feedback message when suggesting IP

**Testing Coverage** (10 new tests in `tests/test_suggested_ip.py`)

Core functionality:
1. `test_suggested_ip_success` - Valid available IP gets assigned
2. `test_suggested_ip_already_taken` - Fallback to auto-allocation when taken
3. `test_suggested_ip_none_uses_auto_allocation` - Backward compatibility

Validation & security:
4. `test_suggested_ip_out_of_subnet` - Reject IPs outside CIDR (422 error)
5. `test_suggested_ip_invalid_format` - Reject malformed IPs (422 error)
6. `test_suggested_ip_network_address` - Reject .0 address (422 error)
7. `test_suggested_ip_broadcast_address` - Reject .255 address (422 error)

Client integration:
8. `test_client_passthrough_ip` - E2E with `--ip` CLI flag
9. `test_client_passthrough_ip_via_env` - E2E with `NACME_SUGGESTED_IP` env var

Edge cases:
10. `test_multiple_hosts_same_suggested_ip_concurrent` - Race condition handling

**Gotchas & Notes**

- **Race condition handling**: Works via existing retry loop in `/add` endpoint
  - UNIQUE constraint on hosts.ip triggers IntegrityError
  - Retry loop catches collision and allocates different IP
  - One client gets suggested IP, other gets fallback

- **Network/broadcast validation**: Only applies to IPv4
  - IPv6 has no broadcast address concept
  - Code checks `net.version == 4` before broadcast validation
  - Future IPv6 support is handled correctly

- **Test infrastructure**: Reused existing fixtures from other test files
  - Same server startup, API key creation, keypair generation patterns
  - Consistent port allocation (18000/19000)
  - Temporary directories for client output

**Use Cases Enabled**

1. **Lighthouse nodes**: Assign stable IPs (e.g., 10.100.0.1, 10.100.0.2) for known infrastructure
2. **NixOS declarative config**: Specify IP in configuration.nix before deployment
3. **Migration from manual**: Preserve existing IP assignments when switching to NACME
4. **Network planning**: Reserve IP ranges for different purposes (lighthouses, services, clients)

**Performance Impact**

- Minimal overhead: single DB query to check IP availability
- Validation is fast (Python ipaddress module)
- Fallback path reuses existing allocation logic
- No additional database schema changes needed

**Next Steps & Future Considerations**

- Consider adding ability to reserve IP ranges for specific API keys
- Could add `suggested_hostname` feature for consistency
- Documentation should highlight lighthouse use case
- Example systemd unit with `NACME_SUGGESTED_IP` would be helpful

**All Tests Passing**: 21/21 tests pass including 10 new suggested IP tests

— Claude (UTC) 2026-01-30

### 2026-01-24 – Client-Generated Keypairs (Betterkeys) Implementation

**Summary**
Successfully implemented the betterkeys feature as specified in `betterkeys.md`. This is a major security uplift where private keys are generated client-side and never transmitted to or stored on the server. The server only receives public keys and returns signed certificates.

**Key Decisions & Gotchas**

- **Key type correction**: Original spec called for ED25519 keys, but nebula-cert v1.10.0 only supports X25519 ("25519" curve) and P256. Updated implementation and tests to use X25519 which is what nebula-cert actually generates by default.
  
- **Backward compatibility**: Maintained full backward compatibility. Requests without `public_key` field use the legacy server-generated keypath and return both cert and key. Requests with `public_key` use the betterkeys flow and return only cert (host_key=null in response).

- **Response model design**: Added optional `host_key` field to `CertBundle` that's `None` for betterkeys and populated for legacy mode. Tests initially expected no field at all, but `host_key=null` is cleaner for API consumers.

- **Exception handling refinement**: Had to let `fastapi.HTTPException` bubble up through the outer exception handler. Initial implementation caught validation errors as generic exceptions and converted them to 500 errors instead of preserving the intended 400/422 status codes.

- **Database schema**: No changes needed. Current schema already stores only `current_cert` and never stores private keys, which is optimal from a security perspective. We don't need a `current_key` column since we never persist private keys.

- **Sync state**: Resolved beads sync issues. No manual sync needed.

---

### 2026-01-24 – Pre-Merge Review Fixes

**Summary**
Addressed comprehensive review feedback from REVIEW.md covering critical blockers and medium priority security/correctness issues. Cleaned up codebase for merge readiness.

**Critical Blockers Fixed**

- **Runtime artifact cleanup**: Removed all `.beads/` files from git tracking and added `.beads/` to `.gitignore`. These were host-specific artifacts causing noisy diffs.

- **Documentation alignment**: Removed backward compatibility claims from README. Server now requires client-generated keys (X25519) exclusively - no legacy support.

- **Crypto terminology consistency**: Updated all ED25519 references to X25519 in tests and documentation. Added clarification note in CA fixture confirming nebula-cert generates CURVE25519 keys despite ED25519 labeling.

- **Database transaction safety**: Refactored `init_db()` to use proper `async with get_db()` context manager, ensuring atomic initialization with rollback on failure.

**Security & Validation Improvements**

- **Enhanced public key validation**: Added Pydantic validator with base64 decoding and 32-byte length check for X25519 keys. Moves validation from runtime to request parsing.

- **Hostname prefix sanitization**: Added validator enforcing `[a-zA-Z0-9-]` charset, 63-char max length, and normalization of repeated hyphens. Prevents malformed input reaching nebula-cert.

- **Performance optimization**: Cached CA certificate content at startup in `_RUNTIME_CONFIG` to eliminate per-request disk I/O.

- **API key security documentation**: Added comprehensive comment explaining raw SHA256 choice for API key hashing and future enhancement path.

**Testing & Documentation**

- **CHANGELOG cleanup**: Consolidated duplicate "Unreleased" sections and documented all changes for merge.

- **Code quality**: Maintained pragmatic type hints, namespaced imports, and single-file architecture per project standards.

**Next Steps**

- Ready for merge to main after final test run validation
- All blockers from REVIEW.md resolved
- Medium priority issues addressed
- Codebase meets security and quality standards for v0.1.0 release

*Signed off by OpenCode bot (UTC-8)*

**Implementation Details**

- **Server changes**: 
  - Added optional `public_key: Optional[str] = None` to `AddRequest` model
  - Added dual-path logic in `/add` handler based on presence of `public_key`
  - Client path: validates X25519 PEM format, uses `nebula-cert sign -in-pub`, returns cert only
  - Legacy path: maintains existing behavior with `nebula-cert sign` (generates keypair), returns both cert and key
  - Updated `CertBundle` response model with optional `host_key` field

- **Client changes**: Already fully implemented! 
  - Generates X25519 keypair locally using `nebula-cert keygen`
  - Sends only public key in `/add` request
  - Saves certificate from response and local private key
  - User messaging emphasizes "never sent to server" security benefit

- **Testing**: Created comprehensive TDD test suite (`test_betterkeys_tdd.py`) covering:
  - Client-generated key flow (success case)
  - Public key validation (empty, invalid format, wrong key type)
  - Backward compatibility (legacy server-generated keys)
  - End-to-end client binary test
  - Certificate validation with nebula-cert

**Next Steps**
- Consider deprecating server-generated keypath in future version (v0.3+)
- Add explicit client/key versioning if needed for migration
- Potentially add certificate renewal flow

*— OpenCode, PST*

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

### 2025-01-22 – Release Attempt Rollback and Fix

**Summary**
First release attempt failed due to GitHub Actions workflow inconsistency. Release workflow tried to manually install Python packages instead of using existing Nix development environment. Successfully rolled back, fixed workflow, and prepared for corrected release.

**Issues Encountered**

**GitHub Actions Workflow Mismatch**
- Problem: release.yml used manual Python pip installation instead of existing Nix setup
- Root cause: Didn't reuse existing test.yml infrastructure (cachix/install-nix-action + nix develop -c pytest)
- Impact: Release workflow would have failed due to environment differences

**Rollback Process**
- Deleted local tag: `git tag -d v0.1.0`
- Deleted remote tag: `git push origin :v0.1.0`
- Reset commit: `git reset --hard HEAD~1` to pre-release state
- All release files restored to staging state

**Fix Implementation**
- Recreated release.yml using Option A approach (fix existing workflow)
- Copied Nix setup pattern from test.yml exactly:
  - `cachix/install-nix-action@v31`
  - `nix develop -c pytest` for test execution
- Removed manual Python/pip installation attempts
- Maintained same release automation structure (version extraction, CHANGELOG validation, release creation)

**Lessons Learned**
- Always reuse existing working infrastructure instead of reinventing
- Test workflows should be identical between CI and release
- Release automation should extend existing patterns, not replace them
- Simplify: Nix dev shell handles everything, no need for manual dependency management

**Current State**
- Rollback completed successfully
- Fixed release.yml with proper Nix setup
- Ready to attempt corrected v0.1.0 release
- DEVLOG properly documents failure and fix process

**Next Steps**
Proceed with corrected v0.1.0 release using fixed GitHub Actions workflow.

— OpenCode, 2025-01-22 PST (Seattle)

### 2026-01-22 – Beads Workflow Management Integration

**Summary**
Integrated Beads AI-native issue tracking system into NACME project to provide better workflow management for AI agents. Added beads as flake dependency, initialized configuration, and set up proper git integration for issue tracking.

**Key Changes Made**

**Flake Integration**
- Added `bd` input to flake.nix pointing to steveyegge/beads GitHub repository
- Configured nixpkgs following to ensure consistent dependency resolution
- Added beads package to development shell environment
- Updated flake.lock with new dependencies (beads, flake-utils, systems)

**Beads Configuration**
- Initialized `.beads/` directory with complete configuration setup
- Added `.beads/config.yaml` with default settings for workflow management
- Created `.beads/README.md` with comprehensive documentation and quick start guide
- Set up `.beads/.gitignore` to exclude runtime files while tracking important config
- Added `.beads/metadata.json` and `.beads/interactions.jsonl` for issue tracking
- Configured `.gitattributes` for proper JSONL merge handling

**Git Integration**
- Set up git merge driver for beads JSONL files to handle merge conflicts intelligently
- Configured proper gitignore patterns to exclude database files, daemon runtime files, and machine-specific state
- Ensured only configuration and documentation files are tracked while runtime data remains local

**Rationale for Beads Integration**
- AI-native design: CLI-first interface works seamlessly with AI coding agents
- Git-native: Issues live in repository alongside code, perfect for our development workflow
- Offline-capable: Works offline, syncs when pushing - fits with our development philosophy
- Branch-aware: Issues can follow our branch workflow (next branch for features)
- Lightweight: Fast, minimal overhead, stays out of the way

**Configuration Decisions**
- Used default beads configuration with sensible defaults
- Left sync branch unset for now (will configure when needed for team workflows)
- Enabled auto-start daemon for better UX
- Configured proper JSONL git integration for merge conflict resolution

**Setup Files Added**
- `.beads/.gitignore`: Excludes runtime files, databases, daemon state
- `.beads/config.yaml`: Beads configuration with all default settings
- `.beads/README.md`: Comprehensive documentation for team usage
- `.beads/metadata.json`: Project metadata for beads system
- `.beads/interactions.jsonl`: Empty interaction log ready for use
- `.gitattributes`: Git merge driver configuration for JSONL files
- Updated `flake.nix` and `flake.lock`: Beads dependency integration

**Next Steps**
- Ready to use `bd` commands for issue tracking and workflow management
- Can create issues with `bd create` and track progress through development cycles
- Issues will sync with git repository and can be managed alongside code
- Future team members can easily pick up workflow through beads documentation

**Beads Commands Available**
- `bd create "issue title"`: Create new issues
- `bd list`: View all issues
- `bd show <issue-id>`: View issue details
- `bd update <issue-id> --status in_progress/done`: Update status
- `bd sync`: Sync issues with git remote

— OpenCode, 2026-01-22 PST (Seattle)

### 2026-01-24 – Feedback Cleanup & Backwards Compatibility Removal

**Summary**
Applied all cleanup feedback from feedback.md including complete removal of backwards compatibility for server-generated keys. Simplified codebase to support only client-generated keypair system (betterkeys), improved error messages, and cleaned up response models.

**Key Changes Applied**

**High Priority Items**
1. **Removed debug print** from client (line 131) - eliminated unnecessary `print(f"DEBUG: server_url='{config.server_url}', type={type(config.server_url)}")`
2. **Standardized success message** in client to be more consistent with better security messaging
3. **Fixed server response model** to exclude host_key field entirely using `exclude_none=True` Pydantic config
4. **Improved P256 public key error message** with specific format hint showing expected PEM header
5. **Removed backwards compatibility** - completely removed server-generated keypath as requested for MVP focus

**Medium Priority Items**  
6. **Extracted nebula signing code** into helper function `run_nebula_sign()` for cleaner code organization
7. **Verified pathlib consistency** - client already uses pathlib consistently throughout

**Backwards Compatibility Removal**
- Updated `AddRequest` model to make `public_key` required (not optional)
- Simplified server logic to single client-key path only
- Removed server-generated key handling code completely
- Updated `CertBundle` model with `exclude_none=True` to omit host_key field entirely
- Updated test expectations to reflect new API behavior

**Error Message Improvements**
- Changed generic "public_key must be a valid Nebula X25519 public key PEM" 
- To specific "public_key must be an X25519 Nebula public key (begins with '-----BEGIN NEBULA X25519 PUBLIC KEY-----')"
- This provides users with exact expected format for debugging

**Response Model Cleanup**
- Added `model_config = pydantic.ConfigDict(exclude_none=True)` to `CertBundle`
- Now client-generated key responses omit host_key field entirely instead of sending null
- Cleaner API response for consumers

**Test Updates**
- Updated `test_add_endpoint_requires_public_key` to reflect backwards compatibility removal
- Test now expects 422 for requests without public_key (instead of 200 for legacy mode)
- Test verifies host_key field is completely absent from responses
- All 11 tests pass after changes

**Client Success Message Update**
- Changed from "Success! Wrote files:" to "Successfully enrolled host!"
- Added lock emoji: "🔒 Private key was generated locally and never sent to the server."
- More consistent, professional tone that emphasizes security benefits

**Code Organization**
- Extracted nebula certificate signing logic into async helper function
- Cleaner separation of concerns in `/add` endpoint
- Removed duplicated error handling since only one code path remains
- Maintained all error handling quality and user-friendly messages

**Impact on MVP**
- Significant simplification: only client-generated keypair system
- Improved security posture: private keys never touch server
- Cleaner API surface: fewer conditional paths and edge cases
- Better user experience: clearer error messages and success feedback
- Reduced maintenance burden: single code path for certificate generation

**Files Modified**
- `nacme/client.py`: Removed debug print, updated success message
- `nacme/server.py`: Removed backwards compatibility, added helper function, improved error messages
- `tests/test_e2e.py`: Updated test expectations for new API behavior

All tests pass and codebase is now cleaner and more focused on the betterkeys security model.

**Next Steps**
- Ready for manual network testing with simplified codebase
- Consider updating documentation to reflect backwards compatibility removal
- Future work on renew/rekey flows should focus on client-generated key model only

— OpenCode, 2026-01-24 PST (Seattle)

### 2026-01-24 – Linting Cleanup

**Summary**
Fixed all linting errors identified by ruff including unused variables and unused imports. Codebase now passes all linting checks while maintaining full functionality.

**Issues Fixed**
1. **Unused variable `cert_content`** in `tests/test_betterkeys_tdd.py:171`
   - Removed assignment to unused variable that was only reading from data["host_cert"]
   - Kept the assertion that verifies hostname contains "betterkeys-" prefix

2. **Unused import `json`** in `tests/test_e2e.py:168`
   - Removed import that wasn't being used in `test_add_endpoint_requires_public_key`
   - Function works correctly without the import

3. **Unused import `urllib.parse`** in `tests/test_e2e.py:262`
   - Removed import that wasn't being used in `test_url_handling_variants`
   - URL handling functionality works correctly without the import

**Verification**
- `ruff check --fix` reports "All checks passed!"
- All 11 tests continue to pass after linting cleanup
- No functional changes made - only removed dead code
- Code is now cleaner and follows linting standards

**Files Modified**
- `tests/test_betterkeys_tdd.py`: Removed unused variable assignment
- `tests/test_e2e.py`: Removed two unused imports

Linting cleanup complete and codebase is now fully compliant.

— OpenCode, 2026-01-24 PST (Seattle)
