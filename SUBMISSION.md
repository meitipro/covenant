# Submission

One submission, under **Builder -> Intelligent Contracts**. This repository is
one standalone primitive.

---

## Before you submit, in order

1. **Measure, do not estimate.**

   ```bash
   python scripts/measure.py --write
   ```

   Checks the house style, runs the suite, runs the full mutation pass, and
   writes the numbers into README.md. It refuses to write anything if the style
   check fails, the suite is red, or a mutation escapes, so a number in the
   README is always one that was checked.

2. **Deploy and exercise.** Through the Studio web interface at
   studio.genlayer.com, following [DEPLOY.md](DEPLOY.md) step by step, with the
   two accounts it asks for. Never put a private key into a file.

3. **Put the whole cycle on chain, not only a success.** The story the run
   tells is the submission: a report that keeps every covenant, one that
   breaks the cash covenant, one that cures it, one that breaks it again, and
   one that leaves it unremedied, so the window runs out and the facility is in
   default. Then a breach on a second facility, forgiven by a waiver. All four
   transitions execute in public, and the refusal the contract exists to make,
   a default nobody decided, is on the record.

4. **Prove the address is evidence for this repository.**

   ```bash
   python scripts/verify_deployment.py 0xYourAddress
   ```

   Reads the source back out of the deploy transaction on chain, compares it
   with `contracts/covenant.py` (identical up to line endings, which pasting
   into a web editor rewrites and nothing runs), and runs `genvm-lint lint` on
   those bytes. **A submission is judged on the deployed source**, so a correct
   repository proves nothing on its own if the address points at an earlier
   draft. Exits non-zero if either check fails, or if `genvm-lint` is missing.

5. **Open the explorer page and check it.** It must show a Deploy transaction
   **and** method calls with a Consensus Result beside them, and no failed or
   abandoned transaction.

6. **Paste the address** into README.md and into this file where `{address}`
   appears, then push.

7. **Upload `brand/social.png`** under Settings -> General -> Social preview.
   GitHub has no API for this.

---

## On chain

Deployed and exercised on studionet at
[`0x19911E7D44Ff51cca345DFac48723B3A6C89338D`](https://explorer-studio.genlayer.com/address/0x19911E7D44Ff51cca345DFac48723B3A6C89338D).
Sixteen transactions, every one `FINALIZED`, none failed. Every value below was
read back from the chain with view calls afterwards, not copied from a local
run, and it is exactly what `tests/test_runbook.py` asserts for the same run.

| # | Transaction | Result |
|---|---|---|
| 1 | deploy | finalized |
| 2 | `open("Harbour Logistics term loan", three conditions, 1, B)` (A) | facility 0 frozen: three conditions, a cure window of one report |
| 3-4 | `report` (B) + `judge(0)` | report 0: `kept\|kept\|kept` |
| 5-6 | `report` (B) + `judge(0)` | report 1: `broken\|kept\|kept`, condition 0 in `breach` with `remaining 1` |
| 7-8 | `report` (B) + `judge(0)` | report 2: **`cured\|kept\|kept`**, condition 0 `compliant`, `cures 1` |
| 9-10 | `report` (B) + `judge(0)` | report 3: `broken\|kept\|kept`, `breaches 2` |
| 11-12 | `report` (B) + `judge(0)` | report 4: **`unremedied\|kept\|kept`**, condition 0 `default`, facility 0 **`defaulted`**, `defaulted_condition 0`, `defaulted_report 4` |
| 13 | `open("Harbour Logistics revolving credit", one condition, 2, B)` (A) | facility 1 frozen: one condition, a cure window of two reports |
| 14-15 | `report` (B) + `judge(1)` | report 5: `broken`, `breach` with `remaining 2` |
| 16 | `waive(1, 0)` (A) | condition 0 of facility 1 `compliant`, `remaining 0`, **`waivers 1`** |

### Reproducing the check

```bash
python scripts/verify_deployment.py 0x19911E7D44Ff51cca345DFac48723B3A6C89338D
```

Reads the source out of the deploy transaction, compares it with
`contracts/covenant.py`, and runs `genvm-lint lint` on those bytes. It reports
the deployed source as identical up to line endings, which pasting into the
Studio editor rewrites and nothing runs.

---

## Title

```
Covenant: a breach is cured within the window or it becomes a default
```

## Notes (under 1000 characters, the box caps at 1000)

```
Covenant tracks the covenants of a loan or supply agreement report by report, and a breach is cured by a later report or it becomes a default, counted in reports, never in days. The lender freezes the conditions and a cure window of 0 to 3 reports at open, the borrower files compliance reports in prose, and the block reads one report against the numbered conditions, one token per condition, met, breached or unstated, asked twice, in the frozen order and reversed, with any disagreement folded to unstated. What crosses consensus is one transition per condition, kept, broken, cured or unremedied, derived from the state that condition is in, so met and unstated agree on a compliant condition and disagree on one in breach, and silence can neither open a breach nor cure one. Agreement is exact on the whole vector, reports are judged strictly in filing order, default is terminal, only the borrower reports and only the lender waives or closes.
```

## Links

```
GitHub:   https://github.com/meitipro/covenant
Contract: https://github.com/meitipro/covenant/blob/main/contracts/covenant.py
Spec:     https://github.com/meitipro/covenant/blob/main/CONTRACTS.md
Decisions https://github.com/meitipro/covenant/blob/main/DECISIONS.md
Tests:    https://github.com/meitipro/covenant/tree/main/tests
Explorer: https://explorer-studio.genlayer.com/address/0x19911E7D44Ff51cca345DFac48723B3A6C89338D
```

---

## What clears the bar, line by line

The category rejects "thin LLM wrappers" and "generic AI decides X demos".

- **The model never decides.** It answers the same three-way question about
  each condition of one report, twice. Which conditions exist, how long a
  breach may run, what counts as a cure, the order reports are judged in, and
  when a breach becomes a default are all deterministic.
- **Consensus compares only what decides something.** Each reading becomes a
  transition from the condition's current state, so a difference that changes
  nothing cannot split a vote, and a difference that changes the outcome
  cannot be forgiven.
- **Uncertainty is in the value, not the comparison.** A condition the two
  orders read differently is stored as unstated, which can neither open a
  breach nor cure one. Nothing reports how unsure the model was, and there is
  no tolerance anywhere in the agreement rule.
- **The validator function is the contribution.** A free structural check
  before any prompt, which refuses a transition the condition's state cannot
  take, then exact equality on the whole vector. Explained in
  [CONTRACTS.md](CONTRACTS.md) with the code.
- **Time is counted in reports.** Nothing depends on elapsed time: a cure
  window is spent only by a report being filed and judged, and reports are
  judged strictly in filing order.
- **Every write is bound to an address.** Only the borrower reports, only the
  lender waives or closes, and a static test asserts every gated write refuses
  a wrong sender.
- **No global scans.** Every per-facility walk follows links the rows carry or
  a range frozen at open. A static test asserts it.
- **The tests have teeth.** The mutation table in the README is generated by a
  script that refuses to emit a table if anything escapes, the agreement rule
  is swept exhaustively, and the simulator can model a leader that lies.
- **It runs with nothing installed.** `pip install pytest && pytest tests/ -q`.

## The one line worth putting first

**The judgment is hard and the thing crossing consensus is one transition per
condition, derived from the state that condition is in, so the network compares
exactly the differences that decide something.** Everything else in the design
follows from it.
