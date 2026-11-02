const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="app-token"]').content;
let source = 'youtube', busy = false, tracks = [], selected = new Set(), trackSignature = '', playlistSignature = '', lastStatus = '', initialized = false;
const defaults = JSON.parse($('defaults').textContent);
for (const key of ['binary', 'config', 'output_dir']) $(key).value = defaults[key] || '';

function message(text, error = false) {
  $('message').textContent = text;
  $('message').classList.toggle('error', error);
}

function controls() {
  for (const button of document.querySelectorAll('[data-source]')) button.disabled = busy;
  for (const id of ['connect', 'scan', 'folder', 'recursive', 'binary', 'config', 'output_dir']) $(id).disabled = busy;
  $('playlist').disabled = busy || !$('playlist').options[0]?.value;
  $('normalize').disabled = busy || !$('playlist').value;
  $('search').disabled = $('download').disabled = $('organize').disabled = busy || selected.size === 0;
  $('organize').hidden = tracks.length === 0 || tracks.some(track => track.service !== 'local');
  $('select-all').disabled = busy || tracks.length === 0;
  $('select-all').checked = tracks.length > 0 && selected.size === tracks.length;
  $('select-all').indeterminate = selected.size > 0 && selected.size < tracks.length;
  $('selection-count').textContent = `${selected.size} selected`;
  for (const checkbox of document.querySelectorAll('#tracks input')) checkbox.disabled = busy;
}

function renderTracks() {
  $('tracks').replaceChildren();
  tracks.forEach((track, index) => {
    const row = document.createElement('tr');
    const checkCell = row.insertCell(); checkCell.className = 'select-cell';
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = selected.has(index);
    checkbox.setAttribute('aria-label', `Select ${track.title}`);
    checkbox.addEventListener('change', () => { checkbox.checked ? selected.add(index) : selected.delete(index); controls(); });
    checkCell.append(checkbox);
    const titleCell = row.insertCell();
    const title = document.createElement('span'); title.className = 'track-title'; title.textContent = track.title;
    const artist = document.createElement('span'); artist.className = 'track-artist'; artist.textContent = track.artists.join(' & ');
    titleCell.append(title, artist);
    const album = row.insertCell(); album.textContent = track.album || 'Unknown release'; if (!track.album) album.className = 'unknown';
    const year = row.insertCell(); year.textContent = track.release_year || '—';
    const linkCell = row.insertCell();
    if (/^https:\/\//.test(track.url || '')) {
      const link = document.createElement('a'); link.href = track.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = 'Open ↗'; linkCell.append(link);
    } else { linkCell.textContent = 'Local'; linkCell.className = 'unknown'; }
    $('tracks').append(row);
  });
  $('track-count').textContent = tracks.length;
  $('empty').hidden = tracks.length > 0;
  controls();
}

async function task(action) {
  const request = {action, source};
  if (action === 'normalize') {
    request.playlist_id = $('playlist').value;
    request.folder = $('folder').value.trim(); request.recursive = $('recursive').checked;
  }
  if (action === 'organize' && !confirm(`Write tags to ${selected.size} file(s) and rename them to "Artist - Title.mp3"?`)) return;
  if (action === 'search' || action === 'download' || action === 'organize') {
    request.indices = [...selected].sort((a, b) => a - b);
    request.options = Object.fromEntries(['binary', 'config', 'output_dir'].map(key => [key, $(key).value.trim()]));
  }
  busy = true; controls(); message('Starting…'); $('activity').open = true;
  try {
    const response = await fetch('/api/tasks', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-App-Token': token}, body: JSON.stringify(request)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
    await poll();
  } catch (error) { busy = false; controls(); message(error.message, true); }
}

async function poll() {
  try {
    const response = await fetch('/api/state');
    if (!response.ok) throw new Error('Could not read app state.');
    const state = await response.json();
    if (!initialized) {
      source = state.source;
      document.querySelectorAll('[data-source]').forEach(tab => tab.setAttribute('aria-selected', String(tab.dataset.source === source)));
      $('folder-controls').hidden = source !== 'folder'; $('playlist-controls').hidden = source === 'folder';
      initialized = true;
    }
    busy = state.job.status === 'running';
    const signature = JSON.stringify(state.tracks);
    if (signature !== trackSignature) {
      trackSignature = signature; tracks = state.tracks; selected = new Set(tracks.map((_, index) => index)); renderTracks();
    }
    const newPlaylistSignature = JSON.stringify(state.playlists);
    if (newPlaylistSignature !== playlistSignature) {
      playlistSignature = newPlaylistSignature; $('playlist').replaceChildren();
      for (const playlist of state.playlists) {
        const option = document.createElement('option'); option.value = playlist.id; option.textContent = playlist.name; $('playlist').append(option);
      }
      if (!state.playlists.length) { const option = document.createElement('option'); option.value = ''; option.textContent = 'Connect to choose a playlist'; $('playlist').append(option); }
      const preferred = state.playlists.find(item => item.name.toLowerCase() === 'salsync'); if (preferred) $('playlist').value = preferred.id;
    }
    $('logs').textContent = state.job.logs.join('\n') || 'No tasks yet.';
    $('status').textContent = {idle:'Ready', running:'Working…', done:'Complete', error:'Needs attention'}[state.job.status];
    $('status').className = `status ${state.job.status}`;
    if (busy) {
      const descriptions = {playlists:'Connecting to your account…', normalize:'Finding track titles and original releases. This can take a few minutes…', search:'Searching Soulseek for the selected tracks…', download:'Downloading and tagging selected MP3s…', organize:'Tagging and renaming selected files…'};
      message(descriptions[state.job.action]);
    } else if (`${state.job.id}:${state.job.status}` !== lastStatus) {
      if (state.job.status === 'error') message(state.job.logs.at(-1) || 'The task failed. See Activity for details.', true);
      else if (state.job.status === 'done') {
        const descriptions = {playlists:state.playlists.length ? 'Choose a playlist, then load its tracks.' : 'No playlists found in this account.', normalize:`${tracks.length} tracks ready to review. Select the tracks you want to search or download.`, search:'Search finished. Matches are listed in Activity.', download:'Download task finished. Check Activity for individual track results.', organize:'Selected files are tagged and renamed.'};
        message(descriptions[state.job.action]);
      }
    }
    lastStatus = `${state.job.id}:${state.job.status}`; controls();
  } catch (error) { message('Cannot reach Salsync. Check that python src/app.py is still running.', true); busy = true; controls(); }
}

document.querySelectorAll('[data-source]').forEach(button => button.addEventListener('click', () => {
  source = button.dataset.source;
  document.querySelectorAll('[data-source]').forEach(tab => tab.setAttribute('aria-selected', String(tab === button)));
  $('folder-controls').hidden = source !== 'folder'; $('playlist-controls').hidden = source === 'folder';
  $('source-hint').textContent = source === 'folder' ? 'Title and artist come from existing tags, or the filename when tags are missing. Files stay untouched until you choose Tag & rename.' : 'Connect your account, then choose a playlist. Sign-in opens in your browser if needed.';
  $('playlist').replaceChildren(new Option('Connect to choose a playlist', ''));
  // Only display playlists fetched for the currently selected service.
  playlistSignature = ''; controls();
  if (source !== 'folder') task('playlists');
}));
$('playlist').addEventListener('change', controls);
$('connect').addEventListener('click', () => task('playlists'));
$('normalize').addEventListener('click', () => task('normalize'));
$('scan').addEventListener('click', () => task('normalize'));
$('search').addEventListener('click', () => task('search'));
$('download').addEventListener('click', () => task('download'));
$('organize').addEventListener('click', () => task('organize'));
$('select-all').addEventListener('change', () => { selected = $('select-all').checked ? new Set(tracks.map((_, index) => index)) : new Set(); renderTracks(); });
poll(); setInterval(poll, 1000);
