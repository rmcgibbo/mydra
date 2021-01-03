import argparse
import itertools
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pytimeparse
import strictyaml
from tabulate import tabulate
from termcolor import colored

from .mydra import build, instantiate, log


def main():
    p = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument(
        "-f",
        "--nixpkgs",
        help="Path to nixpkgs git checkout",
        required=True,
        type=os.path.abspath,
    )
    p.add_argument("-t", "--timeout", type=pytimeparse.parse, default=float("inf"))
    p.add_argument("yml")

    args = p.parse_args()
    deadline = datetime.now() + timedelta(seconds=args.timeout)

    return execute(nixpkgs=args.nixpkgs, yml=args.yml, deadline=deadline)


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


def execute(nixpkgs: Path, yml: Path, deadline: datetime):
    with github_ci_group("Build logs"):
        packages = list(expand_package_attrnames(yml))
        drv2attr = instantiate(packages, nixpkgs)
        successes, failures = build(drv2attr, deadline=deadline)

    rows = []
    for drvpath, storepath in successes.items():
        attr = drv2attr[drvpath]
        rows.append((colored("✓", "green"), attr, "SUCCESS",))
    for drvpath, reason in failures.items():
        attr = drv2attr.get(drvpath, "")
        color = "white" if reason == "CANNOT BUILD" else "red"
        rows.append((colored("✗", color), attr, reason))
    
    print()
    print(tabulate(rows))

    with github_ci_group("Failure logs"):
        for drvpath in failures:
            print(colored(f"$ nix log -f. {drvpath}", "red"))
            log(drvpath, "stdout")


@contextmanager
def github_ci_group(s: str):
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::group::{s}")
        yield
        print("::endgroup::")
    else:
        yield
