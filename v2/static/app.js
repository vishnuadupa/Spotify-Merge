/* ═══════════════════════════════════════════════════════════════════
   Spotify Library Manager v2 — Kanban edition
   ═══════════════════════════════════════════════════════════════════ */

const S = {
  status:{}, languages:[], playlists:[],
  workspace:[],                 // [{slot, playlist_id}] -> Kanban columns
  filters:{ lang:'', genre:'', mood:'', sort:'name', q:'' },
  tracks:[], total:0, offset:0, LIMIT:100,
  selected:new Set(),
  vizData:[], vizOpen:false,
  addColSeg:'new',
};
const $ = id => document.getElementById(id);

document.addEventListener('DOMContentLoaded', () => {
  // Each binder is isolated: one missing element can never break the rest of the UI.
  [bindTopbar, bindToolbar, bindModals, bindViz, bindAddColumn].forEach(fn => {
    try { fn(); } catch (e) { console.error('bind failed:', fn.name, e); }
  });
  // Escape closes any open modal (standard, expected behavior)
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') document.querySelectorAll('.modal:not(.hidden)').forEach(m => m.classList.add('hidden'));
  });
  loadStatus(); loadLanguages(); loadGenres(); loadPlaylists().then(loadWorkspace);
  handleAuthReturn();
  setInterval(pollChanges, 4000);
});

function handleAuthReturn(){
  const p = new URLSearchParams(location.search);
  if (p.has('auth_done')||p.has('error')){
    history.replaceState({},'','/');
    loadStatus();
    if (p.get('auth_done')) toast(`✓ ${p.get('auth_done')} account connected`,'success');
    if (p.get('error')) toast('Auth error: '+p.get('error'),'error');
  }
}

/* ── status ─────────────────────────────────────────────── */
async function loadStatus(){
  const d = await api('/api/status'); S.status = d;
  setAcc('old', d.old); setAcc('new', d.new);
  refreshAccountSelectors();
  updateChangeCount(d.stats?.pending_changes||0);
  const connected = d.old?.ok || d.new?.ok;
  const loaded = d.library_loaded;
  updateGuide(connected, loaded, d.stats?.pending_changes||0);
  // First-time user with no credentials yet → open Setup once so the path is obvious.
  if (!d.has_config && !S._setupShown){ S._setupShown = true; $('modal-setup').classList.remove('hidden'); }
  if (!loaded){
    if(!connected){
      $('empty-msg').textContent = 'Connect your Spotify account to get started.';
      $('empty-sub').textContent = 'Open Setup, paste your app credentials, and connect — it takes a minute.';
      $('btn-empty-setup').classList.remove('hidden');
      $('btn-empty-load').classList.add('hidden');
    } else {
      $('empty-msg').textContent = 'Account connected — now pull in your library.';
      $('empty-sub').textContent = "We'll fetch every song from your liked tracks and playlists, then sort them by language and genre.";
      $('btn-empty-load').classList.remove('hidden');
      $('btn-empty-setup').classList.add('hidden');
    }
  }
}

// 3-step guide ribbon: Connect → Load → Organize
function updateGuide(connected, loaded, pending){
  const s1=$('gstep-1'), s2=$('gstep-2'), s3=$('gstep-3'), hint=$('guide-hint');
  [s1,s2,s3].forEach(s=>s.className='guide-step');
  if(!connected){
    s1.classList.add('active');
    hint.textContent='Start here → open Setup to connect your account.';
  } else if(!loaded){
    s1.classList.add('done'); s2.classList.add('active');
    hint.textContent='Next → click “Load my library” to pull your songs.';
  } else {
    s1.classList.add('done'); s2.classList.add('done'); s3.classList.add('active');
    hint.textContent = pending>0
      ? `${pending} change(s) staged — hit “Push to Spotify” when ready.`
      : 'Drag songs into playlists, then push to Spotify.';
  }
}
function setAcc(label,info){
  const el=$(`${label}-status-txt`); if(!el)return;
  if(info?.ok){ el.textContent=`${info.name} (${info.id})`; el.className='acc-status connected'; }
  else{ el.textContent='Not connected'; el.className='acc-status'; }
}

// Source (fetch-from) and Target (push-to) account selectors.
// Same on both = single-account in-place edit. Different = migration (either direction).
function refreshAccountSelectors(){
  const accts=[];
  if(S.status.old?.ok) accts.push({label:'old', name:S.status.old.name});
  if(S.status.new?.ok) accts.push({label:'new', name:S.status.new.name});
  const src=$('src-select'), tgt=$('tgt-select');
  if(!accts.length){
    src.innerHTML=tgt.innerHTML='<option value="">— none —</option>';
    S.source=S.target=null; return;
  }
  const opts=accts.map(a=>`<option value="${a.label}">${esc(a.name)}</option>`).join('');
  src.innerHTML=opts; tgt.innerHTML=opts;
  const has=l=>accts.some(a=>a.label===l);
  S.source = (localStorage.getItem('src') && has(localStorage.getItem('src'))) ? localStorage.getItem('src') : accts[0].label;
  // default target = second account if two connected (migration), else same (single-account)
  S.target = (localStorage.getItem('tgt') && has(localStorage.getItem('tgt'))) ? localStorage.getItem('tgt')
             : (accts[1] ? accts[1].label : accts[0].label);
  src.value=S.source; tgt.value=S.target;
}
async function pollChanges(){
  const d = await api('/api/changes').catch(()=>[]);
  updateChangeCount(Array.isArray(d)?d.length:0);
}
function updateChangeCount(n){
  const b=$('change-count');
  if(n>0){ b.textContent=n; b.classList.remove('hidden'); } else b.classList.add('hidden');
  S.pending=n;
}

/* ── language tabs ──────────────────────────────────────── */
async function loadLanguages(){
  S.languages = await api('/api/languages');
  const nav=$('lang-tabs');
  nav.innerHTML = `<span class="lang-tab ${S.filters.lang===''?'active':''}" data-lang="">All</span>`;
  if(!S.languages.length){ nav.innerHTML += `<span class="lang-loading">Load your library to begin →</span>`; return; }
  for(const l of S.languages){
    const t=document.createElement('span');
    t.className='lang-tab'+(S.filters.lang===l.language?' active':'');
    t.dataset.lang=l.language;
    t.innerHTML=`${esc(l.language)}<span class="cnt">${l.count}</span>`;
    nav.appendChild(t);
  }
  nav.querySelectorAll('.lang-tab').forEach(t=>t.addEventListener('click',()=>{
    nav.querySelectorAll('.lang-tab').forEach(x=>x.classList.remove('active'));
    t.classList.add('active');
    S.filters.lang=t.dataset.lang; S.filters.genre=''; loadGenres(); reload();
    $('lib-title').textContent = t.dataset.lang || 'All Languages';
  }));
}

// genre dropdown — scoped to the current language tab
async function loadGenres(){
  const q = S.filters.lang ? `?language=${encodeURIComponent(S.filters.lang)}` : '';
  const genres = await api('/api/genres'+q).catch(()=>[]);
  const sel=$('genre-select');
  sel.innerHTML = '<option value="">All Genres</option>' +
    genres.map(g=>`<option value="${esc(g.genre)}">${esc(g.genre)} (${g.count})</option>`).join('');
  sel.value = S.filters.genre || '';
}

/* ── tracks ─────────────────────────────────────────────── */
function buildQuery(){
  const f=S.filters;
  const p=new URLSearchParams({ language:f.lang, genre:f.genre, mood:f.mood, sort:f.sort, q:f.q,
    offset:S.offset, limit:S.LIMIT });
  return p.toString();
}
async function loadTracks(replace){
  const d = await api('/api/tracks?'+buildQuery());
  S.tracks = replace ? d.tracks : [...S.tracks, ...d.tracks];
  S.total = d.total;
  renderTracks(replace);
}
function reload(){ S.offset=0; S.tracks=[]; loadTracks(true); }

function renderTracks(replace){
  const list=$('track-list');
  if(replace) list.innerHTML='';
  if(S.tracks.length===0){ $('empty-state').classList.remove('hidden'); list.classList.add('hidden');
    $('btn-load-more').classList.add('hidden'); $('lib-count').textContent=''; return; }
  $('empty-state').classList.add('hidden'); list.classList.remove('hidden');
  $('lib-count').textContent = `${S.total} songs`;
  const start = replace?0:list.children.length;
  for(let i=start;i<S.tracks.length;i++) list.appendChild(trackRow(S.tracks[i]));
  $('btn-load-more').classList.toggle('hidden', S.tracks.length>=S.total);
  if(S.tracks.length<S.total) $('btn-load-more').textContent=`Load more (${S.tracks.length}/${S.total})`;
}

function trackRow(t){
  const row=document.createElement('div');
  row.className='trow'; row.dataset.id=t.id; row.draggable=true;
  const mood=t.mood||'Unknown';
  const bpm=t.tempo?Math.round(t.tempo):'';
  const art=t.album_art?`<img class="art" src="${esc(t.album_art)}" loading="lazy">`:`<div class="art"></div>`;
  row.innerHTML=`${art}
    <div class="meta"><div class="t-name">${esc(t.name)}</div>
      <div class="t-artist">${esc((t.artists||[]).join(', '))}</div></div>
    <span class="t-mood mood-${mood}">${mood}</span>
    <span class="t-bpm">${bpm?bpm+' bpm':''}</span>
    <span class="t-dur">${fmtDur(t.duration_ms)}</span>`;
  row.addEventListener('click', e=>toggleSel(t.id,row));
  row.addEventListener('dragstart', e=>{
    const ids = S.selected.has(t.id)&&S.selected.size>0 ? [...S.selected] : [t.id];
    e.dataTransfer.setData('ids', JSON.stringify(ids));
    e.dataTransfer.effectAllowed='copy';
    row.classList.add('dragging');
  });
  row.addEventListener('dragend', ()=>row.classList.remove('dragging'));
  if(S.selected.has(t.id)) row.classList.add('sel');
  return row;
}
function toggleSel(id,row){
  if(S.selected.has(id)){ S.selected.delete(id); row.classList.remove('sel'); }
  else { S.selected.add(id); row.classList.add('sel'); }
}

/* ── playlists + workspace (Kanban) ─────────────────────── */
async function loadPlaylists(){ S.playlists = await api('/api/playlists'); }
function plById(id){ return S.playlists.find(p=>p.id===id); }

async function loadWorkspace(){
  S.workspace = await api('/api/workspace');
  // first run: auto-pin liked songs + a couple owned playlists if workspace empty
  if(S.workspace.length===0 && S.playlists.length){
    const auto = S.playlists.filter(p=>!p.followed).slice(0,4).map(p=>p.id);
    if(auto.length){ S.workspace = auto.map((id,i)=>({slot:i,playlist_id:id})); await saveWorkspace(); }
  }
  renderKanban();
}
async function saveWorkspace(){
  await api('/api/workspace','POST',{ slots: S.workspace.map(w=>w.playlist_id) });
}

function renderKanban(){
  const wrap=$('kanban-cols');
  wrap.querySelectorAll('.kcol').forEach(c=>c.remove());
  const addBtn=$('btn-add-col');
  for(const w of S.workspace){
    const pl=plById(w.playlist_id); if(!pl) continue;
    wrap.insertBefore(kanbanCol(pl), addBtn);
  }
}

function kanbanCol(pl){
  const col=document.createElement('div');
  col.className='kcol'; col.dataset.id=pl.id;
  const badge = pl.local_only?'<span class="kcol-badge">local</span>'
              : pl.followed?'<span class="kcol-badge" style="background:#1a1a3a;color:#88f">followed</span>':'';
  col.innerHTML=`
    <div class="kcol-head">
      <div class="kcol-title">
        <span class="kcol-name">${esc(pl.name)}</span>${badge}
        <span class="kcol-x" title="Remove column">✕</span>
      </div>
      <div class="kcol-count">${pl.actual_count||pl.track_count||0} songs</div>
    </div>
    <div class="kcol-body"><div class="kcol-empty">drag songs here</div></div>`;

  col.querySelector('.kcol-x').addEventListener('click',()=>removeColumn(pl.id));

  // drop target
  col.addEventListener('dragover', e=>{ e.preventDefault(); col.classList.add('drag-over'); });
  col.addEventListener('dragleave', e=>{ if(!col.contains(e.relatedTarget)) col.classList.remove('drag-over'); });
  col.addEventListener('drop', async e=>{
    e.preventDefault(); col.classList.remove('drag-over');
    const ids=JSON.parse(e.dataTransfer.getData('ids')||'[]');
    if(ids.length) await addToPlaylist(pl.id, ids);
  });

  loadColTracks(pl.id, col);
  return col;
}

async function loadColTracks(plId, col){
  const d = await api(`/api/tracks?playlist=${plId}&limit=300`);
  const body = col.querySelector('.kcol-body');
  if(!d.tracks.length){ body.innerHTML='<div class="kcol-empty">drag songs here</div>'; return; }
  body.innerHTML='';
  for(const t of d.tracks){
    const kt=document.createElement('div'); kt.className='kt';
    const art=t.album_art?`<img class="kt-art" src="${esc(t.album_art)}" loading="lazy">`:`<div class="kt-art"></div>`;
    kt.innerHTML=`${art}
      <div class="kt-info"><div class="kt-name">${esc(t.name)}</div>
        <div class="kt-artist">${esc((t.artists||[]).join(', '))}</div></div>
      <span class="kt-x" title="Remove">✕</span>`;
    kt.querySelector('.kt-x').addEventListener('click', async ()=>{
      await api(`/api/playlist/${plId}/remove`,'POST',{track_ids:[t.id]});
      kt.remove(); pollChanges(); refreshColCount(plId);
    });
    body.appendChild(kt);
  }
}

async function addToPlaylist(plId, ids){
  await api(`/api/playlist/${plId}/add`,'POST',{track_ids:ids});
  toast(`Added ${ids.length} song${ids.length>1?'s':''}`,'success');
  S.selected.clear();
  document.querySelectorAll('.trow.sel').forEach(r=>r.classList.remove('sel'));
  await loadPlaylists();
  const col=document.querySelector(`.kcol[data-id="${CSS.escape(plId)}"]`);
  if(col){ loadColTracks(plId,col); refreshColCount(plId); }
  pollChanges();
}
async function refreshColCount(plId){
  await loadPlaylists();
  const pl=plById(plId);
  const col=document.querySelector(`.kcol[data-id="${CSS.escape(plId)}"]`);
  if(col&&pl) col.querySelector('.kcol-count').textContent=`${pl.actual_count||0} songs`;
}

async function removeColumn(plId){
  S.workspace = S.workspace.filter(w=>w.playlist_id!==plId);
  await saveWorkspace(); renderKanban();
}
async function addColumnFor(plId){
  if(S.workspace.some(w=>w.playlist_id===plId)){ toast('Already a column','info'); return; }
  S.workspace.push({slot:S.workspace.length, playlist_id:plId});
  await saveWorkspace(); renderKanban();
}

/* ── add-column modal ───────────────────────────────────── */
function bindAddColumn(){
  $('btn-add-col').addEventListener('click', ()=>{
    $('modal-add-col').classList.remove('hidden');
    renderExistingList();
  });
  document.querySelectorAll('.seg').forEach(s=>s.addEventListener('click',()=>{
    document.querySelectorAll('.seg').forEach(x=>x.classList.remove('active'));
    s.classList.add('active'); S.addColSeg=s.dataset.seg;
    $('seg-new').classList.toggle('hidden', s.dataset.seg!=='new');
    $('seg-existing').classList.toggle('hidden', s.dataset.seg!=='existing');
  }));
  $('btn-create-col').addEventListener('click', async ()=>{
    const name=$('new-col-name').value.trim();
    if(!name){ toast('Name required','error'); return; }
    const res=await api('/api/playlist/create','POST',{name, description:$('new-col-desc').value.trim(), track_ids:[]});
    $('new-col-name').value=''; $('new-col-desc').value='';
    closeModal('modal-add-col');
    await loadPlaylists();
    await addColumnFor(res.id);
    toast(`Playlist "${name}" created`,'success');
  });
  $('existing-search').addEventListener('input', renderExistingList);
}
function renderExistingList(){
  const q=($('existing-search').value||'').toLowerCase();
  const el=$('existing-list'); el.innerHTML='';
  const pinned=new Set(S.workspace.map(w=>w.playlist_id));
  for(const pl of S.playlists){
    if(pinned.has(pl.id)) continue;
    if(q && !pl.name.toLowerCase().includes(q)) continue;
    const d=document.createElement('div'); d.className='existing-item';
    const art=pl.is_liked_songs?`<div class="ph" style="background:linear-gradient(135deg,#450af5,#c4efd9)"></div>`
            : pl.image_url?`<img src="${esc(pl.image_url)}">`:`<div class="ph"></div>`;
    d.innerHTML=`${art}<div><div class="ei-name">${esc(pl.name)}</div>
      <div class="ei-cnt">${pl.actual_count||pl.track_count||0} songs${pl.followed?' · followed':''}</div></div>`;
    d.addEventListener('click', async ()=>{ closeModal('modal-add-col'); await addColumnFor(pl.id); });
    el.appendChild(d);
  }
  if(!el.children.length) el.innerHTML='<div class="hint">No more playlists to add.</div>';
}

/* ── toolbar ────────────────────────────────────────────── */
function bindToolbar(){
  $('sort-select').addEventListener('change', e=>{ S.filters.sort=e.target.value; reload(); });
  $('genre-select').addEventListener('change', e=>{ S.filters.genre=e.target.value; reload(); });
  $('btn-empty-load').addEventListener('click', fetchLibrary);
  $('btn-empty-setup').addEventListener('click', ()=>$('modal-setup').classList.remove('hidden'));
  document.querySelectorAll('.mpill').forEach(p=>p.addEventListener('click',()=>{
    document.querySelectorAll('.mpill').forEach(x=>x.classList.remove('active'));
    p.classList.add('active'); S.filters.mood=p.dataset.mood; reload();
  }));
  $('btn-load-more').addEventListener('click', ()=>{ S.offset+=S.LIMIT; loadTracks(false); });
  $('btn-viz').addEventListener('click', toggleViz);
  $('btn-fetch').addEventListener('click', fetchLibrary);
  $('btn-enrich').addEventListener('click', runEnrich);
}

/* ── topbar ─────────────────────────────────────────────── */
function bindTopbar(){
  $('btn-setup').addEventListener('click', ()=>$('modal-setup').classList.remove('hidden'));
  $('btn-push').addEventListener('click', pushToSpotify);
  $('btn-undo').addEventListener('click', undo);
  $('search-input').addEventListener('input', debounce(e=>{ S.filters.q=e.target.value; reload(); },300));
  $('src-select').addEventListener('change', e=>{ S.source=e.target.value; localStorage.setItem('src',S.source); });
  $('tgt-select').addEventListener('change', e=>{ S.target=e.target.value; localStorage.setItem('tgt',S.target); });
}

/* ── modals ─────────────────────────────────────────────── */
function bindModals(){
  document.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',()=>closeModal(b.dataset.close)));
  document.querySelectorAll('.modal').forEach(m=>m.addEventListener('click',e=>{ if(e.target===m) m.classList.add('hidden'); }));
  $('btn-save-cfg').addEventListener('click', async ()=>{
    const id=$('inp-client-id').value.trim(), sec=$('inp-client-secret').value.trim();
    if(!id||!sec){ toast('Spotify Client ID and Secret are required','error'); return; }
    await api('/api/config','POST',{client_id:id, client_secret:sec, lastfm_api_key:$('inp-lastfm').value.trim()});
    toast('Saved — now connect an account below','success');
    $('inp-client-secret').value=''; $('inp-lastfm').value=''; loadStatus();
  });
}
function closeModal(id){ $(id).classList.add('hidden'); }

/* ── fetch library ──────────────────────────────────────── */
async function fetchLibrary(){
  const label = S.source || (S.status.new?.ok?'new':(S.status.old?.ok?'old':null));
  if(!label || !S.status[label]?.ok){ toast('Connect an account first (⚙)','error'); $('modal-setup').classList.remove('hidden'); return; }
  const srcName = S.status[label].name;
  showProgress(`Loading library from ${srcName}…`,['liked_songs','playlists','audio_features','genres']);
  const sse=new EventSource('/api/stream');
  sse.onmessage=e=>{
    const ev=JSON.parse(e.data);
    if(ev.type==='progress') setBar(ev.cat,ev.done,ev.total);
    else if(ev.type==='log') logLine(ev.msg,ev.level);
    else if(ev.type==='fetch_done'||ev.type==='error'){
      sse.close();
      setTimeout(()=>{ hideProgress(); loadLanguages(); loadGenres(); loadPlaylists().then(loadWorkspace); reload(); toast('Library loaded!','success'); },700);
    }
  };
  await api('/api/library/fetch','POST',{account:label});
}

/* ── enrich (Last.fm) ───────────────────────────────────── */
async function runEnrich(){
  if(!S.status.library_loaded){ toast('Load your library first','info'); return; }
  if(!S.status.has_lastfm){
    toast('Add a Last.fm API key in Setup first','error');
    $('modal-setup').classList.remove('hidden'); return;
  }
  showProgress('Enriching languages & genres from Last.fm…',['enrich']);
  const sse=new EventSource('/api/stream');
  sse.onmessage=e=>{
    const ev=JSON.parse(e.data);
    if(ev.type==='progress') setBar(ev.cat,ev.done,ev.total);
    else if(ev.type==='log') logLine(ev.msg,ev.level);
    else if(ev.type==='enrich_done'||ev.type==='error'){
      sse.close();
      setTimeout(()=>{ hideProgress(); loadLanguages(); loadGenres(); reload();
        toast(`Enriched ${ev.hit||0} songs — languages & genres updated`,'success'); },700);
    }
  };
  await api('/api/enrich','POST');
}

/* ── push ───────────────────────────────────────────────── */
async function pushToSpotify(){
  if(!S.pending){ toast('No pending changes','info'); return; }
  const label = S.target || (S.status.new?.ok?'new':(S.status.old?.ok?'old':null));
  if(!label || !S.status[label]?.ok){ toast('Pick a target account (⚙)','error'); return; }
  const tgtName=S.status[label].name;
  const mode = (S.source===S.target) ? `edit ${tgtName}'s library in place` : `migrate into ${tgtName}'s account`;
  if(!confirm(`Push ${S.pending} change(s) — ${mode}.\n\nPlaylists with matching names are merged (no dupes); new names are created.`)) return;
  showProgress(`Pushing ${S.pending} changes…`,[]);
  const sse=new EventSource('/api/stream');
  sse.onmessage=e=>{
    const ev=JSON.parse(e.data);
    if(ev.type==='log') logLine(ev.msg,ev.level);
    else if(ev.type==='push_done'||ev.type==='error'){
      sse.close();
      setTimeout(()=>{ hideProgress(); pollChanges(); loadPlaylists().then(renderKanban);
        toast(`Pushed ${ev.pushed||0} ops${ev.created?', '+ev.created+' playlists created':''}`,'success'); },700);
    }
  };
  await api('/api/push','POST',{account:label});
}

async function undo(){
  const r=await api('/api/undo','POST');
  if(r.undone){ toast('Change undone','info'); reload(); loadPlaylists().then(renderKanban); pollChanges(); }
  else toast('Nothing to undo','info');
}

/* ── inline viz (mood map) ──────────────────────────────── */
const MC={ Happy:'#ffd700',Sad:'#6495ed',Energetic:'#ff6b35',Chill:'#40e0d0',Dance:'#ff69b4',
  Angry:'#dc143c',Romantic:'#ff8da1',Focus:'#9370db',Neutral:'#888',Unknown:'#3a3a3a' };

function bindViz(){
  $('btn-viz-close').addEventListener('click', ()=>{ S.vizOpen=false; $('viz-panel').classList.add('hidden'); });
  const c=$('viz-canvas');
  c.addEventListener('mousemove', vizHover);
  c.addEventListener('click', vizClick);
}
async function toggleViz(){
  S.vizOpen=!S.vizOpen;
  $('viz-panel').classList.toggle('hidden', !S.vizOpen);
  if(S.vizOpen){ const q=S.filters.lang?`?language=${encodeURIComponent(S.filters.lang)}`:'';
    S.vizData=await api('/api/mood-map'+q); drawViz(); }
}
function drawViz(){
  const c=$('viz-canvas'), x=c.getContext('2d'), W=c.width, H=c.height, P=24;
  x.clearRect(0,0,W,H);
  x.strokeStyle='#181818'; x.lineWidth=1;
  x.beginPath(); x.moveTo(P,H/2); x.lineTo(W-P,H/2); x.stroke();
  x.beginPath(); x.moveTo(W/2,P); x.lineTo(W/2,H-P); x.stroke();
  for(const t of S.vizData){
    const px=P+(t.valence||0)*(W-P*2), py=(H-P)-(t.energy||0)*(H-P*2);
    const col=MC[t.mood]||'#3a3a3a';
    x.beginPath(); x.arc(px,py,3.2,0,7); x.fillStyle=col+'aa'; x.fill();
  }
}
function vizNearest(e){
  const c=$('viz-canvas'), r=c.getBoundingClientRect();
  const mx=(e.clientX-r.left)*(c.width/r.width), my=(e.clientY-r.top)*(c.height/r.height);
  const W=c.width,H=c.height,P=24; let best=null,bd=14;
  for(const t of S.vizData){
    const px=P+(t.valence||0)*(W-P*2), py=(H-P)-(t.energy||0)*(H-P*2);
    const d=Math.hypot(mx-px,my-py); if(d<bd){ bd=d; best=t; }
  }
  return best;
}
function vizHover(e){
  const t=vizNearest(e), tip=$('viz-tooltip');
  if(t){ tip.classList.remove('hidden'); tip.style.left=(e.offsetX+12)+'px'; tip.style.top=(e.offsetY-10)+'px';
    const arts=Array.isArray(t.artists)?t.artists.join(', '):JSON.parse(t.artists||'[]').join(', ');
    tip.innerHTML=`<b>${esc(t.name)}</b><br><span style="color:#888">${esc(arts)}</span><br>
      <span style="color:${MC[t.mood]||'#888'}">${t.mood}</span> · ${Math.round((t.energy||0)*100)}% energy`;
  } else tip.classList.add('hidden');
}
function vizClick(e){
  const t=vizNearest(e); if(!t) return;
  S.filters.mood=t.mood;
  document.querySelectorAll('.mpill').forEach(p=>p.classList.toggle('active',p.dataset.mood===t.mood));
  reload();
}

/* ── progress overlay ───────────────────────────────────── */
function showProgress(title,cats){
  $('prog-title').textContent=title; $('prog-rows').innerHTML=''; $('prog-log').innerHTML='';
  $('progress-overlay').classList.remove('hidden');
  for(const c of cats){
    const d=document.createElement('div'); d.className='prow';
    d.innerHTML=`<div class="prow-label"><span>${catLabel(c)}</span><span id="pp-${c}">waiting</span></div>
      <div class="prow-bar"><div class="prow-fill" id="pf-${c}"></div></div>`;
    $('prog-rows').appendChild(d);
  }
}
function setBar(cat,done,total){
  const f=$('pf-'+cat), t=$('pp-'+cat); if(!f)return;
  f.style.width=(total>0?Math.round(done/total*100):0)+'%';
  if(t) t.textContent=total>0?`${done}/${total}`:'…';
}
function logLine(msg,level){
  const l=document.createElement('div'); l.className='lg '+(level||''); l.textContent=msg;
  $('prog-log').appendChild(l); $('prog-log').scrollTop=$('prog-log').scrollHeight;
}
function hideProgress(){ $('progress-overlay').classList.add('hidden'); }

/* ── helpers ────────────────────────────────────────────── */
function fmtDur(ms){ if(!ms)return''; const s=Math.floor(ms/1000); return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`; }
function catLabel(c){ return {liked_songs:'Liked Songs',playlists:'Playlists',audio_features:'Audio Features',genres:'Genres',enrich:'Last.fm tags'}[c]||c; }
function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function debounce(fn,ms){ let t; return (...a)=>{ clearTimeout(t); t=setTimeout(()=>fn(...a),ms); }; }
function toast(msg,type='info',dur=3000){
  const el=document.createElement('div'); el.className='toast '+type; el.textContent=msg;
  $('toast-stack').appendChild(el); setTimeout(()=>el.remove(),dur);
}
async function api(url,method='GET',body=null){
  const o={method,headers:{'Content-Type':'application/json'}};
  if(body) o.body=JSON.stringify(body);
  const r=await fetch(url,o); return r.json();
}
