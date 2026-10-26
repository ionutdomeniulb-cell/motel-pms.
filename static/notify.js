/* Alerte recepție ↔ cameriste (v15, regândit pentru telefon/tabletă: Android și iOS).
   Principii: sunet din fișiere audio (HTMLAudio, nu WebAudio, ca să sune și cu butonul silențios pe iOS), deblocare la orice atingere,
   detectarea blocajelor (play care nu răspunde → element nou), o singură buclă de control care se repornește la revenirea în pagină,
   timeout pe toate cererile de rețea, indicator de conexiune și ecran menținut aprins (unde browserul permite). */
(() => {
  const root = document.getElementById('pmsNotify');
  if (!root) return;
  const cfg = {endpoint: root.dataset.endpoint, updates: root.dataset.updates, user: root.dataset.user, audience: root.dataset.audience,
               urgentUrl: root.dataset.soundUrgent, infoUrl: root.dataset.soundInfo};
  const K = {last: `pms.notify.last.${cfg.user}`, pending: `pms.notify.pending.${cfg.user}`, sound: 'pms.notify.sound', awake: 'pms.notify.awake'};
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (_) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) { /* stocare indisponibilă */ } },
  };
  const baseTitle = document.title;
  const now = () => Date.now();
  const livePage = ['/', '/housekeeping'].includes(location.pathname);

  /* ================= SUNET ================= */
  const Sound = (() => {
    let soundOn = store.get(K.sound, true), armed = false, blockedAttempt = false, hiddenAt = 0, urgentEl = null, infoEl = null;
    const make = url => { const a = new Audio(url); a.preload = 'auto'; a.setAttribute('playsinline', ''); a.load(); return a; };
    const build = () => { urgentEl = make(cfg.urgentUrl); infoEl = make(cfg.infoUrl); };
    try { if (navigator.audioSession) navigator.audioSession.type = 'playback'; } catch (_) { /* nu e disponibil */ }
    build();
    const timeout = (p, ms) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(Object.assign(new Error('timeout'), {name: 'TimeoutError'})), ms))]);

    /* Apelat în interiorul unui gest al utilizatorului: deblochează ambele elemente audio (fișierele încep cu 80 ms de liniște). */
    function unlock() {
      if (armed || !soundOn) return;
      let pending = 2, okCount = 0;
      const done = ok => { pending--; if (ok) okCount++; if (!pending) { armed = okCount > 0; UI.update(); } };
      [urgentEl, infoEl].forEach(el => {
        try {
          const p = el.play();
          if (p && p.then) p.then(() => { el.pause(); el.currentTime = 0; done(true); }).catch(() => done(false)); else done(true);
        } catch (_) { done(false); }
      });
    }
    async function play(level) {
      if (!soundOn) return false;
      const el = level === 'urgent' ? urgentEl : infoEl;
      try {
        el.pause(); el.currentTime = 0; el.muted = false; el.volume = 1;
        await timeout(el.play(), 2500);
        armed = true; UI.update(); return true;
      } catch (e) {
        armed = false; blockedAttempt = true;             // blocat sau „agățat”: cerem o atingere și refacem elementele
        if (e.name === 'TimeoutError') build();
        UI.update(); return false;
      }
    }
    return {
      unlock, play,
      get on() { return soundOn; }, get armed() { return armed; },
      set on(v) { soundOn = !!v; store.set(K.sound, soundOn); if (!soundOn) armed = false; },
      get locked() { return soundOn && !armed; },
      get needsAttention() { return soundOn && !armed && (cfg.audience === 'housekeeping' || blockedAttempt); },   // bara mare: cameriste sau după o alertă care n-a putut suna
      markHidden() { hiddenAt = now(); },
      resumed() { if (hiddenAt && now() - hiddenAt > 45000) armed = false; hiddenAt = 0; },  // după fundal lung, iOS poate fi resetat sunetul
    };
  })();

  /* ================= REȚEA ================= */
  async function fetchJson(url, ms = 8000) {
    const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), ms);
    try {
      const r = await fetch(url, {headers: {Accept: 'application/json'}, cache: 'no-store', credentials: 'same-origin', signal: ctl.signal});
      if (r.redirected && /\/login/.test(r.url)) { location.reload(); return null; }
      if (!r.ok || !(r.headers.get('content-type') || '').includes('json')) return null;
      return await r.json();
    } finally { clearTimeout(t); }
  }
  let lastOk = now();

  /* ================= ALERTE ================= */
  const box = document.createElement('div');
  box.className = 'pms-alerts'; box.setAttribute('role', 'region'); box.setAttribute('aria-label', 'Alerte'); box.setAttribute('aria-live', 'assertive');
  document.body.append(box);
  const shown = new Map();
  const pendingList = () => store.get(K.pending, []);
  let lastUrgentAt = 0, repeats = 0, flashOn = false;

  function render(item, persistent) {
    if (shown.has(item.id)) return;
    const el = document.createElement('div');
    el.className = `pms-alert ${item.priority === 'urgent' ? 'pms-urgent' : 'pms-normal'}`; el.setAttribute('role', 'alert');
    const body = document.createElement('div'); body.className = 'pms-alert-body';
    const title = document.createElement('b'); title.textContent = item.title;
    const text = document.createElement('span'); text.textContent = item.text;
    const time = document.createElement('small');
    time.textContent = new Date(item.created_at || now()).toLocaleTimeString('ro-RO', {hour: '2-digit', minute: '2-digit'});
    body.append(title, text, time);
    const actions = document.createElement('div'); actions.className = 'pms-alert-actions';
    if (cfg.audience === 'reception' && location.pathname !== '/') { const a = document.createElement('a'); a.href = '/#hkPanel'; a.textContent = 'Deschide'; actions.append(a); }
    const ok = document.createElement('button'); ok.type = 'button'; ok.textContent = 'Am văzut'; ok.addEventListener('click', () => dismiss(item.id));
    actions.append(ok); el.append(body, actions); box.append(el); shown.set(item.id, el);
    if (!persistent) setTimeout(() => dismiss(item.id), 20000);
  }
  function dismiss(id) {
    const el = shown.get(id); if (el) { el.remove(); shown.delete(id); }
    store.set(K.pending, pendingList().filter(x => x.id !== id));
    if (!pendingList().length) { repeats = 0; document.title = baseTitle; }
  }
  async function announce(items, {persistUrgent = true} = {}) {
    if (!items.length) return;
    let urgent = false;
    items.forEach(item => {
      const isUrgent = item.priority === 'urgent'; urgent = urgent || isUrgent;
      if (isUrgent && persistUrgent) store.set(K.pending, pendingList().filter(x => x.id !== item.id).concat(item));
      render(item, isUrgent);
      if ('Notification' in window && window.isSecureContext && Notification.permission === 'granted' && document.hidden) {
        try { new Notification(item.title, {body: item.text, tag: `pms-${item.id}`, requireInteraction: isUrgent}); } catch (_) { /* ignorat */ }
      }
    });
    if (urgent) { if (navigator.vibrate) navigator.vibrate([300, 120, 300, 120, 300]); lastUrgentAt = now(); repeats = 0; }
    await Sound.play(urgent ? 'urgent' : 'info');
    UI.update();
  }

  /* ================= ECRAN ACTIV ================= */
  const Awake = (() => {
    let lock = null, want = store.get(K.awake, cfg.audience === 'housekeeping');
    const supported = () => 'wakeLock' in navigator && window.isSecureContext;
    async function acquire() {
      if (!want || !supported() || lock || document.hidden) return;
      try { lock = await navigator.wakeLock.request('screen'); lock.addEventListener('release', () => { lock = null; UI.update(); }); } catch (_) { lock = null; }
      UI.update();
    }
    return {supported, acquire, get want() { return want; }, set want(v) { want = !!v; store.set(K.awake, want); if (!want && lock) { lock.release().catch(() => {}); lock = null; } UI.update(); },
            get active() { return !!lock; }};
  })();

  /* ================= INTERFAȚĂ (buton, bară de sunet blocat, panou) ================= */
  const UI = (() => {
    const control = document.createElement('div'); control.className = 'pms-control';
    control.innerHTML = '<button type="button" class="pms-soundbar" hidden></button><button type="button" class="pms-control-toggle" aria-expanded="false"></button><div class="pms-control-panel" hidden></div>';
    document.body.append(control);
    const bar = control.querySelector('.pms-soundbar'), toggle = control.querySelector('.pms-control-toggle'), panel = control.querySelector('.pms-control-panel');
    bar.textContent = '🔇 Sunet blocat de browser — atingeți aici pentru a-l activa';
    bar.addEventListener('click', () => { Sound.unlock(); setTimeout(update, 300); });
    const btn = (label, fn) => { const b = document.createElement('button'); b.type = 'button'; b.textContent = label; b.addEventListener('click', fn); return b; };
    const testItem = (priority, title, text) => ({id: `test-${priority}-${now()}`, priority, title, text, created_at: new Date().toISOString()});
    function build() {
      panel.replaceChildren();
      panel.append(btn(Sound.on ? 'Sunet: pornit (apăsați pentru oprire)' : 'Sunet: oprit (apăsați pentru pornire)', () => { Sound.on = !Sound.on; Sound.unlock(); update(); }));
      panel.append(btn('Testează alerta urgentă', () => { Sound.unlock(); announce([testItem('urgent', 'Test: solicitare nouă', 'Camera 101 · Curățenie (alertă de probă)')], {persistUrgent: false}); }));
      panel.append(btn('Testează alerta de informare', () => { Sound.unlock(); announce([testItem('normal', 'Test: informare', 'Camera 101 a fost marcată curată (alertă de probă)')]); }));
      if (Awake.supported()) panel.append(btn(Awake.want ? 'Ecran activ: pornit (apăsați pentru oprire)' : 'Ecran activ: oprit (apăsați pentru pornire)', () => { Awake.want = !Awake.want; if (Awake.want) Awake.acquire(); }));
      if ('Notification' in window && window.isSecureContext && Notification.permission !== 'granted') panel.append(btn('Activează notificările din browser', () => Notification.requestPermission().then(update)));
      const note = document.createElement('p');
      note.textContent = window.isSecureContext ? 'Atingeți ecranul după deschiderea paginii pentru a activa sunetul. Lăsați pagina deschisă și ecranul pornit.'
        : 'Conexiune HTTP: ecranul activ și notificările din browser sunt indisponibile. Folosiți HTTPS (vezi MOBIL.md) sau setați ecranul să nu se stingă.';
      panel.append(note);
    }
    function update() {
      const offline = now() - lastOk > 30000;
      bar.hidden = !Sound.needsAttention;
      toggle.textContent = offline ? '⚠ Fără conexiune la PMS' : (!Sound.on ? '🔕 Sunet oprit' : (Sound.locked ? '🔇 Sunet blocat' : '🔔 Alerte active'));
      toggle.classList.toggle('is-locked', offline || Sound.locked || !Sound.on);
      build();
    }
    toggle.addEventListener('click', () => { Sound.unlock(); const open = panel.hidden; panel.hidden = !open; toggle.setAttribute('aria-expanded', String(open)); update(); });
    return {update};
  })();

  // Orice atingere deblochează sunetul (iOS cere touchend/click, nu touchstart).
  ['touchend', 'click', 'keydown'].forEach(ev => document.addEventListener(ev, () => { if (Sound.locked) Sound.unlock(); Awake.acquire(); }, {capture: true, passive: true}));

  /* ================= ALERTE NOI + ACTUALIZARE LIVE ================= */
  const seen = new Set();
  let polling = false, pollStarted = 0, lastPoll = 0, lastSig = 0, signature = null;
  async function pollOnce() {
    if (polling && now() - pollStarted < 4000) return;   // o cerere agățată >4 s nu mai blochează: pornim alta imediat
    polling = true; pollStarted = lastPoll = now();
    try {
      const last = store.get(K.last, null);
      const d = await fetchJson(cfg.endpoint + (last === null ? '' : `?after_id=${encodeURIComponent(last)}`));
      if (!d) return;
      lastOk = now();
      store.set(K.last, last !== null && d.last_id < last ? d.last_id : Math.max(d.last_id, last || 0));
      const open = new Set(d.open_request_ids || []);
      pendingList().filter(x => x.request_id && !open.has(x.request_id)).forEach(x => dismiss(x.id));
      const fresh = (d.items || []).filter(i => !seen.has(i.id)); fresh.forEach(i => seen.add(i.id));   // cereri paralele nu dublează alerta
      if (fresh.length) { await announce(fresh); refreshSoon(); }
    } catch (_) { /* reîncercăm la următorul ciclu */ } finally { polling = false; UI.update(); }
  }
  async function checkSignature() {
    lastSig = now();
    try {
      const d = await fetchJson(cfg.updates); if (!d) return;
      const sig = JSON.stringify([(d.requests || []).map(x => [x.id, x.status, x.completed_at]), d.latest_booking_update, d.latest_cleaning_update]);
      if (signature !== null && sig !== signature) refreshSoon();
      signature = sig;
    } catch (_) { /* următorul ciclu */ }
  }
  const hasActiveEntry = () => { const el = document.activeElement; return (el && (el.matches('input, textarea, select') || el.isContentEditable)) || document.querySelector('dialog[open]'); };
  let busy = false, busyAt = 0, refreshTimer = null, lastRefresh = now();
  async function refreshMain() {
    if (!livePage || (busy && now() - busyAt < 15000) || hasActiveEntry()) return;
    busy = true; busyAt = now(); lastRefresh = now();
    const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), 10000);
    try {
      const r = await fetch(location.href, {cache: 'no-store', credentials: 'same-origin', headers: {Accept: 'text/html'}, signal: ctl.signal});
      if (r.redirected && /\/login/.test(r.url)) { location.reload(); return; }
      if (!r.ok) return;
      const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
      const next = doc.querySelector('main'), cur = document.querySelector('main');
      if (!next || !cur) return;
      const sc = cur.querySelector('.calendar-scroll'), left = sc ? sc.scrollLeft : 0;
      cur.replaceChildren(...next.childNodes);
      const sc2 = cur.querySelector('.calendar-scroll'); if (sc2) sc2.scrollLeft = left;
      applyDetails();
    } catch (_) { /* următoarea încercare */ } finally { clearTimeout(t); busy = false; }
  }
  function refreshSoon() { if (!livePage) return; clearTimeout(refreshTimer); refreshTimer = setTimeout(refreshMain, 800); }

  /* ================= SECȚIUNI EXTINDERE / RESTRÂNGERE ================= */
  function applyDetails() {
    document.querySelectorAll('details[data-persist]').forEach(d => { d.open = d.dataset.forceOpen ? true : store.get(`pms.details.${d.dataset.persist}`, false); });
  }
  document.addEventListener('toggle', e => { const d = e.target; if (d.matches && d.matches('details[data-persist]') && !d.dataset.forceOpen) store.set(`pms.details.${d.dataset.persist}`, d.open); }, true);

  /* ================= BUCLA DE CONTROL (o singură sursă de timp) ================= */
  function tick() {
    const hidden = document.hidden, every = hidden ? 15000 : 5000, t = now();
    if (t - lastPoll >= every) pollOnce();
    if (livePage && t - lastSig >= every) checkSignature();
    if (livePage && t - lastRefresh >= 60000) refreshMain();                         // schimbările bazate pe oră (ex. 13:00)
    const urgent = pendingList().length;
    if (urgent && Sound.on && t - lastUrgentAt >= 20000 && repeats < 6) { repeats++; lastUrgentAt = t; Sound.play('urgent'); }   // repetare, cu recuperare după fundal
    if (urgent && hidden) { flashOn = !flashOn; document.title = flashOn ? '🔔 Solicitare nouă' : baseTitle; } else if (!urgent && document.title !== baseTitle) document.title = baseTitle;
    if ((t - lastOk > 30000) !== !!UI._offline) { UI._offline = t - lastOk > 30000; UI.update(); }
  }
  function resume() { Sound.resumed(); Awake.acquire(); lastPoll = 0; lastSig = 0; tick(); UI.update(); }
  document.addEventListener('visibilitychange', () => { if (document.hidden) Sound.markHidden(); else resume(); });
  window.addEventListener('pageshow', e => { if (e.persisted) { pendingList().forEach(i => render(i, true)); } resume(); });   // revenire din cache (iOS Safari)
  window.addEventListener('online', resume); window.addEventListener('focus', resume);
  window.addEventListener('storage', e => { if (e.key === K.pending && !pendingList().length) [...shown.keys()].forEach(id => { if (!String(id).startsWith('test-')) dismiss(id); }); });

  applyDetails(); UI.update();
  pendingList().forEach(item => render(item, true));      // alertele neconfirmate rămân vizibile după navigare
  tick(); setInterval(tick, 1000);
  window.PMS = {test: () => announce([{id: `test-${now()}`, priority: 'urgent', title: 'Test', text: 'Alertă de probă', created_at: new Date().toISOString()}], {persistUrgent: false}),
                refreshMain, poll: pollOnce, debug: () => ({polling, sincePollStart: now() - pollStarted, sinceLastPoll: now() - lastPoll, sinceLastOk: now() - lastOk, hidden: document.hidden}), sound: {get armed() { return Sound.armed; }, get locked() { return Sound.locked; }, play: Sound.play}};
})();
