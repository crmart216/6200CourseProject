/** Browser-side encryption for a deliberately server-escrowed (NOT E2EE) chat demo. */
export const CIPHER_PREFIX = 'enc:v1:';
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', {fatal: true});

function cryptoApi(): Crypto {
  if (!globalThis.crypto?.subtle) {
    throw new Error('Encryption requires a secure browser context. Open this app on localhost or HTTPS.');
  }
  return globalThis.crypto;
}

export function toBase64(bytes: Uint8Array): string {
  // Binary-to-base64 conversion is chunked to avoid argument-count limits.
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  }
  return btoa(binary);
}

export function fromBase64(value: string): Uint8Array {
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) {
    throw new Error('Invalid base64 encoding');
  }
  const decoded = atob(value);
  return Uint8Array.from(decoded, character => character.charCodeAt(0));
}

function pemToDer(pem: string): Uint8Array {
  const match = pem.match(/-----BEGIN PUBLIC KEY-----([\s\S]*?)-----END PUBLIC KEY-----/);
  if (!match) throw new Error('Expected a PEM-encoded RSA public key');
  return fromBase64(match[1].replace(/\s+/g, ''));
}

export async function generateIdentityKeys(): Promise<{publicKey: string; privateKey: CryptoKey}> {
  const subtle = cryptoApi().subtle;
  // Private key is non-extractable; public SPKI is exportable for server wrapping.
  const pair = await subtle.generateKey(
    {name: 'RSA-OAEP', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256'},
    false,
    ['encrypt', 'decrypt'],
  );
  const der = new Uint8Array(await subtle.exportKey('spki', pair.publicKey));
  const wrapped = toBase64(der).match(/.{1,64}/g)?.join('\n') || '';
  return {publicKey: `-----BEGIN PUBLIC KEY-----\n${wrapped}\n-----END PUBLIC KEY-----\n`, privateKey: pair.privateKey};
}

export async function generateGroupKeyForServer(serverPublicKey: string): Promise<{
  key: CryptoKey;
  encryptedGroupKey: string;
}> {
  const subtle = cryptoApi().subtle;
  const rsa = await subtle.importKey('spki', pemToDer(serverPublicKey), {name: 'RSA-OAEP', hash: 'SHA-256'}, false, ['encrypt']);
  // The 32 random bytes must be temporarily exportable to wrap for the server.
  const exportableKey = await subtle.generateKey({name: 'AES-GCM', length: 256}, true, ['encrypt', 'decrypt']);
  const raw = await subtle.exportKey('raw', exportableKey);
  const encrypted = await subtle.encrypt({name: 'RSA-OAEP'}, rsa, raw);
  // Keep only a non-extractable AES key in browser storage.
  const key = await subtle.importKey('raw', raw, {name: 'AES-GCM', length: 256}, false, ['encrypt', 'decrypt']);
  return {key, encryptedGroupKey: toBase64(new Uint8Array(encrypted))};
}

export async function unwrapGroupKey(encryptedGroupKey: string, privateKey: CryptoKey): Promise<CryptoKey> {
  const subtle = cryptoApi().subtle;
  let raw: ArrayBuffer;
  try {
    raw = await subtle.decrypt({name: 'RSA-OAEP'}, privateKey, fromBase64(encryptedGroupKey));
  } catch {
    throw new Error('Cannot unwrap the group key with this browser\'s RSA private key.');
  }
  if (raw.byteLength !== 32) throw new Error('The server returned an invalid AES-256 key.');
  return subtle.importKey('raw', raw, {name: 'AES-GCM', length: 256}, false, ['encrypt', 'decrypt']);
}

export function isEncryptedMessage(content: string): boolean {
  return content.startsWith(CIPHER_PREFIX);
}

export async function encryptMessage(plaintext: string, key: CryptoKey): Promise<string> {
  const api = cryptoApi();
  const iv = api.getRandomValues(new Uint8Array(12));
  const ciphertext = await api.subtle.encrypt({name: 'AES-GCM', iv}, key, encoder.encode(plaintext));
  const serialized = `${CIPHER_PREFIX}${toBase64(iv)}:${toBase64(new Uint8Array(ciphertext))}`;
  // The backend stores message.content as a string limited to 10,000 characters.
  if (serialized.length > 10000) throw new Error('Encrypted message exceeds the server limit. Please shorten your message.');
  return serialized;
}

export async function decryptMessage(serialized: string, key: CryptoKey): Promise<string> {
  if (!isEncryptedMessage(serialized)) return serialized; // Pre-existing plaintext messages.
  const parts = serialized.slice(CIPHER_PREFIX.length).split(':');
  if (parts.length !== 2) throw new Error('Invalid encrypted message format');
  const iv = fromBase64(parts[0]);
  if (iv.length !== 12) throw new Error('Invalid message nonce');
  const plaintext = await cryptoApi().subtle.decrypt({name: 'AES-GCM', iv}, key, fromBase64(parts[1]));
  return decoder.decode(plaintext);
}
