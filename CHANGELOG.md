# Changelog

All notable changes to NACME will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Fixed
- IP allocation now uses hybrid strategy: sequential scan for small networks (< 100k addresses), random for large
- Added collision retry pattern (max 10 attempts) to handle concurrent requests gracefully
- Server validates CA files and nebula-cert binary at startup with clear error messages
- Enhanced nebula-cert error handling with specific error analysis and better user messages

### Changed  
- IP allocation is now deterministic for typical /24 networks (sequential from random start)
- Config values cached in memory instead of DB lookup per request (performance improvement)
- Increased allocation retry limit to 100 for large networks (future IPv6 support)
- Improved error messages for nebula-cert failures (permission, file format, IP/group validation)

### Added
- Startup validation for critical dependencies (CA cert/key, nebula-cert binary, DB directory)
- Runtime config caching for performance
- Structured logging for allocation collisions and retries
- Database persistence test to verify server restart reliability
- Better error messages distinguishing IP vs hostname collisions vs other failures

### Changed
- Enforced Clojure-style namespaced imports throughout the codebase
- Updated import style guidelines in AGENTS.md documentation
- Converted all imports in `nacme/server.py` and `nacme/client.py` to use namespaced imports
- Fixed database method calls to use proper aiosqlite cursor patterns

### Added
- Import style guidelines to AGENTS.md specifying Clojure-style namespaced imports only