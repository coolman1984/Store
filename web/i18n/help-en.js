// Help in plain English: "Guide me" (short steps) and "Solve a problem" (why and what to do). No welcome slideshow.
export default {
  guides: [
    { id: 'sell', icon: 'cart', title: 'Sell to a customer', steps: [
      'Open "Sell" or press F2 anywhere.', 'Scan the barcode or type part of the name and press Enter: the product is in the receipt.',
      'For appliances with a serial number (fridge, washer…), pick or scan the serial on the box.',
      'Press F4 or "Pay" and choose how they pay. For cash, type what the customer gave you: the change shows in big digits.',
      'Print the receipt or send it on WhatsApp, then Enter for the next sale.'] },
    { id: 'instal', icon: 'calendar', title: 'Sell on shop instalments', steps: [
      'Choose the customer at the top of the receipt (add them with name and mobile if new).', 'In payment choose "Shop instalments".',
      'Choose the months, the down payment, the first due date and the guarantor if any.',
      'The program shows the instalment fee and the monthly amount. Agree them with the customer and press "Paid".',
      'Every day "Customers" lists who is due today or late, each with a WhatsApp reminder button.'] },
    { id: 'return', icon: 'return', title: 'Take a return or exchange', steps: [
      'Open "Sales" and find the invoice by number, customer or serial.', 'Open it and press "Return".',
      'Write the quantity coming back and its condition: good goes back to the shelf, damaged goes to "Damaged and repair".',
      'Choose how the money goes back and write the reason. A cashier needs a manager to type their password.',
      'For an exchange: make the return, then a new sale with the other product.'] },
    { id: 'receive', icon: 'truck', title: 'Receive goods from a supplier', steps: [
      'Open "Receive goods".', 'Choose the supplier and the place the goods go to (store or shop).',
      'Add each product with quantity and purchase price; scan the serial of each appliance.',
      'If you paid part now, write it: the rest is recorded on the supplier\'s account.', 'Press "Save". The average cost updates by itself.'] },
    { id: 'prices', icon: 'percent', title: 'Raise a whole brand\'s prices', steps: [
      'Open "Products & prices" and press "Bulk price change".', 'Choose the brand or category and type the percentage (e.g. 7).',
      'Choose the rounding (e.g. to 5 EGP) and the day the new prices start.', 'Press "Preview", check before/after, then "Apply". Old invoices never change.'] },
    { id: 'close', icon: 'lock', title: 'Close the shift at the end of the day', steps: [
      'Open "Cash & shifts".', 'Press "Close shift" and type the count of each note, or the whole amount.',
      'The program shows over or short. If there is a difference, write what happened.',
      'The counted cash goes to the main safe; the owner sees any difference in "Owner\'s eye".'] },
    { id: 'count', icon: 'clipboard', title: 'Count the stock', steps: [
      'Open "Stock & shelves" → "Count".', 'Choose the place and press "Start count": products are listed shelf by shelf.',
      'Type what you really counted; the difference shows at once.', 'Press "Close count" with the reason: stock is adjusted and the owner sees the value.'] },
  ],
  problems: [
    { q: 'The cashier sees "A manager must approve"', a: ['The discount is above the cashier\'s limit, the price is under the minimum, or the customer is over their credit limit.',
      'A manager types their own user name and password on the same screen; the approval is saved on the invoice.', 'To change someone\'s discount limit: Settings → People & permissions.'] },
    { q: 'Saving is refused and a red licence bar shows', a: ['The trial code ended or belongs to another PC.', 'All data is safe: you can open, print, export and back up.',
      'Open Settings → Licence, copy the "Device code", send it to the vendor and paste the new code there.'] },
    { q: 'A product does not show at the counter', a: ['Check it is not hidden in "Products & prices".', 'If it uses serials and all are in the store, move some to the shop first.',
      'If the barcode does not scan, type part of the name or the product code.'] },
    { q: 'The drawer is short at the end of the day', a: ['Open the shift\'s drawer moves: every expense, cash refund and hand-over to the safe is listed.',
      'Card, wallet and InstaPay money never enters the drawer; it is counted apart.', 'If there is still a difference, write it with a clear reason when closing; the owner sees it.'] },
    { q: 'A phone cannot open the program', a: ['The phone must be on the shop\'s Wi-Fi.', 'Settings → Backups shows this PC\'s address: type it in the phone\'s browser.',
      'If Windows asks to allow the program on the network, choose "Private network".'] },
    { q: 'The power went off during a sale', a: ['Any sale that showed its green tick is saved.', 'If the power went before the tick, check "Sales"; if it is missing, do it again — it is never recorded twice.'] },
  ],
};
