{
  description = "Octocook — multi-recipe cooking scheduler";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-darwin" "aarch64-darwin" "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f:
        nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in {
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = with pkgs; [
            python312       # tools/ + server/ (3.10+ required for X | None syntax)
            nodejs_22       # web/ (Vite 8 requires 20.19+)
            sqlite          # sqlite3 CLI for inspecting octocook.db
          ];

          shellHook = ''
            echo "🐙 Octocook dev shell"
            echo "   Python $(python3 --version)"
            echo "   Node   $(node --version)"
            echo "   SQLite $(sqlite3 --version | cut -d' ' -f1)"
            echo ""
            echo "First time? Run: make setup"
          '';
        };
      });
    };
}
