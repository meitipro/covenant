#!/usr/bin/env bash
#
# deploy.sh - the optional CLI route. DEPLOY.md's Studio walkthrough is the
# primary route and needs nothing but a browser.
#
#   bash scripts/deploy.sh <network> <lender-account> <borrower-account> <borrower-address>
#   bash scripts/deploy.sh studionet lender borrower 0xYourBorrowerAddress
#
# Covenant needs two signers: the lender opens, waives and closes, and only the
# borrower may report. The GenLayer CLI keeps named accounts in its own
# keystore (`genlayer account create --name lender`), and
# `genlayer account use <name>` switches the signer. No key passes through this
# script or any file in this repository.
#
# READ EVERY RECEIPT. `genlayer write` exits 0 for a transaction that rolled
# back, timed out or ended undetermined, so `set -e` does not stop on a failed
# judgment. After each checkpoint below the script pauses: compare the view it
# printed with the value DEPLOY.md expects, and stop if they differ.
#
# Requires: npm i -g genlayer, and genvm-lint (pip install genvm-linter).

set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

NETWORK="${1:?network, for example studionet}"
LENDER="${2:?the CLI account name that signs as the lender}"
BORROWER="${3:?the CLI account name that signs as the borrower}"
BORROWER_ADDR="${4:?the borrower account's address}"

step()  { printf '\n\033[33m%s\033[0m\n' "$*"; }
pause() { read -r -p "  Expected: $*. Enter to continue, Ctrl-C to stop. " _; }

# `network` is a command group, not a value: `genlayer network studionet`
# answers "unknown command" and exits 1.
genlayer network set "$NETWORK"

step "lint"
# utf-8 stdout, or the linter dies printing its own tick on Windows and reports
# a passing contract as failed.
PYTHONIOENCODING=utf-8 genvm-lint lint contracts/covenant.py

step "deploy, from the lender"
genlayer account use "$LENDER"
OUT=$(genlayer deploy --contract contracts/covenant.py)
printf '%s\n' "$OUT"
# The deploy output also carries the transaction hash, 64 hex characters, and a
# bare 0x[0-9a-fA-F]{40} matches its first 40. Take the address from a line
# that names an address, as a whole 40 character word, or stop.
ADDR=$(printf '%s\n' "$OUT" | grep -i 'address' | grep -oE '\b0x[0-9a-fA-F]{40}\b' | head -1 || true)
if [ -z "$ADDR" ]; then
  echo "could not read a contract address from the deploy output; stopping" >&2
  exit 1
fi
step "deployed at $ADDR"

CONDITIONS="a cash balance of at least 2 million EUR at quarter end|audited annual accounts delivered within 90 days of year end|the vessel fleet insured against total loss"
TAIL=" Audited annual accounts for the last financial year were delivered within 90 days of year end. The vessel fleet is insured against total loss."

# --args is variadic. A JSON array is ONE argument, not the argument list, so
# every value below is a separate token. The CLI may encode a 40 hex character
# token as an address rather than a string; the contract reads the borrower
# through str() either way, so both arrive as the same address.
step "1      open, from the lender: three conditions, a cure window of one report"
genlayer write "$ADDR" open --args "Harbour Logistics term loan" "$CONDITIONS" 1 "$BORROWER_ADDR"

report_and_judge() {
  local k="$1" cash="$2" rid="$3"
  step "report $k, from the borrower: $cash million EUR"
  genlayer account use "$BORROWER"
  genlayer write "$ADDR" report --args 0 "Compliance report $k: the cash balance at quarter end was $cash million EUR.$TAIL"
  genlayer write "$ADDR" judge --args 0
  genlayer call "$ADDR" get_report --args "$rid"
}

report_and_judge 1 2.4 0
pause "transitions kept|kept|kept"
report_and_judge 2 1.7 1
pause "transitions broken|kept|kept, condition 0 in breach with remaining 1"
report_and_judge 3 2.2 2
report_and_judge 4 1.6 3
report_and_judge 5 1.5 4
genlayer call "$ADDR" facility --args 0
pause "unremedied|kept|kept, facility 0 defaulted, defaulted_condition 0, defaulted_report 4"

# Nothing more is sent to facility 0. It is in default and refuses every
# write, the tests cover those refusals, and a failed transaction on the
# explorer page costs more than it shows.

step "12     open, from the lender: one condition, a cure window of two reports"
genlayer account use "$LENDER"
genlayer write "$ADDR" open --args "Harbour Logistics revolving credit" "a cash balance of at least 1 million EUR at quarter end" 2 "$BORROWER_ADDR"

step "13-14  report and judge on facility 1"
genlayer account use "$BORROWER"
genlayer write "$ADDR" report --args 1 "Compliance report 1: the cash balance at quarter end was 0.8 million EUR."
genlayer write "$ADDR" judge --args 1
genlayer call "$ADDR" conditions_of --args 1

step "15     waive, from the lender"
genlayer account use "$LENDER"
genlayer write "$ADDR" waive --args 1 0
genlayer call "$ADDR" conditions_of --args 1

cat <<TXT

  Contract:  $ADDR
  Explorer:  https://explorer-studio.genlayer.com/address/$ADDR

Before submitting, prove the address is evidence for THIS repository:

  python scripts/verify_deployment.py $ADDR

It reads the source back off chain, compares it with contracts/covenant.py, and
lints those bytes. A correct repository proves nothing on its own if the
address points at an earlier draft.

Then read every value in DEPLOY.md's reads table back from the chain, replace
the expected values in SUBMISSION.md with them, and paste the address into
README.md and SUBMISSION.md where {address} appears.

TXT
