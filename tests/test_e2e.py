"""
End-to-end tests. The real contract file, executed.

tests/test_logic.py covers the pure rules. This file covers everything they
cannot reach: the state machine in storage, the cure window counted over real
reports, sequential judging, the linked walk, the two-pass block, the
validator's gates against a leader that lies, the authority rules, and every
branch that only fires when the leader and a validator see different things.

It runs on tests/glsim.py, a small GenVM stand-in, so it needs no Studio and no
network:

    pytest tests/test_e2e.py -v

The important property is that the leader and the validator get their own
independent mock answers. Every mocking framework feeds both nodes the same
data by default, which is exactly why a contract that quietly assumes both
nodes see identical bytes passes its suite and fails on a real network.
"""

import ast
import collections
import pathlib
import re

import pytest

import glsim as S

CONTRACT_PATH = "contracts/covenant.py"
M = S.load_contract(CONTRACT_PATH)

LABEL = "Harbour Logistics term loan"
C0 = "a cash balance of at least 2 million EUR at quarter end"
C1 = "audited annual accounts delivered within 90 days of year end"
C2 = "the vessel fleet insured against total loss"
NAMES = [C0, C1, C2]
CONDITIONS = "|".join(NAMES)
TAIL = (" Audited annual accounts for the last financial year were delivered within"
        " 90 days of year end. The vessel fleet is insured against total loss.")

LENDER = "0x" + "11" * 20
BORROWER = "0x" + "22" * 20
STRANGER = "0x" + "99" * 20


def text(k, cash):
    return ("Compliance report %d: the cash balance at quarter end was %s million EUR."
            % (k, cash)) + TAIL


def passes(forward, reverse, names=NAMES, because="read from the report"):
    """Mock both presentation orders of one judgment.

    The forward prompt opens its conditions block with names[0] as row [0];
    the reversed prompt opens with names[-1]. A mock keys on that opening row,
    and no key can match both prompts. `reverse` is given in the REVERSED
    order, exactly as a model would answer it, so a test has to think about
    the un-reversal the contract does.
    """
    keys = {
        "[0] " + names[0]: {"readings": forward, "because": because},
        "[0] " + names[-1]: {"readings": reverse, "because": because},
    }
    fwd = M.build_prompt(LABEL, names, "any report", len(names))
    rev = M.build_prompt(LABEL, list(reversed(names)), "any report", len(names))
    for key in keys:
        assert (key in fwd) != (key in rev), "a mock key matches both prompts: %r" % key
    return keys


def stable(vector, names=NAMES):
    """The common case: both orders read every condition the same way."""
    return passes(vector, "|".join(reversed(vector.split("|"))), names)


def by_report(table, names=NAMES, label=LABEL):
    """Key every (report, order) on its FULL prompt, so one mock table answers
    several queued reports differently and a judgment of the wrong report
    finds the wrong answer. `table` maps report text to the forward reading."""
    out = {}
    for body, forward in table.items():
        n = len(names)
        rev = "|".join(reversed(forward.split("|")))
        out[M.build_prompt(label, names, body, n)] = {"readings": forward, "because": "x"}
        out[M.build_prompt(label, list(reversed(names)), body, n)] = {"readings": rev, "because": "x"}
    return out


def single(label, name, body, vector):
    """One condition: the two orders are the same prompt, so key on all of it."""
    return {M.build_prompt(label, [name], body, 1): {"readings": vector, "because": "x"}}


class TestCovenant:

    def deploy(self, cure=1, conditions=CONDITIONS):
        c = S.deploy(CONTRACT_PATH)
        S.set_sender(LENDER)
        S.call(c, "open", LABEL, conditions, cure, BORROWER)
        return c

    def file(self, c, body, fid=0):
        S.set_sender(BORROWER)
        try:
            S.call(c, "report", fid, body)
        finally:
            S.set_sender(LENDER)

    def mocks(self, prompts, v_prompts=None):
        S.set_mocks(leader_pages={}, leader_prompts=prompts, validator_pages={},
                    validator_prompts=v_prompts if v_prompts is not None else prompts)

    def judged(self, c, vector, fid=0, k=1, cash="2.4"):
        """File one report, judge it with both orders reading `vector`."""
        body = text(k, cash)
        self.file(c, body, fid)
        self.mocks(stable(vector))
        S.call(c, "judge", fid)
        return c.get_report(c.report_count() - 1)

    def cond(self, c, k, fid=0):
        return c.conditions_of(fid)["conditions"][k]

    # -- the facility ---------------------------------------------------------

    def test_a_facility_opens_frozen_and_compliant(self):
        c = self.deploy()
        f = c.facility(0)
        assert f["status"] == "active" and f["cure"] == 1 and f["conditions"] == 3
        assert f["reports"] == 0 and f["judged"] == 0 and f["defaulted"] is False
        assert f["lender"] == LENDER and f["borrower"] == BORROWER
        rows = c.conditions_of(0)["conditions"]
        assert [r["name"] for r in rows] == NAMES
        assert all(r["state"] == "compliant" and r["remaining"] == 0 for r in rows)

    def test_a_report_lands_before_it_is_judged(self):
        c = self.deploy()
        self.file(c, text(1, "2.4"))
        f = c.facility(0)
        assert f["reports"] == 1 and f["judged"] == 0 and f["pending"] == 1
        r = c.get_report(0)
        assert r["judged"] is False and r["transitions"] == "" and r["states_after"] == ""
        assert r["seq"] == 1 and r["by"] == BORROWER and r["facility"] == 0

    # -- transitions, applied ---------------------------------------------------

    def test_a_clean_report_keeps_every_covenant(self):
        c = self.deploy()
        r = self.judged(c, "met|met|met")
        assert r["transitions"] == "kept|kept|kept"
        assert r["states_after"] == "compliant|compliant|compliant"
        assert c.facility(0)["judged"] == 1 and c.facility(0)["pending"] == 0

    def test_silence_on_a_compliant_condition_keeps_it(self):
        c = self.deploy()
        r = self.judged(c, "met|unstated|unstated")
        assert r["transitions"] == "kept|kept|kept"

    def test_a_breached_condition_is_broken_and_enters_breach(self):
        c = self.deploy(cure=2)
        r = self.judged(c, "breached|met|met", cash="1.7")
        assert r["transitions"] == "broken|kept|kept"
        assert r["states_after"] == "breach|compliant|compliant"
        assert self.cond(c, 0) == {"index": 0, "facility": 0, "name": C0, "state": "breach",
                                   "remaining": 2, "breaches": 1, "cures": 0, "waivers": 0}
        assert c.status(0) == "active" and c.in_default(0) is False

    def test_a_later_report_that_shows_it_met_cures_the_breach(self):
        c = self.deploy(cure=1)
        self.judged(c, "breached|met|met", k=1, cash="1.7")
        r = self.judged(c, "met|met|met", k=2, cash="2.2")
        assert r["transitions"] == "cured|kept|kept"
        assert r["states_after"] == "compliant|compliant|compliant"
        row = self.cond(c, 0)
        assert row["state"] == "compliant" and row["remaining"] == 0
        assert row["cures"] == 1 and row["breaches"] == 1

    def test_silence_on_a_breach_does_not_cure_it(self):
        """The burden of showing a cure is on the party who benefits from it."""
        c = self.deploy(cure=2)
        self.judged(c, "breached|met|met", k=1, cash="1.7")
        r = self.judged(c, "unstated|met|met", k=2)
        assert r["transitions"] == "unremedied|kept|kept"
        row = self.cond(c, 0)
        assert row["state"] == "breach" and row["remaining"] == 1 and row["cures"] == 0

    def test_cure_zero_is_an_immediate_default(self):
        c = self.deploy(cure=0)
        r = self.judged(c, "breached|met|met", cash="1.7")
        assert r["transitions"] == "broken|kept|kept"
        assert r["states_after"] == "default|compliant|compliant"
        f = c.facility(0)
        assert f["status"] == "defaulted" and f["defaulted"] is True
        assert f["defaulted_condition"] == 0 and f["defaulted_report"] == 0
        assert c.in_default(0) is True and c.status(0) == "defaulted"

    def test_cure_one_is_counted_exactly(self):
        c = self.deploy(cure=1)
        self.judged(c, "breached|met|met", k=1, cash="1.7")
        assert c.status(0) == "active" and self.cond(c, 0)["remaining"] == 1
        r = self.judged(c, "breached|met|met", k=2, cash="1.6")
        assert r["transitions"] == "unremedied|kept|kept"
        assert r["states_after"] == "default|compliant|compliant"
        assert c.facility(0)["defaulted_report"] == 1

    def test_cure_three_is_counted_exactly(self):
        """Three reports of window, counted one at a time. Nothing depends on
        elapsed time: a window is spent only by a report being filed."""
        c = self.deploy(cure=3)
        self.judged(c, "breached|met|met", k=1, cash="1.7")
        for k, left in ((2, 2), (3, 1)):
            r = self.judged(c, "breached|met|met", k=k, cash="1.6")
            assert r["transitions"] == "unremedied|kept|kept"
            assert self.cond(c, 0)["remaining"] == left and c.status(0) == "active"
        r = self.judged(c, "unstated|met|met", k=4)
        assert r["transitions"] == "unremedied|kept|kept"
        assert self.cond(c, 0)["state"] == "default" and self.cond(c, 0)["remaining"] == 0
        f = c.facility(0)
        assert f["status"] == "defaulted" and f["defaulted_report"] == 3
        assert f["defaulted_condition"] == 0

    def test_several_conditions_move_at_once(self):
        c = self.deploy(cure=1)
        r = self.judged(c, "breached|met|breached", k=1, cash="1.7")
        assert r["transitions"] == "broken|kept|broken"
        assert r["states_after"] == "breach|compliant|breach"
        r = self.judged(c, "met|breached|unstated", k=2)
        assert r["transitions"] == "cured|broken|unremedied"
        assert r["states_after"] == "compliant|breach|default"
        f = c.facility(0)
        assert f["status"] == "defaulted"
        assert f["defaulted_condition"] == 2 and f["defaulted_report"] == 1
        assert [self.cond(c, k)["state"] for k in range(3)] == ["compliant", "breach", "default"]
        assert self.cond(c, 1)["remaining"] == 1

    def test_the_first_defaulted_condition_is_recorded(self):
        c = self.deploy(cure=0)
        self.judged(c, "met|breached|breached")
        assert c.facility(0)["defaulted_condition"] == 1

    def test_a_defaulted_facility_refuses_everything_after(self):
        c = self.deploy(cure=0)
        self.judged(c, "breached|met|met", cash="1.7")
        self.file_refused = None
        S.set_sender(BORROWER)
        try:
            with pytest.raises(S.UserError, match="in default"):
                S.call(c, "report", 0, text(2, "2.4"))
        finally:
            S.set_sender(LENDER)
        for call in (("judge", 0), ("waive", 0, 0), ("close", 0)):
            with pytest.raises(S.UserError, match="in default"):
                S.call(c, *call)
        assert c.may_report(0, BORROWER) is False
        assert c.facility(0)["reports"] == 1 and c.status(0) == "defaulted"

    def test_default_is_terminal_even_with_reports_queued(self):
        c = self.deploy(cure=0)
        self.file(c, text(1, "1.7"))
        self.file(c, text(2, "2.4"))
        self.mocks(by_report({text(1, "1.7"): "breached|met|met",
                              text(2, "2.4"): "met|met|met"}))
        S.call(c, "judge", 0)
        assert c.status(0) == "defaulted" and c.facility(0)["pending"] == 1
        with pytest.raises(S.UserError, match="in default"):
            S.call(c, "judge", 0)
        assert c.get_report(1)["judged"] is False

    # -- sequential judging ---------------------------------------------------

    def test_three_reports_filed_before_any_is_judged_are_judged_in_filing_order(self):
        """judge() takes no report id. A borrower who files a breach and then a
        clean report cannot have the clean one read first, and the window is
        counted over the reports in the order they were filed."""
        c = self.deploy(cure=1)
        bodies = [text(1, "2.4"), text(2, "1.7"), text(3, "2.2")]
        for b in bodies:
            self.file(c, b)
        assert c.facility(0)["pending"] == 3
        self.mocks(by_report({bodies[0]: "met|met|met", bodies[1]: "breached|met|met",
                              bodies[2]: "met|met|met"}))
        for _ in range(3):
            S.call(c, "judge", 0)
        rows = c.reports_of(0)["reports"]
        assert [r["id"] for r in rows] == [0, 1, 2] and [r["seq"] for r in rows] == [1, 2, 3]
        assert [r["transitions"] for r in rows] == \
            ["kept|kept|kept", "broken|kept|kept", "cured|kept|kept"]
        assert all(r["judged"] for r in rows)
        assert c.facility(0)["pending"] == 0 and self.cond(c, 0)["cures"] == 1

    def test_a_report_filed_after_the_queue_emptied_is_next(self):
        c = self.deploy(cure=1)
        self.judged(c, "met|met|met", k=1)
        self.file(c, text(2, "1.7"))
        self.file(c, text(3, "2.2"))
        self.mocks(by_report({text(2, "1.7"): "breached|met|met",
                              text(3, "2.2"): "met|met|met"}))
        S.call(c, "judge", 0)
        assert c.get_report(1)["transitions"] == "broken|kept|kept"
        assert c.get_report(2)["judged"] is False
        S.call(c, "judge", 0)
        assert c.get_report(2)["transitions"] == "cured|kept|kept"

    def test_judge_refuses_when_nothing_is_waiting(self):
        c = self.deploy()
        with pytest.raises(S.UserError, match="no report is waiting"):
            S.call(c, "judge", 0)
        self.judged(c, "met|met|met")
        with pytest.raises(S.UserError, match="no report is waiting"):
            S.call(c, "judge", 0)

    # -- waiver ---------------------------------------------------------------

    def test_the_lender_may_waive_a_breach(self):
        c = self.deploy(cure=2)
        self.judged(c, "breached|met|met", cash="1.7")
        S.call(c, "waive", 0, 0)
        row = self.cond(c, 0)
        assert row["state"] == "compliant" and row["remaining"] == 0
        assert row["waivers"] == 1 and row["breaches"] == 1
        assert c.status(0) == "active"

    def test_a_waiver_forgives_only_the_breach_it_names(self):
        c = self.deploy(cure=1)
        self.judged(c, "breached|met|met", k=1, cash="1.7")
        S.call(c, "waive", 0, 0)
        r = self.judged(c, "breached|met|met", k=2, cash="1.5")
        assert r["transitions"] == "broken|kept|kept"
        row = self.cond(c, 0)
        assert row["state"] == "breach" and row["breaches"] == 2 and row["waivers"] == 1

    def test_a_condition_that_is_not_in_breach_cannot_be_waived(self):
        c = self.deploy()
        with pytest.raises(S.UserError, match="not in breach"):
            S.call(c, "waive", 0, 1)
        assert self.cond(c, 1)["waivers"] == 0

    @pytest.mark.parametrize("who", [BORROWER, STRANGER])
    def test_only_the_lender_may_waive(self, who):
        c = self.deploy(cure=2)
        self.judged(c, "breached|met|met", cash="1.7")
        S.set_sender(who)
        try:
            with pytest.raises(S.UserError, match="only the lender may waive"):
                S.call(c, "waive", 0, 0)
        finally:
            S.set_sender(LENDER)
        assert self.cond(c, 0)["state"] == "breach"

    @pytest.mark.parametrize("k", [3, -1, 99])
    def test_waive_refuses_a_condition_that_does_not_exist(self, k):
        c = self.deploy()
        with pytest.raises(S.UserError, match="no such condition"):
            S.call(c, "waive", 0, k)

    # -- close ----------------------------------------------------------------

    def test_the_lender_may_close_once_every_report_is_judged(self):
        c = self.deploy()
        self.judged(c, "met|met|met")
        S.call(c, "close", 0)
        assert c.status(0) == "closed" and c.in_default(0) is False
        S.set_sender(BORROWER)
        try:
            with pytest.raises(S.UserError, match="closed"):
                S.call(c, "report", 0, text(2, "2.4"))
        finally:
            S.set_sender(LENDER)
        for call in (("judge", 0), ("waive", 0, 0), ("close", 0)):
            with pytest.raises(S.UserError, match="closed"):
                S.call(c, *call)
        assert c.may_report(0, BORROWER) is False

    def test_close_is_refused_while_a_report_is_unjudged(self):
        c = self.deploy()
        self.file(c, text(1, "1.7"))
        with pytest.raises(S.UserError, match="waiting to be judged"):
            S.call(c, "close", 0)
        assert c.status(0) == "active"
        self.mocks(stable("breached|met|met"))
        S.call(c, "judge", 0)
        S.call(c, "close", 0)
        assert c.status(0) == "closed"

    @pytest.mark.parametrize("who", [BORROWER, STRANGER])
    def test_only_the_lender_may_close(self, who):
        c = self.deploy()
        S.set_sender(who)
        try:
            with pytest.raises(S.UserError, match="only the lender may close"):
                S.call(c, "close", 0)
        finally:
            S.set_sender(LENDER)
        assert c.status(0) == "active"

    # -- the mirror, caught inside the leader ----------------------------------

    def test_a_condition_the_two_orders_read_differently_is_unstated(self):
        """Forward reads the cash covenant breached; the reversed order reads
        it met. The fold makes it unstated, and unstated opens no breach."""
        c = self.deploy()
        self.file(c, text(1, "2.0"))
        self.mocks(passes("breached|met|met", "met|met|met"))
        S.call(c, "judge", 0)
        assert c.get_report(0)["transitions"] == "kept|kept|kept"
        assert self.cond(c, 0)["breaches"] == 0

    def test_a_disagreement_between_the_orders_does_not_cure_a_breach(self):
        c = self.deploy(cure=2)
        self.judged(c, "breached|met|met", k=1, cash="1.7")
        self.file(c, text(2, "2.0"))
        # reversed order lists C2, C1, C0, so its last token is the cash covenant
        self.mocks(passes("met|met|met", "met|met|breached"))
        S.call(c, "judge", 0)
        assert c.get_report(1)["transitions"] == "unremedied|kept|kept"
        assert self.cond(c, 0)["cures"] == 0

    def test_the_reversed_answer_is_read_back_into_the_frozen_order(self):
        """A consistent model: C0 breached in both orders, which is row [0]
        forward and row [2] reversed. Un-reversed, the orders agree."""
        c = self.deploy()
        self.file(c, text(1, "1.7"))
        self.mocks(passes("breached|met|met", "met|met|breached"))
        S.call(c, "judge", 0)
        assert c.get_report(0)["transitions"] == "broken|kept|kept"

    def test_the_same_position_marked_in_both_orders_is_position_bias(self):
        """The model marks row [2] in both prompts: C2 forward, C0 reversed.
        That is a lean on position, and the fold catches it. A contract that
        forgot the un-reversal would read it as agreement and break C2, the
        wrong condition, on a report that says nothing against it."""
        c = self.deploy()
        self.file(c, text(1, "2.4"))
        self.mocks(passes("met|met|breached", "met|met|breached"))
        S.call(c, "judge", 0)
        assert c.get_report(0)["transitions"] == "kept|kept|kept"
        assert self.cond(c, 2)["breaches"] == 0

    def test_an_unusable_pass_can_neither_open_a_breach_nor_cure_one(self):
        c = self.deploy(cure=2)
        self.file(c, text(1, "1.7"))
        self.mocks(passes("breached|met|breached", "banana"))
        S.call(c, "judge", 0)
        assert c.get_report(0)["transitions"] == "kept|kept|kept"
        self.judged(c, "breached|met|met", k=2, cash="1.7")
        self.file(c, text(3, "2.4"))
        self.mocks(passes("met|met|met", "met|met"))           # wrong length
        S.call(c, "judge", 0)
        assert c.get_report(2)["transitions"] == "unremedied|kept|kept"

    def test_a_prompt_answer_that_is_not_an_object_is_unusable_not_fatal(self):
        """json mode does not guarantee an object. A list or a bare string is
        an unusable answer and is recorded as one, rather than crashing the
        block and failing the transaction."""
        c = self.deploy(cure=2)
        self.judged(c, "breached|met|met", k=1, cash="1.7")
        self.file(c, text(2, "2.4"))
        self.mocks({"[0] " + C0: ["met", "met", "met"], "[0] " + C2: "met|met|met"})
        S.call(c, "judge", 0)
        assert c.get_report(1)["transitions"] == "unremedied|kept|kept"
        assert self.cond(c, 0)["cures"] == 0

    # -- consensus ------------------------------------------------------------

    def test_nodes_reading_a_condition_differently_do_not_agree(self):
        c = self.deploy()
        self.file(c, text(1, "1.7"))
        self.mocks(stable("breached|met|met"), v_prompts=stable("met|met|met"))
        with pytest.raises(S.UserError):
            S.call(c, "judge", 0)
        assert c.get_report(0)["judged"] is False and c.facility(0)["judged"] == 0
        assert self.cond(c, 0)["state"] == "compliant"

    def test_met_and_unstated_agree_on_a_compliant_condition(self):
        """Both are kept. The difference decides nothing, so it cannot split
        a vote, and the network settles."""
        c = self.deploy()
        self.file(c, text(1, "2.4"))
        self.mocks(stable("met|met|met"), v_prompts=stable("unstated|met|unstated"))
        S.call(c, "judge", 0)
        assert c.get_report(0)["transitions"] == "kept|kept|kept"

    def test_met_and_unstated_disagree_on_a_condition_in_breach(self):
        """Cured against unremedied. That difference decides whether a default
        is coming, so the network must agree on it or not settle."""
        c = self.deploy(cure=2)
        self.judged(c, "breached|met|met", k=1, cash="1.7")
        self.file(c, text(2, "2.2"))
        self.mocks(stable("met|met|met"), v_prompts=stable("unstated|met|met"))
        with pytest.raises(S.UserError):
            S.call(c, "judge", 0)
        row = self.cond(c, 0)
        assert row["state"] == "breach" and row["remaining"] == 2 and row["cures"] == 0

    def test_the_leader_s_explanation_is_stored_sanitised(self):
        """`why` is the one stored field the leader chooses outright, so it is
        cleaned at the point it is stored, not only where it is produced."""
        c = self.deploy()
        self.file(c, text(1, "2.4"))
        self.mocks(stable("met|met|met"))
        S.set_leader_payload({"transitions": "kept|kept|kept",
                              "because": "<b>{x}`y`" + chr(1) + "z"})
        try:
            S.call(c, "judge", 0)
        finally:
            S.set_leader_payload(None)
        assert c.get_report(0)["why"] == "bxy z"
        assert c.get_report(0)["reason_is_leader_supplied"] is True

    # -- the validator's gates, against a leader it does not trust ------------

    def test_a_leader_that_rolled_back_is_refused_and_nothing_is_stored(self):
        """Only the forward prompt is mocked, so the leader's block fails. The
        validator must refuse it cleanly rather than read a result that is not
        there."""
        c = self.deploy()
        self.file(c, text(1, "2.4"))
        self.mocks({"[0] " + C0: {"readings": "met|met|met", "because": "x"}})
        with pytest.raises(S.UserError):
            S.call(c, "judge", 0)
        assert S.RT.last_validator_verdict is False
        assert c.get_report(0)["judged"] is False

    def test_a_leader_payload_that_is_not_a_mapping_is_refused_for_free(self):
        c = self.deploy()
        self.file(c, text(1, "2.4"))
        self.mocks(stable("met|met|met"))          # mocks first: set_mocks resets the payload
        S.set_leader_payload("not a mapping")
        try:
            with pytest.raises(S.UserError):
                S.call(c, "judge", 0)
        finally:
            S.set_leader_payload(None)
        assert S.validator_prompt_calls() == 0
        assert c.get_report(0)["judged"] is False

    @pytest.mark.parametrize("payload", [
        {"transitions": "kept|kept", "because": "x"},              # wrong length
        {"transitions": "cured|kept|kept", "because": "x"},        # cured while compliant
        {"transitions": "kept|kept|banana", "because": "x"},       # not a transition
        {"because": "x"},                                          # nothing at all
    ])
    def test_a_malformed_proposal_is_refused_with_zero_validator_prompts(self, payload):
        """The free layer is only worth having if it is free, and the prompt
        count is the only observable difference."""
        c = self.deploy()
        self.file(c, text(1, "2.4"))
        self.mocks(stable("met|met|met"))
        S.set_leader_payload(payload)
        try:
            with pytest.raises(S.UserError):
                S.call(c, "judge", 0)
        finally:
            S.set_leader_payload(None)
        assert S.validator_prompt_calls() == 0
        assert c.get_report(0)["judged"] is False

    def test_a_lying_leader_cannot_break_a_covenant_the_report_keeps(self):
        """A well formed lie passes layer 1 and dies at layer 2, after the
        validator has read the report itself."""
        c = self.deploy()
        self.file(c, text(1, "2.4"))
        self.mocks(stable("met|met|met"))
        S.set_leader_payload({"transitions": "broken|kept|kept", "because": "x"})
        try:
            with pytest.raises(S.UserError):
                S.call(c, "judge", 0)
        finally:
            S.set_leader_payload(None)
        assert S.validator_prompt_calls() == 2
        assert self.cond(c, 0)["state"] == "compliant"

    # -- may_report mirrors report() -------------------------------------------

    def test_may_report_mirrors_report_in_every_state(self):
        c = self.deploy(cure=0)
        with pytest.raises(S.UserError, match="no such facility"):
            c.may_report(9, BORROWER)
        with pytest.raises(S.UserError, match="no such facility"):
            c.may_report(9, "not-an-address")
        assert c.may_report(0, "not-an-address") is False
        assert c.may_report(0, BORROWER) is True
        assert c.may_report(0, LENDER) is False
        assert c.may_report(0, STRANGER) is False
        for who, ok in ((LENDER, False), (STRANGER, False), (BORROWER, True)):
            S.set_sender(who)
            try:
                if ok:
                    S.call(c, "report", 0, text(1, "1.7"))
                else:
                    with pytest.raises(S.UserError, match="only the borrower"):
                        S.call(c, "report", 0, text(1, "1.7"))
            finally:
                S.set_sender(LENDER)
        self.mocks(stable("breached|met|met"))
        S.call(c, "judge", 0)
        assert c.status(0) == "defaulted" and c.may_report(0, BORROWER) is False
        d = self.deploy()
        self.judged(d, "met|met|met")
        S.call(d, "close", 0)
        assert d.may_report(0, BORROWER) is False

    def test_a_facility_takes_at_most_40_reports(self):
        """Only the borrower appends reports, so reaching the cap can only
        cost the borrower its own chance to show a cure. The lender can always
        close, once the queue is judged."""
        c = self.deploy()
        for k in range(40):
            self.file(c, "Compliance report number %d, long enough to be filed." % k)
        assert c.may_report(0, BORROWER) is False
        S.set_sender(BORROWER)
        try:
            with pytest.raises(S.UserError, match="capped at 40 reports"):
                S.call(c, "report", 0, text(41, "2.4"))
        finally:
            S.set_sender(LENDER)
        assert c.facility(0)["reports"] == 40 and len(c.reports_of(0)["reports"]) == 40

    # -- the linked walk --------------------------------------------------------

    def test_two_facilities_never_see_each_other_s_rows(self):
        c = self.deploy(cure=1)
        S.call(c, "open", "Second facility", "a cash balance of at least 1 million EUR at quarter end", 2, BORROWER)
        one = "a cash balance of at least 1 million EUR at quarter end"
        b1 = "Compliance report 1: the cash balance at quarter end was 0.8 million EUR."
        self.file(c, b1, fid=1)
        self.file(c, text(1, "1.7"), fid=0)
        self.file(c, "Compliance report 2: the cash balance at quarter end was 1.2 million EUR.", fid=1)
        self.file(c, text(2, "2.2"), fid=0)
        assert [r["id"] for r in c.reports_of(0)["reports"]] == [1, 3]
        assert [r["id"] for r in c.reports_of(1)["reports"]] == [0, 2]
        prompts = by_report({text(1, "1.7"): "breached|met|met", text(2, "2.2"): "met|met|met"})
        prompts.update(single("Second facility", one, b1, "breached"))
        self.mocks(prompts)
        S.call(c, "judge", 1)
        assert c.get_report(0)["transitions"] == "broken"
        assert [r["judged"] for r in c.reports_of(0)["reports"]] == [False, False]
        S.call(c, "judge", 0)
        S.call(c, "judge", 0)
        assert [r["transitions"] for r in c.reports_of(0)["reports"]] == \
            ["broken|kept|kept", "cured|kept|kept"]
        assert c.conditions_of(1)["conditions"][0]["remaining"] == 2
        assert [r["name"] for r in c.conditions_of(1)["conditions"]] == [one]
        assert [r["facility"] for r in c.conditions_of(0)["conditions"]] == [0, 0, 0]
        assert c.get_report(2)["judged"] is False
        # facility 1's condition is in breach while facility 0's first one is
        # compliant again, so a judgment that read the wrong row's state would
        # call this cure "kept"
        b2 = "Compliance report 2: the cash balance at quarter end was 1.2 million EUR."
        self.mocks(single("Second facility", one, b2, "met"))
        S.call(c, "judge", 1)
        assert c.get_report(2)["transitions"] == "cured"
        assert c.conditions_of(1)["conditions"][0]["cures"] == 1
        assert self.cond(c, 0)["cures"] == 1

    def test_a_single_condition_facility_is_judged_on_one_prompt_twice(self):
        """With one condition the two orders are the same prompt, so the second
        call is a plain self-consistency check rather than a position check."""
        c = self.deploy()
        name = "the vessel fleet insured against total loss"
        S.call(c, "open", "One covenant", name, 0, BORROWER)
        body = "Compliance report 1: the fleet insurance lapsed on the first day of the quarter."
        self.file(c, body, fid=1)
        self.mocks(single("One covenant", name, body, "breached"))
        S.call(c, "judge", 1)
        assert c.get_report(0)["transitions"] == "broken"
        assert c.in_default(1) is True and c.in_default(0) is False
        assert len(S.RT.leader_env.prompt_calls) == 2
        assert S.RT.leader_env.prompt_calls[0] == S.RT.leader_env.prompt_calls[1]

    # -- authority ------------------------------------------------------------

    @pytest.mark.parametrize("who", [LENDER, STRANGER])
    def test_only_the_borrower_may_report(self, who):
        c = self.deploy()
        S.set_sender(who)
        try:
            with pytest.raises(S.UserError, match="only the borrower may file"):
                S.call(c, "report", 0, text(1, "2.4"))
        finally:
            S.set_sender(LENDER)
        assert c.facility(0)["reports"] == 0

    def test_anyone_may_judge_and_that_is_deliberate(self):
        """judge() adds no text and can reach only the transitions the oldest
        report and the frozen conditions imply. The lender wants breaches
        judged and the borrower wants cures judged, so there is nobody to
        protect the record from here."""
        c = self.deploy()
        self.file(c, text(1, "1.7"))
        self.mocks(stable("breached|met|met"))
        S.set_sender(STRANGER)
        try:
            S.call(c, "judge", 0)
        finally:
            S.set_sender(LENDER)
        assert c.get_report(0)["transitions"] == "broken|kept|kept"

    def test_the_report_records_the_account_that_filed_it(self):
        c = self.deploy()
        self.file(c, text(1, "2.4"))
        assert c.get_report(0)["by"] == BORROWER

    def test_an_address_is_matched_by_value_not_by_spelling(self):
        c = S.deploy(CONTRACT_PATH)
        S.call(c, "open", LABEL, CONDITIONS, 1, "0x" + "AB" * 20)
        S.set_sender("0x" + "ab" * 20)
        try:
            S.call(c, "report", 0, text(1, "2.4"))
        finally:
            S.set_sender(LENDER)
        assert c.may_report(0, "0x" + "Ab" * 20) is True
        assert c.facility(0)["reports"] == 1

    # -- validation, at both edges ---------------------------------------------

    @pytest.mark.parametrize("label,ok", [("a", False), ("ab", True),
                                          ("x" * 120, True), ("x" * 121, False)])
    def test_the_label_bounds(self, label, ok):
        c = S.deploy(CONTRACT_PATH)
        if ok:
            S.call(c, "open", label, CONDITIONS, 1, BORROWER)
            assert c.facility(0)["label"] == label
        else:
            with pytest.raises(S.UserError, match="at least 2 characters|capped at 120 characters"):
                S.call(c, "open", label, CONDITIONS, 1, BORROWER)
            assert c.count() == 0

    def test_a_condition_is_capped_and_never_truncated(self):
        c = S.deploy(CONTRACT_PATH)
        with pytest.raises(S.UserError, match="a condition is capped at 120 characters"):
            S.call(c, "open", LABEL, "x" * 121 + "|b", 1, BORROWER)
        S.call(c, "open", LABEL, "x" * 120 + "|b", 1, BORROWER)
        assert c.conditions_of(0)["conditions"][0]["name"] == "x" * 120

    def test_the_number_of_conditions_is_bounded(self):
        c = S.deploy(CONTRACT_PATH)
        eight = "|".join("condition %d" % k for k in range(8))
        S.call(c, "open", LABEL, eight, 1, BORROWER)
        assert c.facility(0)["conditions"] == 8
        with pytest.raises(S.UserError, match="capped at 8 conditions"):
            S.call(c, "open", LABEL, eight + "|condition 8", 1, BORROWER)
        for empty in ("", "|||", "  |  "):
            with pytest.raises(S.UserError, match="at least one condition"):
                S.call(c, "open", LABEL, empty, 1, BORROWER)
        for dupes in ("alpha|beta|alpha", "Cash floor|cash floor"):
            with pytest.raises(S.UserError, match="same wording"):
                S.call(c, "open", LABEL, dupes, 1, BORROWER)
        assert c.count() == 1

    @pytest.mark.parametrize("cure,ok", [(0, True), (3, True), (4, False), (-1, False)])
    def test_the_cure_window_bounds(self, cure, ok):
        c = S.deploy(CONTRACT_PATH)
        if ok:
            S.call(c, "open", LABEL, CONDITIONS, cure, BORROWER)
            assert c.facility(0)["cure"] == cure
        else:
            with pytest.raises(S.UserError, match="0 to 3 reports"):
                S.call(c, "open", LABEL, CONDITIONS, cure, BORROWER)

    def test_the_borrower_must_be_another_address(self):
        c = S.deploy(CONTRACT_PATH)
        for bad in ("not-an-address", "0x1234", "", "0x" + "zz" * 20):
            with pytest.raises(S.UserError, match="not a 20 byte hex address"):
                S.call(c, "open", LABEL, CONDITIONS, 1, bad)
        with pytest.raises(S.UserError, match="must be different accounts"):
            S.call(c, "open", LABEL, CONDITIONS, 1, LENDER.upper().replace("0X", "0x"))
        assert c.count() == 0

    @pytest.mark.parametrize("n,ok", [(19, False), (20, True), (800, True), (801, False)])
    def test_the_report_length_bounds(self, n, ok):
        c = self.deploy()
        S.set_sender(BORROWER)
        try:
            if ok:
                S.call(c, "report", 0, "r" * n)
                assert len(c.get_report(0)["text"]) == n
            else:
                with pytest.raises(S.UserError, match="at least 20 characters|capped at 800 characters"):
                    S.call(c, "report", 0, "r" * n)
                assert c.facility(0)["reports"] == 0
        finally:
            S.set_sender(LENDER)

    def test_a_read_with_a_bad_id_is_a_user_error(self):
        c = self.deploy()
        for m, arg in (("facility", 9), ("facility", -1), ("status", 1), ("in_default", -1),
                       ("conditions_of", 5), ("reports_of", -1)):
            with pytest.raises(S.UserError, match="no such facility"):
                getattr(c, m)(arg)
        for arg in (0, -1):
            with pytest.raises(S.UserError, match="no such report"):
                c.get_report(arg)
        for call in (("report", 3, text(1, "2.4")), ("judge", -1), ("close", 7)):
            with pytest.raises(S.UserError, match="no such facility"):
                S.call(c, *call)

    def test_caller_text_is_cleaned_into_storage_and_fenced_only_at_the_prompt(self):
        c = S.deploy(CONTRACT_PATH)
        S.call(c, "open", "Harbour" + chr(7) + "\nloan", "cash" + chr(0) + "floor|fleet  insured", 1, BORROWER)
        assert c.facility(0)["label"] == "Harbour loan"
        assert [r["name"] for r in c.conditions_of(0)["conditions"]] == ["cash floor", "fleet insured"]
        body = "Cash <b>2.4m</b> [1] above the floor,\n\n fleet" + chr(27) + "insured."
        self.file(c, body)
        stored = c.get_report(0)["text"]
        assert stored == "Cash <b>2.4m</b> [1] above the floor, fleet insured."
        self.mocks({"[0] cash floor": {"readings": "met|met", "because": "x"},
                    "[0] fleet insured": {"readings": "met|met", "because": "x"}})
        S.call(c, "judge", 0)
        sent = S.RT.leader_env.prompt_calls[0]
        assert "Cash (b)2.4m(/b) (1) above the floor, fleet insured." in sent
        assert "Harbour loan" in sent
        assert c.get_report(0)["text"] == stored


# ===========================================================================
# GenVM storage and boundary rules, by static analysis.
# ===========================================================================

class TestStorageShape:
    def _tree(self):
        return ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))

    def _contract(self):
        return [x for x in self._tree().body if isinstance(x, ast.ClassDef)
                and any("gl.Contract" in ast.unparse(b) for b in x.bases)][0]

    def test_the_contract_imports_under_genvm_storage_rules(self):
        assert hasattr(S.load_contract(CONTRACT_PATH), "Contract")

    def test_the_header_pins_the_runner(self):
        first = pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8").split("\n", 1)[0]
        assert first == ('# { "Depends": "py-genlayer:'
                         '1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }')

    def test_init_is_present(self):
        assert "__init__" in [m.name for m in self._contract().body if isinstance(m, ast.FunctionDef)]

    def test_no_storage_dataclass_holds_a_collection(self):
        for cls in [x for x in self._tree().body if isinstance(x, ast.ClassDef)]:
            if "allow_storage" not in " ".join(ast.unparse(d) for d in cls.decorator_list):
                continue
            for st in cls.body:
                if isinstance(st, ast.AnnAssign):
                    ann = ast.unparse(st.annotation)
                    assert "DynArray" not in ann and "TreeMap" not in ann, (cls.name, ann)

    def test_no_forbidden_storage_types(self):
        for cls in [x for x in self._tree().body if isinstance(x, ast.ClassDef)]:
            decs = " ".join(ast.unparse(d) for d in cls.decorator_list)
            is_contract = any("gl.Contract" in ast.unparse(b) for b in cls.bases)
            if "allow_storage" not in decs and not is_contract:
                continue
            for st in cls.body:
                if isinstance(st, ast.AnnAssign):
                    ann = ast.unparse(st.annotation)
                    assert ann not in ("int", "float", "list", "dict", "tuple"), (cls.name, ann)

    def test_no_storage_field_or_method_is_declared_twice(self):
        for cls in [x for x in self._tree().body if isinstance(x, ast.ClassDef)]:
            fields = [st.target.id for st in cls.body if isinstance(st, ast.AnnAssign)]
            meths = [m.name for m in cls.body if isinstance(m, ast.FunctionDef)]
            for names in (fields, meths):
                dupes = [n for n, k in collections.Counter(names).items() if k > 1]
                assert not dupes, f"{cls.name}: {dupes}"

    def test_every_persistent_field_is_declared_in_the_class_body(self):
        cls = self._contract()
        declared = {st.target.id for st in cls.body if isinstance(st, ast.AnnAssign)}
        for m in [x for x in cls.body if isinstance(x, ast.FunctionDef)]:
            for node in ast.walk(m):
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target] if isinstance(node, ast.AugAssign) else [])
                for tg in targets:
                    if isinstance(tg, ast.Attribute) and isinstance(tg.value, ast.Name) and tg.value.id == "self":
                        assert tg.attr in declared, f"self.{tg.attr} undeclared"

    def test_every_stored_field_is_read_somewhere(self):
        """A field nothing reads is a field whose comment nobody checks."""
        tree = self._tree()
        fields = set()
        for cls in [x for x in tree.body if isinstance(x, ast.ClassDef)]:
            if "allow_storage" in " ".join(ast.unparse(d) for d in cls.decorator_list):
                fields |= {st.target.id for st in cls.body if isinstance(st, ast.AnnAssign)}
        loaded = {n.attr for n in ast.walk(self._contract())
                  if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load)}
        assert fields - loaded == set(), f"written, never read: {sorted(fields - loaded)}"

    def test_the_block_boundary_carries_flat_strings_only(self):
        blocks = [x for x in ast.walk(self._tree()) if isinstance(x, ast.FunctionDef) and x.name == "leader_fn"]
        assert blocks
        for blk in blocks:
            for r in [n for n in ast.walk(blk) if isinstance(n, ast.Return)]:
                assert isinstance(r.value, ast.Dict)
                for k, v in zip(r.value.keys, r.value.values):
                    assert isinstance(k, ast.Constant) and isinstance(k.value, str)
                    assert not isinstance(v, (ast.Dict, ast.List, ast.Set, ast.Tuple,
                                              ast.Compare, ast.BoolOp, ast.Constant))

    def test_the_block_never_touches_storage(self):
        for blk in [x for x in ast.walk(self._tree()) if isinstance(x, ast.FunctionDef)
                    and x.name in ("leader_fn", "validator_fn")]:
            for n in ast.walk(blk):
                if isinstance(n, ast.Name):
                    assert n.id != "self", f"{blk.name} reads storage"

    def test_prompts_are_only_ever_run_inside_the_block(self):
        cls = self._contract()
        for m in [x for x in cls.body if isinstance(x, ast.FunctionDef)]:
            inner = {id(n) for f in ast.walk(m) if isinstance(f, ast.FunctionDef)
                     and f.name in ("leader_fn", "validator_fn") for n in ast.walk(f)}
            for n in ast.walk(m):
                if isinstance(n, ast.Attribute) and ast.unparse(n).startswith("gl.nondet"):
                    assert id(n) in inner, f"{m.name} runs a prompt outside the block"

    def test_no_identity_comparison_on_storage(self):
        for n in ast.walk(self._tree()):
            if isinstance(n, ast.Compare) and any(isinstance(o, (ast.Is, ast.IsNot)) for o in n.ops):
                assert "self." not in ast.unparse(n)

    def test_every_gated_write_checks_the_sender(self):
        """Not a substring search. For every write except `open` (which sets
        the lender) and `judge` (deliberately open, see the behavioural test),
        there must be an `if` whose test reads the sender, directly or through a
        local assigned from it, and whose body raises."""
        UNGATED = {"open", "judge"}
        writes = [m for m in self._contract().body if isinstance(m, ast.FunctionDef)
                  and any("gl.public.write" in ast.unparse(d) for d in m.decorator_list)]
        assert {m.name for m in writes} == {"open", "report", "judge", "waive", "close"}
        for m in writes:
            if m.name in UNGATED:
                continue
            aliases = set()
            for node in ast.walk(m):
                if isinstance(node, ast.Assign) and "sender_address" in ast.unparse(node.value):
                    aliases |= {t.id for t in node.targets if isinstance(t, ast.Name)}
            gated = False
            for node in ast.walk(m):
                if not isinstance(node, ast.If):
                    continue
                reads = ("sender_address" in ast.unparse(node.test)
                         or any(isinstance(x, ast.Name) and x.id in aliases for x in ast.walk(node.test)))
                raises = any(isinstance(x, ast.Raise) for st in node.body for x in ast.walk(st))
                gated = gated or (reads and raises)
            assert gated, f"{m.name} has no sender check that refuses"

    def test_no_global_scan_over_any_storage_array(self):
        """Every walk follows links or a frozen range. A loop, or a
        comprehension, over range(len(self.<array>)) is a scan of everybody
        else's rows."""
        scans = [ast.unparse(n.iter) for n in ast.walk(self._tree())
                 if isinstance(n, (ast.For, ast.comprehension))
                 and re.search(r"len\(self\.", ast.unparse(n.iter))]
        assert scans == [], scans
