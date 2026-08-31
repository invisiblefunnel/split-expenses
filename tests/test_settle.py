import contextlib
import importlib.util
import io
import json
import random
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SOLVER_PATH = ROOT / "skills" / "split-expenses" / "scripts" / "settle.py"


def load_solver():
    """Import settle.py by path: it ships as a lone script, not as a package."""

    spec = importlib.util.spec_from_file_location("split_expenses_solver", SOLVER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the settlement solver")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


solver = load_solver()


def request_for(values):
    return {
        "balances": [
            {"participant": f"P{index}", "amount": str(value)}
            for index, value in enumerate(values)
        ]
    }


def reference_best_groups(values):
    """Evaluate the documented subset recurrence directly, one entry per mask."""

    subset_count = 1 << len(values)
    sums = [0] * subset_count
    best = [0] * subset_count

    for mask in range(1, subset_count):
        low = mask & -mask
        sums[mask] = sums[mask ^ low] + values[low.bit_length() - 1]

        best_without_one = 0
        remaining = mask
        while remaining:
            bit = remaining & -remaining
            best_without_one = max(best_without_one, best[mask ^ bit])
            remaining ^= bit

        best[mask] = best_without_one + (1 if sums[mask] == 0 else 0)

    return best, sums


def minimum_transfer_oracle(values):
    """Exhaustively inspect set partitions, independently of the solver DP."""

    if not values:
        return 0

    group_totals = []
    best_group_count = 0

    def visit(position):
        nonlocal best_group_count

        if position == len(values):
            if all(total == 0 for total in group_totals):
                best_group_count = max(best_group_count, len(group_totals))
            return

        if len(group_totals) + (len(values) - position) <= best_group_count:
            return

        value = values[position]
        for group_index in range(len(group_totals)):
            group_totals[group_index] += value
            visit(position + 1)
            group_totals[group_index] -= value

        group_totals.append(value)
        visit(position + 1)
        group_totals.pop()

    visit(0)
    if best_group_count == 0:
        raise AssertionError("zero-sum input had no zero-sum partition")
    return len(values) - best_group_count


class SettlementTests(unittest.TestCase):
    def assert_settlement_invariants(self, request, response):
        original = {
            row["participant"]: int(row["amount"]) for row in request["balances"]
        }
        residual = original.copy()

        for transfer in response["transfers"]:
            payer = transfer["from"]
            recipient = transfer["to"]
            amount = int(transfer["amount"])

            self.assertIn(payer, original)
            self.assertIn(recipient, original)
            self.assertNotEqual(payer, recipient)
            self.assertGreater(amount, 0)
            self.assertLess(original[payer], 0)
            self.assertGreater(original[recipient], 0)
            self.assertLessEqual(amount, -residual[payer])
            self.assertLessEqual(amount, residual[recipient])

            residual[payer] += amount
            residual[recipient] -= amount

        self.assertTrue(all(value == 0 for value in residual.values()))

    def test_documented_example(self):
        request = {
            "balances": [
                {"participant": "You", "amount": "667"},
                {"participant": "Brand", "amount": "-334"},
                {"participant": "Cooper", "amount": "-333"},
            ]
        }

        self.assertEqual(
            solver.solve_request(request),
            {
                "transfers": [
                    {"from": "Brand", "to": "You", "amount": "334"},
                    {"from": "Cooper", "to": "You", "amount": "333"},
                ]
            },
        )

    def test_empty_and_zero_vectors_are_settled(self):
        self.assertEqual(solver.solve_request({"balances": []}), {"transfers": []})
        self.assertEqual(
            solver.solve_request(
                {
                    "balances": [
                        {"participant": "A", "amount": "0"},
                        {"participant": "B", "amount": "-0"},
                        {"participant": "C", "amount": "+0"},
                    ]
                }
            ),
            {"transfers": []},
        )

    def test_zero_rows_do_not_count_toward_capacity(self):
        request = {
            "balances": [
                {"participant": f"Z{index}", "amount": "0"} for index in range(100)
            ]
        }
        self.assertEqual(solver.solve_request(request), {"transfers": []})

    def test_large_integers(self):
        large = 10**120
        request = {
            "balances": [
                {"participant": "A", "amount": str(large)},
                {"participant": "B", "amount": str(-(large - 1))},
                {"participant": "C", "amount": "-1"},
            ]
        }
        response = solver.solve_request(request)
        self.assertEqual(
            response,
            {
                "transfers": [
                    {"from": "B", "to": "A", "amount": str(large - 1)},
                    {"from": "C", "to": "A", "amount": "1"},
                ]
            },
        )
        self.assert_settlement_invariants(request, response)

    def test_multiple_debtors_and_creditors(self):
        request = {
            "balances": [
                {"participant": "A", "amount": "10"},
                {"participant": "B", "amount": "5"},
                {"participant": "C", "amount": "-7"},
                {"participant": "D", "amount": "-8"},
            ]
        }
        response = solver.solve_request(request)
        self.assertEqual(
            response,
            {
                "transfers": [
                    {"from": "C", "to": "A", "amount": "7"},
                    {"from": "D", "to": "A", "amount": "3"},
                    {"from": "D", "to": "B", "amount": "5"},
                ]
            },
        )
        self.assert_settlement_invariants(request, response)

    def test_ties_are_broken_by_input_order(self):
        request = {
            "balances": [
                {"participant": "A", "amount": "5"},
                {"participant": "B", "amount": "5"},
                {"participant": "C", "amount": "-5"},
                {"participant": "D", "amount": "-5"},
            ]
        }
        expected = {
            "transfers": [
                {"from": "C", "to": "A", "amount": "5"},
                {"from": "D", "to": "B", "amount": "5"},
            ]
        }
        self.assertEqual(solver.solve_request(request), expected)
        self.assertEqual(solver.solve_request(request), expected)

    def test_group_levels_are_nested_bitsets_over_subsets(self):
        amounts = [5, -5, 7, -7]
        levels, zero_sum = solver._compute_group_levels(amounts)

        self.assertEqual(len(levels), 2)
        self.assertTrue(all(len(level) == (1 << 4) // 8 for level in levels))
        self.assertEqual(len(zero_sum), (1 << 4) // 8)

        for subset in range(1 << 4):
            memberships = [solver._bitset_contains(level, subset) for level in levels]
            self.assertEqual(memberships, sorted(memberships, reverse=True))

    def test_group_levels_match_the_documented_recurrence(self):
        generator = random.Random(20260818)
        # Covers both the direct and the meet-in-the-middle zero-sum paths.
        for participant_count in (2, 5, solver._DIRECT_SUBSET_SUM_LIMIT + 1, 14):
            for case_index in range(4):
                values = [
                    generator.choice([value for value in range(-6, 7) if value])
                    for _ in range(participant_count - 1)
                ]
                final_value = -sum(values)
                if final_value == 0:
                    continue
                values.append(final_value)

                with self.subTest(count=participant_count, case=case_index):
                    expected_best, expected_sums = reference_best_groups(values)
                    levels, zero_sum = solver._compute_group_levels(values)

                    for subset in range(1 << participant_count):
                        self.assertEqual(
                            solver._best_group_count(levels, subset),
                            expected_best[subset],
                        )
                        self.assertEqual(
                            solver._bitset_contains(zero_sum, subset),
                            expected_sums[subset] == 0,
                        )

    def test_subset_sums_are_indexed_by_bit_mask(self):
        self.assertEqual(solver._subset_sums([]), [0])
        self.assertEqual(solver._subset_sums([3, -5]), [0, 3, -5, -2])

    def test_random_vectors_match_exhaustive_partition_oracle(self):
        generator = random.Random(20260817)

        for case_index in range(200):
            participant_count = generator.randint(2, 8)
            while True:
                values = [
                    generator.choice([value for value in range(-20, 21) if value])
                    for _ in range(participant_count - 1)
                ]
                final_value = -sum(values)
                if final_value != 0:
                    values.append(final_value)
                    break

            with self.subTest(case=case_index, values=values):
                request = request_for(values)
                response = solver.solve_request(request)
                self.assert_settlement_invariants(request, response)
                self.assertEqual(
                    len(response["transfers"]), minimum_transfer_oracle(values)
                )
                self.assertEqual(response, solver.solve_request(request))

    def test_maximum_capacity_input_is_settled_exactly(self):
        generator = random.Random(20260819)
        values = [
            generator.choice([value for value in range(-500, 501) if value])
            for _ in range(solver.MAX_NONZERO_PARTICIPANTS - 1)
        ]
        values.append(-sum(values))
        self.assertNotEqual(values[-1], 0)

        request = request_for(values)
        response = solver.solve_request(request)
        self.assert_settlement_invariants(request, response)
        self.assertEqual(response, solver.solve_request(request))

    def test_twenty_one_nonzero_participants_fail_before_dp(self):
        request = request_for(([1] * 20) + [-20])

        with (
            mock.patch.object(
                solver,
                "_compute_group_levels",
                side_effect=AssertionError("DP must not be entered"),
            ),
            self.assertRaises(solver.InputError) as raised,
        ):
            solver.solve_request(request)

        self.assertEqual(raised.exception.code, "capacity_exceeded")
        self.assertEqual(
            raised.exception.details,
            {"limit": 20, "non_zero_participants": 21},
        )

    def test_validation_failures(self):
        cases = [
            ({}, "invalid_input"),
            ({"balances": [], "extra": True}, "invalid_input"),
            ({"balances": "not-an-array"}, "invalid_input"),
            ({"balances": [{}]}, "invalid_input"),
            (
                {
                    "balances": [
                        {"participant": "", "amount": "0"},
                    ]
                },
                "invalid_input",
            ),
            (
                {
                    "balances": [
                        {"participant": "A", "amount": 0},
                    ]
                },
                "invalid_input",
            ),
            (
                {
                    "balances": [
                        {"participant": "A", "amount": "1.0"},
                    ]
                },
                "invalid_input",
            ),
            (
                {
                    "balances": [
                        {"participant": "A", "amount": "1"},
                        {"participant": "A", "amount": "-1"},
                    ]
                },
                "invalid_input",
            ),
            (
                {
                    "balances": [
                        {"participant": "A", "amount": "1"},
                    ]
                },
                "not_zero_sum",
            ),
        ]

        for request, error_code in cases:
            with self.subTest(request=request):
                with self.assertRaises(solver.InputError) as raised:
                    solver.solve_request(request)
                self.assertEqual(raised.exception.code, error_code)

    def test_amount_digit_limit_is_reported_as_invalid_input(self):
        limit = solver.MAX_AMOUNT_DIGITS
        accepted = request_for([int("9" * limit), -int("9" * limit)])
        self.assert_settlement_invariants(accepted, solver.solve_request(accepted))

        oversized = {
            "balances": [
                {"participant": "A", "amount": "-" + "9" * (limit + 1)},
                {"participant": "B", "amount": "9" * (limit + 1)},
            ]
        }
        with self.assertRaises(solver.InputError) as raised:
            solver.solve_request(oversized)
        self.assertEqual(raised.exception.code, "invalid_input")

    def test_cli_success_writes_only_stdout(self):
        process = subprocess.run(
            [sys.executable, str(SOLVER_PATH)],
            input=json.dumps(request_for([3, -3])),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(process.returncode, 0)
        self.assertEqual(process.stderr, "")
        self.assertEqual(
            json.loads(process.stdout),
            {"transfers": [{"from": "P1", "to": "P0", "amount": "3"}]},
        )

    def test_cli_validation_errors_are_json_on_stderr(self):
        cases = [
            ("not json", "invalid_input"),
            (json.dumps(request_for([1, -2])), "not_zero_sum"),
            (json.dumps(request_for(([1] * 20) + [-20])), "capacity_exceeded"),
        ]

        for request_text, error_code in cases:
            with self.subTest(error_code=error_code):
                process = subprocess.run(
                    [sys.executable, str(SOLVER_PATH)],
                    input=request_text,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(process.returncode, 2)
                self.assertEqual(process.stdout, "")
                self.assertEqual(
                    json.loads(process.stderr)["error"]["code"], error_code
                )

    def test_cli_rejects_arguments_instead_of_waiting_on_stdin(self):
        process = subprocess.run(
            [sys.executable, str(SOLVER_PATH), "--help"],
            input="",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stdout, "")
        error = json.loads(process.stderr)["error"]
        self.assertEqual(error["code"], "invalid_input")
        self.assertEqual(error["details"], {"arguments": ["--help"]})

    def test_interactive_stdin_is_rejected_instead_of_blocking(self):
        class TerminalStdin(io.StringIO):
            def isatty(self):
                return True

        stdout = io.StringIO()
        stderr = io.StringIO()
        status = solver.run(TerminalStdin(""), stdout, stderr)

        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            json.loads(stderr.getvalue())["error"]["code"], "invalid_input"
        )

    def test_unexpected_failure_reports_the_exception_type(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with mock.patch.object(
            solver, "solve_request", side_effect=MemoryError("solver ran out")
        ):
            status = solver.run(io.StringIO('{"balances":[]}'), stdout, stderr)

        self.assertEqual(status, 1)
        self.assertEqual(stdout.getvalue(), "")
        error = json.loads(stderr.getvalue())["error"]
        self.assertEqual(error["code"], "invariant_failure")
        self.assertEqual(error["details"], {"exception": "MemoryError: solver ran out"})

    def test_main_reads_stdin_when_given_no_arguments(self):
        stdout = io.StringIO()
        with (
            mock.patch.object(sys, "argv", ["settle.py"]),
            mock.patch.object(
                sys, "stdin", io.StringIO(json.dumps(request_for([2, -2])))
            ),
            contextlib.redirect_stdout(stdout),
        ):
            status = solver.main()

        self.assertEqual(status, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {"transfers": [{"from": "P1", "to": "P0", "amount": "2"}]},
        )

    def test_internal_invariant_failure_uses_exit_status_one(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with mock.patch.object(
            solver,
            "solve_request",
            side_effect=solver.InvariantFailure("test invariant"),
        ):
            status = solver.run(io.StringIO('{"balances":[]}'), stdout, stderr)

        self.assertEqual(status, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            json.loads(stderr.getvalue())["error"]["code"], "invariant_failure"
        )


if __name__ == "__main__":
    unittest.main()
