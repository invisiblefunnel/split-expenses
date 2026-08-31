---
name: split-expenses
description: Track group expenses and payments in conversation with a visible zero-sum balance table, and settle them with the bundled exact solver. Use when the user records, reviews, updates, or settles shared costs.
---

# Split Expenses

Interpret group expenses from the conversation and keep one current balance table.

## Maintain balances

- Treat the latest **Current balances — CURRENCY** table as the complete current state.
- Use one unique display label per participant. Positive means value owed to the participant; negative means value the participant owes. Require the table to sum to zero.
- Keep one denomination and indivisible unit for the conversation. Display balances as signed values.
- Interpret participants, shares, expenses, and payments from conversational context. Ask for clarification only when a valid zero-sum update cannot be produced.
- After recording an expense or payment, show the complete updated table.

```md
**Current balances — CURRENCY**

| Participant | Balance |
| --- | ---: |
| Unique label | +amount |
| Other label | -amount |
```

## Settle balances

1. Build one request from the latest table for `scripts/settle.py`. Preserve row order and participant labels, and encode balances as integer strings in the table's indivisible unit:

   ```json
   {"balances":[{"participant":"You","amount":"667"},{"participant":"Brand","amount":"-334"},{"participant":"Cooper","amount":"-333"}]}
   ```

2. Run the bundled script with Python 3 and parse its JSON response:

   ```bash
   python3 scripts/settle.py
   ```

3. Display the returned transfers in order and in the table's denomination. An empty `transfers` array means no payments are needed.
4. Show the current table unchanged. Treat the settlement as a proposal and update balances when the user records an actual payment.
5. If the script is unavailable or returns an error, report the error and keep the current table unchanged.
