"""The runbook, executed, and the documents held to the code.

This file drives tests/glsim.py through DEPLOY.md's exact sequence: the same
methods, the argument strings copied character for character from the
document, the same two accounts, in the same order, with mocks returning the
answers DEPLOY.md says to expect. It then asserts every value DEPLOY.md's
checkpoints and reads table claim, and every result in SUBMISSION.md's
expected table.

It mirrors DEPLOY.md and must be updated with it. Every argument string used
here is also asserted to appear verbatim in DEPLOY.md, so the two cannot drift
apart in silence.

The second half holds the other documents to the code: every contract snippet
they quote must be the source as it stands, every constant they quote must be
the constant the contract runs, and the portal Notes must fit the portal box.

    pytest tests/test_runbook.py -v
"""

import pathlib
import re

import pytest

import glsim as S

CONTRACT_PATH = "contracts/covenant.py"
M = S.load_contract(CONTRACT_PATH)
SOURCE = pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8")
DEPLOY = pathlib.Path("DEPLOY.md").read_text(encoding="utf-8")
SUBMISSION = pathlib.Path("SUBMISSION.md").read_text(encoding="utf-8")
README = pathlib.Path("README.md").read_text(encoding="utf-8")
CONTRACTS = pathlib.Path("CONTRACTS.md").read_text(encoding="utf-8")

A = "0x" + "a1" * 20          # the lender
B = "0x" + "b2" * 20          # the borrower

# -- the arguments, character for character as DEPLOY.md gives them ----------

LABEL0 = "Harbour Logistics term loan"
CONDITIONS0 = ("a cash balance of at least 2 million EUR at quarter end|"
               "audited annual accounts delivered within 90 days of year end|"
               "the vessel fleet insured against total loss")
CURE0 = 1
TAIL = (" Audited annual accounts for the last financial year were delivered within"
        " 90 days of year end. The vessel fleet is insured against total loss.")
CASH = ("2.4", "1.7", "2.2", "1.6", "1.5")
REPORTS0 = ["Compliance report %d: the cash balance at quarter end was %s million EUR."
            % (k + 1, CASH[k]) + TAIL for k in range(5)]
# what DEPLOY.md expects the model to read in each report, frozen order
READINGS0 = ("met|met|met", "breached|met|met", "met|met|met",
             "breached|met|met", "breached|met|met")

LABEL1 = "Harbour Logistics revolving credit"
CONDITIONS1 = "a cash balance of at least 1 million EUR at quarter end"
CURE1 = 2
REPORT1 = "Compliance report 1: the cash balance at quarter end was 0.8 million EUR."
READING1 = "breached"


def in_doc(value, doc):
    """A value as the document writes it: in backticks, pipes escaped inside a
    table and bare outside one."""
    v = str(value)
    return ("`%s`" % v) in doc or ("`%s`" % v.replace("|", "\\|")) in doc


def mocks_for_facility_0():
    names = CONDITIONS0.split("|")
    out = {}
    for body, forward in zip(REPORTS0, READINGS0):
        reverse = "|".join(reversed(forward.split("|")))
        out[M.build_prompt(LABEL0, names, body, 3)] = {"readings": forward, "because": "demo"}
        out[M.build_prompt(LABEL0, list(reversed(names)), body, 3)] = \
            {"readings": reverse, "because": "demo"}
    out[M.build_prompt(LABEL1, [CONDITIONS1], REPORT1, 1)] = {"readings": READING1, "because": "demo"}
    return out


def as_(who, c, method, *args):
    S.set_sender(who)
    try:
        return S.call(c, method, *args)
    finally:
        S.set_sender(A)


@pytest.fixture(scope="module")
def run():
    """DEPLOY.md, steps 1 to 15, with a snapshot at every point it checks."""
    S.set_mocks(leader_prompts=mocks_for_facility_0())
    c = S.deploy(CONTRACT_PATH)
    seen = {}
    as_(A, c, "open", LABEL0, CONDITIONS0, CURE0, B)                   # 1
    for k in range(5):                                                  # 2 to 11
        as_(B, c, "report", 0, REPORTS0[k])
        as_(A if k % 2 == 0 else B, c, "judge", 0)                      # either account
        seen["report", k] = c.get_report(k)
        seen["conditions0", k] = c.conditions_of(0)["conditions"]
        seen["facility0", k] = c.facility(0)
    as_(A, c, "open", LABEL1, CONDITIONS1, CURE1, B)                   # 12
    as_(B, c, "report", 1, REPORT1)                                     # 13
    as_(B, c, "judge", 1)                                               # 14
    seen["report", 5] = c.get_report(5)
    seen["conditions1", "judged"] = c.conditions_of(1)["conditions"][0]
    as_(A, c, "waive", 1, 0)                                            # 15
    seen["conditions1", "waived"] = c.conditions_of(1)["conditions"][0]
    return c, seen


class TestRunbook:
    def test_every_argument_is_the_one_deploy_md_gives(self):
        for value in (LABEL0, CONDITIONS0, CURE0, LABEL1, CONDITIONS1, CURE1, REPORT1,
                      *REPORTS0):
            assert in_doc(value, DEPLOY), value

    def test_the_methods_run_are_the_methods_deploy_md_names(self):
        for method in ("open", "report", "judge", "waive"):
            assert "| `%s` |" % method in DEPLOY
        assert "Fifteen writes" in DEPLOY

    def test_checkpoint_1_every_covenant_kept(self, run):
        _, seen = run
        r = seen["report", 0]
        assert r["transitions"] == "kept|kept|kept" and in_doc(r["transitions"], DEPLOY)
        assert r["states_after"] == "compliant|compliant|compliant"
        assert in_doc(r["states_after"], DEPLOY)
        assert seen["facility0", 0]["pending"] == 0

    def test_checkpoint_2_the_cash_covenant_broken(self, run):
        _, seen = run
        r = seen["report", 1]
        assert r["transitions"] == "broken|kept|kept" and in_doc(r["transitions"], DEPLOY)
        assert r["states_after"] == "breach|compliant|compliant"
        assert in_doc(r["states_after"], DEPLOY)
        c0 = seen["conditions0", 1][0]
        assert (c0["state"], c0["remaining"], c0["breaches"]) == ("breach", 1, 1)
        assert seen["facility0", 1]["status"] == "active"

    def test_report_3_cures_it(self, run):
        _, seen = run
        assert seen["report", 2]["transitions"] == "cured|kept|kept"
        c0 = seen["conditions0", 2][0]
        assert (c0["state"], c0["remaining"], c0["cures"]) == ("compliant", 0, 1)

    def test_report_4_breaks_it_again(self, run):
        _, seen = run
        assert seen["report", 3]["transitions"] == "broken|kept|kept"
        c0 = seen["conditions0", 3][0]
        assert (c0["state"], c0["remaining"], c0["breaches"]) == ("breach", 1, 2)

    def test_checkpoint_3_unremedied_and_the_default(self, run):
        _, seen = run
        r = seen["report", 4]
        assert r["transitions"] == "unremedied|kept|kept" and in_doc(r["transitions"], DEPLOY)
        assert r["states_after"] == "default|compliant|compliant"
        f = seen["facility0", 4]
        assert f["status"] == "defaulted" and f["defaulted"] is True
        assert f["defaulted_condition"] == 0 and f["defaulted_report"] == 4

    def test_the_revolving_credit_breach_and_waiver(self, run):
        c, seen = run
        r = seen["report", 5]
        assert r["transitions"] == "broken" and r["states_after"] == "breach"
        j = seen["conditions1", "judged"]
        assert (j["state"], j["remaining"], j["breaches"]) == ("breach", 2, 1)
        w = seen["conditions1", "waived"]
        assert (w["state"], w["remaining"], w["waivers"]) == ("compliant", 0, 1)
        assert c.facility(1)["status"] == "active"

    def test_the_reads_table(self, run):
        c, _ = run
        assert c.count() == 2 and c.report_count() == 6
        assert c.status(0) == "defaulted" and c.in_default(0) is True
        assert c.facility(0) == {
            "label": LABEL0, "lender": A, "borrower": B, "status": "defaulted", "cure": 1,
            "conditions": 3, "reports": 5, "judged": 5, "pending": 0, "defaulted": True,
            "defaulted_condition": 0, "defaulted_report": 4,
        }
        rows = c.conditions_of(0)["conditions"]
        assert [(r["state"], r["remaining"], r["breaches"], r["cures"], r["waivers"]) for r in rows] == \
            [("default", 0, 2, 1, 0), ("compliant", 0, 0, 0, 0), ("compliant", 0, 0, 0, 0)]
        reports = c.reports_of(0)["reports"]
        assert [r["seq"] for r in reports] == [1, 2, 3, 4, 5]
        assert [r["transitions"] for r in reports] == [
            "kept|kept|kept", "broken|kept|kept", "cured|kept|kept",
            "broken|kept|kept", "unremedied|kept|kept"]
        for t in {r["transitions"] for r in reports}:
            assert in_doc(t, DEPLOY), t
        r4 = c.get_report(4)
        assert r4["transitions"] == "unremedied|kept|kept"
        assert r4["states_after"] == "default|compliant|compliant"
        assert r4["reason_is_leader_supplied"] is True
        assert c.status(1) == "active" and c.in_default(1) is False
        f1 = c.facility(1)
        assert (f1["status"], f1["cure"], f1["conditions"], f1["reports"], f1["judged"],
                f1["pending"], f1["defaulted"]) == ("active", 2, 1, 1, 1, 0, False)
        k = c.conditions_of(1)["conditions"][0]
        assert (k["state"], k["remaining"], k["breaches"], k["cures"], k["waivers"]) == \
            ("compliant", 0, 1, 0, 1)
        assert c.may_report(0, B) is False
        assert c.may_report(1, B) is True
        assert c.may_report(1, A) is False
        for phrase in ("`defaulted_report 4`", "`reports 5`", "`judged 5`", "`cure 2`",
                       "`waivers 1`", "`breaches 2`", "`2`", "`6`"):
            assert phrase in DEPLOY, phrase

    def test_submission_md_claims_what_the_run_produces(self, run):
        c, seen = run
        claims = {
            "kept|kept|kept": seen["report", 0]["transitions"],
            "broken|kept|kept": seen["report", 1]["transitions"],
            "cured|kept|kept": seen["report", 2]["transitions"],
            "unremedied|kept|kept": seen["report", 4]["transitions"],
            "broken": seen["report", 5]["transitions"],
        }
        for claim, actual in claims.items():
            assert in_doc(claim, SUBMISSION), claim
            assert claim == actual
        assert seen["report", 3]["transitions"] == "broken|kept|kept"
        for phrase, ok in (
            ("`remaining 1`", seen["conditions0", 1][0]["remaining"] == 1),
            ("`cures 1`", seen["conditions0", 2][0]["cures"] == 1),
            ("`breaches 2`", seen["conditions0", 3][0]["breaches"] == 2),
            ("`defaulted`", c.facility(0)["status"] == "defaulted"),
            ("`defaulted_condition 0`", c.facility(0)["defaulted_condition"] == 0),
            ("`defaulted_report 4`", c.facility(0)["defaulted_report"] == 4),
            ("`remaining 2`", seen["conditions1", "judged"]["remaining"] == 2),
            ("`waivers 1`", seen["conditions1", "waived"]["waivers"] == 1),
        ):
            assert phrase in SUBMISSION, phrase
            assert ok, phrase
        assert "facility 0 frozen: three conditions, a cure window of one report" in SUBMISSION
        assert "facility 1 frozen: one condition, a cure window of two reports" in SUBMISSION


# ===========================================================================
# The documents, held to the code as it stands.
# ===========================================================================

def code_blocks(doc, lang="python"):
    return re.findall(r"```%s\n(.*?)```" % lang, doc, re.S)


def notes():
    return SUBMISSION.split("## Notes", 1)[1].split("```", 2)[1].strip("\n")


class TestDocuments:
    def test_every_function_the_docs_quote_is_the_source_as_it_stands(self):
        quoted = [b for doc in (README, CONTRACTS) for b in code_blocks(doc)
                  if b.lstrip().startswith("def ")]
        assert quoted, "no quoted function found"
        for block in quoted:
            assert block.strip("\n") in SOURCE, "drifted from the contract:\n" + block

    def test_the_caps_table_matches_the_contract(self):
        rows = re.findall(r"^\| `((?:MAX|MIN)_\w+)` \| (\d+)", CONTRACTS, re.M)
        assert len(rows) >= 9
        for name, value in rows:
            assert getattr(M, name) == int(value), name

    def test_the_state_machine_table_matches_transition(self):
        rows = re.findall(r"^\| `(compliant|breach)` \| `(met|breached|unstated)` \| `(\w+)` \|",
                          README, re.M)
        assert len(rows) == 6
        for state, token, want in rows:
            assert M.transition(state, token) == want, (state, token)

    def test_the_consuming_contract_snippet_compares_addresses_case_insensitively(self):
        block = [b for b in code_blocks(README) if "contract_interface" in b][0]
        assert ".lower()" in block and "in_default" in block

    def test_the_notes_fit_the_portal_box(self):
        n = len(notes())
        print("Notes: %d characters" % n)
        assert 0 < n <= 1000

    def test_the_notes_carry_no_address_and_lean_on_commas(self):
        text = notes()
        assert not re.search(r"0x[0-9a-fA-F]{6,}", text) and "{address}" not in text
        assert text.count(",") > 3 * text.count(".")

    def test_the_title(self):
        title = SUBMISSION.split("## Title", 1)[1].split("```", 2)[1].strip("\n")
        assert title == "Covenant: a breach is cured within the window or it becomes a default"

    def test_the_readme_carries_the_measured_markers(self):
        for name in ("tests", "mutations"):
            assert "<!-- measured:%s -->" % name in README
            assert "<!-- /measured:%s -->" % name in README
