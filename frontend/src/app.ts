export {};
interface User { id: string; username: string; display_name: string; }
interface Group { id: string; name: string; description: string; created_by: string; }
interface Member { user_id: string; group_id: string; }
interface Message { id: string; sender_id: string; content: string; created_at: string; updated_at: string | null; }
const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
let users: User[] = [], groups: Group[] = [], members: Member[] = [];
let userId = localStorage.getItem('common-user') || '', groupId = '', generation = 0;
let refreshRunning = false, pending = false, messageSnapshot = '';
const error = (text = '') => { $('error').textContent = text; $('error').hidden = !text; };
async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch('/api/v1' + path, {method, headers: body === undefined ? {} : {'Content-Type':'application/json'}, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(20000)});
  if (!response.ok) {
    const data = await response.json().catch(() => ({detail: response.statusText}));
    const detail = Array.isArray(data.detail) ? data.detail.map((d: {loc: string[]; msg: string}) => `${d.loc.join('.')}: ${d.msg}`).join('; ') : data.detail;
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
function node(tag: string, text: string, className = '') { const el = document.createElement(tag); el.textContent = text; el.className = className; return el; }
function name(id: string) { return users.find(u => u.id === id)?.display_name || id.slice(0, 8); }
async function act(work: () => Promise<void>) {
  if (pending) return;
  pending = true; error(); updateControls();
  try { await work(); } catch (e) { error(e instanceof Error ? e.message : String(e)); }
  finally { pending = false; updateControls(); }
}
function updateControls() {
  const joined = members.some(m => m.user_id === userId);
  ($('join') as HTMLButtonElement).disabled = !userId || joined || pending;
  ($('leave') as HTMLButtonElement).disabled = !joined || pending;
  ($('send') as HTMLButtonElement).disabled = !joined || pending;
  ($('content') as HTMLTextAreaElement).disabled = !joined;
  for (const id of ['user-form','group-form']) $(id).querySelectorAll('button').forEach(b => b.disabled = pending || (id === 'group-form' && !userId));
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
  if (!users.some(u => u.id === userId)) userId = '';
  const select = $<HTMLSelectElement>('identity'); select.replaceChildren(new Option('Select a user', ''));
  users.forEach(u => select.add(new Option(`${u.display_name} (@${u.username})`, u.id)));
  select.value = userId; renderGroups(); updateControls();
}
async function openGroup(id: string) {
  generation++; groupId = id; members = []; messageSnapshot = ''; error();
  $<HTMLFormElement>('message-form').reset(); $('messages').replaceChildren(node('p', 'Loading conversation…', 'muted'));
  $('welcome').hidden = true; $('room').hidden = false; renderGroups(); updateControls();
  await refreshRoom();
}
async function refreshRoom() {
  if (!groupId) return;
  const id = groupId, current = generation;
  try {
    const [group, nextMembers, messages] = await Promise.all([api<Group>(`/groups/${id}`), all<Member>(`/groups/${id}/members`), all<Message>(`/groups/${id}/messages`)]);
    if (current !== generation) return;
    members = nextMembers;
    $('room-name').textContent = group.name; $('room-description').textContent = group.description;
    $('member-bar').textContent = `${members.length} members · ${members.map(m => name(m.user_id)).join(', ')}`;
    const signature = JSON.stringify([messages, userId, users]);
    if (signature !== messageSnapshot) {
      const list = $('messages'); const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 90;
      const first = !messageSnapshot; list.replaceChildren();
      if (!messages.length) list.append(node('p', 'The conversation starts here. Send the first message.', 'empty'));
      for (const message of messages) {
        const item = node('div', '', 'message ' + (message.sender_id === userId ? 'own' : ''));
        item.append(node('div', `${name(message.sender_id)} · ${new Date(message.created_at).toLocaleString()}${message.updated_at ? ' · edited' : ''}`, 'meta'), node('p', message.content, 'bubble'));
        if (message.sender_id === userId) {
          const actions = node('div', '', 'message-actions');
          for (const action of ['Edit', 'Delete']) {
            const button = node('button', action, 'quiet') as HTMLButtonElement;
            button.onclick = () => void act(async () => {
              if (action === 'Delete') { if (!confirm('Delete this message?')) return; await api(`/groups/${id}/messages/${message.id}`, 'DELETE'); }
              else { const content = prompt('Edit message', message.content); if (content === null || !content.trim()) return; if (content.trim().length > 10000) throw new Error('Messages must be 10,000 characters or fewer.'); await api(`/groups/${id}/messages/${message.id}`, 'PUT', {content:content.trim()}); }
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
    $('status').textContent = 'Up to date · refreshes every 3 seconds'; updateControls();
  } catch (e) { if (current === generation) { $('status').textContent = 'Refresh failed · retrying automatically'; error(e instanceof Error ? e.message : String(e)); } }
}
function bindForm(id: string, work: (data: FormData, form: HTMLFormElement) => Promise<void>) {
  $<HTMLFormElement>(id).onsubmit = event => { event.preventDefault(); const form = event.currentTarget as HTMLFormElement; void act(() => work(new FormData(form), form)); };
}
bindForm('user-form', async (data, form) => {
  const user = await api<User>('/users', 'POST', {username:String(data.get('username')).trim(), display_name:String(data.get('display_name')).trim()});
  userId = user.id; localStorage.setItem('common-user', userId); form.reset(); await loadDirectory(); await refreshRoom();
});
bindForm('group-form', async (data, form) => {
  const group = await api<Group>('/groups', 'POST', {name:String(data.get('name')).trim(), description:String(data.get('description')).trim(), created_by:userId});
  form.reset(); await loadDirectory(); await openGroup(group.id);
});
bindForm('message-form', async (data, form) => {
  const id = groupId; const content = String(data.get('content')).trim(); if (!content) return;
  await api(`/groups/${id}/messages`, 'POST', {sender_id:userId, content});
  if (id === groupId) { form.reset(); await refreshRoom(); $('messages').scrollTop = $('messages').scrollHeight; }
});
$('identity').onchange = () => { userId = $<HTMLSelectElement>('identity').value; localStorage.setItem('common-user', userId); updateControls(); void refreshRoom(); };
$('search').oninput = renderGroups;
$('refresh').onclick = () => void act(async () => { await loadDirectory(); await refreshRoom(); });
$('join').onclick = () => void act(async () => { await api(`/groups/${groupId}/members`, 'POST', {user_id:userId}); await refreshRoom(); });
$('leave').onclick = () => void act(async () => { if (!confirm('Leave this group?')) return; await api(`/groups/${groupId}/members/${userId}`, 'DELETE'); await refreshRoom(); });
$('edit-group').onclick = () => void act(async () => {
  const id = groupId; const group = await api<Group>(`/groups/${id}`);
  const name = prompt('Group name', group.name); if (!name?.trim()) return;
  const description = prompt('Description', group.description); if (description === null) return;
  await api(`/groups/${id}`, 'PUT', {name:name.trim(), description}); await loadDirectory(); await refreshRoom();
});
$('delete-group').onclick = () => void act(async () => {
  const id = groupId; if (!confirm('Delete this group and all its messages?')) return;
  await api(`/groups/${id}`, 'DELETE');
  if (groupId === id) { generation++; groupId = ''; members = []; $('room').hidden = true; $('welcome').hidden = false; }
  await loadDirectory();
});
setInterval(() => { if (document.hidden || refreshRunning || pending) return; refreshRunning = true; void refreshRoom().finally(() => { refreshRunning = false; }); }, 3000);
void act(loadDirectory);
