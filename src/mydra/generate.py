import os
import subprocess
import appdirs
import glob
import json
import shutil
import pandas as pd
import tempfile
from contextlib import contextmanager


def process_file(fn: str):
    with open(fn) as foo:
        data = json.load(foo)    
 
    df = pd.DataFrame(data["build_results"])    
    df["link"] = df["drvpath"].apply(lambda x: "https://raw.githubusercontent.com/rmcgibbo/mydra/gh-pages/logs/" + os.path.basename(x))

    df["name"] = df["drvpath"].apply(lambda x: os.path.basename(x)[33:][:-4])
    df["status_link"] = df.apply(axis=1, func=lambda row: f"[{row['status']}]({row['link']})")


    with open(f"content/post/build-{data['nixpkgs']['commit']}.md", "w") as f:
        f.write(f"""---
title: "{data['nixpkgs']['commit']}"
date: "{data['nixpkgs']['committed_date']}"
draft: false
---""")
        print("Front matter\n\nsdfsdsf \n\nsdf sdfdsf\n\n", file=f)
        print("<!--more-->", file=f)

        print('{{< table "table table-striped table-bordered" >}}', file=f)
        f.write(df[["attr", "name", "status_link"]].to_markdown(index=False))
        print('{{< /table >}}', file=f)


def copytree(src, dst, symlinks=False, ignore=None):
    # https://stackoverflow.com/a/12514470
    for item in os.listdir(src):
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            shutil.copytree(s, d, symlinks, ignore, copy_function=shutil.copy)
        else:
            shutil.copy(s, d)

@contextmanager
def chdir(dir):
    cwd = os.path.abspath(os.getcwd())
    os.chdir(dir)
    yield
    os.chdir(cwd)

def main():
    td = tempfile.mkdtemp()
    copytree(os.path.join(os.path.dirname(__file__), "hugosite"), td)
    
    with chdir(td):
        print(td)
        os.makedirs("content/post", exist_ok=True)
        cache_dir = appdirs.AppDirs("mydra").user_cache_dir
        for fn in glob.glob(cache_dir + "/build-*.json"):
            process_file(fn)
        subprocess.run(["hugo"])
    
    shutil.rmtree("public", ignore_errors=True)
    copytree(td + "/public", "public")
    print(td)
    shutil.rmtree(td, ignore_errors=False)
