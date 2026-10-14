import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('owner pending app builds approve and refuse without undefined symbols', () => {
  const src = readFileSync(new URL('../public/owner/app.js', import.meta.url), 'utf8');
  assert.ok(!src.includes('paidNote'));
  assert.match(src, /موافق — شهري/);
  assert.match(src, /textContent = 'رفض'/);
  assert.match(src, /إصدار ترخيص مدفوع/);
  assert.doesNotMatch(src, /has_customer && confirm\('إعادة إصدار تجربة/);
});
