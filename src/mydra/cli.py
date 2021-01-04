import argparse
import itertools
import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import git
import pandas as pd
import pytimeparse
import strictyaml
from appdirs import AppDirs
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
    p.add_argument("-t", "--timeout", type=pytimeparse.parse, default=None)
    p.add_argument("yml")
    # p.add_argument("-o", "--report", default=None)

    args = p.parse_args()
    deadline = (
        (datetime.now() + timedelta(seconds=args.timeout))
        if args.timeout is not None
        else None
    )

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


def execute(
    nixpkgs: Path,
    yml: Path,
    # report: Optional[str],
    deadline: Optional[datetime],
):
    try:
        commit = git.Repo(nixpkgs).commit()
        nixpkgs_hash = str(commit)
        nixpkgs_date = datetime.fromtimestamp(commit.committed_date).isoformat()
    except git.exc.InvalidGitRepositoryError:
        raise ValueError(f"Could not determine git hash from nixpkgs={nixpkgs}. Please use a git clone!")

    packages = list(expand_package_attrnames(yml))
    drv2attr = instantiate(packages, nixpkgs)
    successes, failures = build(drv2attr, deadline=deadline)

    rows = []
    for drvpath, storepath in successes.items():
        attr = drv2attr[drvpath]
        rows.append(
            {
                "icon": colored("✓", "green"),
                "attr": attr,
                "status": "SUCCESS",
                "drvpath": drvpath,
            }
        )
    for drvpath, reason in failures.items():
        attr = drv2attr.get(drvpath, "")
        color = "white" if reason == "CANNOT BUILD" else "red"
        rows.append(
            {
                "icon": colored("✗", color),
                "attr": attr,
                "status": reason,
                "drvpath": drvpath,
            }
        )

    df = pd.DataFrame(rows)
    print(tabulate(df[["icon", "attr", "status"]].to_records(index=False)))

    cache_dir = Path(AppDirs("mydra").user_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    outjson = {
        "nixpkgs": {"commit": nixpkgs_hash, "committed_date": nixpkgs_date},
        "build_results": rows,
    }
    with open(cache_dir.joinpath(f"build-{nixpkgs_hash}.json"), "w") as f:
        json.dump(outjson, f, indent=4)
