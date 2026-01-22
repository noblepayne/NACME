# nacme_client.py - Simple client to onboard a host via NACME server
import argparse
import os
import sys
import tempfile
import pathlib
import time

import httpx
import pydantic


# === Config via env + CLI args ===
class ClientConfig(pydantic.BaseModel):
    server_url: pydantic.HttpUrl
    api_key: str
    out_dir: pathlib.Path = pathlib.Path("/etc/nebula")
    ca_file: str = "ca.crt"
    cert_file: str = "host.crt"
    key_file: str = "host.key"
    hostname_prefix: str | None = None

    @pydantic.field_validator("out_dir", mode="before")
    def ensure_dir(cls, v):
        if v is None:
            v = "/etc/nebula"
        path = pathlib.Path(v)
        # The client should not fail if it cannot create the directory,
        # but it should try. The user may be running as non-root.
        try:
            path.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            print(
                f"Warning: Could not create output directory {path}. Assuming it exists.",
                file=sys.stderr,
            )
        return path


def load_config() -> ClientConfig:
    parser = argparse.ArgumentParser(description="NACME client - onboard a host")
    parser.add_argument("--server", help="Server URL (overrides NACME_SERVER_URL)")
    parser.add_argument("--key", help="API key (overrides NACME_API_KEY)")
    parser.add_argument(
        "--prefix", help="Hostname prefix (overrides NACME_HOSTNAME_PREFIX)"
    )
    parser.add_argument(
        "--out-dir",
        type=pathlib.Path,
        help="Output directory (overrides NACME_OUT_DIR)",
    )
    parser.add_argument("--ca-file", help="CA cert filename (overrides NACME_CA_FILE)")
    parser.add_argument(
        "--cert-file", help="Host cert filename (overrides NACME_CERT_FILE)"
    )
    parser.add_argument(
        "--key-file", help="Host key filename (overrides NACME_KEY_FILE)"
    )
    args = parser.parse_args()

    # Collect config from environment and CLI args, with CLI taking precedence
    config_data = {
        "server_url": args.server or os.getenv("NACME_SERVER_URL"),
        "api_key": args.key or os.getenv("NACME_API_KEY"),
        "hostname_prefix": args.prefix or os.getenv("NACME_HOSTNAME_PREFIX"),
        "out_dir": args.out_dir or os.getenv("NACME_OUT_DIR"),
        "ca_file": args.ca_file or os.getenv("NACME_CA_FILE"),
        "cert_file": args.cert_file or os.getenv("NACME_CERT_FILE"),
        "key_file": args.key_file or os.getenv("NACME_KEY_FILE"),
    }
    # Filter out None values so Pydantic defaults can apply
    config_data = {k: v for k, v in config_data.items() if v is not None}

    try:
        return ClientConfig(**config_data)
    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        print(
            "Please provide required arguments via CLI flags or environment variables (e.g., NACME_SERVER_URL).",
            file=sys.stderr,
        )
        sys.exit(1)


# === Main logic ===
def main():
    config = load_config()

    cert_path = config.out_dir / config.cert_file
    key_path = config.out_dir / config.key_file

    # Idempotent: skip if already present
    if cert_path.exists() and key_path.exists():
        print(f"Host files already exist in {config.out_dir} → skipping add.")
        print(f"  cert: {cert_path}")
        print(f"  key:  {key_path}")
        sys.exit(0)

    payload = {"api_key": config.api_key}
    if config.hostname_prefix:
        payload["hostname_prefix"] = config.hostname_prefix

    print(f"Requesting new host cert from {config.server_url}/add ...")
    print(f"DEBUG: server_url='{config.server_url}', type={type(config.server_url)}")

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{str(config.server_url).rstrip('/')}/add",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        ca_path = config.out_dir / config.ca_file

        # Atomic writes
        def atomic_write(path: pathlib.Path, content: str):
            with tempfile.NamedTemporaryFile(
                mode="w", dir=config.out_dir, delete=False
            ) as tmp:
                tmp.write(content)
            os.rename(tmp.name, path)
            os.chmod(path, 0o600)  # restrictive perms for key

        atomic_write(ca_path, data["ca_cert"])
        atomic_write(cert_path, data["host_cert"])
        atomic_write(key_path, data["host_key"])

        print("Success! Wrote files:")
        print(f"  CA:   {ca_path}")
        print(f"  Cert: {cert_path}")
        print(f"  Key:  {key_path}")
        print(f"  Host: {data['hostname']} @ {data['ip']}")
        print(f"  Expires: {time.ctime(data['expiry'])}")

    except httpx.HTTPStatusError as e:
        print(f"Request failed: {e}", file=sys.stderr)
        if e.response is not None:
            print(e.response.text, file=sys.stderr)
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"Request error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
