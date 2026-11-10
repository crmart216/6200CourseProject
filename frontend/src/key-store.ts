/** IndexedDB stores non-extractable browser CryptoKeys; no private/raw key in localStorage. */
export type RoomAccess = {mode: 'encrypted'; key: CryptoKey} | {mode: 'legacy'};
type IdentityKeys = {publicKey: string; privateKey: CryptoKey};
const DB_NAME = 'common-key-exchange-v1';
let dbPromise: Promise<IDBDatabase> | undefined;

function database(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    if (!globalThis.indexedDB) { reject(new Error('This browser does not support IndexedDB key storage.')); return; }
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore('identities');
      request.result.createObjectStore('rooms');
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error('Could not open browser key storage.'));
    request.onblocked = () => reject(new Error('Browser key storage is blocked by another tab.'));
  });
  // Allow a retry if storage was transiently blocked or unavailable.
  dbPromise.catch(() => { dbPromise = undefined; });
  return dbPromise;
}

async function read<T>(storeName: string, key: string): Promise<T | undefined> {
  const db = await database();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(storeName, 'readonly');
    const request = transaction.objectStore(storeName).get(key);
    request.onsuccess = () => resolve(request.result as T | undefined);
    request.onerror = () => reject(request.error || new Error('Browser key read failed.'));
    transaction.onabort = () => reject(transaction.error || new Error('Browser key read aborted.'));
  });
}

async function write(storeName: string, id: string, value?: unknown): Promise<void> {
  const db = await database();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(storeName, 'readwrite');
    if (value === undefined) transaction.objectStore(storeName).delete(id);
    else transaction.objectStore(storeName).put(value, id);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error || new Error('Browser key write failed.'));
    transaction.onabort = () => reject(transaction.error || new Error('Browser key write aborted.'));
  });
}

export async function ensureIdentity(userId: string, generate: () => Promise<IdentityKeys>): Promise<IdentityKeys> {
  const existing = await read<IdentityKeys>('identities', userId);
  if (existing) return existing;
  const newKeys = await generate();
  await write('identities', userId, newKeys);
  return newKeys;
}

const roomId = (userId: string, groupId: string) => `${userId}:${groupId}`;
export async function getRoomAccess(userId: string, groupId: string): Promise<RoomAccess | undefined> {
  if (!userId || !groupId) return undefined;
  return read<RoomAccess>('rooms', roomId(userId, groupId));
}
export async function saveRoomAccess(userId: string, groupId: string, access: RoomAccess): Promise<void> {
  await write('rooms', roomId(userId, groupId), access);
}
export async function clearRoomAccess(userId: string, groupId: string): Promise<void> {
  await write('rooms', roomId(userId, groupId));
}
export async function checkKeyStorage(): Promise<void> {
  await database();
}
