"""Integration tests, run against GenLayer Studio with gltest.

    pip install genlayer-test
    GENLAYER_STUDIO=1 gltest --network studionet tests/test_integration.py

They are opt in: without GENLAYER_STUDIO set they skip, so that
`pytest tests/ -q` stays clean on a machine that has genlayer-test
installed but no Studio to talk to.

These are slower than the other suites and they prove something different:
that the contract deploys, that storage round-trips, that the linked walk holds
on a real runtime, and that the deterministic gates fire.

Everything here exercises the deterministic half, which needs no inference: a
facility opens with a frozen catalogue, a report lands before it is judged, the
authority rules fire, refusals are clean. The judging path costs two prompts
per node and belongs in a manual Studio run; see DEPLOY.md.
"""

import os

import pytest

# gltest is only needed for this file. Skip cleanly when it is absent so that
# `pytest tests/` works out of the box on a machine with nothing installed but
# pytest, and still runs everything else.
gltest = pytest.importorskip(
    "gltest",
    reason="integration tests need genlayer-test and a running Studio: "
           "pip install genlayer-test, then GENLAYER_STUDIO=1 gltest",
)
from gltest import get_contract_factory, get_accounts        # noqa: E402
from gltest.assertions import tx_execution_succeeded         # noqa: E402


# The second half of the same guard, and it is the half that bites.
#
# importorskip above covers "genlayer-test is not installed". It does NOT cover
# "genlayer-test IS installed and there is no Studio to talk to", which is the
# common case for anybody who reviews GenLayer contracts: the plugin loads,
# collects this file, and every test in it fails on a connection error rather
# than skipping. So the gate is explicit. These tests need a live Studio, and
# you say so.
if not os.environ.get("GENLAYER_STUDIO"):
    pytest.skip(
        "integration tests run against a live GenLayer Studio and are opt in: "
        "set GENLAYER_STUDIO=1 to enable them. Everything else runs offline "
        "with pytest tests/ -q",
        allow_module_level=True,
    )


LABEL = "Harbour Logistics term loan"
CONDITIONS = ("a cash balance of at least 2 million EUR at quarter end|"
              "audited annual accounts delivered within 90 days of year end|"
              "the vessel fleet insured against total loss")
REPORT = ("Compliance report 1: the cash balance at quarter end was 2.4 million EUR. "
          "Audited annual accounts for the last financial year were delivered within "
          "90 days of year end. The vessel fleet is insured against total loss.")


def same(a, b):
    """Every address a view returns is the EIP-55 checksummed string on chain."""
    return str(a).lower() == str(b).lower()


class TestCovenant:
    """The deterministic half on a real runtime. Two accounts, because the
    borrower must differ from the lender."""

    @pytest.fixture
    def two(self):
        accounts = get_accounts()
        if len(accounts) < 2:
            pytest.skip("needs two configured accounts: a lender and a borrower")
        return accounts[0], accounts[1]

    @pytest.fixture
    def contract(self, two):
        lender, _ = two
        factory = get_contract_factory(contract_file_path="covenant.py")
        return factory.deploy(args=[], account=lender)

    def test_a_facility_opens_with_a_frozen_catalogue(self, contract, two):
        lender, borrower = two
        assert tx_execution_succeeded(contract.open(args=[LABEL, CONDITIONS, 1, borrower.address]))
        f = contract.facility(args=[0])
        assert f["status"] == "active" and f["cure"] == 1 and f["conditions"] == 3
        assert same(f["lender"], lender.address) and same(f["borrower"], borrower.address)
        names = [c["name"] for c in contract.conditions_of(args=[0])["conditions"]]
        assert names[0] == "a cash balance of at least 2 million EUR at quarter end"

    def test_a_report_lands_before_it_is_judged(self, contract, two):
        _, borrower = two
        contract.open(args=[LABEL, CONDITIONS, 1, borrower.address])
        assert tx_execution_succeeded(contract.connect(borrower).report(args=[0, REPORT]))
        f = contract.facility(args=[0])
        assert f["reports"] == 1 and f["judged"] == 0 and f["pending"] == 1
        assert contract.get_report(args=[0])["judged"] is False

    def test_a_fragment_is_refused(self, contract, two):
        _, borrower = two
        contract.open(args=[LABEL, CONDITIONS, 1, borrower.address])
        with pytest.raises(Exception):
            contract.connect(borrower).report(args=[0, "short"])

    def test_duplicate_conditions_are_refused(self, contract, two):
        _, borrower = two
        with pytest.raises(Exception):
            contract.open(args=[LABEL, "alpha|alpha", 1, borrower.address])

    def test_a_cure_window_above_three_is_refused(self, contract, two):
        _, borrower = two
        with pytest.raises(Exception):
            contract.open(args=[LABEL, CONDITIONS, 4, borrower.address])

    def test_the_lender_cannot_be_the_borrower(self, contract, two):
        lender, _ = two
        with pytest.raises(Exception):
            contract.open(args=[LABEL, CONDITIONS, 1, lender.address])

    def test_an_unknown_facility_is_refused(self, contract):
        with pytest.raises(Exception):
            contract.facility(args=[9])

    def test_a_negative_id_does_not_return_the_newest_row(self, contract, two):
        # Python accepts -1 and hands back the last row, correctly formatted,
        # with nothing failing anywhere.
        _, borrower = two
        contract.open(args=[LABEL, CONDITIONS, 1, borrower.address])
        with pytest.raises(Exception):
            contract.facility(args=[-1])


class TestAuthority:
    """The authorisation rules, against a real runtime.

    These matter more than the rest of this file. tests/glsim.py models
    gl.message.sender_address with a variable a test can set; a node derives it
    from a signature. A rule that holds in the simulator and not on chain would
    be invisible to every other test here.
    """

    @pytest.fixture
    def three(self):
        accounts = get_accounts()
        if len(accounts) < 3:
            pytest.skip("needs three configured accounts: lender, borrower, stranger")
        return accounts[0], accounts[1], accounts[2]

    @pytest.fixture
    def contract(self, three):
        lender, borrower, _ = three
        factory = get_contract_factory(contract_file_path="covenant.py")
        c = factory.deploy(args=[], account=lender)
        c.open(args=[LABEL, CONDITIONS, 1, borrower.address])
        return c

    def test_only_the_borrower_may_report(self, contract, three):
        lender, borrower, stranger = three
        with pytest.raises(Exception):
            contract.connect(stranger).report(args=[0, REPORT])
        with pytest.raises(Exception):
            contract.connect(lender).report(args=[0, REPORT])
        assert tx_execution_succeeded(contract.connect(borrower).report(args=[0, REPORT]))
        assert same(contract.get_report(args=[0])["by"], borrower.address)

    def test_only_the_lender_may_close(self, contract, three):
        _, borrower, stranger = three
        for who in (borrower, stranger):
            with pytest.raises(Exception):
                contract.connect(who).close(args=[0])
        assert tx_execution_succeeded(contract.close(args=[0]))
        assert contract.status(args=[0]) == "closed"

    def test_close_is_refused_while_a_report_is_unjudged(self, contract, three):
        _, borrower, _ = three
        contract.connect(borrower).report(args=[0, REPORT])
        with pytest.raises(Exception):
            contract.close(args=[0])

    def test_nobody_may_waive_a_condition_that_is_not_in_breach(self, contract, three):
        _, borrower, stranger = three
        for who in (borrower, stranger):
            with pytest.raises(Exception):
                contract.connect(who).waive(args=[0, 0])
        with pytest.raises(Exception):
            contract.waive(args=[0, 0])

    def test_may_report_answers_what_report_enforces(self, contract, three):
        lender, borrower, stranger = three
        assert contract.may_report(args=[0, borrower.address]) is True
        assert contract.may_report(args=[0, lender.address]) is False
        assert contract.may_report(args=[0, stranger.address]) is False
        assert contract.may_report(args=[0, "not-an-address"]) is False

    def test_an_address_is_matched_by_value_not_by_spelling(self, contract, three):
        """An Address is 20 raw bytes on chain, so case carries no meaning."""
        _, borrower, _ = three
        upper = "0x" + borrower.address[2:].upper()
        assert contract.may_report(args=[0, upper]) is True
        assert contract.may_report(args=[0, borrower.address.lower()]) is True
