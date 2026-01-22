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
- IP allocation and hostname generation
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

Core features are complete and tested for homelab deployments.
