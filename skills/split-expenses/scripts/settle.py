#!/usr/bin/env python3
"""Calculate an exact minimum-transfer settlement from net balances.

Read one JSON request from stdin and write one JSON response to stdout. All
amounts are integer strings in a caller-defined indivisible unit.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any, TextIO

MAX_NONZERO_PARTICIPANTS = 20

# Bounds every amount so that the input sum and every returned transfer stay
# inside CPython's default integer-to-string limit, and so formatting a
# response can never fail on an otherwise valid request.
MAX_AMOUNT_DIGITS = 1000

# At or below this size every subset sum is enumerated directly; above it the
# zero-sum bitset is assembled by meeting in the middle. Any value of 5 or more
# keeps a half-subset block at least one byte wide, which that path requires.
_DIRECT_SUBSET_SUM_LIMIT = 12

_INTEGER_PATTERN = re.compile(r"[+-]?[0-9]+")

# One transfer: the paying participant's index, the receiving one's, and a
# positive amount.
Transfer = tuple[int, int, int]


class InputError(Exception):
    """A validation failure that should be reported with exit status 2."""

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class InvariantFailure(Exception):
    """A solver invariant failure that should be reported with status 1."""


def _invalid(message: str) -> InputError:
    return InputError("invalid_input", message)


def _parse_request(request: Any) -> list[tuple[str, int]]:
    if not isinstance(request, dict) or set(request) != {"balances"}:
        raise _invalid("request must be an object containing only 'balances'")

    raw_balances = request["balances"]
    if not isinstance(raw_balances, list):
        raise _invalid("'balances' must be an array")

    parsed: list[tuple[str, int]] = []
    seen_participants: set[str] = set()

    for position, raw_balance in enumerate(raw_balances):
        if not isinstance(raw_balance, dict) or set(raw_balance) != {
            "participant",
            "amount",
        }:
            raise _invalid(
                f"balance at index {position} must contain only "
                "'participant' and 'amount'"
            )

        participant = raw_balance["participant"]
        amount_text = raw_balance["amount"]

        if not isinstance(participant, str) or not participant.strip():
            raise _invalid(
                f"participant at index {position} must be a non-empty string"
            )
        if participant in seen_participants:
            raise _invalid(f"participant labels must be unique: {participant!r}")
        if not isinstance(amount_text, str) or not _INTEGER_PATTERN.fullmatch(
            amount_text
        ):
            raise _invalid(
                f"amount at index {position} must be a base-10 integer string"
            )
        if len(amount_text.lstrip("+-")) > MAX_AMOUNT_DIGITS:
            raise _invalid(
                f"amount at index {position} must have at most "
                f"{MAX_AMOUNT_DIGITS} digits"
            )

        seen_participants.add(participant)
        parsed.append((participant, int(amount_text, 10)))

    return parsed


def _subset_sums(values: list[int]) -> list[int]:
    """Return the sum of every subset of `values`, indexed by bit mask."""

    sums = [0]
    for value in values:
        sums += [total + value for total in sums]
    return sums


def _bitset_width(count: int) -> int:
    """Return the byte width of a bitset holding one bit per subset."""

    # Rounded up to a whole byte for the few counts with fewer than 8 subsets.
    return max(1, (1 << count) >> 3)


def _zero_sum_subsets(amounts: list[int]) -> bytes:
    """Return a packed bitset marking every subset that sums to zero."""

    count = len(amounts)

    if count <= _DIRECT_SUBSET_SUM_LIMIT:
        marked = bytearray(_bitset_width(count))
        for subset, total in enumerate(_subset_sums(amounts)):
            if total == 0:
                marked[subset >> 3] |= 1 << (subset & 7)
        return bytes(marked)

    # Meet in the middle. A subset sums to zero exactly when its low half
    # cancels its high half, so each high-half subset selects one precomputed
    # block of low-half subsets. Only 2^(count/2) sums are ever materialized,
    # and the bitset is assembled block-wise instead of subset-by-subset.
    half = count // 2
    block_length = (1 << half) >> 3
    blocks: dict[int, bytearray] = {}

    for subset, total in enumerate(_subset_sums(amounts[:half])):
        block = blocks.get(total)
        if block is None:
            block = blocks[total] = bytearray(block_length)
        block[subset >> 3] |= 1 << (subset & 7)

    cancelling = {total: bytes(block) for total, block in blocks.items()}
    empty_block = bytes(block_length)
    return b"".join(
        cancelling.get(-total, empty_block) for total in _subset_sums(amounts[half:])
    )


def _exclusion_patterns(count: int) -> list[int]:
    """Return, per participant, the bitset of subsets that exclude them."""

    universe = 1 << count
    patterns: list[int] = []

    for participant_index in range(count):
        # Subsets excluding a participant alternate with those including them
        # in runs of 2^i, so each pattern is one run of ones repeatedly doubled
        # to the full width: 0b0011 for i = 1, 0b00001111 for i = 2.
        run = 1 << participant_index
        pattern = (1 << run) - 1
        width = run << 1
        while width < universe:
            pattern |= pattern << width
            width <<= 1
        patterns.append(pattern)

    return patterns


def _add_one_participant(bitset: int, patterns: list[int]) -> int:
    """Return every subset formed by adding one participant to `bitset`."""

    grown = 0
    for participant_index, excluded in enumerate(patterns):
        grown |= (bitset & excluded) << (1 << participant_index)
    return grown


def _close_upward(bitset: int, patterns: list[int]) -> int:
    """Return every superset of every subset in `bitset`."""

    for participant_index, excluded in enumerate(patterns):
        bitset |= (bitset & excluded) << (1 << participant_index)
    return bitset


def _bitset_contains(bitset: bytes, subset: int) -> bool:
    return bool((bitset[subset >> 3] >> (subset & 7)) & 1)


def _compute_group_levels(amounts: list[int]) -> tuple[list[bytes], bytes]:
    """Return the DP levels and the zero-sum bitset for `amounts`.

    A subset can be split into `k` disjoint zero-sum groups exactly when it
    contains `k` pairwise disjoint non-empty zero-sum subsets, so the DP
    ```
    bestGroups[mask] = max(bestGroups[mask without one participant])
                       + 1 when sum(mask) is zero
    ```
    is stored as its nested level sets `L[k] = {mask: bestGroups[mask] >= k}`
    rather than as one entry per subset. Each level is the upward closure of
    the zero-sum subsets that already contain `k - 1` disjoint groups, which
    the whole-word integer operations below evaluate for every subset at once.
    """

    count = len(amounts)
    width = _bitset_width(count)
    zero_sum = _zero_sum_subsets(amounts)
    patterns = _exclusion_patterns(count)

    # The empty subset sums to zero but forms no group.
    zero_sum_groups = int.from_bytes(zero_sum, "little") & ~1
    seeds = zero_sum_groups
    levels: list[bytes] = []

    while seeds:
        level = _close_upward(seeds, patterns)
        levels.append(level.to_bytes(width, "little"))
        seeds = zero_sum_groups & _add_one_participant(level, patterns)

    return levels, zero_sum


def _best_group_count(levels: list[bytes], subset: int) -> int:
    """Return the maximum number of disjoint zero-sum groups within `subset`."""

    group_count = 0
    for level in levels:
        if not _bitset_contains(level, subset):
            break
        group_count += 1
    return group_count


def _reconstruct_groups(
    amounts: list[int], levels: list[bytes], zero_sum: bytes
) -> list[list[int]]:
    """Reconstruct input-order-tied zero-sum groups without parent pointers.

    Both the members of each group and the groups themselves come back in
    ascending participant index order.
    """

    mask = (1 << len(amounts)) - 1
    ordering: list[int] = []

    while mask:
        zero_sum_bonus = 1 if _bitset_contains(zero_sum, mask) else 0
        target = _best_group_count(levels, mask) - zero_sum_bonus

        for participant_index in range(len(amounts)):
            bit = 1 << participant_index
            if mask & bit and _best_group_count(levels, mask ^ bit) == target:
                ordering.append(participant_index)
                mask ^= bit
                break
        else:
            raise InvariantFailure("could not reconstruct an optimal DP path")

    groups: list[list[int]] = []
    current_group: list[int] = []
    running_sum = 0

    for participant_index in ordering:
        current_group.append(participant_index)
        running_sum += amounts[participant_index]
        if running_sum == 0:
            current_group.sort()
            groups.append(current_group)
            current_group = []

    if current_group or len(groups) != len(levels):
        raise InvariantFailure("reconstructed groups do not match the DP optimum")

    groups.sort()
    return groups


def _match_group(group: list[int], amounts: list[int]) -> list[Transfer]:
    """Clear one zero-sum group by walking its two sides in input order."""

    debtors = [index for index in group if amounts[index] < 0]
    creditors = [index for index in group if amounts[index] > 0]

    if not debtors or not creditors:
        raise InvariantFailure("a non-empty zero-sum group lacks one side")

    remaining = {index: abs(amounts[index]) for index in debtors + creditors}
    transfers: list[Transfer] = []
    debtor_position = 0
    creditor_position = 0

    while debtor_position < len(debtors) and creditor_position < len(creditors):
        debtor = debtors[debtor_position]
        creditor = creditors[creditor_position]
        amount = min(remaining[debtor], remaining[creditor])

        if amount <= 0:
            raise InvariantFailure("matcher produced a non-positive transfer")

        transfers.append((debtor, creditor, amount))
        remaining[debtor] -= amount
        remaining[creditor] -= amount

        if remaining[debtor] == 0:
            debtor_position += 1
        if remaining[creditor] == 0:
            creditor_position += 1

    if debtor_position != len(debtors) or creditor_position != len(creditors):
        raise InvariantFailure("matcher left value unsettled inside a group")

    return transfers


def _verify_transfers(
    amounts: list[int], transfers: list[Transfer], expected_count: int
) -> None:
    residuals = amounts.copy()

    for debtor_index, creditor_index, amount in transfers:
        if debtor_index == creditor_index or amount <= 0:
            raise InvariantFailure("transfer is self-directed or non-positive")
        if amounts[debtor_index] >= 0 or amounts[creditor_index] <= 0:
            raise InvariantFailure("transfer is not directly debtor-to-creditor")
        if amount > -residuals[debtor_index] or amount > residuals[creditor_index]:
            raise InvariantFailure("transfer exceeds a remaining position")

        residuals[debtor_index] += amount
        residuals[creditor_index] -= amount

    if len(transfers) != expected_count:
        raise InvariantFailure("transfer count does not match the exact optimum")
    if any(residuals):
        raise InvariantFailure("generated transfers do not clear every balance")


def solve_request(request: Any) -> dict[str, list[dict[str, str]]]:
    parsed = _parse_request(request)
    total = sum(amount for _, amount in parsed)

    if total != 0:
        raise InputError(
            "not_zero_sum",
            "balance amounts must sum to zero",
            {"sum": str(total)},
        )

    nonzero = [(participant, amount) for participant, amount in parsed if amount != 0]
    nonzero_count = len(nonzero)
    if nonzero_count > MAX_NONZERO_PARTICIPANTS:
        raise InputError(
            "capacity_exceeded",
            "exact settlement supports at most "
            f"{MAX_NONZERO_PARTICIPANTS} non-zero participants",
            {
                "limit": MAX_NONZERO_PARTICIPANTS,
                "non_zero_participants": nonzero_count,
            },
        )

    if not nonzero:
        return {"transfers": []}

    participants = [participant for participant, _ in nonzero]
    amounts = [amount for _, amount in nonzero]
    levels, zero_sum = _compute_group_levels(amounts)
    groups = _reconstruct_groups(amounts, levels, zero_sum)

    indexed_transfers: list[Transfer] = []
    for group in groups:
        indexed_transfers.extend(_match_group(group, amounts))

    expected_count = len(amounts) - len(levels)
    _verify_transfers(amounts, indexed_transfers, expected_count)

    return {
        "transfers": [
            {
                "from": participants[debtor_index],
                "to": participants[creditor_index],
                "amount": str(amount),
            }
            for debtor_index, creditor_index, amount in indexed_transfers
        ]
    }


def _write_json(stream: TextIO, value: Any) -> None:
    json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
    stream.write("\n")


def _write_error(stream: TextIO, code: str, message: str, details: Any = None) -> None:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    _write_json(stream, {"error": error})


def run(stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    try:
        try:
            if stdin.isatty():
                raise _invalid("stdin must be a piped JSON request, not a terminal")
            request = json.load(stdin)
        except (json.JSONDecodeError, UnicodeError) as error:
            raise _invalid(
                "stdin must contain exactly one valid JSON request"
            ) from error

        response = solve_request(request)
    except InputError as error:
        _write_error(stderr, error.code, error.message, error.details)
        return 2
    except InvariantFailure as error:
        _write_error(stderr, "invariant_failure", str(error))
        return 1
    except Exception as error:
        _write_error(
            stderr,
            "invariant_failure",
            "unexpected internal solver failure",
            {"exception": f"{type(error).__name__}: {error}"[:200]},
        )
        return 1

    _write_json(stdout, response)
    return 0


def main() -> int:
    arguments = sys.argv[1:]
    if arguments:
        _write_error(
            sys.stderr,
            "invalid_input",
            "settle.py takes no arguments and reads one JSON request on stdin",
            {"arguments": arguments},
        )
        return 2
    return run(sys.stdin, sys.stdout, sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
