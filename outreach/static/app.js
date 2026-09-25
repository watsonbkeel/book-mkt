'use strict';
for (const form of document.querySelectorAll('form[data-confirm]')) {
  form.addEventListener('submit', event => { if (!window.confirm(form.dataset.confirm)) event.preventDefault(); });
}
// Update counters only, never auto-send or auto-approve from a browser.
if (document.querySelector('[data-metric]')) {
  window.setInterval(async () => {
    try {
      const response = await fetch('/api/summary', { credentials: 'same-origin' });
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) return;
      const data = await response.json();
      for (const node of document.querySelectorAll('[data-metric]')) {
        if (typeof data[node.dataset.metric] === 'number') node.textContent = String(data[node.dataset.metric]);
      }
    } catch (_) { /* Offline counters remain the last server-rendered values. */ }
  }, 30000);
}
