# NACME
ACME for Nebula PKI.

Automated certificate minting for Nebula networks. Designed to sit on top of your existing CA and handle the certificate lifecycle without becoming a full control plane.

## Quick Start

```bash
# Setup (one-time)
./dev.sh  # recommended: enters Nix development environment
# or ensure nebula-cert and Python 3.12+ dependencies are available

# Configure
export NACME_MASTER_KEY="your-master-key"
export NACME_SUBNET_CIDR="10.100.0.0/24"
export NACME_CA_CERT="./ca.crt"
export NACME_CA_KEY="./ca.key"

# Start server
python nacme/server.py

# Create API key
API_KEY=$(curl -s -X POST http://localhost:9000/keys \
  -H "X-Master-Key: $NACME_MASTER_KEY" \
  -d '["group1"]' | jq -r '.api_key')

# Client onboarding
export NACME_API_KEY="$API_KEY"
python nacme/client.py  # writes ca.crt, host.crt, host.key
```

## What NACME Is (and Isn't)

**NACME provides:**
- Automated certificate minting when presented with valid API keys
- IP allocation and hostname generation (with optional IP suggestions)
- Database persistence across server restarts
- Simple API for certificate requests

**NACME does not:**
- Manage network configurations or routing
- Provide a full control plane or monitoring
- Handle certificate renewals (planned for future versions)
- Replace your existing PKI infrastructure

## Configuration

**Required**: 
- `NACME_MASTER_KEY` - Master key for creating API keys
- `NACME_SUBNET_CIDR` - Network CIDR (e.g., "10.100.0.0/24")
- `NACME_CA_CERT` - Path to your existing Nebula CA certificate
- `NACME_CA_KEY` - Path to your existing Nebula CA private key

**Optional**: 
- `NACME_PUBLIC_PORT` - Public API port (default: 8000)
- `NACME_ADMIN_PORT` - Admin API port (default: 9000)
- `NACME_DB_PATH` - Database file path (default: "nacme.db")
- `NACME_DEFAULT_EXPIRY_DAYS` - Certificate validity period (default: 365)
- `NACME_RANDOM_SUFFIX_LENGTH` - Length of hostname suffix (default: 6)

**Client-specific**:
- `NACME_SERVER_URL` - Server URL for client requests
- `NACME_API_KEY` - API key for authentication
- `NACME_OUT_DIR` - Output directory for certificates (default: "/etc/nebula")
- `NACME_HOSTNAME_PREFIX` - Custom hostname prefix (optional)
- `NACME_SUGGESTED_IP` - Suggested IP address (optional, see below)

## Features

### Client-Generated Keypairs (Betterkeys)

NACME requires client-generated keypairs for enhanced security:

- **Private key isolation**: Private keys are generated locally on the client machine and never transmitted to or stored on the server
- **Zero server exposure**: Server compromise cannot leak private keys since they never touch the server
- **Compatible workflow**: Uses the same `nebula-cert keygen` + `sign -in-pub` pattern as manual Nebula certificate management

**Usage**: The client automatically generates keypairs locally and sends only the public key to the server. This is the required mode for all clients.

### Suggested IP Addresses

Clients can suggest specific IP addresses, useful for lighthouse nodes or declarative configurations:

```bash
# Using CLI flag
python nacme/client.py --ip 10.100.0.10

# Using environment variable
export NACME_SUGGESTED_IP="10.100.0.10"
python nacme/client.py
```

**Behavior**:
- If the suggested IP is valid and available, it will be assigned
- If the suggested IP is already taken, the system automatically falls back to auto-allocation
- Suggested IPs must be within the configured subnet and cannot be network/broadcast addresses

**Use cases**:
- **Lighthouse nodes**: Assign stable IPs (e.g., 10.100.0.1, 10.100.0.2) for known infrastructure
- **NixOS declarative configs**: Specify IP in configuration.nix before deployment
- **Migration from manual**: Preserve existing IP assignments when switching to NACME

## Development

Testing strategy uses end-to-end blackbox tests with some smoke tests.

```bash
./dev.sh     # enter development environment
pytest -v     # run test suite
```

## Contributing

We prefer small, focused PRs that follow the existing patterns:
- See `AGENTS.md` for detailed development guidelines
- Check `docs/DEVLOG.md` for project context and decisions
- End-to-end and integration tests preferred over unit tests
- Maintain the existing code style and import patterns

## Release Notes

### v0.1.0 - First Stable Release

This release delivers a complete automated certificate management solution for Nebula networks:

- **Automated certificate minting** for Nebula networks
- **SQLite database persistence** for reliability  
- **End-to-end onboarding flow** with single command
- **Comprehensive test suite** with 5 passing tests
- **Nix development environment** for reproducible builds
- **Robust IP allocation** with collision handling
- **Concurrency safety** for simultaneous requests
- **Structured logging** and error handling

#### Current Limitations

- IPv4 focus (IPv6 algorithm ready for future)
- No certificate renewal functionality yet
- Development servers without HTTPS
- Single-file server architecture (by MVP design)
