# NACME v0.1.0 - First Stable Release

## Key Features

- **Automated certificate minting** for Nebula networks
- **SQLite database persistence** for reliability  
- **End-to-end onboarding flow** with single command
- **Comprehensive test suite** with 5 passing tests
- **Nix development environment** for reproducible builds
- **Robust IP allocation** with collision handling
- **Concurrency safety** for simultaneous requests
- **Structured logging** and error handling

## Installation

### Option 1: Nix Development Environment (Recommended)
```bash
git clone https://github.com/yourusername/nacme.git
cd nacme
./dev.sh
```

### Option 2: pip Install
```bash
pip install nacme
```

### Option 3: Development from Source
```bash
git clone https://github.com/yourusername/nacme.git
cd nacme
python -m pip install -e .
```

## Quick Start

```bash
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

## Current Limitations

- IPv4 focus (IPv6 algorithm ready for future)
- No certificate renewal functionality yet
- Development servers without HTTPS
- Single-file server architecture (by MVP design)

## What's Next

v0.1.1 will focus on:
- Certificate renewal functionality
- HTTPS support for production deployments
- Enhanced monitoring and observability

## Documentation

Complete setup and usage instructions available in README.md.

## Contributing

We welcome contributions! See AGENTS.md for development guidelines and docs/DEVLOG.md for project context.