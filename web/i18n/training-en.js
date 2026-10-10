// Practice-shop exercises in plain English. Each exercise: the story (the problem), its steps, the checks, and one thing to remember.
// {...} is filled from the exercise's made-up data.
export default {
  return: {
    icon: 'return', title: 'A fridge comes back faulty',
    story: '{customer} brought back the fridge she bought today (invoice {number}, {total}). The door does not close properly. She wants her money back.',
    steps: [
      'Sign in as {user}, password {password}.',
      'Open Sales and click invoice {number}.',
      'Click Return, choose the fridge, set its condition to Damaged: to repair, keep the refund in cash, and write the reason.',
      'The program asks for a manager to approve: type {approver} and password {password}.',
      'Come back here from Help and click Check my work.'],
    checks: { returned: 'A return was recorded for the invoice', damaged: 'The fridge was recorded as damaged (not back on sale)',
      approved: 'A manager approved the return (not the cashier alone)', cash: 'The money went back in cash from the drawer' },
    tip: 'A damaged item never goes back on sale, and a return needs a manager so a cashier cannot pay money out alone.',
  },
  drawer: {
    icon: 'cash', title: 'The drawer is 15 pounds short',
    story: 'Shift {number} started with 500 pounds and sold for cash. The drawer should hold {expected} but you counted {physical}. The cashier says he paid {missing} for tea and coffee from the drawer and forgot to write it down.',
    steps: [
      'Sign in as {user}, password {password}.',
      'Open Cash and shift, click Expense, and record {missing} (hospitality) with the note tea and coffee.',
      'Click Close shift and type {physical} in Counted. The difference must be zero.',
      'Close the shift, come back here and click Check my work.'],
    checks: { expense: 'The expense was recorded ({missing})', closed: 'The shift was closed', exact: 'The difference is zero: the drawer holds what it should' },
    tip: 'A shortage is never hidden: if money left, record it with its reason before closing, not after.',
  },
  count: {
    icon: 'clipboard', title: 'The shelf count is off',
    story: 'On the shelf at {place} you counted {physical} of {product}, but the system says {expected}. You want the books to match what is really there.',
    steps: [
      'Sign in as {user}, password {password}.',
      'Open Stock and shelves, then Count, choose {place} and click Start count.',
      'Type {physical} next to {product}.',
      'Click Close count and write the reason (for example: missing from the shelf).',
      'Come back here and click Check my work.'],
    checks: { counted: 'Counted {physical}', closed: 'The count was closed', settled: 'The balance was settled (minus {missing})' },
    tip: 'A count never erases anything: it adds an adjustment with its reason, and the owner can see it.',
  },
  discount: {
    icon: 'eye', title: 'A big discount to look at',
    story: 'Today the cashier gave {pct}% off ({given}) on invoice {number} ({product}). A manager ({approver_name}) approved it at the counter. As the owner, you decide whether it was fine.',
    steps: [
      'Sign in as {user}, password {password}.',
      "Open Owner's eye. The discount on invoice {number} is listed there with who gave it and who approved it.",
      'Click Seen and write your note: why it was fine, or what you will say to them.',
      'Come back here and click Check my work.'],
    checks: { seen: "The discount was marked as seen in the Owner's eye", noted: 'You wrote your own note (not just a tick)' },
    tip: 'Marking something as seen never changes the money. It only records that you looked, and what you thought.',
  },
};
