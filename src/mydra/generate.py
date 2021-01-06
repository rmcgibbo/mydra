import glob
import json
import os
import argparse
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime
from subprocess import run

import appdirs
import pandas as pd
import pytz


LOG_URL = "http://mydra-logs.rmcgibbo.org/"


def process_file(fn: str):
    with open(fn) as foo:
        data = json.load(foo)

    def fmt_status_link(row):
        status = row["status"]
        link = LOG_URL + os.path.basename(row["drvpath"])
        if status == "DEP FAILED":
            return "DEP FAILED"
        md_link = f"[{status}]({link})"
        return md_link

    df = pd.DataFrame(data["build_results"])
    df["name"] = df["drvpath"].apply(lambda x: os.path.basename(x)[33:][:-4])
    df["status_link"] = df.apply(axis=1, func=fmt_status_link)
    date = datetime.fromisoformat(data["nixpkgs"]["committed_date"])
    date_fmt = date.astimezone(pytz.timezone("US/Eastern")).strftime(
        "%b %-d %-I:%M %p %Z"
    )

    failed_attrs = sorted((a for a in df.query("status in ('BUILDER FAILED', 'DEP FAILED')").attr if a))

    with open(f"content/post/build-{data['nixpkgs']['commit']}.md", "w") as f:
        f.write(
            f"""---
title: "nixpkgs {data['nixpkgs']['commit'][:8]}"
date: "{date.isoformat()}"
draft: false
---"""
        )
        print(
            f"""nixpkgs: [{data['nixpkgs']['commit'][:8]}](https://github.com/NixOS/nixpkgs/commit/{data['nixpkgs']['commit']}); {date_fmt}""",
            file=f,
            end="  \n",
        )
        print(
            f"failure(s): {', '.join(failed_attrs)}",
            file=f,
            end="  \n",
        )
        print("<!--more-->\n\n", file=f)
        if "log_url" in data:
            print(f"[githib actions log]({data['log_url']})", file=f, end="  \n")
        if "yaml_url" in data:
            print(f"[mydra cfg]({data['yaml_url']})", file=f, end="  \n")

        print('{{< table "table table-striped table-bordered" >}}', file=f)
        f.write(df[["attr", "name", "status_link"]].to_markdown(index=False))
        print("{{< /table >}}", file=f)


@contextmanager
def chdir(dir):
    cwd = os.path.abspath(os.getcwd())
    os.chdir(dir)
    yield
    os.chdir(cwd)


def execute():
    td = tempfile.mkdtemp(prefix="mydra-hugo-")

    run(
        f"cp -r {os.path.join(os.path.dirname(__file__), 'hugosite')}/. {td}",
        check=True,
        shell=True,
    )
    run(f"find {td}/ -type d -exec chmod +rwx {{}} \;", check=True, shell=True)

    with chdir(td):
        os.makedirs("content/post", exist_ok=True)
        cache_dir = appdirs.AppDirs("mydra").user_cache_dir
        for fn in glob.glob(cache_dir + "/build-*.json"):
            process_file(fn)
        run(["hugo"], check=True)

    shutil.rmtree("public", ignore_errors=True)
    shutil.copytree(td + "/public", "public")
    shutil.rmtree(td, ignore_errors=False)


def main():
    p = argparse.ArgumentParser()
    return execute()
