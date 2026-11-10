/** Public, automatically refreshed, read-only audit log viewer. No credentials. */
interface AuditGroup { id: string; name: string; }
interface Versions { encrypted?: string | null; decrypted?: string | null; format?: string; decryption_error?: string; }
interface Delivery extends Versions { message_id: string; sender_id: string; }
interface AuditEvent {
  id: number; occurred_at: string; event_type: string; group_id: string | null;
  group_name: string | null; user_id: string | null; message_id: string | null;
  details: Record<string, unknown>;
}
const byId = (id: string) => document.getElementById(id) as HTMLElement;
const query = new URLSearchParams(location.search);
const requestedGroup = query.get('group') || '';
let selectedGroup = requestedGroup;
let groups: AuditGroup[] = [];
let nextId = 0;
let loaded = 0;
let fetching = false;
let lastError = '';
let lastGroupsRefresh = 0;

function element<K extends keyof HTMLElementTagNameMap>(tag: K, content = '', className = ''): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.textContent = content;
  node.className = className;
  return node;
}
function linkFor(groupId: string): string {
  return groupId ? `/logs?group=${encodeURIComponent(groupId)}` : '/logs';
}
function setStatus(text: string, failed = false) {
  byId('connection').textContent = text;
  byId('connection').classList.toggle('offline', failed);
}
function setHeading() {
  byId('page-title').textContent = selectedGroup
    ? (groups.find(group => group.id === selectedGroup)?.name || `Group ${selectedGroup.slice(0, 8)}`)
    : 'All activity';
}
function renderGroups() {
  const container = byId('channels'); container.replaceChildren();
  const all = element('a', 'All activity', 'channel all' + (!selectedGroup ? ' active' : ''));
  all.href = '/logs'; all.dataset.group = '';
  container.append(all);
  for (const group of groups) {
    const anchor = element('a', group.name, 'channel' + (selectedGroup === group.id ? ' active' : ''));
    anchor.href = linkFor(group.id); anchor.dataset.group = group.id;
    container.append(anchor);
  }
  setHeading();
}
function addBlock(container: HTMLElement, label: string, value: string, className = '') {
  container.append(element('div', label, 'data-label'));
  container.append(element('pre', value, 'data-text ' + className));
}
function appendVersions(container: HTMLElement, value: Versions) {
  if (value.decrypted !== undefined && value.decrypted !== null) {
    addBlock(container, 'Decrypted / plaintext', value.decrypted);
  } else if (value.decryption_error) {
    addBlock(container, 'Decryption unavailable', value.decryption_error, 'fallback');
  }
  if (typeof value.encrypted === 'string') addBlock(container, 'Encrypted / ciphertext', value.encrypted, 'cipher');
  else if (value.format === 'plaintext') addBlock(container, 'Encryption', 'Legacy message — sent as plaintext');
}
function appendDetails(target: HTMLElement, details: Record<string, unknown>, kind: string) {
  // Received, individual sent and deleted messages are rendered as matched
  // decrypted + encrypted values; GET /messages deliveries can contain a batch.
  if ('encrypted' in details || 'decrypted' in details) {
    appendVersions(target, details as Versions);
  } else if (kind === 'messages_sent' && Array.isArray(details.messages)) {
    for (const item of details.messages) {
      const entry = item as Delivery;
      const holder = element('div', '', 'delivery');
      holder.append(element('div', `Message ${entry.message_id} · sender ${entry.sender_id}`, 'delivery-title'));
      appendVersions(holder, entry); target.append(holder);
    }
  } else if (kind === 'message_updated') {
    for (const step of ['before', 'after'] as const) {
      const data = details[step];
      if (data && typeof data === 'object') {
        const holder = element('div', '', 'delivery');
        holder.append(element('div', step.toUpperCase(), 'delivery-title'));
        appendVersions(holder, data as Versions);
        target.append(holder);
      }
    }
  } else if (Object.keys(details).length) {
    // Public RSA/AES key exchange metadata; no raw private or unwrapped AES keys.
    for (const [key, value] of Object.entries(details)) {
      addBlock(target, key.replaceAll('_', ' '), String(value));
    }
  }
}
function renderEvent(event: AuditEvent) {
  const item = element('article', '', 'event');
  const top = element('div', '', 'event-top');
  const type = element('span', event.event_type.replaceAll('_', ' '), 'event-type' +
    (event.event_type.includes('key') ? ' key' : event.event_type.includes('message') ? ' message' : ''));
  const timestamp = new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(event.occurred_at)
    ? event.occurred_at : `${event.occurred_at}Z`);
  const time = element('time', Number.isNaN(timestamp.valueOf()) ? event.occurred_at : timestamp.toISOString().replace('T', ' ').replace('.000Z', 'Z'), 'time');
  time.dateTime = Number.isNaN(timestamp.valueOf()) ? event.occurred_at : timestamp.toISOString();
  top.append(type, time); item.append(top);
  const meta = element('div', `Event #${event.id}`, 'event-meta');
  if (event.group_id) {
    const group = element('a', ` · ${event.group_name || 'Group'} (${event.group_id.slice(0, 8)})`);
    group.href = linkFor(event.group_id); meta.append(group);
  }
  if (event.user_id) meta.append(document.createTextNode(` · user ${event.user_id}`));
  if (event.message_id) meta.append(document.createTextNode(` · message ${event.message_id}`));
  item.append(meta);
  const detail = element('div', '', 'event-detail');
  appendDetails(detail, event.details, event.event_type);
  if (detail.childNodes.length) item.append(detail);
  return item;
}
function appendBatch(events: AuditEvent[]) {
  if (!events.length) {
    if (loaded === 0) byId('events').replaceChildren(element('p', 'No events yet. New events will appear here automatically.', 'empty'));
    return;
  }
  if (loaded === 0) byId('events').replaceChildren();
  const fragment = document.createDocumentFragment();
  for (const event of events) {
    if (event.id <= nextId) continue;
    fragment.append(renderEvent(event));
    nextId = event.id;
    loaded++;
  }
  byId('events').append(fragment);
  byId('counter').textContent = `${loaded.toLocaleString()} event${loaded === 1 ? '' : 's'}`;
}
async function refreshGroups() {
  const response = await fetch('/api/v1/logs/groups', {cache: 'no-store'});
  if (!response.ok) throw new Error(`Could not fetch groups (${response.status})`);
  groups = await response.json() as AuditGroup[];
  // Keep a group link for a direct deep link even when the group never existed.
  if (selectedGroup && !groups.some(group => group.id === selectedGroup)) {
    groups.push({id: selectedGroup, name: `Group ${selectedGroup.slice(0, 8)}`});
  }
  renderGroups();
}
async function refresh() {
  if (fetching) return;
  fetching = true;
  try {
    if (Date.now() - lastGroupsRefresh >= 5000) {
      await refreshGroups(); lastGroupsRefresh = Date.now();
    }
    // Drain pagination when there are more than 200 new events. A cursor, not
    // timestamps, prevents omissions when multiple rows share a timestamp.
    for (let page = 0; page < 20; page++) {
      const params = new URLSearchParams({after: String(nextId), limit: '200'});
      if (selectedGroup) params.set('group_id', selectedGroup);
      const response = await fetch(`/api/v1/logs?${params}`, {cache: 'no-store'});
      if (!response.ok) throw new Error(`Backend returned ${response.status}`);
      const events = await response.json() as AuditEvent[];
      appendBatch(events);
      if (events.length < 200) break;
    }
    lastError = '';
    setStatus('● Live · auto-refreshing');
  } catch (error) {
    lastError = error instanceof Error ? error.message : String(error);
    setStatus(`● Disconnected · retrying: ${lastError}`, true);
    if (!loaded) byId('events').replaceChildren(element('p', lastError, 'empty'));
  } finally {
    fetching = false;
  }
}
// Direct links remain bookmarkable and work without cookies, authentication or
// a local browser identity. Ordinary navigation resets the event cursor.
renderGroups();
void refresh();
setInterval(() => { if (!document.hidden) void refresh(); }, 1800);
window.addEventListener('focus', () => void refresh());
