"""Smoke tests for NACME server and client imports."""

import os
import pathlib
import sys

import pytest

# Add project root to path so we can import nacme modules
project_root = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_server_import_missing_env_vars():
    """Test that server import fails with missing required environment variables."""
    # Clear any existing NACME env vars
    env_vars_to_clear = [
        "NACME_MASTER_KEY",
        "NACME_SUBNET_CIDR",
        "NACME_PUBLIC_PORT",
        "NACME_ADMIN_PORT",
        "NACME_DB_PATH",
        "NACME_CA_CERT",
        "NACME_CA_KEY",
    ]

    original_values = {}
    for var in env_vars_to_clear:
        if var in os.environ:
            original_values[var] = os.environ[var]
            del os.environ[var]

    try:
        # Import should fail due to missing required env vars
        # The server calls sys.exit(1) on config failure, so we expect SystemExit
        with pytest.raises(SystemExit):
            import nacme.server  # noqa: F401
    finally:
        # Restore original env vars
        for var, value in original_values.items():
            os.environ[var] = value


def test_client_import():
    """Test that client module can be imported successfully."""
    # Client should be importable without env vars since it uses CLI args
    import nacme.client as client

    assert client is not None
    assert hasattr(client, "ClientConfig")
    assert hasattr(client, "load_config")


def test_server_import_with_env_vars():
    """Test that server imports successfully with required env vars set."""
    # Set minimal required env vars
    test_env = {
        "NACME_MASTER_KEY": "test-master-key-32-chars-long-!",
        "NACME_SUBNET_CIDR": "10.100.0.0/24",
    }

    original_values = {}
    for var, value in test_env.items():
        if var in os.environ:
            original_values[var] = os.environ[var]
        os.environ[var] = value

    try:
        # Import should work with required vars set
        import nacme.server as server

        config = server.AppConfig()
        assert config.master_key == "test-master-key-32-chars-long-!"
        assert config.subnet_cidr == "10.100.0.0/24"
        assert config.public_port == 8000  # default value
        assert config.admin_port == 9000  # default value
    finally:
        # Restore original env vars
        for var, value in original_values.items():
            if var in os.environ:
                os.environ[var] = value
            else:
                del os.environ[var]
