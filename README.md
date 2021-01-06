# mydra

"Personal hydra"

This is a front-end for `nix build` for the purposes of testing the compilation of a set
of packages against a local checkout of nixpkgs. It implements negative caching (which
`nix build` doesn't have anymore) so that failed builds are remembered and not re-attempted
from invocation of mydra to the next.

CLI usage
=========

```
$ nix run -f . -c mydra
usage: mydra [-h] -f NIXPKGS [-t TIMEOUT] [--log-url LOG_URL] [--yaml-url YAML_URL] yaml

positional arguments:
  yaml

optional arguments:
  -h, --help            show this help message and exit
  -f NIXPKGS, --nixpkgs NIXPKGS
                        Path to nixpkgs git checkout (default: None)
  -t TIMEOUT, --timeout TIMEOUT
```

Give it a config file (YAML, sorry), a path to a nixpkgs checkput, optionally a timeout, like "60m"
for the total build time. For an example YAML file, look in the repo.


CI/CD + website usage
=====================

This repo has github actions set to run the tool every 6 hours, using the latest nixpkgs-master.
See the file `.github/workflow/mydra.yml` for the definition of the github actions workflow. It
uses Cachix (thanks! Cachix is great!) to cache build derivations and AWS S3 to store the build
logs and the information about which builds failed that normally are cached in your home
directory when you invoke `mydra` from the command line. Then, it builds a really hacky static
website that it uploads to github pages.

If you'd like to fork this and deploy it yourself, you'll need to change a few things:
1. AWS_BUCKET_CACHE and AWS_BUCKET_LOGS in the workflow file will need to point to buckets
   you control, rather than to mine. Or you could store the information some other way.
2. baseURL in `src/mydra/hugosite/config.toml` and some other metadata there will need to be
   updated to point to resources you control.
3. You'll need to set your own values for the AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and
   CACHIX_AUTH_TOKEN secrets.