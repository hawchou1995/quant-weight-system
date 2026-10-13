"""Prevent delayed intraday jobs from rolling newer closing data backwards."""
import argparse
from pathlib import Path
import re
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
LIVE = "https://hawchou1995.github.io/quant-weight-system/"
FILES = ("enhanced_data.js", "short_pool.js", "a5_pool.js")
ASOF = re.compile(rb'"as_of"\s*:\s*"(\d{4}-\d{2}-\d{2})"')


def data_day(body):
    match = ASOF.search(body)
    return match.group(1).decode("ascii") if match else None


def live_file(name):
    request = urllib.request.Request(LIVE + name + "?cb=" + str(int(time.time())),
                                    headers={"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def stage(root, output, fetch=live_file):
    output.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in FILES:
        body = (root / name).read_bytes()
        local = data_day(body)
        remote = data_day(fetch(name))  # read failure aborts publication (fail-retain)
        if not local or not remote:
            raise ValueError(f"Cannot establish data dates for {name}; retain deployed files")
        if local < remote:
            print(f"[rt-guard] retain {name}: live={remote} newer than local={local}", flush=True)
            continue
        (output / name).write_bytes(body)
        copied.append(name)
        print(f"[rt-guard] stage {name}: {local} >= {remote}", flush=True)
    return copied


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="staging")
    args = parser.parse_args()
    stage(ROOT, ROOT / args.out)


if __name__ == "__main__":
    main()
