"""Prove the deployed contract is the contract in this repository.

    python scripts/verify_deployment.py 0xYourAddress

A submission is judged on the DEPLOYED source. The reviewer reads it back off
chain, diffs it against the repository, and runs the linter on those bytes, so
a repository that is correct proves nothing on its own if the address points at
an earlier draft. Two GenLayer submissions have been rejected for exactly that,
with the fix already sitting in the repository, unreachable.

This script does the same three things the reviewer does:

    1. reads the contract source back off chain
    2. compares it with contracts/covenant.py
    3. runs `genvm-lint lint` on the bytes that came off the chain

The comparison is identical up to line endings and the trailing newline, and no
further. Pasting a file into a web editor rewrites LF to CRLF and usually drops
the final newline; neither changes a byte of what runs, so both are normalised
before comparing, and a difference of that kind is reported separately, as
cosmetic. Anything that survives the normalisation is a material difference and
fails the check, with the first lines of the diff printed.

It exits non-zero if the source differs materially, if the lint fails, or if
genvm-lint is not installed (pip install genvm-linter): a gate that cannot run
its check fails closed.
"""

import argparse
import base64
import difflib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "contracts" / "covenant.py"
RPC = "https://studio.genlayer.com/api"


def rpc(method, params, rpc_url):
    """One JSON-RPC call. Returns (result, error); never raises on an RPC error."""
    req = urllib.request.Request(
        rpc_url,
        data=json.dumps({"jsonrpc": "2.0", "method": method,
                         "params": params, "id": 1}).encode(),
        # Without a User-Agent the Studio endpoint answers 403, which reads
        # like a bad address rather than a missing header.
        headers={"Content-Type": "application/json",
                 "User-Agent": "covenant-verify/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            out = json.loads(r.read())
    except Exception as e:                       # noqa: BLE001
        return None, str(e)
    if isinstance(out, dict) and "error" in out:
        return None, str(out["error"])
    return (out.get("result") if isinstance(out, dict) else out), None


def as_source(raw):
    """A contract source from what an endpoint returned, or None."""
    if not isinstance(raw, str) or not raw:
        return None
    if raw.lstrip().startswith("#"):
        return raw
    try:
        text = base64.b64decode(raw).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    return text if text.lstrip().startswith("#") else None


def deployed_source(address, rpc_url):
    """The source that was actually deployed, and where it was read from.

    Asks the node for the contract's code first, then falls back to the deploy
    transaction. Addresses are case sensitive to this endpoint: a lower cased
    address comes back as "contract not found". Pass the checksummed form the
    explorer shows.
    """
    code, err = rpc("gen_getContractCode", [address], rpc_url)
    text = as_source(code)
    if text is not None:
        return text, "gen_getContractCode"
    txs, err2 = rpc("sim_getTransactionsForAddress", [address], rpc_url)
    if isinstance(txs, list):
        for tx in txs:
            data = tx.get("data") if isinstance(tx, dict) else None
            text = as_source((data or {}).get("contract_code") if isinstance(data, dict) else None)
            if text is not None:
                return text, "deploy tx " + str(tx.get("hash", ""))
    raise SystemExit(
        f"could not read a contract source for {address} ({err or ''} {err2 or ''}). "
        "Check the address casing: it is not normalised here."
    )


def lint(text):
    """Run the linter on the bytes that came off the chain, not on the repo file.

    `check` also runs validate, which cannot see a class named Contract and so
    reports a working contract as broken. `lint` is the half that matters here
    and it has no such blind spot.
    """
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "deployed.py"
        p.write_text(text, encoding="utf-8", newline="")
        try:
            proc = subprocess.run(
                ["genvm-lint", "lint", str(p)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                # The linter prints a tick and dies encoding it under the cp1252
                # stdout Windows hands a child process, reporting a PASSING
                # contract as failed.
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        except FileNotFoundError:
            print("genvm-lint is not installed: pip install genvm-linter")
            raise SystemExit(2)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def canonical(text):
    return text.replace("\r\n", "\n").rstrip("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("address", help="the deployed contract address, checksummed")
    ap.add_argument("--rpc", default=RPC)
    args = ap.parse_args()

    local = SOURCE.read_bytes().decode("utf-8")
    remote, where = deployed_source(args.address, args.rpc)

    print(f"  address      {args.address}")
    print(f"  read from    {where}")
    print(f"  repo file    {SOURCE.relative_to(ROOT).as_posix()}  ({len(local)} chars)")
    print(f"  on chain     {len(remote)} chars")

    same = canonical(local) == canonical(remote)
    cosmetic = same and local != remote
    print(f"  identical    {'yes' if same else 'NO'}")
    if cosmetic:
        print("               cosmetic only: line endings or the trailing newline "
              "differ, which nothing runs")

    ok_lint, out = lint(remote)
    print(f"  lint         {'passed' if ok_lint else 'FAILED'}")
    if not ok_lint:
        for line in out.splitlines():
            print(f"               {line}")

    if not same:
        print("\n  The deployed source is not this file. First differences:\n")
        diff = difflib.unified_diff(
            canonical(remote).splitlines(),
            canonical(local).splitlines(),
            fromfile="deployed", tofile="repository", lineterm="", n=1,
        )
        for i, line in enumerate(diff):
            if i > 40:
                print("               ... truncated")
                break
            print(f"               {line}")

    if same and ok_lint:
        print("\n  The address is evidence for this repository. Safe to submit.")
        return 0
    print("\n  Do NOT submit this address. Redeploy from the current file.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
