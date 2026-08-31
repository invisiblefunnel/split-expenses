"""Replay the conversation the README screenshots show, as arithmetic.

The screenshots are rendered from hand-written HTML (docs/examples/chat.html),
so nothing else stops the numbers in them from drifting away from what the
skill would really produce. Every balance table in the four pictures is
repeated below, and the settlement is the solver's own answer rather than a
transcribed one. Amounts are in cents, the indivisible unit the table is
kept in.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOLVER_PATH = ROOT / "skills" / "split-expenses" / "scripts" / "settle.py"

EVERYONE = ("You", "Brand", "Cooper", "Doyle")


def expense(payer, total, shares):
    """Balance movements for one expense: the payer is out `total`, sharers owe."""

    if sum(shares.values()) != total:
        raise AssertionError(f"shares do not add up to {total}")
    deltas = {participant: -share for participant, share in shares.items()}
    deltas[payer] = deltas.get(payer, 0) + total
    return deltas


def payment(payer, payee, amount):
    """Balance movements for money that actually changed hands."""

    return {payer: amount, payee: -amount}


def combine(*movements):
    merged = {}
    for movement in movements:
        for participant, delta in movement.items():
            merged[participant] = merged.get(participant, 0) + delta
    return merged


def undo(movement):
    return {participant: -delta for participant, delta in movement.items()}


# €92.00 of food does not divide by three. The skill does not say who absorbs
# the difference, so this is only one valid outcome; what the tests check is
# that the shares stay even and still add up.
FOOD_SHARES = {"You": 3067, "Brand": 3067, "Cooper": 3066}

# The cruise is recorded at €280.00 and later corrected to €300.00. A
# correction re-splits the original expense rather than adding a second one,
# which is exactly undo-then-reapply.
CRUISE_AT_280 = expense("Doyle", 28000, dict.fromkeys(EVERYONE, 7000))
CRUISE_AT_300 = expense("Doyle", 30000, dict.fromkeys(EVERYONE, 7500))

# Each step is what the conversation decides, followed by the table the
# assistant then displayed. The two are only allowed to agree.
STEPS = [
    (
        "Apartment €690.00, You paid, three ways",
        expense("You", 69000, {"You": 23000, "Brand": 23000, "Cooper": 23000}),
        {"You": 46000, "Brand": -23000, "Cooper": -23000},
    ),
    (
        "Receipt €124.00, Brand paid: €32.00 of wine two ways, €92.00 three ways",
        expense(
            "Brand",
            12400,
            {
                "You": 1600 + FOOD_SHARES["You"],
                "Brand": 1600 + FOOD_SHARES["Brand"],
                "Cooper": FOOD_SHARES["Cooper"],
            },
        ),
        {"You": 41333, "Brand": -15267, "Cooper": -26066},
    ),
    (
        "Seine cruise €280.00, Doyle paid, four ways — Doyle joins the roster",
        CRUISE_AT_280,
        {"You": 34333, "Brand": -22267, "Cooper": -33066, "Doyle": 21000},
    ),
    (
        "Louvre €66.00, You paid, three ways — Brand sat this one out",
        expense("You", 6600, {"You": 2200, "Cooper": 2200, "Doyle": 2200}),
        {"You": 38733, "Brand": -22267, "Cooper": -35266, "Doyle": 18800},
    ),
    (
        "Taxi to CDG €56.00, Cooper paid, four ways",
        expense("Cooper", 5600, dict.fromkeys(EVERYONE, 1400)),
        {"You": 37333, "Brand": -23667, "Cooper": -31066, "Doyle": 17400},
    ),
    (
        "Correction: the cruise was €300.00, not €280.00",
        combine(undo(CRUISE_AT_280), CRUISE_AT_300),
        {"You": 36833, "Brand": -24167, "Cooper": -31566, "Doyle": 18900},
    ),
    (
        "Cooper handed You €100.00 in cash",
        payment("Cooper", "You", 10000),
        {"You": 26833, "Brand": -24167, "Cooper": -21566, "Doyle": 18900},
    ),
]

# The three payment rows under "Settle up — 3 payments".
SETTLEMENT = [
    ("Brand", "You", 24167),
    ("Cooper", "You", 2666),
    ("Cooper", "Doyle", 18900),
]


def replay():
    """Yield (description, balances) for the table shown after each message."""

    balances = {}
    for description, movement, _ in STEPS:
        balances = combine(balances, movement)
        yield description, balances


class ExampleConversationTest(unittest.TestCase):
    def tables(self):
        return [balances for _, balances in replay()]

    def test_tables_match_the_screenshots(self):
        for (description, balances), (_, _, shown) in zip(replay(), STEPS):
            with self.subTest(description):
                self.assertEqual(balances, shown)

    def test_every_table_sums_to_zero(self):
        for description, balances in replay():
            with self.subTest(description):
                self.assertEqual(sum(balances.values()), 0)

    def test_the_roster_grows_by_itself(self):
        before, after = self.tables()[1], self.tables()[2]
        self.assertNotIn("Doyle", before, "Doyle has not taken a share yet")
        self.assertIn("Doyle", after, "paying for the cruise puts Doyle on the roster")
        # Joining costs the other three a share of the cruise and nothing else.
        for participant in ("You", "Brand", "Cooper"):
            self.assertEqual(before[participant] - after[participant], 7000)

    def test_sitting_one_expense_out_keeps_you_on_the_roster(self):
        before, after = self.tables()[2], self.tables()[3]
        self.assertEqual(before["Brand"], after["Brand"], "Brand skipped the Louvre")
        self.assertIn("Brand", after, "skipping an expense is not leaving the group")

    def test_a_correction_only_re_splits_the_expense_it_names(self):
        before, after = self.tables()[4], self.tables()[5]
        moved = {p: after[p] - before[p] for p in EVERYONE}
        self.assertEqual(moved, combine(undo(CRUISE_AT_280), CRUISE_AT_300))
        # €20.00 more on the cruise: €5.00 onto each of the four shares.
        self.assertEqual(
            moved, {"You": -500, "Brand": -500, "Cooper": -500, "Doyle": 1500}
        )

    def test_the_food_shares_are_even_and_add_up(self):
        shares = list(FOOD_SHARES.values())
        self.assertEqual(sum(shares), 9200)
        self.assertLessEqual(max(shares) - min(shares), 1)

    def test_settlement_is_the_solvers_own_answer(self):
        final = self.tables()[-1]
        request = {
            "balances": [
                {"participant": participant, "amount": str(amount)}
                for participant, amount in final.items()
            ]
        }
        result = subprocess.run(
            [sys.executable, str(SOLVER_PATH)],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            check=True,
        )
        transfers = [
            (transfer["from"], transfer["to"], int(transfer["amount"]))
            for transfer in json.loads(result.stdout)["transfers"]
        ]
        self.assertEqual(transfers, SETTLEMENT)


if __name__ == "__main__":
    unittest.main()
