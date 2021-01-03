{ pkgs ? import <nixpkgs> { } }:

with pkgs;
with python38Packages;

let
  filterSrcByPrefix = src: prefixList:
    lib.cleanSourceWith {
      filter = (path: type:
        let relPath = lib.removePrefix (toString ./. + "/") (toString path);
        in lib.any (prefix: lib.hasPrefix prefix relPath) prefixList);
      inherit src;
    };
in buildPythonPackage {
  pname = "mydra";
  format = "pyproject";

  version = if lib.pathIsDirectory ./.git then
    builtins.substring 0 8 (lib.commitIdFromGitRepo ./.git)
  else
    "";

  # derivation depends only on pyproject.toml + src/ directory
  src = filterSrcByPrefix ./. [ "pyproject.toml" "src" ];

  doCheck = false;
  nativeBuildInputs = [ flit ];
  propagatedBuildInputs = [
    appdirs
    pexpect
    pythonix
    strictyaml
    tabulate
    termcolor
  ];
}
