"""
TDD tests for suggested IP feature - allow clients to suggest specific IPs.

These tests define the desired behavior:
1. Clients can suggest a specific IP address for their host
2. If suggested IP is valid and available, it gets assigned
3. If suggested IP is taken, system falls back to auto-allocation
4. Suggested IP must be within configured subnet and not reserved addresses
5. Client CLI supports --ip flag to pass through to API
"""

import os
import pathlib
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
            "NACME_PUBLIC_PORT": "18000",
            "NACME_ADMIN_PORT": "19000",
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


@pytest.fixture
def server_process(test_env):
    """Start server in subprocess for testing."""
    server_path = os.path.join(os.path.dirname(__file__), "..", "nacme", "server.py")

    proc = subprocess.Popen(
        [sys.executable, server_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(os.environ, **test_env),
    )

    # Give server time to start up
    time.sleep(3)

    # Verify server is responding
    max_attempts = 20
    for attempt in range(max_attempts):
        try:
            resp = httpx.get(
                f"http://localhost:{test_env['NACME_PUBLIC_PORT']}/docs", timeout=1
            )
            if resp.status_code == 200:
                print(f"Server started successfully on attempt {attempt + 1}")
                break
        except Exception as e:
            if attempt == max_attempts - 1:
                # Get server output for debugging
                stdout, stderr = proc.communicate(timeout=1)
                print(f"Server stdout: {stdout.decode()}")
                print(f"Server stderr: {stderr.decode()}")
                proc.terminate()
                pytest.fail(f"Server failed to start: {e}")
            time.sleep(0.5)

    yield proc

    # Clean up
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def api_key(server_process, test_env):
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


def generate_test_keypair():
    """Generate a test keypair for requests."""
    with tempfile.TemporaryDirectory() as tmp:
        key_path = f"{tmp}/test.key"
        pub_path = f"{tmp}/test.pub"

        subprocess.run(
            ["nebula-cert", "keygen", "-out-key", key_path, "-out-pub", pub_path],
            check=True,
            capture_output=True,
        )

        public_key = pathlib.Path(pub_path).read_text()
        return public_key


def test_suggested_ip_success(test_env, server_process, api_key):
    """Test that a valid, available suggested IP gets assigned."""
    public_url = f"http://localhost:{test_env['NACME_PUBLIC_PORT']}"
    public_key = generate_test_keypair()

    # Suggest an IP that should be available (10.200.0.100)
    suggested_ip = "10.200.0.100"

    resp = httpx.post(
        f"{public_url}/add",
        json={
            "api_key": api_key,
            "hostname_prefix": "lighthouse",
            "public_key": public_key,
            "suggested_ip": suggested_ip,
        },
        timeout=10,
    )

    assert resp.status_code == 200, f"Request failed: {resp.text}"
    data = resp.json()

    # Verify we got the exact IP we requested
    assert data["ip"] == suggested_ip, f"Expected IP {suggested_ip}, got {data['ip']}"
    assert "lighthouse" in data["hostname"]
    assert "host_cert" in data


def test_suggested_ip_already_taken(test_env, server_process, api_key):
    """Test that when suggested IP is taken, system falls back to auto-allocation."""
    public_url = f"http://localhost:{test_env['NACME_PUBLIC_PORT']}"

    # First request: claim an IP
    public_key_1 = generate_test_keypair()
    suggested_ip = "10.200.0.50"

    resp1 = httpx.post(
        f"{public_url}/add",
        json={
            "api_key": api_key,
            "public_key": public_key_1,
            "suggested_ip": suggested_ip,
        },
        timeout=10,
    )

    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["ip"] == suggested_ip

    # Second request: try to claim the same IP
    public_key_2 = generate_test_keypair()

    resp2 = httpx.post(
        f"{public_url}/add",
        json={
            "api_key": api_key,
            "public_key": public_key_2,
            "suggested_ip": suggested_ip,  # Same IP as first request
        },
        timeout=10,
    )

    assert resp2.status_code == 200, f"Fallback failed: {resp2.text}"
    data2 = resp2.json()

    # Should have gotten a different IP via auto-allocation
    assert data2["ip"] != suggested_ip, "Should have fallen back to auto-allocation"
    assert data2["ip"].startswith("10.200.0."), "Should be in same subnet"
    assert "host_cert" in data2


def test_suggested_ip_out_of_subnet(test_env, server_process, api_key):
    """Test that IPs outside configured subnet are rejected."""
    public_url = f"http://localhost:{test_env['NACME_PUBLIC_PORT']}"
    public_key = generate_test_keypair()

    # Subnet is 10.200.0.0/24, so 10.201.0.1 is out of range
    out_of_subnet_ip = "10.201.0.1"

    resp = httpx.post(
        f"{public_url}/add",
        json={
            "api_key": api_key,
            "public_key": public_key,
            "suggested_ip": out_of_subnet_ip,
        },
        timeout=10,
    )

    assert resp.status_code == 422, f"Should reject out-of-subnet IP: {resp.text}"
    assert "subnet" in resp.text.lower() or "not in" in resp.text.lower()


def test_suggested_ip_invalid_format(test_env, server_process, api_key):
    """Test that malformed IP strings are rejected."""
    public_url = f"http://localhost:{test_env['NACME_PUBLIC_PORT']}"
    public_key = generate_test_keypair()

    invalid_ips = [
        "not-an-ip",
        "256.1.1.1",  # Out of range
        "10.200.0",  # Incomplete
        "10.200.0.1.1",  # Too many octets
        "",  # Empty string
        "10.200.0.abc",  # Non-numeric
    ]

    for invalid_ip in invalid_ips:
        resp = httpx.post(
            f"{public_url}/add",
            json={
                "api_key": api_key,
                "public_key": public_key,
                "suggested_ip": invalid_ip,
            },
            timeout=10,
        )

        assert resp.status_code == 422, (
            f"Should reject invalid IP '{invalid_ip}': {resp.text}"
        )


def test_suggested_ip_network_address(test_env, server_process, api_key):
    """Test that network address (.0) cannot be assigned."""
    public_url = f"http://localhost:{test_env['NACME_PUBLIC_PORT']}"
    public_key = generate_test_keypair()

    # Network address for 10.200.0.0/24
    network_address = "10.200.0.0"

    resp = httpx.post(
        f"{public_url}/add",
        json={
            "api_key": api_key,
            "public_key": public_key,
            "suggested_ip": network_address,
        },
        timeout=10,
    )

    assert resp.status_code == 422, f"Should reject network address: {resp.text}"
    assert "network address" in resp.text.lower()


def test_suggested_ip_broadcast_address(test_env, server_process, api_key):
    """Test that broadcast address (.255) cannot be assigned."""
    public_url = f"http://localhost:{test_env['NACME_PUBLIC_PORT']}"
    public_key = generate_test_keypair()

    # Broadcast address for 10.200.0.0/24
    broadcast_address = "10.200.0.255"

    resp = httpx.post(
        f"{public_url}/add",
        json={
            "api_key": api_key,
            "public_key": public_key,
            "suggested_ip": broadcast_address,
        },
        timeout=10,
    )

    assert resp.status_code == 422, f"Should reject broadcast address: {resp.text}"
    assert "broadcast" in resp.text.lower()


def test_client_passthrough_ip(test_env, server_process, api_key):
    """Test end-to-end client CLI with --ip flag."""
    with tempfile.TemporaryDirectory() as temp_out_dir:
        # Set up client environment
        client_env = dict(test_env)
        suggested_ip = "10.200.0.150"

        client_env.update(
            {
                "NACME_SERVER_URL": f"http://localhost:{test_env['NACME_PUBLIC_PORT']}",
                "NACME_API_KEY": api_key,
                "NACME_OUT_DIR": temp_out_dir,
            }
        )

        # Run client with --ip flag
        client_path = os.path.join(
            os.path.dirname(__file__), "..", "nacme", "client.py"
        )

        proc = subprocess.run(
            [sys.executable, client_path, "--ip", suggested_ip],
            env=dict(os.environ, **client_env),
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Verify client succeeded
        assert proc.returncode == 0, f"Client failed: {proc.stderr}\n{proc.stdout}"

        # Verify output files exist
        assert os.path.exists(os.path.join(temp_out_dir, "ca.crt"))
        assert os.path.exists(os.path.join(temp_out_dir, "host.crt"))
        assert os.path.exists(os.path.join(temp_out_dir, "host.key"))

        # Verify output indicates correct IP
        output = proc.stdout
        assert suggested_ip in output, f"Expected IP {suggested_ip} in output"


def test_client_passthrough_ip_via_env(test_env, server_process, api_key):
    """Test end-to-end client CLI with NACME_SUGGESTED_IP env var."""
    with tempfile.TemporaryDirectory() as temp_out_dir:
        # Set up client environment
        client_env = dict(test_env)
        suggested_ip = "10.200.0.160"

        client_env.update(
            {
                "NACME_SERVER_URL": f"http://localhost:{test_env['NACME_PUBLIC_PORT']}",
                "NACME_API_KEY": api_key,
                "NACME_OUT_DIR": temp_out_dir,
                "NACME_SUGGESTED_IP": suggested_ip,  # Via env var instead of CLI flag
            }
        )

        # Run client without --ip flag (should use env var)
        client_path = os.path.join(
            os.path.dirname(__file__), "..", "nacme", "client.py"
        )

        proc = subprocess.run(
            [sys.executable, client_path],
            env=dict(os.environ, **client_env),
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Verify client succeeded
        assert proc.returncode == 0, f"Client failed: {proc.stderr}\n{proc.stdout}"

        # Verify output indicates correct IP
        output = proc.stdout
        assert suggested_ip in output, f"Expected IP {suggested_ip} in output"


def test_multiple_hosts_same_suggested_ip_concurrent(test_env, server_process, api_key):
    """Test race condition: two clients suggest same IP concurrently.

    One should get the suggested IP, the other should fall back.
    """
    import concurrent.futures

    public_url = f"http://localhost:{test_env['NACME_PUBLIC_PORT']}"
    suggested_ip = "10.200.0.200"

    def make_request():
        """Make a request with the same suggested IP."""
        public_key = generate_test_keypair()
        resp = httpx.post(
            f"{public_url}/add",
            json={
                "api_key": api_key,
                "public_key": public_key,
                "suggested_ip": suggested_ip,
            },
            timeout=10,
        )
        return resp

    # Fire off two requests concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(make_request) for _ in range(2)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    # Both requests should succeed
    assert all(r.status_code == 200 for r in results), "Both requests should succeed"

    # Extract IPs from responses
    ips = [r.json()["ip"] for r in results]

    # Exactly one should have gotten the suggested IP
    suggested_count = sum(1 for ip in ips if ip == suggested_ip)
    assert suggested_count == 1, (
        f"Exactly one request should get suggested IP {suggested_ip}, got {ips}"
    )

    # The other should have gotten a different IP (fallback)
    assert len(set(ips)) == 2, f"Should have two different IPs, got {ips}"
    assert all(ip.startswith("10.200.0.") for ip in ips), "Both IPs should be in subnet"


def test_suggested_ip_none_uses_auto_allocation(test_env, server_process, api_key):
    """Test that omitting suggested_ip still works (backward compatibility)."""
    public_url = f"http://localhost:{test_env['NACME_PUBLIC_PORT']}"
    public_key = generate_test_keypair()

    # Request without suggested_ip field at all
    resp = httpx.post(
        f"{public_url}/add",
        json={
            "api_key": api_key,
            "public_key": public_key,
            # No suggested_ip field
        },
        timeout=10,
    )

    assert resp.status_code == 200, f"Request without suggested_ip failed: {resp.text}"
    data = resp.json()

    # Should get an auto-allocated IP in the subnet
    assert "ip" in data
    assert data["ip"].startswith("10.200.0.")
    assert "host_cert" in data
