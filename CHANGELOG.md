# Changelog

All notable changes to NACME will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-01-22

### Added
- NACME server with FastAPI endpoints for certificate management
- NACME client for automated certificate onboarding
- SQLite database schema for API keys, hosts, and configuration
- Certificate generation using nebula-cert integration
- Test infrastructure with PKI fixtures
- End-to-end test covering complete onboarding flow
- Database persistence test for server reliability
- Nix development environment with all dependencies
- Comprehensive documentation (ARCHITECTURE.md, DEVLOG.md, AGENTS.md)
- Structured logging and error handling throughout
- URL handling test covering various server URL formats
- Security guidelines and known limitations section in README
- Contributing guidelines section in README
- .gitignore file for proper version control hygiene

### Changed
- README expanded with project description and setup instructions
- Added CHANGELOG.md for version tracking
- Code style guidance updated for pragmatic approach (AGENTS.md)
- Simplified type hints from `typing.Dict` to `dict` for clarity

### Fixed
- IP allocation uses hybrid strategy (sequential for small networks, random for large)
- Added collision retry pattern for concurrent requests (max 10 attempts)
- Server validates dependencies at startup with clear error messages
- Enhanced nebula-cert error handling with specific failure analysis
- Config values cached in memory for performance improvement
- Double-slash URL issue in client using `urllib.parse.urljoin`
- URL construction now handles trailing slashes and path variations correctly

## Unreleased