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


def test_end_to_end_onboarding(test_env, server_process, api_key):
    """Test complete onboarding flow: server + client."""
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
        server_url = f"http://localhost:{test_env['NACME_PUBLIC_PORT']}".rstrip("/")
        print(f"Server URL being set: {server_url}")
        client_env["NACME_SERVER_URL"] = server_url
        proc = subprocess.run(
            [sys.executable, client_path],
            env=dict(os.environ, **client_env),
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Verify client succeeded
        assert proc.returncode == 0, f"Client failed: {proc.stderr}"

        # Verify output files exist
        ca_path = os.path.join(temp_out_dir, "ca.crt")
        cert_path = os.path.join(temp_out_dir, "host.crt")
        key_path = os.path.join(temp_out_dir, "host.key")

        assert os.path.exists(ca_path), "CA certificate not created"
        assert os.path.exists(cert_path), "Host certificate not created"
        assert os.path.exists(key_path), "Host key not created"

        # Verify file permissions (key should be 600)
        key_stat = os.stat(key_path)
        assert oct(key_stat.st_mode)[-3:] == "600", (
            "Host key should have 600 permissions"
        )

        # Verify file contents are non-empty
        assert os.path.getsize(ca_path) > 0, "CA certificate is empty"
        assert os.path.getsize(cert_path) > 0, "Host certificate is empty"
        assert os.path.getsize(key_path) > 0, "Host key is empty"

        # Verify certificates are valid nebula certificates
        ca_content = pathlib.Path(ca_path).read_text()
        cert_content = pathlib.Path(cert_path).read_text()

        assert "-----BEGIN NEBULA CERTIFICATE V2-----" in ca_content
        assert "-----END NEBULA CERTIFICATE V2-----" in ca_content
        assert "-----BEGIN NEBULA CERTIFICATE V2-----" in cert_content
        assert "-----END NEBULA CERTIFICATE V2-----" in cert_content

        # Verify client output contains expected info
        assert "Success!" in proc.stdout
        assert "CA:" in proc.stdout
        assert "Cert:" in proc.stdout
        assert "Key:" in proc.stdout
        assert "Host:" in proc.stdout
        assert "Expires:" in proc.stdout


def test_url_handling_variants(test_env, server_process, api_key):
    """Test that client handles different server URL formats correctly."""
    import urllib.parse

    base_port = test_env["NACME_PUBLIC_PORT"]

    # Test different URL formats that should all resolve to the same endpoint
    url_variants = [
        f"http://localhost:{base_port}",  # no trailing slash
        f"http://localhost:{base_port}/",  # single trailing slash
        f"http://localhost:{base_port}//",  # double trailing slash
        f"http://localhost:{base_port}/api",  # path without trailing slash
        f"http://localhost:{base_port}/api/",  # path with trailing slash
    ]

    for variant_url in url_variants:
        with tempfile.TemporaryDirectory() as temp_out_dir:
            client_env = dict(test_env)
            client_env.update(
                {
                    "NACME_SERVER_URL": variant_url,
                    "NACME_API_KEY": api_key,
                    "NACME_OUT_DIR": temp_out_dir,
                }
            )

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

            # Should succeed regardless of URL format quirks
            assert proc.returncode == 0, (
                f"Client failed with URL {variant_url}: {proc.stderr}"
            )

            # Verify certificate files were created
            assert os.path.exists(os.path.join(temp_out_dir, "ca.crt"))
            assert os.path.exists(os.path.join(temp_out_dir, "host.crt"))
            assert os.path.exists(os.path.join(temp_out_dir, "host.key"))
