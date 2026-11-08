import {
  decryptMessage, encryptMessage, generateGroupKeyForServer, generateIdentityKeys,
  isEncryptedMessage, unwrapGroupKey,
} from './crypto.js';
import {
  checkKeyStorage, clearRoomAccess, ensureIdentity, getRoomAccess,
  saveRoomAccess, type RoomAccess,
} from './key-store.js';

interface User { id: string; username: string; display_name: string; }
interface Group { id: string; name: string; description: string; created_by: string; }
interface Member { user_id: string; group_id: string; }
interface JoinedMember extends Member { encrypted_group_key?: string; }
interface Message { id: string; sender_id: string; content: string; created_at: string; updated_at: string | null; }
interface PublicKeyResponse { public_key: string; }

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
let users: User[] = [], groups: Group[] = [], members: Member[] = [];
let userId = localStorage.getItem('common-user') || '', groupId = '', generation = 0;
let refreshRunning = false, pending = false, messageSnapshot = '';
let roomAccess: RoomAccess | undefined;
let roomHasEncryptedMessages = false;

const error = (text = '') => { $('error').textContent = text; $('error').hidden = !text; };
async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch('/api/v1' + path, {
    method,
    headers: body === undefined ? {} : {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(20000),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({detail: response.statusText}));
    const detail = Array.isArray(data.detail)
      ? data.detail.map((d: {loc: string[]; msg: string}) => `${d.loc.join('.')}: ${d.msg}`).join('; ')
      : data.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return response.status === 204 ? undefined as T : response.json();
}
async function all<T>(path: string): Promise<T[]> {
  const result: T[] = [];
  for (let offset = 0; ; offset += 100) {
    const batch = await api<T[]>(`${path}?limit=100&offset=${offset}`);
    result.push(...batch);
    if (batch.length < 100) return result;
  }
}
function node(tag: string, text: string, className = '') {
  const element = document.createElement(tag); element.textContent = text; element.className = className; return element;
}
function name(id: string) { return users.find(u => u.id === id)?.display_name || id.slice(0, 8); }
async function act(work: () => Promise<void>) {
  if (pending) return;
  pending = true; error(); updateControls();
  try { await work(); } catch (e) { error(e instanceof Error ? e.message : String(e)); }
  finally { pending = false; updateControls(); }
}
function canWrite(): boolean {
  if (!members.some(m => m.user_id === userId)) return false;
  return roomAccess?.mode === 'encrypted' || (roomAccess?.mode === 'legacy' && !roomHasEncryptedMessages);
}
function updateControls() {
  const joined = members.some(m => m.user_id === userId);
  $<HTMLButtonElement>('join').disabled = !userId || joined || pending;
  $<HTMLButtonElement>('leave').disabled = !joined || pending;
  $<HTMLButtonElement>('send').disabled = !canWrite() || pending;
  $<HTMLTextAreaElement>('content').disabled = !canWrite();
  $<HTMLSelectElement>('identity').disabled = pending;
  $('groups').querySelectorAll('button').forEach(button => button.disabled = pending);
  $('legacy-mode').hidden = !joined || !!roomAccess || roomHasEncryptedMessages;
  $<HTMLButtonElement>('legacy-mode').disabled = pending;
  for (const id of ['user-form', 'group-form']) {
    $(id).querySelectorAll('button').forEach(button => button.disabled = pending || (id === 'group-form' && !userId));
  }
  for (const id of ['edit-group', 'delete-group', 'refresh']) $<HTMLButtonElement>(id).disabled = pending;
}
function renderGroups() {
  const query = $<HTMLInputElement>('search').value.toLowerCase();
  const container = $('groups'); container.replaceChildren();
  const visible = groups.filter(g => g.name.toLowerCase().includes(query));
  if (!visible.length) container.append(node('p', 'No groups found. Create one below.', 'muted'));
  for (const group of visible) {
    const button = node('button', '', 'group ' + (group.id === groupId ? 'selected' : '')) as HTMLButtonElement;
    button.append(node('span', '#', 'hash'), node('span', group.name));
    button.onclick = () => { void openGroup(group.id); };
    container.append(button);
  }
}
async function loadDirectory() {
  const [newUsers, newGroups] = await Promise.all([all<User>('/users'), all<Group>('/groups')]);
  users = newUsers; groups = newGroups;
  if (!users.some(user => user.id === userId)) userId = '';
  const select = $<HTMLSelectElement>('identity'); select.replaceChildren(new Option('Select a user', ''));
  users.forEach(user => select.add(new Option(`${user.display_name} (@${user.username})`, user.id)));
  select.value = userId; renderGroups(); updateControls();
}
async function openGroup(id: string) {
  generation++; groupId = id; members = []; messageSnapshot = '';
  roomAccess = undefined; roomHasEncryptedMessages = false; error();
  $<HTMLFormElement>('message-form').reset();
  $('messages').replaceChildren(node('p', 'Loading conversation…', 'muted'));
  $('crypto-status').textContent = 'Checking local group key…';
  $('welcome').hidden = true; $('room').hidden = false; renderGroups(); updateControls();
  await refreshRoom();
}

function encryptionStatus(joined: boolean) {
  if (roomAccess?.mode === 'encrypted') {
    return '🔐 AES-256-GCM · key escrowed by server (not end-to-end encrypted)';
  }
  if (roomHasEncryptedMessages) {
    return joined
      ? '🔒 Encrypted history · key missing in this browser. Leave and rejoin to obtain it.'
      : '🔒 Encrypted history · join to receive your group key';
  }
  if (roomAccess?.mode === 'legacy') return '🔓 Legacy plaintext group · messages are not encrypted';
  return joined
    ? 'Key unavailable · leave and rejoin for encrypted groups, or select legacy plaintext mode below'
    : 'Join to obtain a group key (existing groups may use legacy plaintext)';
}

async function readableContent(content: string, access: RoomAccess | undefined): Promise<{text: string; readable: boolean}> {
  if (!isEncryptedMessage(content)) return {text: content, readable: true};
  if (access?.mode !== 'encrypted') return {text: '🔒 Encrypted message — this browser does not have the group key.', readable: false};
  try {
    return {text: await decryptMessage(content, access.key), readable: true};
  } catch {
    return {text: '🔒 Could not decrypt this message (wrong key or modified ciphertext).', readable: false};
  }
}

async function refreshRoom() {
  if (!groupId) return;
  const id = groupId, identity = userId, current = generation;
  try {
    const [group, nextMembers, messages, access] = await Promise.all([
      api<Group>(`/groups/${id}`),
      all<Member>(`/groups/${id}/members`),
      all<Message>(`/groups/${id}/messages`),
      getRoomAccess(identity, id),
    ]);
    if (current !== generation || identity !== userId) return;
    // Decrypt in the browser, never at the API/proxy. A corrupt message doesn't break the room.
    const content = await Promise.all(messages.map(message => readableContent(message.content, access)));
    if (current !== generation || identity !== userId) return;
    members = nextMembers; roomAccess = access;
    roomHasEncryptedMessages = messages.some(message => isEncryptedMessage(message.content));
    $('room-name').textContent = group.name;
    $('room-description').textContent = group.description;
    $('member-bar').textContent = `${members.length} members · ${members.map(member => name(member.user_id)).join(', ')}`;
    $('crypto-status').textContent = encryptionStatus(members.some(member => member.user_id === identity));
    const signature = JSON.stringify([messages, identity, users, access?.mode, roomHasEncryptedMessages]);
    if (signature !== messageSnapshot) {
      const list = $('messages');
      const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 90;
      const first = !messageSnapshot;
      list.replaceChildren();
      if (!messages.length) list.append(node('p', 'The conversation starts here. Send the first message.', 'empty'));
      for (let i = 0; i < messages.length; i++) {
        const message = messages[i];
        const item = node('div', '', 'message ' + (message.sender_id === identity ? 'own' : ''));
        const plaintextInEncryptedRoom = !isEncryptedMessage(message.content) && access?.mode === 'encrypted';
        const meta = `${name(message.sender_id)} · ${new Date(message.created_at).toLocaleString()}${message.updated_at ? ' · edited' : ''}${plaintextInEncryptedRoom ? ' · legacy plaintext' : ''}`;
        item.append(node('div', meta, 'meta'), node('p', content[i].text, 'bubble'));
        if (message.sender_id === identity) {
          const actions = node('div', '', 'message-actions');
          for (const action of ['Edit', 'Delete']) {
            // An encrypted message cannot be edited without first recovering its key.
            if (action === 'Edit' && (!content[i].readable || !canEdit(access, roomHasEncryptedMessages))) continue;
            const button = node('button', action, 'quiet') as HTMLButtonElement;
            button.onclick = () => void act(async () => {
              if (id !== groupId || identity !== userId) throw new Error('The selected group or user has changed.');
              if (action === 'Delete') {
                if (!confirm('Delete this message?')) return;
                await api(`/groups/${id}/messages/${message.id}`, 'DELETE');
              } else {
                const edited = prompt('Edit message', content[i].text);
                if (edited === null || !edited.trim()) return;
                if (edited.trim().length > 10000) throw new Error('Messages must be 10,000 characters or fewer.');
                const encrypted = await encodeForRoom(edited.trim());
                await api(`/groups/${id}/messages/${message.id}`, 'PUT', {content: encrypted});
              }
              await refreshRoom();
            });
            actions.append(button);
          }
          item.append(actions);
        }
        list.append(item);
      }
      if (first || nearBottom) list.scrollTop = list.scrollHeight;
      messageSnapshot = signature;
    }
    $('status').textContent = 'Up to date · refreshes every 3 seconds';
    updateControls();
  } catch (e) {
    if (current === generation && identity === userId) {
      $('status').textContent = 'Refresh failed · retrying automatically';
      error(e instanceof Error ? e.message : String(e));
    }
  }
}
function canEdit(access: RoomAccess | undefined, containsCiphertext: boolean): boolean {
  return access?.mode === 'encrypted' || (access?.mode === 'legacy' && !containsCiphertext);
}
async function encodeForRoom(plaintext: string): Promise<string> {
  if (!canWrite()) throw new Error('Join this group and obtain its key before sending messages.');
  if (roomAccess?.mode === 'encrypted') return encryptMessage(plaintext, roomAccess.key);
  if (roomAccess?.mode === 'legacy' && !roomHasEncryptedMessages) return plaintext;
  throw new Error('No usable group key. Leave and rejoin to recover it.');
}
function bindForm(id: string, work: (data: FormData, form: HTMLFormElement) => Promise<void>) {
  $<HTMLFormElement>(id).onsubmit = event => {
    event.preventDefault(); const form = event.currentTarget as HTMLFormElement;
    void act(() => work(new FormData(form), form));
  };
}

bindForm('user-form', async (data, form) => {
  const user = await api<User>('/users', 'POST', {
    username: String(data.get('username')).trim(), display_name: String(data.get('display_name')).trim(),
  });
  userId = user.id; localStorage.setItem('common-user', userId); form.reset();
  generation++; messageSnapshot = ''; roomAccess = undefined;
  await loadDirectory(); await refreshRoom();
});

bindForm('group-form', async (data, form) => {
  // Steps 1–4: Alice generates a fresh AES-256 key, wraps it under the server RSA
  // public key, and creates a group. The API deliberately stores the raw AES key.
  await checkKeyStorage();
  const serverKey = await api<PublicKeyResponse>('/publickey');
  const {key, encryptedGroupKey} = await generateGroupKeyForServer(serverKey.public_key);
  const creator = userId;
  const group = await api<Group>('/groups', 'POST', {
    name: String(data.get('name')).trim(), description: String(data.get('description')).trim(),
    created_by: creator, encrypted_group_key: encryptedGroupKey,
  });
  let saveFailure: unknown;
  try { await saveRoomAccess(creator, group.id, {mode: 'encrypted', key}); }
  catch (e) { saveFailure = e; }
  form.reset(); await loadDirectory(); await openGroup(group.id);
  if (saveFailure) throw new Error('Group created, but its AES key could not be saved in this browser. Leave and rejoin to recover it.');
});

bindForm('message-form', async (data, form) => {
  const id = groupId, identity = userId, plaintext = String(data.get('content')).trim();
  if (!plaintext) return;
  // AES-GCM wraps each message with a fresh random 96-bit IV before the POST.
  const content = await encodeForRoom(plaintext);
  await api(`/groups/${id}/messages`, 'POST', {sender_id: identity, content});
  if (id === groupId && identity === userId) {
    form.reset(); await refreshRoom(); $('messages').scrollTop = $('messages').scrollHeight;
  }
});

$('identity').onchange = () => {
  userId = $<HTMLSelectElement>('identity').value;
  localStorage.setItem('common-user', userId);
  generation++; roomAccess = undefined; messageSnapshot = '';
  updateControls(); void refreshRoom();
};
$('search').oninput = renderGroups;
$('refresh').onclick = () => void act(async () => { await loadDirectory(); await refreshRoom(); });
$('join').onclick = () => void act(async () => {
  const id = groupId, identity = userId;
  // Steps 5–7: Bob sends his RSA public key. The backend returns his RSA-OAEP-
  // wrapped AES key, which this browser decrypts using its private CryptoKey.
  const keys = await ensureIdentity(identity, generateIdentityKeys);
  const result = await api<JoinedMember>(`/groups/${id}/members`, 'POST', {
    user_id: identity, public_key: keys.publicKey,
  });
  const access: RoomAccess = result.encrypted_group_key
    ? {mode: 'encrypted', key: await unwrapGroupKey(result.encrypted_group_key, keys.privateKey)}
    : {mode: 'legacy'};
  await saveRoomAccess(identity, id, access);
  generation++; messageSnapshot = ''; await refreshRoom();
});
$('leave').onclick = () => void act(async () => {
  if (!confirm('Leave this group? The locally stored group key will be erased for this membership.')) return;
  const id = groupId, identity = userId;
  await api(`/groups/${id}/members/${identity}`, 'DELETE');
  await clearRoomAccess(identity, id);
  generation++; messageSnapshot = ''; roomAccess = undefined; await refreshRoom();
});
$('legacy-mode').onclick = () => void act(async () => {
  const id = groupId, identity = userId;
  if (!confirm('Only choose this for an OLD plaintext group. This does not recover missing encryption keys. Continue without encryption?')) return;
  await saveRoomAccess(identity, id, {mode: 'legacy'});
  generation++; messageSnapshot = ''; await refreshRoom();
});
$('edit-group').onclick = () => void act(async () => {
  const id = groupId; const group = await api<Group>(`/groups/${id}`);
  const groupName = prompt('Group name', group.name); if (!groupName?.trim()) return;
  const description = prompt('Description', group.description); if (description === null) return;
  await api(`/groups/${id}`, 'PUT', {name: groupName.trim(), description});
  await loadDirectory(); await refreshRoom();
});
$('delete-group').onclick = () => void act(async () => {
  const id = groupId, creator = userId;
  if (!confirm('Delete this group and all its messages?')) return;
  await api(`/groups/${id}`, 'DELETE');
  await clearRoomAccess(creator, id);
  if (groupId === id) {
    generation++; groupId = ''; members = []; roomAccess = undefined;
    $('room').hidden = true; $('welcome').hidden = false;
  }
  await loadDirectory();
});

setInterval(() => {
  if (document.hidden || refreshRunning || pending) return;
  refreshRunning = true;
  void refreshRoom().finally(() => { refreshRunning = false; });
}, 3000);
void act(loadDirectory);
