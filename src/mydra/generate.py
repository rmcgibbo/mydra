import glob
import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from subprocess import run

import appdirs
import pandas as pd


def process_file(fn: str):
    with open(fn) as foo:
        data = json.load(foo)    
 
    df = pd.DataFrame(data["build_results"])    
    df["link"] = df["drvpath"].apply(lambda x: "https://raw.githubusercontent.com/rmcgibbo/mydra/gh-pages/logs/" + os.path.basename(x))

    df["name"] = df["drvpath"].apply(lambda x: os.path.basename(x)[33:][:-4])
    df["status_link"] = df.apply(axis=1, func=lambda row: f"[{row['status']}]({row['link']})")


    with open(f"content/post/build-{data['nixpkgs']['commit']}.md", "w") as f:
        f.write(f"""---
title: "nixpkgs {data['nixpkgs']['commit'][:8]}"
date: "{data['nixpkgs']['committed_date']}"
draft: false
---""")
        print(f"""nixpkgs: [{data['nixpkgs']['commit'][:8]}](https://github.com/NixOS/nixpkgs/commit/{data['nixpkgs']['commit']})  
date: {data['nixpkgs']['committed_date']}  
failure(s): {", ".join(df.query("status == 'BUILDER FAILED'").name)}  

<!--more-->
""", file=f)
        print("", file=f)

        print('{{< table "table table-striped table-bordered" >}}', file=f)
        f.write(df[["attr", "name", "status_link"]].to_markdown(index=False))
        print('{{< /table >}}', file=f)


@contextmanager
def chdir(dir):
    cwd = os.path.abspath(os.getcwd())
    os.chdir(dir)
    yield
    os.chdir(cwd)


def main():
    td = tempfile.mkdtemp(prefix="mydra-hugo-")

    run(f"cp -r {os.path.join(os.path.dirname(__file__), 'hugosite')}/. {td}", check=True, shell=True)
    run(f"find {td}/ -type d -exec chmod +rwx {{}} \;", check=True, shell=True)
    
    with chdir(td):
        print(td)
        os.makedirs("content/post", exist_ok=True)
        cache_dir = appdirs.AppDirs("mydra").user_cache_dir
        for fn in glob.glob(cache_dir + "/build-*.json"):
            process_file(fn)
        run(["hugo"], check=True)
    
    shutil.rmtree("public", ignore_errors=True)
    shutil.copytree(td + "/public", "public")
    shutil.rmtree(td, ignore_errors=False)
