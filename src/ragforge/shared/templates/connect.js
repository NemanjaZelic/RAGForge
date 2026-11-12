'use strict';
const byId = (id) => document.getElementById(id);
const endpoint = location.origin + '/mcp';
byId('endpoint').value = endpoint;
const serverName = 'ragforge-docs';
function configuration() {
  const token = byId('token').value.trim();
  if (!token || /[\s\x00-\x1f\x7f]/.test(token)) throw new Error('Unesi pristupni token bez razmaka.');
  const entry = {type: 'http', url: endpoint, headers: {Authorization: 'Bearer ' + token}};
  const client = byId('client').value;
  if (client === 'codex') {
    return {text: '[mcp_servers."ragforge-docs"]\nurl = ' + JSON.stringify(endpoint) + '\nhttp_headers = { Authorization = ' + JSON.stringify('Bearer ' + token) + ' }\n', file: 'codex-ragforge.toml'};
  }
  const config = client === 'vscode' ? {servers: {[serverName]: entry}} : {mcpServers: {[serverName]: entry}};
  return {text: JSON.stringify(config, null, 2), file: client === 'vscode' ? 'mcp.json' : '.mcp.json', entry};
}
function render() {
  const client = byId('client').value;
  const details = {
    vscode: ['Klikni „Otvori u VS Code-u“ i potvrdi MCP server. Za ručno podešavanje spoji konfiguraciju u .vscode/mcp.json, uz očuvanje postojećih servera.', '.github/skills/ragforge-docs/'],
    claude: ['Spoji preuzeti mcpServers unos u .mcp.json projekta. Sačuvaj postojeće servere, ponovo otvori Claude Code i potvrdi konekciju.', '.claude/skills/ragforge-docs/'],
    codex: ['Spoji preuzeti MCP blok u .codex/config.toml projekta ili postojeći ~/.codex/config.toml. Sačuvaj ostala podešavanja i ponovo otvori Codex.', '.agents/skills/ragforge-docs/'],
    generic: ['Unesi MCP adresu i Bearer token u podešavanja svoje aplikacije. Preuzeti JSON je generički primer; format može da se razlikuje.', 'Folder za skillove ili instrukcije tvoje AI aplikacije.']
  };
  byId('instructions').textContent = details[client][0];
  byId('skill-location').textContent = 'Raspakuj ragforge-docs/ u: ' + details[client][1];
  byId('install').hidden = client !== 'vscode';
  try { byId('preview').textContent = configuration().text.replace(/Bearer [^"\s]+/g, 'Bearer <tvoj-token>'); }
  catch { byId('preview').textContent = 'Nalepi token da bi se napravila konfiguracija.'; }
}
function report(error) { byId('status').textContent = error.message || String(error); }
byId('client').addEventListener('change', render);
byId('token').addEventListener('input', render);
byId('copy').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(configuration().text); byId('status').textContent = 'Konfiguracija je kopirana. Čuvaj token privatno.'; } catch (error) { report(error); }
});
byId('download').addEventListener('click', () => {
  try {
    const config = configuration();
    const url = URL.createObjectURL(new Blob([config.text], {type: 'text/plain;charset=utf-8'}));
    const link = document.createElement('a'); link.href = url; link.download = config.file; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { report(error); }
});
byId('install').addEventListener('click', () => {
  try { location.href = 'vscode:mcp/install?' + encodeURIComponent(JSON.stringify({name: serverName, ...configuration().entry})); }
  catch (error) { report(error); }
});
byId('check').addEventListener('click', async () => {
  const button = byId('check'); button.disabled = true;
  try {
    configuration();
    byId('status').textContent = 'Proveravam vezu…';
    const response = await fetch('/collections', {headers: {Authorization: 'Bearer ' + byId('token').value.trim()}, cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(20000)});
    if (!response.ok) throw new Error(response.status === 401 ? 'Token je nevažeći ili je istekao.' : 'Server odbija pristup (' + response.status + ').');
    const result = await response.json();
    byId('status').textContent = 'Povezano. Dostupne kolekcije: ' + result.collections.map((item) => item.collection_id).join(', ');
  } catch (error) { report(error); } finally { button.disabled = false; }
});
render();
