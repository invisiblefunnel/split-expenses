# The settlement solver

`skills/split-expenses/scripts/settle.py` — the exact minimum-transfer
settlement solver bundled with the split-expenses skill. Stdlib only, no
dependencies, Python 3.9 or newer.

It implements one pure transformation:

```text
zero-sum net balance vector -> minimum-transfer settlement plan
```

It never sees expenses, currencies, rounding policy, nicknames, or history.
The conversational layer in `skills/split-expenses/SKILL.md` owns all of that
and sends this program one homogeneous balance vector.

## Contract

One JSON request on stdin, one JSON response on stdout. Amounts are integer
strings in a single caller-defined indivisible unit — the solver does not know
whether a unit is a cent, a yen, or a point.

```console
$ echo '{"balances":[{"participant":"You","amount":"667"},{"participant":"Brand","amount":"-334"},{"participant":"Cooper","amount":"-333"}]}' | python3 skills/split-expenses/scripts/settle.py
{"transfers":[{"from":"Brand","to":"You","amount":"334"},{"from":"Cooper","to":"You","amount":"333"}]}
```

Transfers are returned in a deterministic order: ties are broken by input
order, so the same request always produces the same plan. An empty
`transfers` array means no payments are needed.

The program takes no command-line arguments and reads only stdin. Passing an
argument, or leaving stdin attached to a terminal, is an error rather than a
prompt or a hang.

## What it validates

Only what the algorithm requires:

- the request is an object containing exactly `balances`;
- each entry contains exactly `participant` and `amount`;
- participant labels are non-empty and unique;
- amounts are base-10 integer strings of at most 1000 digits; and
- the amounts sum to zero.

It does not judge the truth, fairness, or denomination of the balances.
Zero-balance rows are accepted, ignored, and do not count toward the capacity
limit.

The digit bound exists so that an oversized amount is reported as bad input
rather than as an internal fault: CPython refuses to convert integer strings
beyond 4300 digits, on every version this supports.

## Errors

Errors are written to stderr as one JSON object, never to stdout:

```json
{"error":{"code":"not_zero_sum","message":"balance amounts must sum to zero","details":{"sum":"1"}}}
```

`details` is present only when there is something useful to report.

| Exit | Code | Meaning |
| ---: | --- | --- |
| 0 | — | settlement plan on stdout |
| 2 | `invalid_input` | malformed request, bad amount, duplicate label, or arguments passed |
| 2 | `not_zero_sum` | balances do not sum to zero |
| 2 | `capacity_exceeded` | more than 20 non-zero participants |
| 1 | `invariant_failure` | internal failure; no plan is emitted |

An unexpected internal failure still leaves one JSON error object on stderr
and exit status 1 — never a traceback, and never partial output on stdout.
That is why the top level catches every exception, and why `ruff.toml` does
not select `BLE001` or `TRY`.

## Guarantees

Every plan is verified before it is printed. Transfers run directly from a
debtor to a creditor, never exceed either side's remaining position, are
positive and never self-directed, preserve total value, and reduce every
residual balance to exactly zero. The transfer count is checked against the
computed optimum. A plan failing any of these is discarded as an
`invariant_failure` rather than emitted.

## Algorithm

Zero-balance participants are dropped first. Every connected settlement
component must itself sum to zero, and a zero-sum component of `k`
participants settles in `k - 1` transfers, so for the `n` remaining:

```text
minimum transfers = n - maximum disjoint zero-sum groups
```

Deciding whether a group settles in `k` transfers is NP-hard in general. That
maximum is nonetheless found exactly, by subset dynamic programming:

```text
bestGroups[mask] = max(bestGroups[mask without one participant])
                   + 1 when sum(mask) is zero
```

The implementation stores that DP as its nested level sets
`L[k] = {mask : bestGroups[mask] >= k}`, one bit per subset, so each level is
built from the previous one by whole-width shift, and, and or steps that
evaluate many subsets per machine word. The zero-sum bitset is assembled by
meeting in the middle — a subset sums to zero exactly when its low half
cancels its high half — so only `2^(n/2)` sums are ever materialized.

Neither a subset-sum array nor parent pointers are stored: an optimal ordering
is reconstructed afterwards from the levels, split wherever its running sum
returns to zero, then matched debtor-to-creditor within each group.

The result is `O(n · 2^n)` bit operations and `O(n · 2^n)` bits. Measured on
CPython 3.14 against the worst case for level count, `n / 2` exactly
cancelling pairs:

| Non-zero participants | Subsets | Working set | Time |
| ---: | ---: | ---: | ---: |
| 20 | 1,048,576 | 4 MiB | 15 ms |
| 22 | 4,194,304 | 21 MiB | 60 ms |
| 24 | 16,777,216 | 91 MiB | 278 ms |

The enforced limit is 20 non-zero participants, checked before anything is
allocated. Beyond it the solver reports `capacity_exceeded` rather than
returning a heuristic plan labelled as minimal.

## A note on the bytes/int split

Levels are computed as Python integers but stored as `bytes`, which looks
inconsistent and is deliberate. Whole-word shift/and/or on big integers is
what makes the DP fast; byte indexing is what keeps the several thousand
membership queries during reconstruction cheap. Measured over a 2^20-bit set,
4000 queries cost 0.52 ms through `bytes` against 47.7 ms through integer
shifts. Collapsing the two representations would dominate the entire solve.

## Tests

The suite lives in `tests/`, and is not part of the shipped skill. From the
repository root:

```bash
python -m unittest discover -s tests -v      # 21 tests
ruff format --check --diff . && ruff check . # ruff 0.16.3, the version CI pins
```

It checks the DP against a direct evaluation of the documented recurrence, and
whole settlements against an exhaustive set-partition oracle. CI runs it on
CPython 3.9 through 3.14, which is why `ruff.toml` targets `py39`: this file
ships as a fixed artifact and runs on whatever interpreter the host provides.
