/* Canopy: database-backed preferences and messaging; no fabricated report data. */
(() => {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const html = document.documentElement;
  const authenticated = html.dataset.authenticated === 'true';
  const storage = {
    get(key) { try { return localStorage.getItem(`canopy:${key}`); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(`canopy:${key}`, value); } catch { /* Storage is optional for guests. */ } }
  };
  const csrf = () => document.querySelector('input[name=csrfmiddlewaretoken]')?.value || decodeURIComponent(document.cookie.split('; ').find((item) => item.startsWith('csrftoken='))?.split('=')[1] || '');
  let toastTimer;
  const toast = (message) => {
    const node = $('#toast'); if (!node) return;
    node.textContent = message; node.classList.add('visible'); clearTimeout(toastTimer);
    toastTimer = setTimeout(() => node.classList.remove('visible'), 4000);
  };
  const post = async (url, values) => {
    const response = await fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': csrf(), 'Accept': 'application/json' }, body: new URLSearchParams(values) });
    const payload = await response.json().catch(() => null);
    if (!response.ok || response.redirected || payload === null) throw new Error(payload?.error || 'Request failed');
    return payload;
  };
  if (!authenticated) {
    html.dataset.theme = storage.get('theme') === 'dark' ? 'dark' : 'light';
    html.dir = storage.get('direction') === 'ltr' ? 'ltr' : 'rtl';
  }
  $('#theme-toggle')?.addEventListener('click', async () => {
    const before = html.dataset.theme;
    html.dataset.theme = before === 'dark' ? 'light' : 'dark';
    if (!authenticated) { storage.set('theme', html.dataset.theme); return; }
    try { await post('/preferences/update/', { theme: html.dataset.theme, direction: html.dir }); }
    catch { html.dataset.theme = before; toast('ذخیره پوسته انجام نشد؛ اتصال یا ورود خود را بررسی کنید.'); }
  });
  const closeMenu = () => { $('#sidebar')?.classList.remove('open'); $('#overlay')?.classList.remove('visible'); $('#menu-toggle')?.setAttribute('aria-expanded', 'false'); };
  $('#menu-toggle')?.setAttribute('aria-expanded', 'false');
  $('#menu-toggle')?.addEventListener('click', () => {
    const open = $('#sidebar').classList.toggle('open'); $('#overlay').classList.toggle('visible', open);
    $('#menu-toggle').setAttribute('aria-expanded', String(open));
  });
  $('#overlay')?.addEventListener('click', closeMenu);
  $('#notifications-toggle')?.addEventListener('click', () => { const panel = $('#notifications'); panel.hidden = !panel.hidden; $('#notifications-toggle').setAttribute('aria-expanded', String(!panel.hidden)); });
  document.addEventListener('click', (event) => { if (!event.target.closest('.notification-wrap') && $('#notifications')) { $('#notifications').hidden = true; $('#notifications-toggle').setAttribute('aria-expanded', 'false'); } });
  const focusSearch = () => {
    const form = $('.search-box');
    const input = form?.querySelector('input');
    if (input && getComputedStyle(form).display !== 'none') { input.focus(); input.select(); }
    else location.href = form?.getAttribute('action') || '/search/';
  };
  const shortcut = $('#search-shortcut');
  if (shortcut) {
    const label = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘ K' : 'Ctrl K';
    shortcut.querySelector('kbd').textContent = label;
    shortcut.title = `تمرکز روی جستجو (${label})`;
    shortcut.addEventListener('click', focusSearch);
  }
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { closeMenu(); if ($('#notifications')) { $('#notifications').hidden = true; $('#notifications-toggle').setAttribute('aria-expanded', 'false'); } }
    if ((event.metaKey || event.ctrlKey) && (event.code === 'KeyK' || event.key.toLowerCase() === 'k')) {
      event.preventDefault(); focusSearch();
    }
  });
  document.querySelectorAll('[data-toast]').forEach((button) => button.addEventListener('click', () => toast(button.dataset.toast)));
  $('#print-invoice')?.addEventListener('click', () => window.print());
  document.querySelectorAll('form[data-confirm]').forEach((form) => form.addEventListener('submit', (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  }));

  const selections = [...document.querySelectorAll('.record-checkbox')];
  const updateSelection = () => {
    const count = selections.filter((checkbox) => checkbox.checked).length;
    if ($('#bulk-count')) $('#bulk-count').textContent = `${new Intl.NumberFormat('fa-IR').format(count)} رکورد انتخاب شده`;
    if ($('#bulk-submit')) $('#bulk-submit').disabled = count === 0;
    if ($('#select-all-records')) {
      $('#select-all-records').disabled = selections.length === 0;
      $('#select-all-records').checked = count > 0 && count === selections.length;
      $('#select-all-records').indeterminate = count > 0 && count < selections.length;
    }
  };
  selections.forEach((checkbox) => checkbox.addEventListener('change', updateSelection));
  $('#select-all-records')?.addEventListener('change', (event) => { selections.forEach((checkbox) => { checkbox.checked = event.target.checked; }); updateSelection(); });
  updateSelection();
  const showAssignee = () => { if ($('#bulk-assignee')) $('#bulk-assignee').hidden = $('#bulk-action')?.value !== 'assign'; };
  $('#bulk-action')?.addEventListener('change', showAssignee); showAssignee();
  $('#bulk-form')?.addEventListener('submit', (event) => {
    if (!selections.some((checkbox) => checkbox.checked)) { event.preventDefault(); toast('ابتدا رکوردها را انتخاب کنید.'); return; }
    if ($('#bulk-action').value === 'paid' && !window.confirm('پرداخت صورتحساب‌های انتخاب‌شده ثبت شود؟')) event.preventDefault();
  });

  let dragged = null;
  let changingStatus = false;
  document.querySelectorAll('.kanban-card[draggable=true]').forEach((card) => {
    card.addEventListener('dragstart', (event) => {
      if (changingStatus || event.target.closest('select,button,input')) { event.preventDefault(); return; }
      dragged = card; card.classList.add('dragging'); event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', card.dataset.projectId);
    });
    card.addEventListener('dragend', () => { card.classList.remove('dragging'); dragged = null; document.querySelectorAll('.drag-over').forEach((column) => column.classList.remove('drag-over')); });
  });
  document.querySelectorAll('.kanban-column').forEach((column) => {
    column.addEventListener('dragover', (event) => { if (dragged && !changingStatus) { event.preventDefault(); event.dataTransfer.dropEffect = 'move'; column.classList.add('drag-over'); } });
    column.addEventListener('dragleave', (event) => { if (!column.contains(event.relatedTarget)) column.classList.remove('drag-over'); });
    column.addEventListener('drop', async (event) => {
      event.preventDefault(); column.classList.remove('drag-over');
      const card = dragged;
      if (!card || changingStatus || card.dataset.status === column.dataset.status) return;
      changingStatus = true;
      try {
        await post(`/projects/${card.dataset.projectId}/status/`, { status: column.dataset.status, expected_status: card.dataset.status });
        location.reload();
      } catch (error) { toast(error.message === 'Request failed' ? 'تغییر وضعیت ذخیره نشد؛ اتصال یا مجوز خود را بررسی کنید.' : error.message); }
      finally { changingStatus = false; }
    });
  });

  const chart = $('#financial-chart');
  if (chart && $('#financial-data')) {
    const series = JSON.parse($('#financial-data').textContent);
    const NS = 'http://www.w3.org/2000/svg';
    const node = (tag, attributes = {}, content) => {
      const element = document.createElementNS(NS, tag);
      Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
      if (content !== undefined) element.textContent = content;
      return element;
    };
    const svg = node('svg', { viewBox: '0 0 700 220', role: 'img', 'aria-label': 'درآمد و هزینه واقعی به تومان' });
    const max = Math.max(...series.flatMap((item) => [item.income, item.expense]), 1);
    const ceiling = max === 1 ? 1 : Math.ceil(max / (10 ** Math.floor(Math.log10(max)))) * (10 ** Math.floor(Math.log10(max)));
    const fmt = new Intl.NumberFormat('fa-IR', { maximumFractionDigits: 1, notation: 'compact' });
    for (let index = 0; index <= 4; index++) {
      const y = 185 - index * 40;
      svg.append(node('line', { x1: 63, x2: 675, y1: y, y2: y, class: 'chart-grid' }));
      svg.append(node('text', { x: 53, y: y + 4, 'text-anchor': 'end' }, fmt.format(ceiling * index / 4)));
    }
    const x = (index) => 70 + index * (595 / Math.max(series.length - 1, 1));
    const y = (amount) => 185 - amount / ceiling * 160;
    for (const [field, css] of [['income', 'income'], ['expense', 'expense']]) {
      svg.append(node('path', { d: series.map((point, index) => `${index ? 'L' : 'M'}${x(index)} ${y(point[field])}`).join(' '), class: `line-${css}` }));
      series.forEach((point, index) => {
        const circle = node('circle', { cx: x(index), cy: y(point[field]), r: 3.2, class: `point-${css}` });
        circle.append(node('title', {}, `${point.label} · ${field === 'income' ? 'درآمد' : 'هزینه'}: ${new Intl.NumberFormat('fa-IR').format(point[field])} تومان`));
        svg.append(circle);
      });
    }
    series.forEach((point, index) => svg.append(node('text', { x: x(index), y: 210, 'text-anchor': 'middle' }, point.label)));
    chart.replaceChildren(svg);
  }

  const log = $('#chat-log');
  if (log && log.dataset.poll === '1') {
    let lastId = Number(log.dataset.lastId);
    let running = false;
    const peer = log.dataset.peer;
    const acknowledge = () => post('/messages/read/', { with: peer, through: lastId });
    const poll = async () => {
      if (running || document.hidden) return;
      running = true;
      try {
        const response = await fetch(`/messages/poll/?with=${encodeURIComponent(peer)}&since=${lastId}`, { credentials: 'same-origin' });
        if (!response.ok || response.redirected) throw new Error('Request failed');
        const data = await response.json();
        const stickToBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
        data.messages.forEach((item) => {
          if (item.id <= lastId) return;
          $('#empty-chat')?.remove();
          const bubble = document.createElement('div'); bubble.className = `bubble${item.outgoing ? ' outgoing' : ''}`;
          bubble.dataset.messageId = item.id;
          const text = document.createElement('span'); text.style.whiteSpace = 'pre-wrap'; text.textContent = item.body;
          const time = document.createElement('small'); time.textContent = item.time;
          bubble.append(text, time); log.append(bubble); lastId = item.id;
        });
        if (stickToBottom) log.scrollTop = log.scrollHeight;
        await acknowledge();
        if ($('#chat-connection')) $('#chat-connection').textContent = 'متصل';
      } catch { if ($('#chat-connection')) $('#chat-connection').textContent = 'اتصال قطع است؛ تلاش دوباره…'; }
      finally { running = false; }
    };
    log.scrollTop = log.scrollHeight;
    poll();
    const timer = setInterval(poll, 5000);
    window.addEventListener('pagehide', () => clearInterval(timer), { once: true });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
  }
})();
