#!/usr/bin/env node
/** Emit one signed trial code + public key (JSON on stdout) for Python cross-check. */
import { issueTrialCode, importSigningKey, normalize, group } from '../src/afcodes.js';
import { generateKeyPairSync } from 'node:crypto';

const { privateKey, publicKey } = generateKeyPairSync('ed25519');
const pem = privateKey.export({ type: 'pkcs8', format: 'pem' });
const pubDer = publicKey.export({ type: 'spki', format: 'der' });
const raw = pubDer.slice(-32);
const pubB64 = raw.toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

const key = await importSigningKey(pem);
const rawDevice = (process.env.HUB_TEST_DEVICE || 'ABCD2EFGH3').replace(/-/g, '');
const device = group(normalize(rawDevice), 5);
const signed = await issueTrialCode(key, 'al-store', device, 14);
process.stdout.write(JSON.stringify({ code: signed.code, public: pubB64, device }));
