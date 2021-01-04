from __future__ import annotations

# Based heavily on https://github.com/timokau/nix-bisect/blob/master/nix_bisect/nix.py
import fcntl
import itertools
import json
import os
import re
import signal
import struct
import sys
import termios
from datetime import datetime
from distutils.spawn import find_executable
from pathlib import Path
from subprocess import PIPE, CalledProcessError, run
from typing import Dict, List, Optional, Tuple

import nix
import pexpect
from appdirs import AppDirs

Storepath = str
Attribute = str
Drvpath = str


def log(drv: Drvpath, out="return") -> Optional[str]:
    """Returns the build log of a store path."""
    if out == "stdout":
        result = run(["nix", "log", "-f.", drv], text=True)
    else:
        result = run(["nix", "log", "-f.", drv], stdout=PIPE, stderr=PIPE, text=True)
    if result.returncode != 0:
        return None
    return result.stdout


def build_dry(
    drvs: List[Drvpath],
) -> Tuple[List[Drvpath], List[Drvpath]]:
    """Returns a list of drvs to be built and fetched in order to
    realize `drvs`"""
    result = run(
        ["nix-store", "--realize", "--dry-run"] + drvs,
        stdout=PIPE,
        stderr=PIPE,
        text=True,
        check=True,
    )
    lines = result.stderr.splitlines()
    to_fetch = []
    to_build = []
    for line in lines:
        line = line.strip()
        if "these paths will be fetched" in line:
            cur = to_fetch
        elif "these derivations will be built" in line:
            cur = to_build
        elif line.startswith("/nix/store"):
            cur += [line]
        elif line != "":
            raise RuntimeError(f"dry-run parsing failed: {line}")

    return (to_build, to_fetch)


def instantiate(packages: List[Attribute], nixpkgs: str) -> Dict[Drvpath, Attribute]:

    # 1. Attempt to evaluate each package attribute, and if it's
    # not broken or disabled get the drvpath for it.
    kv = nix.eval(
        """
let pkgs = import nixpkgsPath { };
  getPkg = n: (pkgs.lib.getAttrFromPath (pkgs.lib.splitString "." n) pkgs);
  getDrvPath = pkg:
    let maybe = builtins.tryEval pkg.drvPath;
    in if maybe.success then maybe.value else null;
in pkgs.lib.genAttrs maybePackages (n: getDrvPath (getPkg n))
    """,
        vars=dict(nixpkgsPath=nixpkgs, maybePackages=packages),
    )
    answer = {drvpath: attrib for attrib, drvpath in kv.items() if drvpath is not None}

    # 2. Instantiate all of the non-broken drvpaths in the nix store.
    expr2 = "with import %(nixpkgs)s { }; [%(attribs)s]" % dict(
        nixpkgs=nixpkgs, attribs=" ".join(answer.values())
    )
    cmd2 = [find_executable("nix-instantiate"), "-E", expr2]
    run(cmd2, stdout=PIPE, stderr=PIPE, check=True, shell=False)

    return answer


def build(
    drvs: Dict[Drvpath, Attribute],
    use_cache: bool = True,
    write_cache: bool = True,
    deadline: datetime = None,
) -> Tuple[Dict[Drvpath, Storepath], Dict[Drvpath, str]]:
    """Builds `drvs`, returning a list of store paths"""

    # Expand drvs with dependencies that need to be built so
    # that if they fail we can cache their failures too
    for drv in build_dry(list(drvs))[0]:
        if drv not in drvs:
            drvs[drv] = ""

    cache_dir = Path(AppDirs("mydra").user_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = Path(AppDirs("mydra-logs").user_cache_dir)
    logs_dir.mkdir(exist_ok=True)

    cache_file = cache_dir.joinpath("mydra-failures.json")
    if (use_cache or write_cache) and cache_file.exists():
        with open(cache_file, "r") as cf:
            result_cache = json.loads(cf.read())
    else:
        result_cache = dict()

    # Filter drvs down to the ones that aren't in the cache.
    drvs_to_build = dict(drvs)
    failures = {}
    if use_cache:
        for drv in drvs:
            # innocent till proven guilty
            if drv in result_cache:
                del drvs_to_build[drv]
                failures[drv] = result_cache[drv]

    success_storepaths, new_failures = _build_uncached(
        list(drvs_to_build), deadline=deadline
    )
    failures.update(new_failures)

    if write_cache:
        for drv, reason in failures.items():
            if reason not in ("MYDRA TIMEOUT",):
                result_cache[drv] = reason

        # Save all available build logs
        for drv in itertools.chain(success_storepaths, failures):
            build_log_path = logs_dir.joinpath(Path(drv).name)
            if not build_log_path.exists():
                build_log = log(drv)
                if build_log is not None:
                    with open(build_log_path, "w") as f:
                        f.write(build_log)
        
        with open(cache_file, "w") as cf:
            # Write human-readable json for easy hacking.
            cf.write(json.dumps(result_cache, indent=4))

    return success_storepaths, failures


def _build_uncached(
    drvs: List[Drvpath],
    deadline: datetime = None,
) -> Tuple[Dict[Drvpath, Storepath], Dict[Drvpath, str]]:
    if len(drvs) == 0:
        # nothing to do
        return {}, {}

    # Parse the error output of `nix build`
    _CANNOT_BUILD_PAT = re.compile(b"cannot build derivation '([^']+)': (.+)")
    _BUILD_FAILED_PAT = re.compile(b"build of ('[^']+'(, '[^']+')*) failed")
    _BUILDER_FAILED_PAT = re.compile(
        b"builder for '([^']+)' failed with exit code (\\d+);"
    )
    _BUILD_TIMEOUT_PAT = re.compile(b"building of '([^']+)' timed out after.*")

    # print(f"nix build {' '.join(drvs)}")
    # We need to use pexpect instead of subprocess.Popen here, since `nix
    # build` will not produce its regular output when it does not detect a tty.
    cmd = ["build", "--no-link", "--keep-going"]
    if not sys.stdout.isatty():
        cmd += ["--print-build-logs"]

    # print(f"Building {drvs}")
    # sys.stdout.flush()

    build_process = pexpect.spawn(
        "nix",
        cmd + drvs,
        logfile=sys.stdout.buffer,
    )

    # adapted from the pexpect docs
    def _update_build_winsize():
        s = struct.pack("HHHH", 0, 0, 0, 0)
        a = struct.unpack(
            "hhhh", fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, s)
        )
        if not build_process.closed:
            build_process.setwinsize(a[0], a[1])

    if sys.stdout.isatty():
        _update_build_winsize()
        signal.signal(signal.SIGWINCH, lambda _sig, _data: _update_build_winsize())

    TIMED_OUT = False

    drvs_failed = {}
    try:
        while True:
            # This will fill the "match" instance attribute. Raises on EOF. We
            # can only reliably use this for the final error output, not for
            # the streamed output of the actual build (since `nix build` skips
            # lines and trims output). Use `nix.log` for that.
            try:
                build_process.expect(
                    [
                        _CANNOT_BUILD_PAT,
                        _BUILD_FAILED_PAT,
                        _BUILD_TIMEOUT_PAT,
                        _BUILDER_FAILED_PAT,
                    ],
                    timeout=(deadline - datetime.now()).total_seconds()
                    if deadline is not None
                    else None,
                )
            except pexpect.exceptions.TIMEOUT:
                print("Timeout", file=sys.stderr)
                TIMED_OUT = True
                break

            line = build_process.match.group(0)
            # Re-match to find out which pattern matched. This doesn't happen very
            # often, so the wasted effort isn't too bad.
            # Can't wait for https://www.python.org/dev/peps/pep-0572/

            match = _CANNOT_BUILD_PAT.match(line)
            if match is not None:
                drv = match.group(1).decode()
                _reason = match.group(2).decode()
                drvs_failed[drv] = "DEP FAILED"

            match = _BUILD_FAILED_PAT.match(line)
            if match is not None:
                drv_list = match.group(1).decode()
                for drv in (drv.strip("'") for drv in drv_list.split(", ")):
                    if drv not in drvs_failed:
                        drvs_failed[drv] = "DEP FAILED"

            match = _BUILD_TIMEOUT_PAT.match(line)
            if match is not None:
                drv = match.group(1).decode()
                if drv not in drvs_failed:
                    drvs_failed[drv] = "BUILD TIMEOUT"

            match = _BUILDER_FAILED_PAT.match(line)
            if match is not None:
                drv = match.group(1).decode()
                _exit_code = match.group(2).decode()
                if drv not in drvs_failed:
                    drvs_failed[drv] = "BUILDER FAILED"

    except pexpect.exceptions.EOF:
        pass

    drvs_succeeded = list(set(drvs) - set(drvs_failed))

    if TIMED_OUT:
        build_process.kill(9)
        dry = build_dry(drvs_succeeded)
        for drv in dry[0] + dry[1]:
            drvs_failed[drv] = "MYDRA TIMEOUT"
            drvs_succeeded.remove(drv)

    drvs_succeeded_names = {
        os.path.splitext(e)[0].split("-", 1)[1] for e in drvs_succeeded
    }

    location_process = run(
        ["nix-store", "--realize"] + drvs_succeeded,
        stdout=PIPE,
        stderr=PIPE,
        text=True,
        check=True,
    )
    storepaths = [
        e
        for e in location_process.stdout.splitlines()
        if e and e.split("-", 1)[1] in drvs_succeeded_names
    ]
    assert len(storepaths) == len(drvs_succeeded)
    return {d: sp for d, sp in zip(drvs_succeeded, storepaths)}, drvs_failed
