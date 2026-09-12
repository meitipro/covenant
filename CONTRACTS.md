# Covenant - specification

One standalone GenLayer Intelligent Contract.
[`contracts/covenant.py`](contracts/covenant.py), deployed exactly as written,
no build step.

Runner pinned in the header:
`py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`

---

## Purpose

Track the covenants of a loan or supply agreement report by report, and turn a
breach into either a cure or a default by counting reports. The lender freezes
the conditions and a cure window when the facility opens; the borrower files
compliance reports in prose; each report is read on its own, one token per
condition; and whether a breach was cured in time, or became an event of
default, is arithmetic over those readings in filing order.

The failure it catches is not a false report. It is **a report read by whoever
benefits from the reading**: a risk to a covenant read as a breach, or an
optimistic sentence read as compliance, and a cure window counted in whatever
unit suits the reader.

## Consensus

`gl.vm.run_nondet_unsafe`. **Two prompts in one block**, the conditions in
their frozen order and then reversed and renumbered.

The block receives the facility label, the numbered conditions and **one**
report, and returns:

| Field | Type on the wire | Meaning |
|---|---|---|
| `transitions` | pipe joined, one per condition | `kept`, `broken`, `cured` or `unremedied` |
| `because` | short string | leader supplied, sanitised, **not** consensus |

Everything crossing the boundary is a plain string in a flat dict. Nothing
reports how unsure the model was: no confidence, no "the orders agreed" flag,
no retry count.

### The readings

Each condition gets one token:

| Token | Meaning |
|---|---|
| `met` | the report states or directly shows the condition is satisfied |
| `breached` | the report states or directly shows it is not satisfied |
| `unstated` | the report does not address it, or mentions its subject without showing whether it is satisfied |

The prompt says, in as many words, that a condition is not breached because the
report mentions a risk to it, and not met because the report is optimistic
about it, and to judge only this report.

### The fold

The reversed pass lists the conditions last to first, so its row `[0]` is the
frozen row `n-1`. The contract reads the answer back into the frozen order and
folds the two passes per condition: the same token in both orders stands,
different tokens become `unstated`. A pass that is unusable as a whole (the
wrong length, a token outside the three, not a JSON object) makes every
condition `unstated`.

With a single condition the two orders are the same prompt, and the second call
is a plain self-consistency check rather than a position check.

### Canonical transitions

Before the block the contract captures each condition's current state as a
plain list of strings. While a facility is active every condition is
`compliant` or `breach`. Inside the block each folded token becomes a
transition:

```python
def transition(state, token):
    if state == COMPLIANT:
        return BROKEN if token == BREACHED else KEPT
    if state == BREACH:
        return CURED if token == MET else UNREMEDIED
    return ""
```

| State | Reading | Transition |
|---|---|---|
| `compliant` | `met` or `unstated` | `kept` |
| `compliant` | `breached` | `broken` |
| `breach` | `met` | `cured` |
| `breach` | `breached` or `unstated` | `unremedied` |

This is the design. Consensus compares exactly and only what decides
something: on a compliant condition `met` and `unstated` are both `kept`, so
nodes that read them differently agree; on a condition in breach they are
`cured` and `unremedied`, so nodes that read them differently disagree. A
disagreement folded to `unstated` can therefore never open a breach and never
cure one: **silence never creates a breach, and silence never cures one.**

### The validator

1. **Structural honesty, free.** One transition per frozen condition, each
   reachable from that condition's current state: `kept` or `broken` from
   `compliant`, `cured` or `unremedied` from `breach`. A proposal that claims
   `cured` on a compliant condition is refused before any prompt is spent.
2. **Exact equality on the whole vector.** The validator reads the report both
   ways itself, derives its own transitions from the same captured states, and
   compares. No tolerance on any condition.

`covenant_agrees(a, b, s) == covenant_agrees(b, a, s)`, by construction: both
sides pass the same structural check and the comparison is an equality. The
vector compared is the vector stored.

## The state machine

Applied in the deterministic half, from the agreed transitions and from storage
the block never saw:

| Transition | Effect |
|---|---|
| `kept` | nothing |
| `broken` | `breaches + 1`; the condition enters `breach` with `remaining = cure`, or `default` at once when `cure` is 0 |
| `cured` | back to `compliant`, `remaining = 0`, `cures + 1` |
| `unremedied` | `remaining - 1`; at 0 the condition is in `default` |

If any condition is in `default` after a judgment, the facility becomes
`defaulted`, which is terminal, and records the first defaulted condition and
the report that caused it. The report row stores its transitions and the
state of every condition after it (`states_after`).

`waive(facility, condition)` takes a condition in `breach` back to
`compliant` with `remaining = 0` and `waivers + 1`. It forgives the breach it
names; a later report that shows the condition breached opens a new one.

### Cure windows are counted in reports

`cure` is 0 to 3: how many later reports a breach gets to be cured in. Nothing
in the contract depends on elapsed time. There is no block timestamp to read,
and a window counted in days would need somebody to say what day it is. A
window counted in reports is spent only by a report being filed and judged.

### Sequential judging

`judge(facility_id)` takes no report id and always judges the oldest unjudged
report. The facility carries `n_judged` and `next_to_judge`: a report appended
to an empty queue becomes `next_to_judge`, and after a judgment, if reports are
still waiting, `next_to_judge` follows the judged report's `next` link. A
borrower cannot bury a breach under a later clean report, and a window is
counted over reports in the order they were filed.

## State

Every collection is a **top level contract field**. No storage dataclass
contains a collection, because GenVM cannot construct one. Children carry a
parent id; reports also carry the index of the next report on the same
facility, so a facility's reports are walked by following links rather than by
scanning the array. Conditions are appended in one call at `open()`, so they
are contiguous and a range from `first_condition` suffices.

| Field | Type | Note |
|---|---|---|
| `facilities` | `DynArray[Facility]` | append only |
| `conditions` | `DynArray[Condition]` | flat; a facility's conditions are `first_condition + k` |
| `reports` | `DynArray[Report]` | flat; linked through `Report.next` |
| `Facility.lender` | `Address` | the caller of `open()`; waives and closes |
| `Facility.borrower` | `Address` | named at `open()`; the only account that reports |
| `Facility.status` | `str` | `active`, `defaulted` or `closed` |
| `Facility.cure` | `u256` | frozen at `open()`, 0 to 3 reports |
| `Facility.first_condition / n_conditions` | `u256` | the frozen catalogue's range |
| `Facility.first_report / last_report / n_reports` | `u256` | the head, tail and length of the report chain |
| `Facility.n_judged / next_to_judge` | `u256` | the judging queue |
| `Facility.defaulted_condition / defaulted_report` | `u256` | valid only when `defaulted` |
| `Condition.state` | `str` | `compliant`, `breach` or `default` |
| `Condition.remaining` | `u256` | reports left in the window, while in `breach` |
| `Condition.breaches / cures / waivers` | `u256` | counts, for the record |
| `Report.by` | `Address` | the account that filed it |
| `Report.seq` | `u256` | 1-based position in the facility's sequence |
| `Report.judged` | `bool` | set once, by `judge()` |
| `Report.transitions` | `str` | pipe joined, `""` until judged |
| `Report.states_after` | `str` | pipe joined condition states after it, `""` until judged |
| `Report.why` | `str` | leader supplied, sanitised, **not** consensus |
| `Report.next` | `u256` | the next report on the same facility |

## Caps

| Constant | Value | Note |
|---|---|---|
| `MAX_CONDITIONS` | 8 | per facility; also bounds the prompt |
| `MAX_CONDITION` | 120 | characters, after whitespace collapse; refused, never truncated |
| `MIN_LABEL` | 2 | characters |
| `MAX_LABEL` | 120 | characters |
| `MAX_CURE` | 3 | reports a breach may run before it is a default |
| `MIN_REPORT` | 20 | characters |
| `MAX_REPORT` | 800 | characters |
| `MAX_REPORTS` | 40 | per facility, every report counted; bounds every walk |
| `MAX_REASON` | 140 | characters of the leader's explanation |

`open()` refuses a facility with no conditions, more than 8, a condition over
120 characters, or two conditions that differ only in case: the model could not
tell them apart, and neither could a reader.

Every caller string goes through one cleaner on the way into storage: every
character below 32, and 127, becomes a space, then whitespace collapses. At the
prompt boundary only, `fence()` replaces `<` `>` `[` `]` with `(` `)` `(` `)`.

## Authority

| Call | Who | Why |
|---|---|---|
| `open` | anyone | the caller becomes the lender and names the borrower, who must be a different account |
| `report` | the borrower | a report is the borrower's account of its own compliance |
| `judge` | anyone | it adds no text and reaches only the transitions the oldest report and the frozen conditions imply; the lender wants breaches judged and the borrower wants cures judged |
| `waive` | the lender | forgiving a breach is the lender's right to give up, and only a breach can be waived |
| `close` | the lender | once every report is judged, so a close cannot end the record ahead of a breach or a cure |

Anything on a `defaulted` or `closed` facility is refused.

## API

```
open(label: str, conditions: str, cure: u256, borrower: str)   # conditions pipe joined
report(facility_id: u256, text: str)
judge(facility_id: u256)
waive(facility_id: u256, condition: u256)
close(facility_id: u256)

status(facility_id)               -> str    # active | defaulted | closed
in_default(facility_id)           -> bool
facility(facility_id)             -> dict
conditions_of(facility_id)        -> dict
get_report(report_id)             -> dict
reports_of(facility_id)           -> dict
may_report(facility_id, who: str) -> bool
count() / report_count()          -> u256
```

`facility()` returns `defaulted_condition` and `defaulted_report` as `0` unless
`defaulted` is true, and `0` is also a real index, so read `defaulted` first.

`may_report()` asks the question `report()` asks, through the same helper,
`_report_refusal()`, which returns the reason `report()` would refuse or an
empty string, so the view cannot drift from the write. A bad facility id
raises, a malformed address is `False`, and then the facility must be active,
`who` must be its borrower, and the report cap must not be reached. It cannot
check the text, whose length `report()` checks last.

Every address a view returns is the **EIP-55 checksummed string** on chain,
with mixed case. Compare addresses case-insensitively.

Reads with an out-of-range **or negative** id raise a `UserError`: Python list
indexing accepts `-1` and returns the newest row, which would hand a caller a
different record with nothing failing anywhere.

## Reuse

[`lib/covenant_consensus.py`](lib/covenant_consensus.py) holds the pure rules
with no storage and no contract around them. It is **generated** by
`scripts/lift.py` from the contract, and `tests/test_logic.py` compares the two
parsed trees function by function, so a copied rule is always one a deployed
contract actually runs.

The idea worth lifting is `transition()`: let the model read in the
vocabulary that is natural to it, then map each reading onto the vocabulary of
what it decides before anything is compared, so the network agrees on
consequences rather than on wording.
