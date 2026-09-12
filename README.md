<p align="left"><img src="brand/lockup.svg" alt="covenant" height="64"></p>

# Covenant - a breach is cured within the window or it becomes a default

A reusable GenLayer primitive for the covenants in a loan or supply agreement.
The lender freezes the conditions and a cure window when the facility opens,
the borrower files compliance reports in prose, and the contract records,
condition by condition and report by report, whether each covenant was **kept,
broken, cured or left unremedied**. A breach is cured by a later report or it
becomes a default, and the window is counted in reports, never in days. Nobody
decides "default". The contract counts.

- **Contract:** [`contracts/covenant.py`](contracts/covenant.py)
- **Tests:** `pip install pytest && pytest tests/ -q` - nothing else to install
- **Deployed:** [`{address}`](https://explorer-studio.genlayer.com/address/{address}) on studionet
- **Deploying it yourself:** [DEPLOY.md](DEPLOY.md) - the contract, the demo, and the check to run before submitting
- **Verify a deployment:** `python scripts/verify_deployment.py 0x...` - compares the
  on-chain source with this file and lints it
- **Specification:** [CONTRACTS.md](CONTRACTS.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **License:** MIT. Copy the agreement rule; that is what it is for.

---

## The problem

> Keeps a cash balance of at least 2 million EUR at quarter end.

A borrower's compliance report says the balance was 1.7 million. The next one
says 2.2 million. Was the covenant breached, was the breach cured in time, and
is the borrower in default? In practice that is argued over by people reading
prose with opposite incentives: the lender reads a risk to a covenant as a
breach, the borrower reads an optimistic sentence as compliance, and each counts
the cure window in whatever unit suits them.

Ask a model "is the borrower in default?" and you get a confident answer with
no record of which covenant, which report, or how the window was counted.

## How consensus is used

Covenant never asks whether anybody is in default. The conditions and the cure
window are frozen when the facility opens and belong to the contract. The block
sees the numbered conditions and **one report**, and reads one token per
condition: `met`, `breached` or `unstated`.

> The judgment is hard. Read a compliance report and decide whether it actually
> shows a cash balance under the floor, rather than merely mentioning a tight
> quarter.
>
> **The thing that crosses consensus is one transition per condition: kept,
> broken, cured or unremedied.**

Default is then arithmetic the contract does over those transitions, in filing
order, against a window frozen in advance.

### The leader resolves its own uncertainty first

The block reads the report **twice** - once with the conditions in their frozen
order and once reversed and renumbered - and reads the reversed answer back
into the frozen order. A condition read the same way in both orders keeps that
reading. A condition the two orders read differently becomes `unstated`, and a
pass that is unusable as a whole makes every condition `unstated`.

Nothing records that the orders disagreed. That would be a fact about the
sampling rather than the report, and a flag carrying it is true exactly when two
honest nodes are least likely to agree. **Uncertainty belongs in the value,
never in the comparison.**

### Consensus compares consequences, not readings

Before the block, the contract captures each condition's current state as a
plain string. Inside the block each folded reading becomes a transition from
that state:

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
| `compliant` | `met` | `kept` |
| `compliant` | `unstated` | `kept` |
| `compliant` | `breached` | `broken` |
| `breach` | `met` | `cured` |
| `breach` | `unstated` | `unremedied` |
| `breach` | `breached` | `unremedied` |

On a compliant condition `met` and `unstated` are both `kept`: two nodes that
read them differently agree, because the difference decides nothing. On a
condition in breach they are `cured` and `unremedied`: two nodes that read them
differently disagree, because that difference decides whether a default is
coming. A disagreement folded to `unstated` can therefore never open a breach
and never cure one.

**Silence never creates a breach, and silence never cures one.** The burden of
showing a cure is on the party who benefits from it.

### The validator, in two layers

```python
# LAYER 1 -- structural honesty. Costs nothing, runs before any prompt.
#   One transition per frozen condition, each reachable from that condition's
#   current state: kept or broken from compliant, cured or unremedied from
#   breach. A proposal that claims a cure on a compliant condition is a claim
#   the record contradicts, and it dies before any inference is spent on it.

# LAYER 2 -- exact equality on the whole vector.
#   The validator reads the report both ways itself, derives its own
#   transitions from the same captured states, and compares. No tolerance on
#   any condition.
```

There is deliberately **no tolerance** anywhere in layer 2, and the vector
compared is exactly the vector stored, so two nodes that agree always write the
same record.

## The state machine

Applied in the deterministic half, from the agreed transitions and from storage
the block never saw:

| Transition | Effect |
|---|---|
| `kept` | nothing |
| `broken` | `breaches + 1`; the condition enters `breach` with `remaining = cure`, or `default` at once when `cure` is 0 |
| `cured` | back to `compliant`, `remaining = 0`, `cures + 1` |
| `unremedied` | `remaining - 1`; at 0 the condition is in `default` |

When any condition reaches `default`, the facility is `defaulted`, which is
terminal, and it records the first defaulted condition and the report that
caused it. Every report row keeps its transitions and the state of every
condition after it, so the path to a default is on the record report by report.

### The window is counted in reports

`cure` is 0 to 3: how many later reports a breach gets to be cured in, and 0
makes a breach an immediate default. Nothing depends on elapsed time. There is
no block timestamp to read, and a window counted in days would need somebody to
say what day it is. A window counted in reports is spent only by a report being
filed and judged.

### Reports are judged in filing order

`judge()` takes no report id. It always judges the oldest unjudged report, so a
borrower cannot bury a breach under a later clean report, and the window is
counted over the reports in the order they were filed.

### A waiver forgives one breach

The lender may waive a condition that is in `breach`: it goes back to
`compliant` with its window cleared. The waiver forgives the breach it names and
nothing after it, so a later report that shows the condition breached opens a
new breach like any other. A default cannot be waived, because default is
terminal.

## Why this is not a thin LLM wrapper

The model never decides whether anybody is in default. **It answers the same
three-way question about each condition of one report, twice.** Which
conditions exist, how long a breach may run, what counts as a cure, the order
reports are judged in, and when a breach becomes a default - all deterministic,
all computed from storage the block never sees.

Swap in a worse model and the mechanism still works. It reads fewer conditions
consistently, so more of them come back `unstated`, and `unstated` never
changes a condition's standing: a compliant condition stays compliant and a
breach keeps running down its window. The burden stays where it was.

## Who may write to a facility

| Call | Who |
|---|---|
| `open` | anyone. The caller becomes the lender and names the borrower, who must be a different account |
| `report` | the borrower alone, while the facility is active, at most 40 reports per facility |
| `judge` | anyone, deliberately |
| `waive` | the lender alone, and only a condition in `breach` |
| `close` | the lender alone, once every report is judged |

Anything on a `defaulted` or `closed` facility is refused.

`judge()` is open on purpose. It adds no text, it can reach only the
transitions the oldest report and the frozen conditions imply, and both parties
want it called: the lender wants breaches judged and the borrower wants cures
judged.

Only the borrower appends reports, so the report cap is a budget only the
borrower can spend. Reaching it costs the borrower its own chance to show a
cure and nobody else anything; the lender can always close once the queue is
judged.

## The API

```python
open(label, conditions, cure, borrower)   # anyone. conditions pipe joined, frozen here
report(facility_id, text)                 # the borrower alone
judge(facility_id)                        # anyone. judges the oldest unjudged report
waive(facility_id, condition)             # the lender alone, a condition in breach
close(facility_id)                        # the lender alone, once every report is judged

status(facility_id)           -> str    # active | defaulted | closed
in_default(facility_id)       -> bool   # the one line read for another contract
facility(facility_id)         -> dict   # parties, window, counts, where it defaulted
conditions_of(facility_id)    -> dict   # every condition: state, remaining, breaches, cures, waivers
get_report(report_id)         -> dict   # transitions, states after, who filed it
reports_of(facility_id)       -> dict   # every report on the facility, oldest first
may_report(facility_id, who)  -> bool   # would report() accept that address right now
count() / report_count()
```

`may_report()` asks the question `report()` asks, through the same helper: the
facility's status, the borrower, and the report cap. It cannot see the text,
which is the one thing `report()` checks that a view could not.

## Using it from another contract

```python
@gl.contract_interface
class Covenant:
    class View:
        def in_default(self, facility_id: int) -> bool: ...
        def facility(self, facility_id: int) -> dict: ...

cov = Covenant(COVENANT_ADDR).view()

# bind to the parties, never to the label. On chain every address a view
# returns is the EIP-55 checksummed string, so compare case-insensitively.
f = cov.facility(fid)
if f["lender"].lower() != str(expected_lender).lower():
    raise ...

# act only on a default the reports actually produced
if cov.in_default(fid):
    self._accelerate_repayment()
```

`facility()` returns `defaulted_condition` and `defaulted_report` as `0` unless
`defaulted` is true, and `0` is also a real index, so read `defaulted` first.

---

## Running the tests

```bash
pip install pytest
pytest tests/ -q
```

Nothing else is needed. `tests/glsim.py` is a small GenVM stand-in, so the unit,
end-to-end and runbook suites run with no Studio and no network.
`tests/test_runbook.py` replays [DEPLOY.md](DEPLOY.md) step by step and asserts
every value it tells you to expect, so the walkthrough is tested like the code.

The integration suite is **opt in**, and deliberately so. It skips when
`genlayer-test` is absent, and it also skips when `genlayer-test` is present
without a Studio to talk to - otherwise anybody who reviews GenLayer contracts,
and therefore has the plugin installed, would see a wall of connection errors on
a repository that promises an offline run. To run it against a live Studio:

```bash
pip install genlayer-test
GENLAYER_STUDIO=1 gltest --network studionet tests/test_integration.py
```

<!-- measured:tests -->
`pytest tests/ -q` reports **215 passed, 1 skipped**, and every one of the **131** mutations below is caught.
<!-- /measured:tests -->

### The tests have teeth

A passing count is a claim. The table below is evidence: every row is a real edit
to the contract that removes a defence, and the test named beside it is the one
that failed. It is generated by `scripts/mutate.py`, which regenerates the
lifted library from each mutant before the suite runs, so no parity check can
stand in for a behavioural test, and which refuses to emit a table if anything
escapes.

<!-- measured:mutations -->
| Mutation | Caught by |
|---|---|
| a disagreement between the orders keeps the forward reading | `test_a_condition_the_two_orders_read_differently_is_unstated` |
| a disagreement between the orders folds to met | `test_a_disagreement_between_the_orders_does_not_cure_a_breach` |
| a disagreement between the orders folds to breached | `test_a_condition_the_two_orders_read_differently_is_unstated` |
| the reversed pass is ignored, so nothing is mirrored | `test_a_condition_the_two_orders_read_differently_is_unstated` |
| the reversed answer is not read back into the frozen order | `test_a_breached_condition_is_broken_and_enters_breach` |
| an unusable pass read as met | `test_an_unusable_pass_can_neither_open_a_breach_nor_cure_one` |
| an unusable pass read as breached | `test_an_unusable_pass_can_neither_open_a_breach_nor_cure_one` |
| a prompt answer that is not an object crashes the block | `test_a_prompt_answer_that_is_not_an_object_is_unusable_not_fatal` |
| a partly unusable answer read slot by slot | `test_parse_vector_is_all_or_nothing` |
| an answer of the wrong length parsed anyway | `test_parse_vector_is_all_or_nothing` |
| any word accepted as a reading | `test_only_met_breached_or_unstated_survives` |
| a breached reading does not break a compliant condition | `test_a_breached_condition_is_broken_and_enters_breach` |
| every reading breaks a compliant condition | `test_a_clean_report_keeps_every_covenant` |
| silence breaches a compliant condition | `test_silence_on_a_compliant_condition_keeps_it` |
| a met reading does not cure a breach | `test_a_later_report_that_shows_it_met_cures_the_breach` |
| every reading cures a breach | `test_silence_on_a_breach_does_not_cure_it` |
| silence cures a breach | `test_silence_on_a_breach_does_not_cure_it` |
| a condition in default is given a transition | `test_transition_over_its_whole_domain` |
| every condition read against the first condition's state | `test_a_later_report_that_shows_it_met_cures_the_breach` |
| one condition forgiven, the Winnow defect | `test_nodes_reading_a_condition_differently_do_not_agree` |
| agreement loosened to the same number of breaches | `test_met_and_unstated_disagree_on_a_condition_in_breach` |
| the agreement rule stops checking the shape of either side | `test_two_malformed_sides_never_agree_with_each_other` |
| the free structural layer removed | `test_a_malformed_proposal_is_refused_with_zero_validator_prompts` |
| the validator trusts a sound proposal without reading the report | `test_nodes_reading_a_condition_differently_do_not_agree` |
| a leader that rolled back is not refused | `test_a_leader_that_rolled_back_is_refused_and_nothing_is_stored` |
| a leader payload that is not a mapping is not refused | `test_a_leader_payload_that_is_not_a_mapping_is_refused_for_free` |
| a transition vector of the wrong length accepted | `test_the_length_must_match_the_frozen_conditions` |
| an empty transition vector accepted as sound | `test_the_length_must_match_the_frozen_conditions` |
| a transition the condition's state cannot take accepted | `test_a_malformed_proposal_is_refused_with_zero_validator_prompts` |
| a compliant condition allowed to be cured | `test_a_malformed_proposal_is_refused_with_zero_validator_prompts` |
| a proposal of the wrong length parsed anyway | `test_parse_transitions_checks_the_length` |
| a breach is not counted | `test_a_breached_condition_is_broken_and_enters_breach` |
| a cure window of zero is not an immediate default | `test_cure_zero_is_an_immediate_default` |
| the cure window not set when a breach opens | `test_a_breached_condition_is_broken_and_enters_breach` |
| the cure window never spent | `test_silence_on_a_breach_does_not_cure_it` |
| a spent cure window does not default | `test_cure_one_is_counted_exactly` |
| a cure does not return the condition to compliant | `test_a_later_report_that_shows_it_met_cures_the_breach` |
| a cure leaves the old window on the condition | `test_a_later_report_that_shows_it_met_cures_the_breach` |
| a cure is not counted | `test_a_later_report_that_shows_it_met_cures_the_breach` |
| the last defaulted condition recorded instead of the first | `test_the_first_defaulted_condition_is_recorded` |
| a default is not propagated to the facility | `test_cure_zero_is_an_immediate_default` |
| the defaulted condition not recorded | `test_several_conditions_move_at_once` |
| the report that caused the default not recorded | `test_cure_one_is_counted_exactly` |
| the states after a report not recorded | `test_a_clean_report_keeps_every_covenant` |
| the transitions not recorded on the report | `test_a_clean_report_keeps_every_covenant` |
| a judged report not marked judged | `test_three_reports_filed_before_any_is_judged_are_judged_in_filing_order` |
| the judged count not kept | `test_a_clean_report_keeps_every_covenant` |
| the leader's reason stored unsanitised | `test_the_leader_s_explanation_is_stored_sanitised` |
| a transition written onto another facility's condition | `test_two_facilities_never_see_each_other_s_rows` |
| judge takes the newest report instead of the oldest | `test_default_is_terminal_even_with_reports_queued` |
| the queue not advanced after a judgment | `test_three_reports_filed_before_any_is_judged_are_judged_in_filing_order` |
| a report arriving at an empty queue not made next | `test_a_later_report_that_shows_it_met_cures_the_breach` |
| judge runs with nothing waiting | `test_judge_refuses_when_nothing_is_waiting` |
| the previous last report not linked to the new one | `test_three_reports_filed_before_any_is_judged_are_judged_in_filing_order` |
| a facility's first report not recorded as its head | `test_two_facilities_never_see_each_other_s_rows` |
| the facility's report count not kept | `test_a_report_lands_before_it_is_judged` |
| a report's sequence number is not its position | `test_three_reports_filed_before_any_is_judged_are_judged_in_filing_order` |
| the report walk replaced by a scan of every facility's rows | `test_two_facilities_never_see_each_other_s_rows` |
| the conditions read from the start of the array, not the facility's range | `test_two_facilities_never_see_each_other_s_rows` |
| the states read from the start of the array, not the facility's range | `test_two_facilities_never_see_each_other_s_rows` |
| a defaulted facility treated as active | `test_a_defaulted_facility_refuses_everything_after` |
| a closed facility treated as active | `test_the_lender_may_close_once_every_report_is_judged` |
| a status refusal found and never raised | `test_a_defaulted_facility_refuses_everything_after` |
| report() skips the status gate | `test_a_defaulted_facility_refuses_everything_after` |
| judge() skips the status gate | `test_a_defaulted_facility_refuses_everything_after` |
| waive() skips the status gate | `test_a_defaulted_facility_refuses_everything_after` |
| close() skips the status gate | `test_a_defaulted_facility_refuses_everything_after` |
| closing does not end the facility | `test_the_lender_may_close_once_every_report_is_judged` |
| in_default() true for any facility that is not active | `test_the_lender_may_close_once_every_report_is_judged` |
| report left open to anyone | `test_may_report_mirrors_report_in_every_state` |
| the lender allowed to report on the borrower's behalf | `test_may_report_mirrors_report_in_every_state` |
| report() ignores the refusal it was handed | `test_a_defaulted_facility_refuses_everything_after` |
| waive left open to anyone | `test_only_the_lender_may_waive` |
| the borrower allowed to waive its own breach | `test_only_the_lender_may_waive` |
| close left open to anyone | `test_only_the_lender_may_close` |
| close allowed while a report is unjudged | `test_close_is_refused_while_a_report_is_unjudged` |
| a condition that is not in breach can be waived | `test_a_condition_that_is_not_in_breach_cannot_be_waived` |
| a waiver does not return the condition to compliant | `test_the_lender_may_waive_a_breach` |
| a waiver leaves the old window on the condition | `test_the_lender_may_waive_a_breach` |
| a waiver is not counted | `test_the_lender_may_waive_a_breach` |
| the report cap removed | `test_a_facility_takes_at_most_40_reports` |
| a fragment accepted as a report | `test_the_report_length_bounds` |
| an over-long report accepted | `test_the_report_length_bounds` |
| the filing account not recorded on the report | `test_a_report_lands_before_it_is_judged` |
| a one-character label accepted | `test_the_label_bounds` |
| the label cap removed | `test_the_label_bounds` |
| a facility with no conditions accepted | `test_the_number_of_conditions_is_bounded` |
| the conditions cap removed, so an unbounded prompt is built | `test_the_number_of_conditions_is_bounded` |
| an over-long condition accepted | `test_a_condition_is_capped_and_never_truncated` |
| duplicate conditions accepted | `test_the_number_of_conditions_is_bounded` |
| conditions that differ only in case accepted as two | `test_the_number_of_conditions_is_bounded` |
| a cure window above three accepted | `test_the_cure_window_bounds` |
| a negative cure window accepted | `test_the_cure_window_bounds` |
| a malformed borrower address passed to Address() | `test_the_borrower_must_be_another_address` |
| the lender may name itself as the borrower | `test_the_borrower_must_be_another_address` |
| waive's condition index not checked | `test_waive_refuses_a_condition_that_does_not_exist` |
| a negative condition index reaches list indexing | `test_waive_refuses_a_condition_that_does_not_exist` |
| control characters kept in caller text | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| the label stored uncleaned | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| the conditions split without the cleaner | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| the report text stored uncleaned | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| the reason sanitiser disabled | `test_the_leader_s_explanation_is_stored_sanitised` |
| control characters left in reasons | `test_the_leader_s_explanation_is_stored_sanitised` |
| the reason not capped | `test_it_is_capped` |
| the prompt fence removed, so a caller can forge a block | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| the fence deletes instead of replacing | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| square brackets not fenced, so a report can forge a numbered row | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| only the opening angle bracket fenced | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| the report reaches the model unfenced | `test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt` |
| the condition names reach the model unfenced | `test_rows_holds_nothing_but_the_numbering_and_fenced_names` |
| the facility label reaches the model unfenced | `test_the_label_is_fenced_too` |
| the whole block fenced after numbering, which fences away the contract's own rows | `test_a_clean_report_keeps_every_covenant` |
| the count in the prompt derived from caller text | `test_the_count_line_comes_from_n` |
| a concrete example that is itself a valid answer | `test_the_answer_shape_is_a_placeholder_never_a_valid_answer` |
| the risk and optimism sentence dropped from the prompt | `test_a_risk_is_not_a_breach_and_optimism_is_not_compliance` |
| the DATA framing dropped from the prompt | `test_the_prompt_says_the_tagged_text_is_data` |
| the facility bounds check removed | `test_may_report_mirrors_report_in_every_state` |
| negative facility ids allowed through to list indexing | `test_a_read_with_a_bad_id_is_a_user_error` |
| the report bounds check removed | `test_a_read_with_a_bad_id_is_a_user_error` |
| negative report ids allowed through to list indexing | `test_a_read_with_a_bad_id_is_a_user_error` |
| may_report() checks the address before the facility exists | `test_may_report_mirrors_report_in_every_state` |
| may_report() hands a malformed address to Address() | `test_may_report_mirrors_report_in_every_state` |
| may_report() answers only who the borrower is | `test_a_defaulted_facility_refuses_everything_after` |
| may_report() says yes to any well formed address | `test_a_defaulted_facility_refuses_everything_after` |
| a nested mapping returned from the block | `test_a_clean_report_keeps_every_covenant` |
| a bool returned from the block, the noise flag this design refuses | `test_a_clean_report_keeps_every_covenant` |
| the block reads storage | `test_two_facilities_never_see_each_other_s_rows` |
| a collection nested back into a storage dataclass | `TypeError at import` |
| an int storage field | `TypeError at import` |
| a storage field declared twice | `test_no_storage_field_or_method_is_declared_twice` |
| a prompt moved outside the block, which genvm-lint refuses | `test_a_clean_report_keeps_every_covenant` |
<!-- /measured:mutations -->

The simulator can also model **a leader that lies**: `set_leader_payload()` puts
a value on the wire that `leader_fn` would never return, which is the only way to
exercise the checks a validator runs against a peer it does not trust. Without
it, every one of those checks is unreachable in testing and a defence that cannot
be exercised looks identical to one that is not there.

## Design rules

- **The block returns transitions, never an outcome.** One per condition, from
  the four the state machine defines.
- **Consensus compares consequences.** A reading becomes a transition from the
  condition's current state before anything is compared, so a difference that
  decides nothing cannot split a vote and a difference that decides something
  cannot be forgiven.
- **Uncertainty enters the stored value, and only the value.** A condition the
  two orders read differently is `unstated`. Nothing stores how unsure the model
  was.
- **Silence never breaches and never cures.**
- **Time is counted in reports.** Nothing depends on elapsed time, and reports
  are judged strictly in filing order.
- **Default is terminal.** A contract that reads `in_default()` reads a fact
  that will not change under it.
- **Every write is bound to an address**, and a structural test asserts it for
  the methods nobody has written yet.
- **Untrusted text is fenced at the prompt boundary.** `fence()` neutralises `<`
  `>`, which close a tag, and `[` `]`, which number a row, so a report can forge
  neither. Replace, never delete, and at the boundary only.
- **No global scans.** Every per-facility walk follows links the rows carry, or
  a range frozen at open.
- **Refusing is designed.** An unjudged report blocks a close, a default blocks
  everything, and a condition that is not in breach cannot be waived.
- **No web access.** Every input is text the parties supply, which removes an
  entire class of deployment failure.

## Further reading in this repository

- [CONTRACTS.md](CONTRACTS.md) - the full specification: purpose, consensus,
  the state machine, state model, API, reuse
- [DECISIONS.md](DECISIONS.md) - engineering decisions, what they cost, and
  what was built in from a sibling's audit
- [lib/covenant_consensus.py](lib/covenant_consensus.py) - the agreement rules
  on their own, to be copied. Generated by `scripts/lift.py` and checked for
  drift by the suite
- [brand/](brand/) - the mark, the lockup, the palette, and the social card

## Related work

Separate primitives, built to the same standard and submitted independently:
[Accrue](https://github.com/meitipro/accrue) - a credential that can only be
earned.
[Quorum](https://github.com/meitipro/quorum) - one question, several
independent sources, one answer or none.
[Assent](https://github.com/meitipro/assent) - an agreement forms only when the
acceptance matches the offer.
[Ratchet](https://github.com/meitipro/ratchet) - a published commitment that can
only ever be tightened.
[Keystone](https://github.com/meitipro/keystone) - an ordering built one pair at
a time that cannot contradict itself.
[Recant](https://github.com/meitipro/recant) - self-consistency across a record
of statements.

They share an author and a discipline, not a codebase. Each deploys, tests and is
used entirely on its own.

---

Published by [InferNode](https://x.com/Infer_node).
