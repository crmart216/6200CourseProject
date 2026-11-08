const DB_NAME = 'common-key-exchange-v1';
let dbPromise;
function database() {
    if (dbPromise)
        return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
        if (!globalThis.indexedDB) {
            reject(new Error('This browser does not support IndexedDB key storage.'));
            return;
        }
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
async function read(storeName, key) {
    const db = await database();
    return new Promise((resolve, reject) => {
        const transaction = db.transaction(storeName, 'readonly');
        const request = transaction.objectStore(storeName).get(key);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error || new Error('Browser key read failed.'));
        transaction.onabort = () => reject(transaction.error || new Error('Browser key read aborted.'));
    });
}
async function write(storeName, id, value) {
    const db = await database();
    return new Promise((resolve, reject) => {
        const transaction = db.transaction(storeName, 'readwrite');
        if (value === undefined)
            transaction.objectStore(storeName).delete(id);
        else
            transaction.objectStore(storeName).put(value, id);
        transaction.oncomplete = () => resolve();
        transaction.onerror = () => reject(transaction.error || new Error('Browser key write failed.'));
        transaction.onabort = () => reject(transaction.error || new Error('Browser key write aborted.'));
    });
}
export async function ensureIdentity(userId, generate) {
    const existing = await read('identities', userId);
    if (existing)
        return existing;
    const newKeys = await generate();
    await write('identities', userId, newKeys);
    return newKeys;
}
const roomId = (userId, groupId) => `${userId}:${groupId}`;
export async function getRoomAccess(userId, groupId) {
    if (!userId || !groupId)
        return undefined;
    return read('rooms', roomId(userId, groupId));
}
export async function saveRoomAccess(userId, groupId, access) {
    await write('rooms', roomId(userId, groupId), access);
}
export async function clearRoomAccess(userId, groupId) {
    await write('rooms', roomId(userId, groupId));
}
export async function checkKeyStorage() {
    await database();
}
