# NACME Architecture

NACME ("Nebula ACME") is a lightweight, best-effort PKI lease manager for self-hosted Nebula networks.  
It automates adding new hosts and (eventually) renewing certificates without becoming a full control plane or dashboard.

## Goals & Non-Goals

**Goals**
- Make onboarding new Nebula hosts feel as frictionless as Tailscale authkeys
- Automate the manual `nebula-cert sign` step + IP/hostname allocation
- Provide a shared-secret model (API keys scoped to groups)
- Keep everything configurable via environment variables (no code changes)
- Stay extremely simple: best-effort, single-box, no HA, no revocation enforcement
- Complement Nebula without competing with Defined Networking's hosted product

**Non-Goals**
- Full dashboard or policy management
- Certificate revocation (Nebula doesn't support it natively)
- Centralized monitoring, logging to SIEM, MFA, device posture
- Multi-CA support, CA rotation automation
- High-availability or distributed operation

## Core Components

### 1. Public API Server
- Port: configurable (default 8000)
- Endpoints:
  - `POST /add` — given an API key + optional hostname prefix → returns CA cert + fresh host cert/key, IP, hostname, expiry
- Authentication: API key in request body (hashed + looked up in DB)
- Rate/usage limiting: per-key `uses_remaining` counter (optional)
- Zero-config for clients: just key + URL

### 2. Admin API Server
- Port: configurable (default 9000) — separate from public for firewalling
- Endpoints:
  - `POST /keys` — create new API key with groups, optional expiry/uses
- Authentication: static master key via `X-Master-Key` header (env var only)
- Purpose: bootstrap and manage permission bundles (keys)

Both servers run in the **same process** using two `uvicorn.Server` instances via `asyncio.gather`.

### 3. Database (SQLite)
- Single file (`nacme.db` configurable)
- WAL mode + busy timeout for safe concurrent access
- Tables:
  - `configs` — global settings (cidr, expiry_days, suffix_length)
  - `api_keys` — permission bundles (hash, groups_json, expiry, uses_remaining)
  - `hosts` — issued leases (hostname, ip, groups, expiry, current cert/key PEM)
- No ORM: plain parameterized SQL via `aiosqlite`

### 4. Certificate Generation
- Uses `nebula-cert sign` via `plumbum` subprocess
- CA cert/key read from disk (configurable paths)
- Duration: days-based, taken from config
- Temp files for output → read into memory → written by client
- IP format: `<allocated_ip>/<subnet_prefix>` (dynamic from config)

### 5. IP & Hostname Allocation
- IP: random within subnet (skip network/broadcast), collision-checked against DB
- Hostname: `<prefix>-<random-hex-suffix>`, uniqueness checked
- Prefix: optional from request, defaults to "node-"

### 6. Client (nacme_client.py)
- One-shot / pre-start script (suitable for systemd oneshot)
- Checks if `host.crt` + `host.key` already exist → skips if present
- Calls `/add` → atomically writes `ca.crt`, `host.crt`, `host.key`
- Config via env vars + CLI overrides
- Idempotent and safe to run on every boot

## Security & Trust Model

- API keys are bearer tokens — scoped only to issuance/renewal
- Master key is env-only, never stored in DB
- All sensitive data (keys, certs) handled in memory briefly
- Host keys sent over HTTPS (recommended but not enforced in MVP)
- No built-in revocation — expired certs naturally stop working
- CA key never leaves disk or enters process memory beyond read

## Deployment Assumptions

- Single container / single process (two listening ports)
- CA cert/key managed externally (Nix sops, manual, etc.)
- Nebula installed (provides `nebula-cert`)
- SQLite DB on persistent volume

## Future Extensions (post-MVP)

- `/renew` endpoint (verify current key ownership → reissue same groups/IP)
- Cert history table for archiving old certs on renewal
- Basic expiry listing / alerting (GET /hosts?expiring=7d)
- Client-side expiry check + auto-renew timer
- Optional basic web UI (Streamlit?) for admin

This architecture deliberately stays in the "helper automation" space — not a competitor to full Zero Trust mesh solutions.
