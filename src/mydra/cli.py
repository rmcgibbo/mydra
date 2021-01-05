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
    p.add_argument("yaml")
    p.add_argument(
        "-f",
        "--nixpkgs",
        help="Path to nixpkgs git checkout",
        required=True,
        type=os.path.abspath,
    )
    p.add_argument("-t", "--timeout", type=pytimeparse.parse, default=None)
    p.add_argument("--log-url")
    p.add_argument("--yaml-url")

    args = p.parse_args()
    deadline = (
        (datetime.now() + timedelta(seconds=args.timeout))
        if args.timeout is not None
        else None
    )

    return execute(
        nixpkgs=args.nixpkgs,
        yaml=args.yaml,
        deadline=deadline,
        log_url=args.log_url,
        yaml_url=args.yaml_url,
    )


def expand_package_attrnames(yaml: str):
    with open(yaml) as f:
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
    yaml: Path,
    deadline: Optional[datetime],
    log_url: Optional[str],
    yaml_url: Optional[str],
):
    try:
        commit = git.Repo(nixpkgs).commit()
        nixpkgs_hash = str(commit)
        nixpkgs_date = (
            datetime.fromtimestamp(commit.committed_date).astimezone().isoformat()
        )
    except git.exc.InvalidGitRepositoryError:
        raise ValueError(
            f"Could not determine git hash from nixpkgs={nixpkgs}. Please use a git clone!"
        )

    packages = list(expand_package_attrnames(yaml))
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
        "log_url": log_url,
        "yaml_url": yaml_url,
        "build_results": rows,
    }
    with open(cache_dir.joinpath(f"build-{nixpkgs_hash}.json"), "w") as f:
        json.dump(outjson, f, indent=4)
