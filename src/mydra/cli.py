import argparse
import itertools

import strictyaml
from termcolor import colored
from tabulate import tabulate

from .mydra import build, instantiate


def main():
    p = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument(
        "-f",
        "--nixpkgs",
        help="Path to nixpkgs git checkout",
        required=True,
        type=os.path.abspath,
    )
    p.add_argument("yml")
    args = p.parse_args()
    
    return execute(nixpkgs=args.nixpkgs, yml=args.yml)


def expand_package_attrnames(yml: str):
    with open(yml) as f:
        cfg = strictyaml.load(f.read()).data
    if cfg["mydraApi"] != "0":
        raise NotImplementedError(f"Unsupported mydraApi = {cfg['mydraApi']}")
    
    for pyVer, name in itertools.product(
        cfg["pythonVersions"], cfg["pythonPackageNames"]
    ):
        yield f"python{pyVer}Packages.{name}"
    for item in cfg["nativePackages"]:
        yield item


def execute(nixpkgs: str, yml: str):
    packages = list(expand_package_attrnames(yml))
    drv2attr = instantiate(packages, nixpkgs)
    successes, failures = build(drv2attr)

    rows = []
    for drvpath, storepath in successes.items():
        attr = drv2attr[drvpath]
        rows.append((colored("✓", "green"), attr, "SUCCESS", storepath))
    for drvpath, reason in failures.items():
        attr = drv2attr.get(drvpath, "")
        color = "white" if reason == "CANNOT BUILD" else "red"
        rows.append((colored("✗", color), attr, reason, drvpath))

    print()
    print(tabulate(rows))
