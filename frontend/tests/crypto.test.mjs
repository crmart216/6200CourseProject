import {test} from 'node:test';
import assert from 'node:assert/strict';
import {generateKeyPairSync, privateDecrypt, publicEncrypt, constants} from 'node:crypto';
import {
  CIPHER_PREFIX, decryptMessage, encryptMessage, fromBase64, generateGroupKeyForServer,
  generateIdentityKeys, isEncryptedMessage, toBase64, unwrapGroupKey,
} from '../public/crypto.js';

const oaep = {padding: constants.RSA_PKCS1_OAEP_PADDING, oaepHash: 'sha256'};

test('Alice -> server -> Bob RSA-OAEP-SHA256 key exchange and past-message decryption', async () => {
  const server = generateKeyPairSync('rsa', {
    modulusLength: 2048,
    publicKeyEncoding: {type: 'spki', format: 'pem'},
    privateKeyEncoding: {type: 'pkcs8', format: 'pem'},
  });
  // Alice generates a random AES-256 key, wraps it for the server (POST /groups).
  const alice = await generateGroupKeyForServer(server.publicKey);
  assert.equal(alice.key.extractable, false);
  assert.equal(alice.encryptedGroupKey.length, 344);
  const rawGroupKey = privateDecrypt({...oaep, key: server.privateKey}, fromBase64(alice.encryptedGroupKey));
  assert.equal(rawGroupKey.byteLength, 32);
  const beforeBobJoined = await encryptMessage('Before Bob joined 🔐', alice.key);
  assert.ok(beforeBobJoined.startsWith(CIPHER_PREFIX));
  assert.ok(!beforeBobJoined.includes('Before Bob joined'));

  // Bob's non-extractable private RSA key is stored in his browser, NOT on the server.
  const bob = await generateIdentityKeys();
  assert.equal(bob.privateKey.extractable, false);
  assert.match(bob.publicKey, /BEGIN PUBLIC KEY/);
  const forBob = publicEncrypt({...oaep, key: bob.publicKey}, rawGroupKey);
  const bobKey = await unwrapGroupKey(toBase64(forBob), bob.privateKey);
  assert.equal(bobKey.extractable, false);
  assert.equal(await decryptMessage(beforeBobJoined, bobKey), 'Before Bob joined 🔐');
  assert.equal(await decryptMessage('Legacy chat history', bobKey), 'Legacy chat history');

  const edited = await encryptMessage('After Bob joined', bobKey);
  const editedAgain = await encryptMessage('After Bob joined', bobKey);
  assert.notEqual(edited, editedAgain, 'fresh AES-GCM nonce on every encryption');
  assert.equal(await decryptMessage(edited, alice.key), 'After Bob joined');
  assert.equal(isEncryptedMessage('Legacy chat history'), false);

  const tampered = edited.slice(0, -4) + (edited.endsWith('AAAA') ? 'BBBB' : 'AAAA');
  await assert.rejects(decryptMessage(tampered, alice.key));
});

test('bad RSA client key and oversized ciphertext are rejected', async () => {
  const bob = await generateIdentityKeys();
  await assert.rejects(unwrapGroupKey('not-base64', bob.privateKey));
  const server = generateKeyPairSync('rsa', {
    modulusLength: 2048,
    publicKeyEncoding: {type: 'spki', format: 'pem'},
    privateKeyEncoding: {type: 'pkcs8', format: 'pem'},
  });
  const alice = await generateGroupKeyForServer(server.publicKey);
  await assert.rejects(encryptMessage('x'.repeat(9900), alice.key), /server limit/);
});
