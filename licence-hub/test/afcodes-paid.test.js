import { test } from 'node:test';
import assert from 'node:assert/strict';
import { issuePaidCode, issueTrialCode, importSigningKey, normalize, group } from '../src/afcodes.js';
import { createPrivateKey } from 'node:crypto';

function pemFromSeed(seed32) {
  const seed = Buffer.from(seed32);
  const pk = createPrivateKey({
    key: Buffer.concat([Buffer.from('302e020100300506032b657004220420', 'hex'), seed]),
    format: 'der',
    type: 'pkcs8',
  });
  return pk.export({ type: 'pkcs8', format: 'pem' });
}

test('paid monthly and perpetual codes differ from trial codes', async () => {
  const trialPem = pemFromSeed(Buffer.alloc(32, 1));
  const paidPem = pemFromSeed(Buffer.alloc(32, 2));
  const trialKey = await importSigningKey(trialPem);
  const paidKey = await importSigningKey(paidPem);
  const device = group(normalize('7KD2MQX9TP'), 5);
  const trial = await issueTrialCode(trialKey, 'al-store', device, 14);
  const monthly = await issuePaidCode(paidKey, 'al-store', device, 'monthly');
  const permanent = await issuePaidCode(paidKey, 'al-store', device, 'permanent');
  assert.equal(trial.edition, 'trial');
  assert.equal(monthly.edition, 'standard');
  assert.equal(permanent.edition, 'perpetual');
  assert.notEqual(trial.code, monthly.code);
  assert.notEqual(monthly.code, permanent.code);
});
