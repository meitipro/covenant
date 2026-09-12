# Deploying Covenant

Everything you need is on this page. Deploy through the Studio web interface at
**studio.genlayer.com** - paste the contract, deploy, and call the methods
through the form. Never put a private key into a file or hand one to a tool.

You need **two accounts** in Studio: the lender, called **A** below, and the
borrower, called **B**. The account selector in Studio's top bar lets you
create a second account and switch between them; studionet charges no gas, so
nothing needs funding. Write down both addresses before you start. Every step
says which account it is run from.

`tests/test_runbook.py` replays this page step by step, with these exact
strings, and asserts every value it tells you to expect. If the page and the
contract ever disagree, that test fails before you do.

Every compliance report in this demo is identical except for one sentence, the
cash balance, so exactly one thing changes from one report to the next. No
report carries a date or a quarter label: a date would change what "within 90
days of year end" means from one report to the next, and the demo is about the
cash covenant.

---

## 1 - Get the contract

Open the raw file and copy all of it:

**https://raw.githubusercontent.com/meitipro/covenant/main/contracts/covenant.py**

Take it from that link, not from a local copy. What gets deployed has to be the
file in this repository - the reviewer reads the deployed source back off the
chain and compares it, and a submission has been rejected for nothing but a
stale address with the fix already sitting in the repository.

Paste it into Studio and deploy from **A**. **The constructor takes no
arguments.**

---

## 2 - Run the demo

Fifteen writes, in this order. `judge` may be called from either account: it is
open to anyone on purpose.

### Open the term loan - from A

| # | Account | Method | Field | Value |
|---|---|---|---|---|
| 1 | **A** | `open` | `label` | `Harbour Logistics term loan` |
| | | | `conditions` | `a cash balance of at least 2 million EUR at quarter end\|audited annual accounts delivered within 90 days of year end\|the vessel fleet insured against total loss` |
| | | | `cure` | `1` |
| | | | `borrower` | *B's address* |

`conditions` is **one string with pipe separators** - three conditions,
numbered 0 to 2 in that order. `cure` is `1`: a breach gets one later report to
be cured, or it becomes a default. The conditions and the window are frozen
here and can never be edited.

### Report 1: every covenant kept - B files, anyone judges

| # | Account | Method | Field | Value |
|---|---|---|---|---|
| 2 | **B** | `report` | `facility_id` | `0` |
| | | | `text` | `Compliance report 1: the cash balance at quarter end was 2.4 million EUR. Audited annual accounts for the last financial year were delivered within 90 days of year end. The vessel fleet is insured against total loss.` |
| 3 | either | `judge` | `facility_id` | `0` |

> **Stop here and read `get_report(0)`.**
>
> - **`transitions` = `kept|kept|kept`, `states_after` =
>   `compliant|compliant|compliant`** - every covenant kept. Carry on.
> - **anything else** - stop and send me the whole `get_report(0)` JSON. The
>   rest of the demo builds on this report.
> - **the `judge` transaction did not finalize** - nothing was written, and
>   `facility(0).pending` is still `1`. Send me the receipt before calling it
>   again.

### Report 2: the cash covenant broken - B files, anyone judges

| # | Account | Method | Field | Value |
|---|---|---|---|---|
| 4 | **B** | `report` | `facility_id` | `0` |
| | | | `text` | `Compliance report 2: the cash balance at quarter end was 1.7 million EUR. Audited annual accounts for the last financial year were delivered within 90 days of year end. The vessel fleet is insured against total loss.` |
| 5 | either | `judge` | `facility_id` | `0` |

> **Stop here and read `get_report(1)` and `conditions_of(0)`.**
>
> - **`transitions` = `broken|kept|kept`, `states_after` =
>   `breach|compliant|compliant`**, and condition 0 shows `state` = `breach`,
>   `remaining` = `1`, `breaches` = `1`. The facility is still `active`: a
>   breach is not a default until the window runs out. Carry on.
> - **condition 0 came back `kept`** - the report was not read as showing 1.7
>   million under a 2 million floor. Stop and send me the JSON; the rest of the
>   demo depends on this breach.
> - **any other condition came back `broken`** - stop and send me the JSON.

### Report 3: the breach cured - B files, anyone judges

| # | Account | Method | Field | Value |
|---|---|---|---|---|
| 6 | **B** | `report` | `facility_id` | `0` |
| | | | `text` | `Compliance report 3: the cash balance at quarter end was 2.2 million EUR. Audited annual accounts for the last financial year were delivered within 90 days of year end. The vessel fleet is insured against total loss.` |
| 7 | either | `judge` | `facility_id` | `0` |

Expected: `get_report(2).transitions` = `cured|kept|kept`. In
`conditions_of(0)`, condition 0 is back to `compliant` with `remaining` = `0`
and `cures` = `1`.

### Report 4: broken again - B files, anyone judges

| # | Account | Method | Field | Value |
|---|---|---|---|---|
| 8 | **B** | `report` | `facility_id` | `0` |
| | | | `text` | `Compliance report 4: the cash balance at quarter end was 1.6 million EUR. Audited annual accounts for the last financial year were delivered within 90 days of year end. The vessel fleet is insured against total loss.` |
| 9 | either | `judge` | `facility_id` | `0` |

Expected: `get_report(3).transitions` = `broken|kept|kept`. Condition 0 is in
`breach` again with `remaining` = `1`, and `breaches` = `2`.

### Report 5: unremedied, and the default - B files, anyone judges

| # | Account | Method | Field | Value |
|---|---|---|---|---|
| 10 | **B** | `report` | `facility_id` | `0` |
| | | | `text` | `Compliance report 5: the cash balance at quarter end was 1.5 million EUR. Audited annual accounts for the last financial year were delivered within 90 days of year end. The vessel fleet is insured against total loss.` |
| 11 | either | `judge` | `facility_id` | `0` |

> **Stop here and read `get_report(4)` and `facility(0)`.**
>
> - **`transitions` = `unremedied|kept|kept`, `states_after` =
>   `default|compliant|compliant`**, and `facility(0)` shows `status` =
>   `defaulted`, `defaulted` = `true`, `defaulted_condition` = `0`,
>   `defaulted_report` = `4`. The window was one report, the breach was not
>   cured in it, and the facility is in default. Carry on.
> - **`cured` in the first slot** - the model read 1.5 million as meeting a 2
>   million floor. Stop and send me the JSON.
> - **the facility is still `active`** - stop and send me both JSONs.

**Do not try anything more on facility 0.** It is in default, and the contract
refuses every write on it: a report, a judgment, a waiver, a close. The tests
cover every one of those refusals, and a failed transaction on the explorer
page costs more than it shows.

### The revolving credit: a breach, and a waiver

| # | Account | Method | Field | Value |
|---|---|---|---|---|
| 12 | **A** | `open` | `label` | `Harbour Logistics revolving credit` |
| | | | `conditions` | `a cash balance of at least 1 million EUR at quarter end` |
| | | | `cure` | `2` |
| | | | `borrower` | *B's address* |
| 13 | **B** | `report` | `facility_id` | `1` |
| | | | `text` | `Compliance report 1: the cash balance at quarter end was 0.8 million EUR.` |
| 14 | either | `judge` | `facility_id` | `1` |
| 15 | **A** | `waive` | `facility_id` | `1` |
| | | | `condition` | `0` |

After step 14: `get_report(5).transitions` = `broken`, `states_after` =
`breach`, and `conditions_of(1)` shows `state` = `breach`, `remaining` = `2`,
`breaches` = `1`. With a single condition the two presentation orders are the
same prompt, so the second call inside the block is a plain self-consistency
check rather than a position check.

After step 15: `conditions_of(1)` shows `state` = `compliant`, `remaining` =
`0`, `waivers` = `1`, and the facility is still `active`. The waiver forgave
that breach and nothing after it: a later report showing the balance under the
floor would open a new one.

---

## 3 - Reads - free, no transaction

| Call | Argument | Expect |
|---|---|---|
| `count` | | `2` |
| `report_count` | | `6` |
| `status` | `0` | `defaulted` |
| `in_default` | `0` | `true` |
| `facility` | `0` | `status defaulted`, `cure 1`, `conditions 3`, `reports 5`, `judged 5`, `pending 0`, `defaulted true`, `defaulted_condition 0`, `defaulted_report 4` |
| `conditions_of` | `0` | condition 0 `default`, `remaining 0`, `breaches 2`, `cures 1`, `waivers 0`; conditions 1 and 2 `compliant` with every count `0` |
| `reports_of` | `0` | five rows, `seq` 1 to 5, transitions `kept\|kept\|kept`, `broken\|kept\|kept`, `cured\|kept\|kept`, `broken\|kept\|kept`, `unremedied\|kept\|kept` |
| `get_report` | `4` | `transitions unremedied\|kept\|kept`, `states_after default\|compliant\|compliant`, `reason_is_leader_supplied true` |
| `status` | `1` | `active` |
| `in_default` | `1` | `false` |
| `facility` | `1` | `status active`, `cure 2`, `conditions 1`, `reports 1`, `judged 1`, `pending 0`, `defaulted false` |
| `conditions_of` | `1` | `compliant`, `remaining 0`, `breaches 1`, `cures 0`, `waivers 1` |
| `may_report` | `0`, *B's address* | `false` - facility 0 is in default |
| `may_report` | `1`, *B's address* | `true` |
| `may_report` | `1`, *A's address* | `false` - A is the lender |

Every address a view returns is the EIP-55 checksummed form, with mixed case.
Compare addresses case-insensitively.

---

## 4 - Before the portal

```bash
python scripts/verify_deployment.py 0xYourAddress
```

Reads the source back off chain, compares it with `contracts/covenant.py`, and
runs `genvm-lint lint` on those bytes. It must print **"The address is evidence
for this repository. Safe to submit."**

If it prints anything else, do not submit that address. It needs `genvm-lint`
installed (`pip install genvm-linter`), and says so if it is missing.

---

## 5 - Done

Paste the address into README.md and SUBMISSION.md where `{address}` appears,
replace the expected values in SUBMISSION.md with the ones read back from the
chain, and push.

One step stays manual: uploading `brand/social.png` under
Settings -> General -> Social preview. GitHub has no API for it.
