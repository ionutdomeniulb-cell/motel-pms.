/* Interfață: confirmări și ferestre de dialog fără handlere inline (compatibil cu Content-Security-Policy strict). */
(() => {
  // <form data-confirm="Mesaj"> cere confirmare înainte de trimitere
  document.addEventListener('submit', e => {
    const msg = e.target.dataset && e.target.dataset.confirm;
    if (msg && !window.confirm(msg)) e.preventDefault();
  }, true);
  // <button data-open-dialog="id"> deschide un dialog; <button data-close-dialog> îl închide
  document.addEventListener('click', e => {
    const open = e.target.closest('[data-open-dialog]');
    if (open) { const d = document.getElementById(open.dataset.openDialog); if (d && d.showModal) d.showModal(); return; }
    const close = e.target.closest('[data-close-dialog]');
    if (close) { const d = close.closest('dialog'); if (d) d.close(); }
  });

  // Anulare grup: bifare individuală sau tot grupul, cu fereastră de confirmare
  const updateGroup = f => {
    const n = f.querySelectorAll('input[name=booking_ids]:checked').length;
    const counter = f.querySelector('[data-count]'); if (counter) counter.textContent = n;
    const btn = f.querySelector('[data-group-action=selected]'); if (btn) btn.disabled = n === 0;
  };
  document.addEventListener('change', e => { const f = e.target.closest && e.target.closest('[data-group-form]'); if (f) updateGroup(f); });
  document.addEventListener('click', e => {
    const btn = e.target.closest('[data-group-action]');
    if (!btn || btn.disabled) return;
    const f = btn.closest('[data-group-form]'), dlg = document.getElementById('groupConfirm');
    if (!f || !dlg) return;
    const scope = btn.dataset.groupAction;
    const rooms = [...f.querySelectorAll('input[name=booking_ids]')].filter(i => !i.disabled && (scope === 'all' || i.checked)).map(i => i.dataset.room);
    dlg.querySelector('[data-title]').textContent = scope === 'all' ? 'Anulați ÎNTREGUL grup?' : `Anulați ${rooms.length} ${rooms.length === 1 ? 'cameră' : 'camere'}?`;
    dlg.querySelector('[data-body]').textContent = scope === 'all' ? 'Toate camerele active ale grupului vor fi eliberate:' : 'Doar aceste camere vor fi eliberate. Celelalte rămân neschimbate:';
    const list = dlg.querySelector('[data-rooms]'); list.replaceChildren(...rooms.map(r => { const li = document.createElement('li'); li.textContent = `Camera ${r}`; return li; }));
    dlg.returnValue = '';
    dlg.addEventListener('close', () => {
      if (dlg.returnValue !== 'ok') return;
      f.querySelector('[name=scope]').value = scope;
      f.querySelector('[name=confirmed]').value = '1';
      if (scope === 'all') f.querySelectorAll('input[name=booking_ids]').forEach(i => { i.checked = false; });
      f.submit();
    }, {once: true});
    dlg.showModal();
  });
  document.querySelectorAll('[data-group-form]').forEach(updateGroup);
})();

/* Calendar: glisare pe telefon (la marginea tabelului) = perioada anterioară / următoare */
(() => {
  let startX = 0, startY = 0, startLeft = 0, box = null;
  document.addEventListener('touchstart', e => {
    box = e.target.closest && e.target.closest('.calendar-scroll');
    if (!box) return;
    startX = e.touches[0].clientX; startY = e.touches[0].clientY; startLeft = box.scrollLeft;
  }, {passive: true});
  document.addEventListener('touchend', e => {
    if (!box) return;
    const dx = e.changedTouches[0].clientX - startX, dy = e.changedTouches[0].clientY - startY;
    const atStart = startLeft <= 2, atEnd = startLeft + box.clientWidth >= box.scrollWidth - 2;
    box = null;
    if (Math.abs(dx) < 80 || Math.abs(dy) > 60) return;
    const link = document.querySelector(dx < 0 && atEnd ? '[data-cal-next]' : dx > 0 && atStart ? '[data-cal-prev]' : null);
    if (link) location.href = link.href;
  }, {passive: true});
})();
