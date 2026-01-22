import os
import tempfile
import time
import subprocess
import sys

import pytest
import httpx


@pytest.fixture
def test_env():
    """Set up test environment variables for server and client."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test.db")
        ca_cert_path = os.path.join(os.path.dirname(__file__), "fixtures", "ca.crt")
        ca_key_path = os.path.join(os.path.dirname(__file__), "fixtures", "ca.key")

        env = {
            "NACME_MASTER_KEY": "test-master-key-32-chars-long-!",
            "NACME_SUBNET_CIDR": "10.200.0.0/24",
            "NACME_PUBLIC_PORT": "18001",
            "NACME_ADMIN_PORT": "19001",
            "NACME_DB_PATH": db_path,
            "NACME_CA_CERT": ca_cert_path,
            "NACME_CA_KEY": ca_key_path,
            "NACME_DEFAULT_EXPIRY_DAYS": "30",
            "PYTHONPATH": os.path.join(os.path.dirname(__file__), ".."),
        }

        # Save original env vars
        original_env = {k: os.environ.get(k) for k in env.keys()}

        # Set test env vars
        for k, v in env.items():
            os.environ[k] = v

        yield env

        # Restore original env vars
        for k, v in original_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def start_server_process(test_env, timeout=30):
    """Start server in subprocess and wait for it to be ready."""
    server_path = os.path.join(os.path.dirname(__file__), "..", "nacme", "server.py")

    proc = subprocess.Popen(
        [sys.executable, server_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(os.environ, **test_env),
    )

    # Give server time to start up
    max_attempts = timeout // 2
    for attempt in range(max_attempts):
        try:
            resp = httpx.get(
                f"http://localhost:{test_env['NACME_PUBLIC_PORT']}/docs", timeout=1
            )
            if resp.status_code == 200:
                return proc
        except Exception:
            if attempt == max_attempts - 1:
                # Get server output for debugging
                stdout, stderr = proc.communicate(timeout=1)
                print(f"Server stdout: {stdout.decode()}")
                print(f"Server stderr: {stderr.decode()}")
                proc.terminate()
                pytest.fail("Server failed to start")
            time.sleep(2)

    proc.terminate()
    pytest.fail("Server failed to start within timeout")


def create_api_key(test_env):
    """Create an API key via admin endpoint."""
    admin_url = f"http://localhost:{test_env['NACME_ADMIN_PORT']}"

    resp = httpx.post(
        f"{admin_url}/keys",
        headers={"X-Master-Key": test_env["NACME_MASTER_KEY"]},
        json=["test-group"],
        timeout=10,
    )

    assert resp.status_code == 200
    data = resp.json()
    return data["api_key"]


def add_host(test_env, api_key):
    """Add a host via public API."""
    public_url = f"http://localhost:{test_env['NACME_PUBLIC_PORT']}"

    resp = httpx.post(
        f"{public_url}/add",
        json={"api_key": api_key, "hostname_prefix": "test"},
        timeout=10,
    )

    assert resp.status_code == 200
    return resp.json()


def test_database_persistence(test_env):
    """Test that server restart preserves existing data and allows continued operations."""

    # === Phase 1: Start server and create initial data ===
    print("\n=== Phase 1: Initial server startup ===")
    server_proc = start_server_process(test_env)

    # Create API key
    api_key_1 = create_api_key(test_env)
    print(f"Created API key 1: {api_key_1[:20]}...")

    # Add first host
    host_1 = add_host(test_env, api_key_1)
    print(f"Added host 1: {host_1['hostname']} -> {host_1['ip']}")

    # Add second host
    host_2 = add_host(test_env, api_key_1)
    print(f"Added host 2: {host_2['hostname']} -> {host_2['ip']}")

    # Verify hosts have different IPs
    assert host_1["ip"] != host_2["ip"], "Hosts should have different IPs"
    assert host_1["hostname"] != host_2["hostname"], (
        "Hosts should have different hostnames"
    )

    # Gracefully shutdown server
    print("Shutting down server...")
    server_proc.terminate()
    server_proc.wait(timeout=5)
    time.sleep(1)  # Give it time to fully shutdown

    # === Phase 2: Restart server with same database ===
    print("\n=== Phase 2: Server restart ===")
    server_proc_2 = start_server_process(test_env)

    # Create another API key to verify server is fully functional
    api_key_2 = create_api_key(test_env)
    print(f"Created API key 2: {api_key_2[:20]}...")

    # Add a new host (should get a different IP from previous hosts)
    host_3 = add_host(test_env, api_key_2)
    print(f"Added host 3: {host_3['hostname']} -> {host_3['ip']}")

    # Verify new host is unique
    assert host_3["ip"] not in [host_1["ip"], host_2["ip"]], (
        "New host should have unique IP"
    )
    assert host_3["hostname"] not in [host_1["hostname"], host_2["hostname"]], (
        "New host should have unique hostname"
    )

    # === Phase 3: Verify previous data is still accessible ===
    print("\n=== Phase 3: Verify previous data persistence ===")
    # Try to use the original API key again
    host_4 = add_host(test_env, api_key_1)
    print(f"Added host 4 with original API key: {host_4['hostname']} -> {host_4['ip']}")

    # Verify this host is also unique
    all_ips = [host_1["ip"], host_2["ip"], host_3["ip"], host_4["ip"]]
    all_hostnames = [
        host_1["hostname"],
        host_2["hostname"],
        host_3["hostname"],
        host_4["hostname"],
    ]
    assert len(set(all_ips)) == 4, "All hosts should have unique IPs"
    assert len(set(all_hostnames)) == 4, "All hosts should have unique hostnames"

    # Cleanup
    print("\n=== Phase 4: Cleanup ===")
    server_proc_2.terminate()
    server_proc_2.wait(timeout=5)

    print("✅ Database persistence test passed!")

    # Additional verification: Check database file exists and has content
    assert os.path.exists(test_env["NACME_DB_PATH"]), "Database file should exist"
    assert os.path.getsize(test_env["NACME_DB_PATH"]) > 0, (
        "Database file should not be empty"
    )
