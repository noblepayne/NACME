"""
TDD tests for betterkeys feature - client-generated keypairs.

These tests define the desired behavior according to betterkeys.md:
1. Client generates X25519 keypair locally
2. Client sends only public key to server
3. Server signs and returns only certificate (no private key)
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
            "NACME_DEFAULT_EXPIRY_DAYS": "30",  # Shorter expiry for testing
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


def test_client_generated_x25519_keypair(test_env, server_process, api_key):
    """Test client-generated X25519 keypair flow according to betterkeys.md (adjusted for nebula-cert capabilities)."""

    # Generate X25519 keypair locally (as client would)
    with tempfile.TemporaryDirectory() as tmp:
        # Generate test keypair using nebula-cert with X25519
        nebula_cmd = [
            "nebula-cert",
            "keygen",
            "-out-key",
            f"{tmp}/test.key",
            "-out-pub",
            f"{tmp}/test.pub",
        ]

        result = subprocess.run(nebula_cmd, capture_output=True, text=True)
        assert result.returncode == 0, (
            f"Failed to generate test keypair: {result.stderr}"
        )

        # Read public key - should be X25519 format (what nebula-cert generates)
        public_key = pathlib.Path(f"{tmp}/test.pub").read_text()
        assert "-----BEGIN NEBULA X25519 PUBLIC KEY-----" in public_key

        # Test successful request with X25519 public key
        response = httpx.post(
            f"http://localhost:{test_env['NACME_PUBLIC_PORT']}/add",
            json={
                "api_key": api_key,
                "hostname_prefix": "betterkeys-",
                "public_key": public_key,
            },
            timeout=10,
        )

        if response.status_code != 200:
            print(f"Response status: {response.status_code}")
            print(f"Response text: {response.text}")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure for betterkeys (host_key should be None)
        assert "ca_cert" in data
        assert "host_cert" in data
        assert data.get("host_key") is None, (
            "Response should have host_key=None in betterkeys mode"
        )

        # Verify certificate was signed correctly
        assert "-----BEGIN NEBULA CERTIFICATE V2-----" in data["host_cert"]

        # Verify certificate contains our public key (indirectly via validation)
        assert "betterkeys-" in data["hostname"]


def test_public_key_validation(test_env, server_process, api_key):
    """Test public key validation for betterkeys mode."""

    # Test empty public key
    response = httpx.post(
        f"http://localhost:{test_env['NACME_PUBLIC_PORT']}/add",
        json={"api_key": api_key, "public_key": ""},
        timeout=10,
    )
    print(f"Response status: {response.status_code}")
    print(f"Response text: {response.text}")
    assert response.status_code == 422  # Pydantic validation error

    # Test invalid public key format
    response = httpx.post(
        f"http://localhost:{test_env['NACME_PUBLIC_PORT']}/add",
        json={"api_key": api_key, "public_key": "not-a-real-public-key"},
        timeout=10,
    )
    if response.status_code != 422:
        print(f"Invalid format response status: {response.status_code}")
        print(f"Invalid format response text: {response.text}")
    assert response.status_code == 422  # Pydantic validation error

    # Test wrong key type (P256 instead of X25519)
    p256_pub = """-----BEGIN NEBULA P256 PUBLIC KEY-----
BDQZXh+gm9yKFUSW7X5SAo6uaXH7aWRVF9NiCutl9l3HUiVL0pbVahBwFlXrq6tj
UpsdHVLnrDl4QjF+2CqeyCs=
-----END NEBULA P256 PUBLIC KEY-----"""

    response = httpx.post(
        f"http://localhost:{test_env['NACME_PUBLIC_PORT']}/add",
        json={"api_key": api_key, "public_key": p256_pub},
        timeout=10,
    )
    print(f"Response status: {response.status_code}")
    print(f"Response text: {response.text}")
    if response.status_code != 422:
        print("Error: Expected 422 but got different status")
    assert response.status_code == 422  # Pydantic validation error


def test_end_to_end_client_with_betterkeys(test_env, server_process, api_key):
    """Test complete end-to-end flow with actual client binary."""
    with tempfile.TemporaryDirectory() as temp_out_dir:
        # Set up client environment
        client_env = dict(test_env)
        client_env.update(
            {
                "NACME_SERVER_URL": f"http://localhost:{test_env['NACME_PUBLIC_PORT']}".rstrip(
                    "/"
                ),
                "NACME_API_KEY": api_key,
                "NACME_OUT_DIR": temp_out_dir,
            }
        )

        # Run client as subprocess
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
        assert proc.returncode == 0, (
            f"Client failed: {proc.stderr}\nOutput: {proc.stdout}"
        )

        # Verify output files exist
        ca_path = os.path.join(temp_out_dir, "ca.crt")
        cert_path = os.path.join(temp_out_dir, "host.crt")
        key_path = os.path.join(temp_out_dir, "host.key")

        assert os.path.exists(ca_path), "CA certificate not created"
        assert os.path.exists(cert_path), "Host certificate not created"
        assert os.path.exists(key_path), "Host key not created"

        # Verify X25519 keypair was generated locally (what nebula-cert generates)
        key_content = pathlib.Path(key_path).read_text()
        assert "-----BEGIN NEBULA X25519 PRIVATE KEY-----" in key_content
        assert "-----END NEBULA X25519 PRIVATE KEY-----" in key_content

        # Verify certificate was signed by server
        cert_content = pathlib.Path(cert_path).read_text()
        assert "-----BEGIN NEBULA CERTIFICATE V2-----" in cert_content

        # Verify client output indicates betterkeys flow
        output = proc.stdout
        assert "Success" in output
        assert "generated locally" in output.lower() or "never sent" in output.lower()


def test_x25519_certificate_content(test_env, server_process, api_key):
    """Test that X25519 public keys result in valid certificates."""

    # Generate a proper X25519 keypair
    with tempfile.TemporaryDirectory() as tmp:
        # Generate keypair
        subprocess.run(
            [
                "nebula-cert",
                "keygen",
                "-out-key",
                f"{tmp}/test.key",
                "-out-pub",
                f"{tmp}/test.pub",
            ],
            check=True,
            capture_output=True,
        )

        public_key = pathlib.Path(f"{tmp}/test.pub").read_text()

        # Get certificate
        response = httpx.post(
            f"http://localhost:{test_env['NACME_PUBLIC_PORT']}/add",
            json={"api_key": api_key, "public_key": public_key},
            timeout=10,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify certificate can be validated with nebula-cert
        cert_path = pathlib.Path(tmp) / "received.crt"
        cert_path.write_text(data["host_cert"])

        # Try to validate/print certificate
        result = subprocess.run(
            ["nebula-cert", "print", "-path", str(cert_path)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"Certificate validation failed: {result.stderr}"
        # nebula-cert print outputs JSON format, check for valid certificate structure
        assert '"curve":' in result.stdout
        assert '"details":' in result.stdout
