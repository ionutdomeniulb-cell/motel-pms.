/* Recepția de noapte: dialoguri mari pentru telefon, fără handlere inline (compatibil cu CSP). */
(() => {
  const fill = (dlg, data) => { Object.entries(data).forEach(([k, v]) => dlg.querySelectorAll(`[data-${k}]`).forEach(el => { el.textContent = v; })); };
  const open = (id, btn, resetForm) => {
    const dlg = document.getElementById(id), form = dlg.querySelector('form');
    if (resetForm) { form.reset(); form.querySelectorAll('input').forEach(i => i.setCustomValidity('')); }
    form.action = btn.dataset.action;
    fill(dlg, {room: btn.dataset.room, name: btn.dataset.name || '', rate: btn.dataset.rate || ''});
    dlg.showModal();
  };
  document.addEventListener('click', e => {
    let b = e.target.closest('[data-night-room]'); if (b) return open('ndRoomDialog', b, true);
    b = e.target.closest('[data-night-arrived]'); if (b) return open('ndArrivedDialog', b, true);
    b = e.target.closest('[data-night-cancel]'); if (b) return open('ndCancelDialog', b, false);
  });
  // „Cazează acum” cere plata aleasă (la „Rezervă” plata nu se cere)
  const roomForm = document.getElementById('ndRoomForm');
  // Mesajul de validare trebuie șters imediat ce se alege plata; altfel browserul blochează trimiterea înainte de evenimentul „submit”
  const clearPay = () => { if (roomForm) roomForm.querySelectorAll('input[name=payment]').forEach(r => r.setCustomValidity('')); };
  if (roomForm) roomForm.addEventListener('change', e => { if (e.target.name === 'payment') clearPay(); });
  if (roomForm) roomForm.addEventListener('submit', e => {
    const radios = roomForm.querySelectorAll('input[name=payment]'), first = radios[0];
    first.setCustomValidity('');
    if (e.submitter && e.submitter.value === 'occupy' && ![...radios].some(r => r.checked)) {
      e.preventDefault(); first.setCustomValidity('Alegeți cum se plătește.'); first.reportValidity();
    }
  });
  // Reîmprospătare la 45 s dacă nu se lucrează în pagină
  setInterval(() => {
    if (document.hidden || document.querySelector('dialog[open]')) return;
    const el = document.activeElement; if (el && el.matches('input, select, textarea')) return;
    location.reload();
  }, 45000);
})();
