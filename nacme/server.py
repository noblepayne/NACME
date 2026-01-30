# nacme_server.py - Single-file MVP NACME server (add-only)
import asyncio
import base64
import contextlib
import hashlib
import ipaddress
import json
import os
import pathlib
import re
import secrets
import sys
import tempfile
import time

import aiosqlite
import structlog
import uvicorn
import fastapi
import pydantic
import pydantic_settings
import plumbum


# === Config via env vars ===
class AppConfig(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_file=".env", env_prefix="NACME_"
    )

    public_port: int = pydantic.Field(
        8000, description="Port for the public-facing API"
    )
    admin_port: int = pydantic.Field(
        9000, description="Port for the admin API (firewall this!)"
    )
    master_key: str = pydantic.Field(
        ..., description="Master key for creating API keys"
    )
    db_path: str = pydantic.Field(
        "nacme.db", description="Path to the SQLite database file"
    )
    ca_cert: str = pydantic.Field(
        "./ca.crt", description="Path to the Nebula CA certificate"
    )
    ca_key: str = pydantic.Field(
        "./ca.key", description="Path to the Nebula CA private key"
    )
    subnet_cidr: str = pydantic.Field(
        ..., description="Required: CIDR of the Nebula subnet (e.g., '10.100.0.0/24')"
    )
    default_expiry_days: int = pydantic.Field(
        365, description="Default validity period for new certificates in days"
    )
    random_suffix_length: int = pydantic.Field(
        6, description="Length of the random hex suffix for generated hostnames"
    )

    @pydantic.field_validator("master_key")
    def master_key_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("NACME_MASTER_KEY must be set and non-empty")
        return v

    @pydantic.field_validator("subnet_cidr")
    def valid_cidr(cls, v: str) -> str:
        try:
            net = ipaddress.ip_network(v, strict=False)
            if net.num_addresses <= 4:  # Need room for hosts
                raise ValueError(
                    "Subnet too small (need at least /30 for IPv4 or /126 for IPv6)"
                )
            return str(net)
        except ValueError as e:
            raise ValueError(f"Invalid CIDR: {e}")


try:
    CONFIG = AppConfig()
except Exception as e:
    print(f"Configuration error: {e}")
    sys.exit(1)

# Runtime config cache (populated at startup)
_RUNTIME_CONFIG: dict[str, str] = {}

# === Structured logging ===
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
log = structlog.get_logger()


# === DB helpers ===
@contextlib.asynccontextmanager
async def get_db():
    conn = await aiosqlite.connect(CONFIG.db_path)
    try:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA busy_timeout=10000")
        await conn.execute("PRAGMA synchronous=NORMAL")
        yield conn
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
    finally:
        await conn.close()


async def init_db():
    async with get_db() as conn:
        await conn.executescript("""
                CREATE TABLE IF NOT EXISTS configs (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_hash TEXT NOT NULL UNIQUE,
                    expiration INTEGER,
                    uses_remaining INTEGER,
                    groups_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS hosts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hostname TEXT NOT NULL UNIQUE,
                    ip TEXT NOT NULL UNIQUE,
                    groups_json TEXT NOT NULL,
                    expiry INTEGER NOT NULL,
                    api_key_id INTEGER NOT NULL,
                    current_cert TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
            CREATE INDEX IF NOT EXISTS idx_hosts_expiry ON hosts(expiry);
            CREATE INDEX IF NOT EXISTS idx_hosts_hostname ON hosts(hostname);
            CREATE INDEX IF NOT EXISTS idx_hosts_ip ON hosts(ip);
            CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);
        """)

        # Seed from config if missing - atomic transaction ensures all or nothing
        try:
            cursor = await conn.execute("SELECT 1 FROM configs WHERE key = 'cidr'")
            if not await cursor.fetchone():
                await conn.execute(
                    "INSERT INTO configs (key, value) VALUES (?, ?)",
                    ("cidr", CONFIG.subnet_cidr),
                )
                log.info("seeded_cidr", cidr=CONFIG.subnet_cidr)
        except Exception as e:
            log.error("config_seeding_failed", key="cidr", error=str(e), exc_info=True)
            raise

        for key, val in [
            ("default_expiry_days", str(CONFIG.default_expiry_days)),
            ("random_suffix_length", str(CONFIG.random_suffix_length)),
        ]:
            cursor = await conn.execute("SELECT 1 FROM configs WHERE key = ?", (key,))
            if not await cursor.fetchone():
                await conn.execute(
                    "INSERT INTO configs (key, value) VALUES (?, ?)", (key, val)
                )

        # Load all runtime config into memory cache
        cursor = await conn.execute("SELECT key, value FROM configs")
        for row in await cursor.fetchall():
            _RUNTIME_CONFIG[row[0]] = row[1]

        # Cache CA certificate at startup to avoid repeated disk I/O
        try:
            ca_content = pathlib.Path(CONFIG.ca_cert).read_text()
            _RUNTIME_CONFIG["ca_cert_content"] = ca_content
            log.info("ca_cert_cached", path=CONFIG.ca_cert)
        except Exception as e:
            log.error("ca_cert_cache_failed", path=CONFIG.ca_cert, error=str(e))
            raise

        log.info("runtime_config_cached", config=_RUNTIME_CONFIG)


# === Models ===
class AddRequest(pydantic.BaseModel):
    api_key: str
    hostname_prefix: str | None = None
    public_key: str  # PEM string, required for client-generated keypair system
    suggested_ip: str | None = None  # NEW: Optional IP suggestion

    @pydantic.field_validator("hostname_prefix")
    def sanitize_hostname_prefix(cls, v: str | None) -> str | None:
        if v is None:
            return None

        # Strip whitespace
        v = v.strip()

        # Enforce max length
        if len(v) > 63:
            raise ValueError("hostname_prefix must be 63 characters or less")

        # Enforce allowed charset: alphanumeric, hyphens only

        if not re.match(r"^[a-zA-Z0-9-]+$", v):
            raise ValueError(
                "hostname_prefix may only contain letters, numbers, and hyphens"
            )

        # Normalize repeated hyphens to single hyphen
        v = re.sub(r"-+", "-", v)

        # Remove leading/trailing hyphens
        v = v.strip("-")

        # Ensure not empty after sanitization
        if not v:
            raise ValueError("hostname_prefix cannot be empty after sanitization")

        return v

    @pydantic.field_validator("public_key")
    def validate_public_key(cls, v: str) -> str:
        if not v:
            raise ValueError("public_key cannot be empty")

        # Check PEM headers
        if not v.startswith("-----BEGIN NEBULA X25519 PUBLIC KEY-----"):
            raise ValueError("public_key must be an X25519 Nebula public key")

        if "-----END NEBULA X25519 PUBLIC KEY-----" not in v:
            raise ValueError("public_key must have proper PEM footer")

        # Extract base64 content between headers

        try:
            lines = v.strip().split("\n")
            base64_lines = [
                line.strip()
                for line in lines
                if line.strip() and not line.startswith("-----")
            ]
            if not base64_lines:
                raise ValueError("public_key has no body content")

            # Attempt to decode base64 content
            base64_content = "".join(base64_lines)
            decoded = base64.b64decode(base64_content)

            # X25519 public keys should be 32 bytes
            if len(decoded) != 32:
                raise ValueError(
                    "public_key is not a valid X25519 key (incorrect length)"
                )

        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f"public_key contains invalid base64 content: {e}")

        return v

    @pydantic.field_validator("suggested_ip")
    def validate_suggested_ip_format(cls, v: str | None) -> str | None:
        """Validate that suggested_ip is a valid IP address format."""
        if v is None:
            return None

        # Validate IP format
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError("suggested_ip must be a valid IP address")

        return v


class CertBundle(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(exclude_none=True)

    ca_cert: str
    host_cert: str
    ip: str
    hostname: str
    expiry: int


# === Helpers ===
def hash_key(key: str) -> str:
    # Security Note: Using raw SHA256 for API key hashing.
    # For this MVP, we accept the tradeoff of no salt/pepper since:
    # 1. API keys are high-entropy random strings (not user passwords)
    # 2. Keys have usage limits and expiration times
    # 3. Database access already implies compromise of the entire system
    # Future versions could add a server-side pepper from env vars for defense-in-depth.
    return hashlib.sha256(key.encode()).hexdigest()


def validate_ip_in_subnet(ip_str: str, subnet_cidr: str) -> None:
    """Validate that IP is in subnet and not network/broadcast address.

    Raises ValueError with descriptive message if invalid.
    """
    ip = ipaddress.ip_address(ip_str)
    net = ipaddress.ip_network(subnet_cidr)

    # Check if in subnet
    if ip not in net:
        raise ValueError(f"IP {ip_str} is not in subnet {subnet_cidr}")

    # Check if network address
    if ip == net.network_address:
        raise ValueError(f"IP {ip_str} is the network address and cannot be assigned")

    # Check if broadcast address (IPv4 only)
    if net.version == 4 and ip == net.broadcast_address:
        raise ValueError(f"IP {ip_str} is the broadcast address and cannot be assigned")


async def run_nebula_sign(
    nebula_cmd,
    hostname: str,
    ip: str,
    groups: list[str],
    expiry_days: int,
    ca_cert: str,
    ca_key: str,
    subnet_cidr: str,
    public_key_pem: str,
) -> str:
    """Run nebula-cert sign command and return the certificate content."""
    with tempfile.TemporaryDirectory() as tmp:
        out_crt = pathlib.Path(tmp) / "host.crt"
        in_pub = pathlib.Path(tmp) / "host.pub"

        # Write client's public key to temporary file
        in_pub.write_text(public_key_pem)

        nebula_cmd[
            "sign",
            "-ca-crt",
            ca_cert,
            "-ca-key",
            ca_key,
            "-in-pub",
            str(in_pub),
            "-name",
            hostname,
            "-ip",
            f"{ip}/{ipaddress.ip_network(subnet_cidr).prefixlen}",
            "-groups",
            ",".join(groups),
            "-duration",
            f"{expiry_days * 24}h",
            "-out-crt",
            str(out_crt),
        ]()

        # Verify certificate file was created
        if not out_crt.exists():
            raise RuntimeError(
                "nebula-cert completed but output certificate file missing"
            )

        if out_crt.stat().st_size == 0:
            raise RuntimeError("nebula-cert created empty certificate file")

        host_cert = out_crt.read_text()

        # Basic certificate validation
        if "-----BEGIN NEBULA CERTIFICATE V2-----" not in host_cert:
            raise RuntimeError(
                "Generated certificate is not a valid Nebula certificate"
            )

        return host_cert


async def allocate_ip(conn: aiosqlite.Connection) -> str:
    """
    Allocate an unused IP from the configured subnet.

    Strategy selection:
    - Small networks (< 100k addresses): sequential scan from random start
    - Large networks (≥ 100k addresses): random selection

    This handles both typical IPv4 /24 subnets (254 addresses) and future
    IPv6 subnets (trillions of addresses) efficiently.
    """
    cidr_str = _RUNTIME_CONFIG.get("cidr", CONFIG.subnet_cidr)

    net = ipaddress.ip_network(cidr_str)
    num_hosts = net.num_addresses - 2  # Exclude network and broadcast

    if num_hosts < 1:
        raise RuntimeError(f"Network {cidr_str} has no usable addresses")

    # Strategy depends on address space size
    # Threshold of 100k balances memory usage vs sequential scan efficiency
    if num_hosts < 100_000:
        # Small network: sequential scan from random start
        # Guarantees finding an IP if any are available
        cursor = await conn.execute("SELECT ip FROM hosts")
        allocated = {row[0] for row in await cursor.fetchall()}

        # Start at random offset to avoid predictable .1, .2, .3 pattern
        start_offset = secrets.randbelow(num_hosts)

        for i in range(num_hosts):
            offset = (start_offset + i) % num_hosts + 1
            candidate = str(net.network_address + offset)
            if candidate not in allocated:
                return candidate

        raise RuntimeError(
            f"No available IPs in {cidr_str} (all {num_hosts} addresses allocated)"
        )

    else:
        # Large network: random selection
        # Collision probability is negligible even at moderate utilization
        # Example: /64 IPv6 with 1 billion allocated IPs = 0.0054% collision chance
        for attempt in range(100):
            offset = secrets.randbelow(num_hosts) + 1
            candidate = str(net.network_address + offset)

            cursor = await conn.execute(
                "SELECT COUNT(*) FROM hosts WHERE ip = ?", (candidate,)
            )
            count_row = await cursor.fetchone()
            if count_row and count_row[0] == 0:
                return candidate

        # If we hit this with a large network, something is very wrong
        raise RuntimeError(
            f"Could not allocate IP in {cidr_str} after 100 attempts. "
            f"Network may be approaching capacity despite large address space."
        )


async def generate_hostname(conn: aiosqlite.Connection, prefix: str = "node-") -> str:
    suffix_len = int(_RUNTIME_CONFIG.get("random_suffix_length", "6"))

    for _ in range(20):
        suffix = secrets.token_hex((suffix_len + 1) // 2)[:suffix_len]
        hn = f"{prefix.rstrip('-')}-{suffix}"
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM hosts WHERE hostname = ?", (hn,)
        )
        count_row = await cursor.fetchone()
        if count_row and count_row[0] == 0:
            return hn
    raise RuntimeError("Could not generate unique hostname after 20 attempts")


# === Public App ===
public_app = fastapi.FastAPI(title="NACME Public API", docs_url="/docs")


@public_app.post("/add", response_model=CertBundle)
async def add_host(request: AddRequest):
    key_hash = hash_key(request.api_key)

    async with get_db() as conn:
        cursor = await conn.execute(
            "SELECT id, expiration, uses_remaining, groups_json FROM api_keys WHERE key_hash = ?",
            (key_hash,),
        )
        row = await cursor.fetchone()
        if not row:
            log.warning("invalid_key_attempt", prefix=request.hostname_prefix)
            raise fastapi.HTTPException(403, "Invalid API key")

        api_id, exp, uses, groups_json = row
        now = int(time.time())
        if exp and exp < now:
            raise fastapi.HTTPException(403, "API key expired")
        if uses is not None and uses <= 0:
            raise fastapi.HTTPException(403, "No uses remaining on API key")

        groups = json.loads(groups_json)
        if not groups:
            raise fastapi.HTTPException(500, "API key has no groups defined")

        expiry_days = int(
            _RUNTIME_CONFIG.get("default_expiry_days", str(CONFIG.default_expiry_days))
        )
        expiry = now + (expiry_days * 86400)

        # Retry loop for allocation + cert generation + insertion (handles race conditions)
        max_retries = 10

        for retry_attempt in range(max_retries):
            try:
                # IP allocation with optional suggestion
                if request.suggested_ip:
                    try:
                        # Validate IP is in subnet and not reserved
                        validate_ip_in_subnet(request.suggested_ip, CONFIG.subnet_cidr)

                        # Check if available in database
                        cursor = await conn.execute(
                            "SELECT COUNT(*) FROM hosts WHERE ip = ?",
                            (request.suggested_ip,),
                        )
                        count_row = await cursor.fetchone()

                        if count_row and count_row[0] == 0:
                            # IP is available, use it
                            ip = request.suggested_ip
                            log.info("suggested_ip_accepted", ip=ip)
                        else:
                            # IP already taken, fall back to auto-allocation
                            ip = await allocate_ip(conn)
                            log.warning(
                                "suggested_ip_taken_fallback",
                                suggested=request.suggested_ip,
                                allocated=ip,
                            )
                    except ValueError as e:
                        # Invalid IP suggestion (out of subnet, network/broadcast addr)
                        log.warning(
                            "suggested_ip_invalid",
                            ip=request.suggested_ip,
                            error=str(e),
                        )
                        raise fastapi.HTTPException(422, f"Invalid suggested_ip: {e}")
                else:
                    # No suggestion, use auto-allocation
                    ip = await allocate_ip(conn)

                # Generate hostname
                hostname = await generate_hostname(
                    conn, request.hostname_prefix or "node-"
                )

                # Public key validation is now handled by Pydantic validator in AddRequest

                nebula = plumbum.local["nebula-cert"]

                try:
                    host_cert = await run_nebula_sign(
                        nebula,
                        hostname=hostname,
                        ip=ip,
                        groups=groups,
                        expiry_days=expiry_days,
                        ca_cert=CONFIG.ca_cert,
                        ca_key=CONFIG.ca_key,
                        subnet_cidr=CONFIG.subnet_cidr,
                        public_key_pem=request.public_key,
                    )

                except plumbum.ProcessExecutionError as e:
                    # Analyze specific failure modes
                    error_msg = str(e).lower()
                    stderr_lower = e.stderr.lower() if e.stderr else ""

                    if "no such file" in error_msg or "command not found" in error_msg:
                        user_msg = "nebula-cert binary not found or not executable"
                    elif (
                        "permission denied" in error_msg or "access denied" in error_msg
                    ):
                        user_msg = (
                            "Permission denied accessing CA files or working directory"
                        )
                    elif "invalid" in stderr_lower and "certificate" in stderr_lower:
                        user_msg = "CA certificate or key file is invalid or corrupted"
                    elif "invalid" in stderr_lower and "ip" in stderr_lower:
                        user_msg = f"Invalid IP address format: {ip}"
                    elif "invalid" in stderr_lower and "groups" in stderr_lower:
                        user_msg = f"Invalid groups format: {groups}"
                    else:
                        user_msg = (
                            f"Certificate generation failed: {stderr_lower or str(e)}"
                        )

                    log.error(
                        "nebula_cert_sign_failed",
                        error=str(e),
                        stdout=e.stdout,
                        stderr=e.stderr,
                        hostname=hostname,
                        ip=ip,
                        user_message=user_msg,
                    )
                    raise fastapi.HTTPException(500, user_msg)
                except fastapi.HTTPException:
                    # Let FastAPI exceptions bubble up unchanged
                    raise
                except Exception as e:
                    log.error(
                        "nebula_cert_unexpected_error",
                        error=str(e),
                        hostname=hostname,
                        ip=ip,
                    )
                    raise fastapi.HTTPException(
                        500, f"Unexpected error during certificate generation: {e}"
                    )

                # Atomic insert - UNIQUE constraints will catch collisions
                await conn.execute(
                    """
                    INSERT INTO hosts (hostname, ip, groups_json, expiry, api_key_id, 
                                       current_cert, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        hostname,
                        ip,
                        json.dumps(groups),
                        expiry,
                        api_id,
                        host_cert,
                        now,
                        now,
                    ),
                )

                # Success! Break out of retry loop
                break

            except aiosqlite.IntegrityError as e:
                error_msg = str(e).lower()

                if retry_attempt < max_retries - 1:
                    # Still have retries left
                    if "ip" in error_msg:
                        log.warning(
                            "ip_allocation_collision_retry",
                            attempt=retry_attempt + 1,
                            ip=ip,
                        )
                        continue
                    elif "hostname" in error_msg:
                        log.warning(
                            "hostname_collision_retry",
                            attempt=retry_attempt + 1,
                            hostname=hostname,
                        )
                        continue

                # Either exhausted retries or non-collision error
                log.error(
                    "host_insertion_failed",
                    error=str(e),
                    retry_attempt=retry_attempt,
                )
                raise fastapi.HTTPException(
                    500,
                    f"Failed to create host record after {retry_attempt + 1} attempts",
                )
        else:
            # Should never reach here due to exception handling above,
            # but handle it anyway for safety
            raise fastapi.HTTPException(
                500,
                f"Could not allocate unique IP/hostname after {max_retries} attempts",
            )

        if uses is not None:
            await conn.execute(
                "UPDATE api_keys SET uses_remaining = ? WHERE id = ?",
                (uses - 1, api_id),
            )

    # Use cached CA certificate to avoid disk I/O per request
    ca_content = _RUNTIME_CONFIG.get("ca_cert_content")
    if ca_content is None:
        raise fastapi.HTTPException(
            500, "CA certificate not cached - server configuration error"
        )

    log.info(
        "host_added_success", hostname=hostname, ip=ip, groups=groups, client_key=True
    )
    return CertBundle(
        ca_cert=ca_content,
        host_cert=host_cert,
        ip=ip,
        hostname=hostname,
        expiry=expiry,
    )


# === Admin App ===
admin_app = fastapi.FastAPI(title="NACME Admin API", docs_url="/docs-admin")


async def verify_master_key(
    x_master_key: str = fastapi.Header(None, alias="X-Master-Key"),
):
    if x_master_key != CONFIG.master_key:
        raise fastapi.HTTPException(403, "Invalid master key")
    return True


@admin_app.post("/keys")
async def create_api_key(
    groups: list[str],
    expiry_unix: int | None = None,
    uses_remaining: int | None = None,
    _=fastapi.Depends(verify_master_key),
):
    if not groups:
        raise fastapi.HTTPException(400, "At least one group is required")

    new_key = secrets.token_urlsafe(32)
    key_hash = hash_key(new_key)
    now = int(time.time())

    try:
        async with get_db() as conn:
            await conn.execute(
                """
                INSERT INTO api_keys (key_hash, expiration, uses_remaining, groups_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (key_hash, expiry_unix, uses_remaining, json.dumps(groups), now, now),
            )

        log.info("api_key_created", groups=groups, uses=uses_remaining)

    except Exception as e:
        log.error("api_key_creation_failed", error=str(e), exc_info=True)
        raise fastapi.HTTPException(500, f"API key creation failed: {str(e)}")
    return {
        "api_key": new_key,
        "note": "This key is shown only once. Store it securely.",
    }


# === Startup ===
async def validate_startup():
    """Validate critical dependencies before starting server."""
    errors = []

    # Check CA certificate
    ca_cert_path = pathlib.Path(CONFIG.ca_cert)
    if not ca_cert_path.exists():
        errors.append(f"CA certificate not found: {CONFIG.ca_cert}")
    elif not ca_cert_path.is_file():
        errors.append(f"CA certificate path is not a file: {CONFIG.ca_cert}")
    else:
        try:
            ca_cert_path.read_text()
        except Exception as e:
            errors.append(f"Cannot read CA certificate: {e}")

    # Check CA key
    ca_key_path = pathlib.Path(CONFIG.ca_key)
    if not ca_key_path.exists():
        errors.append(f"CA key not found: {CONFIG.ca_key}")
    elif not ca_key_path.is_file():
        errors.append(f"CA key path is not a file: {CONFIG.ca_key}")
    else:
        try:
            ca_key_path.read_text()
        except Exception as e:
            errors.append(f"Cannot read CA key: {e}")

    # Check nebula-cert binary
    try:
        nebula = plumbum.local["nebula-cert"]
        nebula["--version"]()
    except plumbum.CommandNotFound:
        errors.append("nebula-cert binary not found in PATH")
    except Exception as e:
        errors.append(f"nebula-cert validation failed: {e}")

    # Check DB directory is writable
    db_path = pathlib.Path(CONFIG.db_path)
    db_dir = (
        db_path.parent if db_path.parent != pathlib.Path("") else pathlib.Path.cwd()
    )
    if not os.access(db_dir, os.W_OK):
        errors.append(f"Database directory not writable: {db_dir}")

    if errors:
        for error in errors:
            log.error("startup_validation_failed", error=error)
        sys.exit(1)

    log.info("startup_validation_passed")


async def main():
    await validate_startup()
    await init_db()
    log.info(
        "nacme_server_started",
        public_port=CONFIG.public_port,
        admin_port=CONFIG.admin_port,
        subnet=CONFIG.subnet_cidr,
    )

    public_config = uvicorn.Config(
        public_app, host="0.0.0.0", port=CONFIG.public_port, log_level="info"
    )
    admin_config = uvicorn.Config(
        admin_app, host="0.0.0.0", port=CONFIG.admin_port, log_level="info"
    )

    await asyncio.gather(
        uvicorn.Server(public_config).serve(),
        uvicorn.Server(admin_config).serve(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("nacme_server_shutdown")
        sys.exit(0)
