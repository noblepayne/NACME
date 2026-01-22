{
  description = "NACME dev shell (Nebula ACME-like PKI helper)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    bd.url = "github:steveyegge/beads";
    bd.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = {
    self,
    nixpkgs,
    bd,
    ...
  }: let
    system = "x86_64-linux";
    pkgs = nixpkgs.legacyPackages.${system};

    pythonEnv = pkgs.python312.withPackages (ps:
      with ps; [
        fastapi
        uvicorn
        pydantic
        pydantic-settings
        aiosqlite
        plumbum
        structlog
        httpx
        pytest
        pytest-asyncio
        hypothesis
        icontract
      ]);
  in {
    formatter.${system} = pkgs.alejandra;
    devShells.${system}.default = pkgs.mkShell {
      name = "nacme-dev";

      packages = [
        pythonEnv
        pkgs.nebula # provides nebula-cert binary in PATH
        pkgs.sqlite # sqlite3 CLI for quick DB inspection
        pkgs.curl # for manual API testing
        pkgs.jq # pretty-print JSON responses
        pkgs.ruff
        bd.packages.${system}.default
        #pkgs.dotenvx
      ];

      shellHook = ''
        export SHELL=''${OLDSHELL:-$SHELL}
        export PYTHONUNBUFFERED=1
        export PYTHONDONTWRITEBYTECODE=1
        echo "NACME dev shell loaded"
        echo "  Python: $(python --version)"
        echo "  nebula-cert: $(nebula-cert --version || echo 'not found - install nebula package')"
        echo ""
        echo "Quick commands:"
        echo "  python nacme_server.py          # run server"
        echo "  python nacme_client.py          # run client"
        echo "  sqlite3 nacme.db                # inspect DB"
        echo "  curl -X POST http://localhost:9000/keys -H 'X-Master-Key: ...' ..."
        echo ""
        echo "Env vars you might want to set:"
        echo "  export NACME_SUBNET_CIDR=10.100.0.0/24"
        echo "  export NACME_MASTER_KEY=supersecretchangeit"
        echo "  export NACME_SERVER_URL=http://localhost:8000"
        echo "  export NACME_API_KEY=your_generated_key"
      '';
    };
  };
}
