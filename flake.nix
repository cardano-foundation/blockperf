{
  description = "Cardano Blockperf";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-23.11";
    flake-parts.url = "github:hercules-ci/flake-parts";
  };

  outputs = inputs @ {flake-parts, ...}:
    with builtins;
      flake-parts.lib.mkFlake {inherit inputs;} {
        systems = ["x86_64-linux" "x86_64-darwin"];
        perSystem = {
          config,
          pkgs,
          lib,
          ...
        }:
          with pkgs.python3Packages; {
            packages.blockperf = buildPythonApplication {
              pname = "blockperf";

              version = let
                initFile = readFile ./src/blockperf/__init__.py;
                initVersion = head (match ".*__version__ = \"([[:digit:]]\.[[:digit:]]\.[[:digit:]]).*" initFile);
              in "${initVersion}-${inputs.self.shortRev or "dirty"}";

              pyproject = true;
              src = ./.;

              propagatedBuildInputs = [
                paho-mqtt
                prometheus-client
                psutil
                setuptools
              ];

              meta = with lib; {
                description = "Cardano BlockPerf";
                homepage = "https://github.com/cardano-foundation/blockperf";
                license = licenses.mit;
              };
            };
          };
      };
}
