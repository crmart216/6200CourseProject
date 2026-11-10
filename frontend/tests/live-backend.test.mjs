/** Optional cross-language integration test against the companion FastAPI backend.
 * Run with BACKEND_TEST_URL=http://localhost:3000 npm test (uses the frontend proxy).
 * This creates two disposable test users and a group in the selected backend DB.
 */
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {
  encryptMessage, decryptMessage, generateGroupKeyForServer, generateIdentityKeys,
  unwrapGroupKey, isEncryptedMessage,
} from '../public/crypto.js';

const base = process.env.BACKEND_TEST_URL?.replace(/\/$/, '');
const request = async (path, method = 'GET', body) => {
  const response = await fetch(base + '/api/v1' + path, {
    method, headers: {'content-type': 'application/json'}, body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  assert.ok(response.ok, `${method} ${path} failed: ${JSON.stringify(data)}`);
  return data;
};

test('real FastAPI: Alice wraps AES key, Bob joins, decrypts old ciphertext', {skip: !base}, async () => {
  const suffix = randomUUID().slice(0, 12);
  const aliceUser = await request('/users', 'POST', {username: `alice_${suffix}`, display_name: 'Alice'});
  const bobUser = await request('/users', 'POST', {username: `bob_${suffix}`, display_name: 'Bob'});
  const serverKey = await request('/publickey');
  const aliceKey = await generateGroupKeyForServer(serverKey.public_key);
  const group = await request('/groups', 'POST', {
    name: 'Encryption integration test', description: 'For testing only',
    created_by: aliceUser.id, encrypted_group_key: aliceKey.encryptedGroupKey,
  });
  const plaintext = `Secret before Bob joined: ${suffix}`;
  const content = await encryptMessage(plaintext, aliceKey.key);
  await request(`/groups/${group.id}/messages`, 'POST', {sender_id: aliceUser.id, content});
  const bobKeys = await generateIdentityKeys();
  const join = await request(`/groups/${group.id}/members`, 'POST', {
    user_id: bobUser.id, public_key: bobKeys.publicKey,
  });
  assert.ok(join.encrypted_group_key);
  const bobAes = await unwrapGroupKey(join.encrypted_group_key, bobKeys.privateKey);
  const messages = await request(`/groups/${group.id}/messages`);
  assert.equal(messages.length, 1);
  assert.ok(isEncryptedMessage(messages[0].content));
  assert.ok(!messages[0].content.includes(plaintext));
  assert.equal(await decryptMessage(messages[0].content, bobAes), plaintext);
  const response = await encryptMessage('Bob can respond', bobAes);
  const returned = await request(`/groups/${group.id}/messages`, 'POST', {sender_id: bobUser.id, content: response});
  assert.equal(await decryptMessage(returned.content, aliceKey.key), 'Bob can respond');
  // Remove our disposable test group. Users remain because there is no delete user endpoint.
  const removed = await fetch(base + '/api/v1/groups/' + group.id, {method: 'DELETE'});
  assert.equal(removed.status, 204);
});
