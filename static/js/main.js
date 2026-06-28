// ─── API helpers ──────────────────────────────────────────────────────────────
async function api(url, method = 'GET', body = null) {
  try {
    const opts = { method, credentials: 'same-origin' };
    if (body !== null) {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(url, opts);
    const text = await res.text();
    try {
      return JSON.parse(text);
    } catch {
      return { success: false, message: res.ok ? 'Javob o\'qib bo\'lmadi' : 'Server xatosi (' + res.status + ')' };
    }
  } catch {
    return { success: false, message: 'Tarmoq xatosi' };
  }
}

// ─── Toast ────────────────────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const iconSpan = document.createElement('span');
  iconSpan.textContent = icons[type] || 'ℹ️';
  const msgSpan = document.createElement('span');
  msgSpan.style.flex = '1';
  msgSpan.innerHTML = msg;
  const close = document.createElement('span');
  close.className = 'toast-close';
  close.textContent = '✕';
  close.onclick = () => el.remove();
  el.append(iconSpan, msgSpan, close);
  const container = document.getElementById('toastContainer');
  if (container) container.appendChild(el); else document.body.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ─── Modal ────────────────────────────────────────────────────────────────────
function openModal(title, html, extraClass = '') {
  document.getElementById('modalTitle').textContent = title;
  document.getElementById('modalBody').innerHTML = html;
  const box = document.getElementById('globalModalBox');
  box.className = 'modal ' + extraClass;
  document.getElementById('globalModal').style.display = 'flex';
  document.body.style.overflow = 'hidden';
}
function closeModal() {
  document.getElementById('globalModal').style.display = 'none';
  document.body.style.overflow = '';
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
document.getElementById('globalModal')?.addEventListener('click', e => {
  if (e.target === document.getElementById('globalModal')) closeModal();
});

// ─── Sidebar ──────────────────────────────────────────────────────────────────
function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('sidebarOverlay').classList.toggle('open');
}
function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebarOverlay').classList.remove('open');
}

// ─── Bog'cha brendi (faqat login qilingan admin panel) ─────────────────────────
async function loadKindergartenBranding() {
  try {
    const s = await api('/api/settings');
    if (!s || !s.name) return;

    const pagePart = document.querySelector('.topbar-page');
    if (pagePart) {
      document.title = pagePart.textContent.trim() + ' — ' + s.name;
    } else {
      document.title = s.name;
    }

    const nameEl = document.getElementById('sidebarName');
    const topName = document.getElementById('topbarKgName');
    const fullName = s.name;
    if (nameEl) nameEl.textContent = fullName.length > 18 ? fullName.slice(0, 18) + '…' : fullName;
    if (topName) topName.textContent = fullName;

    const logoUrl = (s.logo || '').trim();
    ['sidebarLogo', 'topbarLogo'].forEach(id => {
      const img = document.getElementById(id);
      const fallback = document.getElementById('sidebarLogoFallback');
      if (!img) return;
      if (logoUrl) img.src = logoUrl;
      img.style.display = '';
      img.onerror = () => {
        img.style.display = 'none';
        if (fallback) fallback.style.display = '';
      };
      if (fallback) fallback.style.display = 'none';
    });
  } catch (e) { console.warn('Branding yuklanmadi:', e); }
}

async function loadSidebarName() {
  return loadKindergartenBranding();
}

async function loadPlatformAlerts() {
  const bar = document.getElementById('platformAlertBar');
  if (!bar) return;
  try {
    const d = await api('/api/platform/alerts');
    const alerts = d.alerts || [];
    const sub = d.subscription || {};
    if (sub.message && document.getElementById('ownerSubLine')) {
      document.getElementById('ownerSubLine').textContent = sub.message;
    }
    if (!alerts.length) { bar.style.display = 'none'; return; }
    bar.style.display = 'block';
    bar.innerHTML = alerts.map(a => {
      const isSub = a.icon === '💳' || a.icon === '⏰' || a.icon === '🎁';
      return `<div class="platform-alert-item alert-${a.type}" style="${isSub ? 'font-size:14px;font-weight:800;padding:16px 20px' : ''}">
        <span>${escapeHtml(a.icon || 'ℹ️')}</span>
        <span>${escapeHtml(a.message)}</span>
      </div>`;
    }).join('');
  } catch (e) { console.warn('Alerts yuklanmadi:', e); bar.style.display = 'none'; }
}

// ─── Payment check badge ──────────────────────────────────────────────────────
async function loadCheckBadge() {
  try {
    const d = await api('/api/payment-checks/pending-count');
    const badge = document.getElementById('checkBadge');
    if (badge) {
      if (d && d.count > 0) { badge.textContent = d.count; badge.style.display = 'inline'; }
      else badge.style.display = 'none';
    }
  } catch (e) { console.warn('Check badge yuklanmadi:', e); }
}

// ─── Notification badge ───────────────────────────────────────────────────────
async function loadNotifBadge() {
  try {
    const d = await api('/api/notifications/unread-count');
    const badge = document.getElementById('notifBadge');
    if (badge) {
      if (d && d.count > 0) { badge.textContent = d.count; badge.style.display = 'inline'; }
      else badge.style.display = 'none';
    }
  } catch (e) { console.warn('Notif badge yuklanmadi:', e); }
}

// ─── Button Ripple ────────────────────────────────────────────────────────────
document.addEventListener('mousemove', e => {
  const btn = e.target.closest('.btn');
  if (!btn) return;
  const rect = btn.getBoundingClientRect();
  btn.style.setProperty('--mx', ((e.clientX - rect.left) / rect.width * 100) + '%');
  btn.style.setProperty('--my', ((e.clientY - rect.top) / rect.height * 100) + '%');
});

// ─── Format currency ──────────────────────────────────────────────────────────
function fmtCurrency(n, currency = 'UZS') {
  return Number(n).toLocaleString('uz-UZ') + ' ' + currency;
}

// ─── Format date ──────────────────────────────────────────────────────────────
function fmtDate(str) {
  if (!str) return '—';
  const d = new Date(str);
  return d.toLocaleDateString('uz-UZ', { year: 'numeric', month: '2-digit', day: '2-digit' });
}

function fmtDateTime(str) {
  if (!str) return '—';
  const d = new Date(str);
  return d.toLocaleString('uz-UZ', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

// ─── Status badge ─────────────────────────────────────────────────────────────
function statusBadge(status) {
  const map = {
    active: ['badge-success', "Faol"],
    inactive: ['badge-gray', "Nofaol"],
    present: ['badge-success', "Keldi"],
    absent: ['badge-danger', "Kelmadi"],
    excused: ['badge-warning', "Sababli"],
    full: ['badge-success', "To'liq"],
    partial: ['badge-warning', "Qisman"],
    check: ['badge-info', "Chek orqali"],
    paid: ['badge-success', "To'langan"],
    unpaid: ['badge-danger', "To'lanmagan"],
  };
  const [cls, label] = map[status] || ['badge-gray', escapeHtml(status)];
  return `<span class="badge ${cls}">${label}</span>`;
}

// ─── Confirm dialog ───────────────────────────────────────────────────────────
let _pendingConfirm = null;

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function confirmAction(msg, onYes) {
  _pendingConfirm = onYes;
  openModal('Tasdiqlash', `
    <p style="color:var(--text2);margin-bottom:20px;line-height:1.5">${escapeHtml(msg)}</p>
    <div style="display:flex;gap:10px;justify-content:flex-end">
      <button type="button" class="btn btn-ghost" id="confirmCancelBtn">Bekor qilish</button>
      <button type="button" class="btn btn-danger" id="confirmYesBtn">Ha, davom etish</button>
    </div>
  `);
  document.getElementById('confirmCancelBtn').onclick = () => {
    _pendingConfirm = null;
    closeModal();
  };
  document.getElementById('confirmYesBtn').onclick = async () => {
    const fn = _pendingConfirm;
    _pendingConfirm = null;
    closeModal();
    if (fn) await fn();
  };
}

// ─── Phone format ─────────────────────────────────────────────────────────────
function phoneLink(phone) {
  if (!phone) return '—';
  return `<a class="phone-link" href="tel:${phone.replace(/[^0-9+]/g,'')}">📞 ${escapeHtml(phone)}</a>`;
}

// ─── Month picker helper ──────────────────────────────────────────────────────
function currentYearMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function monthName(ym) {
  if (!ym) return '';
  const [y, m] = ym.split('-');
  return new Date(y, m - 1).toLocaleString('uz-UZ', { month: 'long', year: 'numeric' });
}

// ─── Avatar initials ──────────────────────────────────────────────────────────
function avatarHtml(student) {
  if (!student) return '<div class="student-avatar" style="background:#6366f120;color:#6366f1">?</div>';
  if (student.image) {
    const initial = escapeHtml((student.first_name||'?').charAt(0));
    return `<div class="student-avatar"><img src="${escapeHtml(student.image)}" alt="${escapeHtml(student.first_name||'')}" data-initial="${initial}"></div>`;
  }
  const colors = ['#6366f1','#22c55e','#f59e0b','#ef4444','#8b5cf6','#a855f7'];
  const color = colors[((student.first_name||'?').charCodeAt(0) || 0) % colors.length];
  return `<div class="student-avatar" style="background:${color}20;color:${color}">${escapeHtml((student.first_name||'?')[0] || '?')}</div>`;
}

// ─── Image upload ─────────────────────────────────────────────────────────────
async function uploadImage(file) {
  const fd = new FormData();
  fd.append('image', file);
  try {
    const res = await fetch('/api/upload-image', { method: 'POST', body: fd });
    if (!res.ok) return { success: false, message: 'Server xatosi (' + res.status + ')' };
    return res.json();
  } catch (e) { return { success: false, message: 'Yuklashda xatolik' }; }
}

// ─── Theme & Language ─────────────────────────────────────────
// Handle broken student images
document.addEventListener('error', function(e) {
  const img = e.target;
  if (img.tagName === 'IMG' && img.hasAttribute('data-initial')) {
    const parent = img.parentElement;
    if (parent && parent.classList.contains('student-avatar')) {
      const initial = document.createElement('span');
      initial.textContent = img.getAttribute('data-initial');
      parent.innerHTML = '';
      parent.appendChild(initial);
    }
  }
}, true);

async function toggleTheme() {
  const html = document.documentElement;
  const current = html.getAttribute('data-theme') || 'light';
  const next = current === 'dark' ? 'light' : 'dark';
  const res = await api('/api/theme', 'POST', { theme: next });
  if (res.success) {
    html.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    const icon = document.getElementById('themeIcon');
    if (icon) icon.textContent = next === 'dark' ? '☀️' : '🌙';
  }
}

// ─── Performance Mode Toggle ──────────────────────────────────────────────────
function togglePerformanceMode() {
  const html = document.documentElement;
  const isLow = html.classList.contains('low-perf');
  if (isLow) {
    html.classList.remove('low-perf');
    localStorage.setItem('perf-mode', 'high');
    toast('🚀 Tezkor rejim o\'chirildi (Dizayn to\'liq yoqildi)', 'info');
  } else {
    html.classList.add('low-perf');
    localStorage.setItem('perf-mode', 'low');
    toast('⚡ Tezkor rejim yoqildi (Kuchsiz qurilmalar uchun)', 'success');
  }
  updatePerfToggleIcon();
}

function updatePerfToggleIcon() {
  const icon = document.getElementById('perfIcon');
  if (!icon) return;
  const isLow = document.documentElement.classList.contains('low-perf');
  icon.innerHTML = isLow ? '<i class="fas fa-bolt" style="color:#eab308"></i>' : '<i class="fas fa-gauge-high"></i>';
  const toggleBtn = document.getElementById('perfToggle');
  if (toggleBtn) {
    toggleBtn.title = isLow ? 'Tezkor rejim yoqilgan (Dizayn soddalashtirilgan)' : 'Tezkor rejim o\'chirilgan';
  }
}

document.addEventListener('DOMContentLoaded', () => {
  updatePerfToggleIcon();
});


async function setLang(lang) {
  const res = await api('/api/lang', 'POST', { lang });
  if (res.success) {
    localStorage.setItem('lang', lang);
    location.reload();
  }
}

function toggleLangMenu() {
  const menu = document.getElementById('langMenu');
  const arrow = document.querySelector('.lang-arrow');
  if (menu) menu.classList.toggle('open');
  if (arrow) arrow.classList.toggle('open');
}
document.addEventListener('click', e => {
  if (!e.target.closest('.lang-switch')) {
    const menu = document.getElementById('langMenu');
    const arrow = document.querySelector('.lang-arrow');
    if (menu) menu.classList.remove('open');
    if (arrow) arrow.classList.remove('open');
  }
});

// ─── Page Progress Bar ─────────────────────────────────────────────────────────
(function() {
  const bar = document.createElement('div');
  bar.id = 'pageProgress';
  document.body.prepend(bar);
  let ticking = false;
  window.addEventListener('scroll', () => {
    if (!ticking) {
      requestAnimationFrame(() => {
        const scrollTop = window.scrollY;
        const docHeight = document.documentElement.scrollHeight - window.innerHeight;
        const progress = docHeight > 0 ? Math.min(scrollTop / docHeight * 100, 100) : 0;
        bar.style.width = progress + '%';
        bar.style.opacity = progress < 2 ? '0' : '1';
        ticking = false;
      });
      ticking = true;
    }
  });
})();

// ─── Scroll Reveal ──────────────────────────────────────────────────────────────
(function() {
  if (!('IntersectionObserver' in window)) return;
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('vs');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });
  document.querySelectorAll('.rv').forEach(el => observer.observe(el));
})();

// ─── Global Search ──────────────────────────────────────────────────────────
(function() {
  const input = document.getElementById('globalSearchInput');
  const dropdown = document.getElementById('searchDropdown');
  const wrap = document.getElementById('globalSearchWrap');
  if (!input || !dropdown) return;

  let timer = null;
  let activeIdx = -1;

  function escapeHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function renderResults(data) {
    let html = '';
    let globalIdx = 0;
    const students = data.students || [];
    const parents = data.parents || [];
    const groups = data.groups || [];

    if (!students.length && !parents.length && !groups.length) {
      dropdown.innerHTML = '<div class="sd-empty">Nothing found</div>';
      dropdown.classList.add('open');
      return;
    }

    if (students.length) {
      html += '<div class="sd-section"><span class="sd-label">Students</span></div>';
      students.forEach((s) => {
        const cls = globalIdx === activeIdx ? 'sd-item active' : 'sd-item';
        const statusDot = s.status === 'active'
          ? '<span class="sd-status" style="background:#10b981"></span>'
          : '<span class="sd-status" style="background:#94a3b8"></span>';
        html += `<div class="${cls}" data-url="/students" data-idx="${globalIdx}">
          ${statusDot}
          <div class="sd-info">
            <span class="sd-name">${escapeHtml(s.name)}</span>
            <span class="sd-sub">${escapeHtml(s.parent)} · ${escapeHtml(s.phone) || '—'}</span>
          </div>
          <span class="sd-tag">${escapeHtml(s.group)}</span>
        </div>`;
        globalIdx++;
      });
    }

    if (parents.length) {
      html += '<div class="sd-section"><span class="sd-label">Parents</span></div>';
      parents.forEach((p) => {
        const cls = globalIdx === activeIdx ? 'sd-item active' : 'sd-item';
        const childStr = p.children && p.children.length ? p.children.join(', ') : '';
        html += `<div class="${cls}" data-url="/parents" data-idx="${globalIdx}">
          <span class="sd-icon"><i class="fas fa-user"></i></span>
          <div class="sd-info">
            <span class="sd-name">${escapeHtml(p.name)}</span>
            <span class="sd-sub">${escapeHtml(p.phone)}${childStr ? ' · ' + escapeHtml(childStr) : ''}</span>
          </div>
        </div>`;
        globalIdx++;
      });
    }

    if (groups.length) {
      html += '<div class="sd-section"><span class="sd-label">Groups</span></div>';
      groups.forEach((g) => {
        const cls = globalIdx === activeIdx ? 'sd-item active' : 'sd-item';
        html += `<div class="${cls}" data-url="/students?group=${encodeURIComponent(g)}" data-idx="${globalIdx}">
          <span class="sd-icon"><i class="fas fa-layer-group"></i></span>
          <div class="sd-info">
            <span class="sd-name">${escapeHtml(g)}</span>
            <span class="sd-sub">Group</span>
          </div>
          <span class="sd-arrow"><i class="fas fa-arrow-right"></i></span>
        </div>`;
        globalIdx++;
      });
    }

    dropdown.innerHTML = html;
    dropdown.classList.add('open');

    // Click handlers
    dropdown.querySelectorAll('.sd-item').forEach(el => {
      el.addEventListener('click', () => {
        window.location.href = el.dataset.url;
      });
      el.addEventListener('mousedown', e => {
        e.preventDefault();
        window.location.href = el.dataset.url;
      });
    });
  }

  function doSearch(q) {
    if (!q || q.length < 1) {
      dropdown.classList.remove('open');
      return;
    }
    fetch('/api/search?q=' + encodeURIComponent(q))
      .then(r => r.json())
      .then(data => { activeIdx = -1; renderResults(data); })
      .catch(() => { dropdown.classList.remove('open'); });
  }

  input.addEventListener('input', () => {
    clearTimeout(timer);
    const val = input.value.trim();
    if (!val) { dropdown.classList.remove('open'); return; }
    timer = setTimeout(() => doSearch(val), 250);
  });

  input.addEventListener('keydown', e => {
    const items = dropdown.querySelectorAll('.sd-item');
    if (!items.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIdx = Math.min(activeIdx + 1, items.length - 1);
      items.forEach((el, i) => el.classList.toggle('active', i === activeIdx));
      items[activeIdx]?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIdx = Math.max(activeIdx - 1, -1);
      items.forEach((el, i) => el.classList.toggle('active', i === activeIdx));
      if (activeIdx >= 0) items[activeIdx]?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter' && activeIdx >= 0) {
      e.preventDefault();
      items[activeIdx]?.click();
    } else if (e.key === 'Escape') {
      dropdown.classList.remove('open');
      input.blur();
    }
  });

  // Close dropdown on outside click
  document.addEventListener('click', e => {
    if (!wrap.contains(e.target)) {
      dropdown.classList.remove('open');
    }
  });

  // Close on blur with delay
  input.addEventListener('blur', () => {
    setTimeout(() => dropdown.classList.remove('open'), 200);
  });

  input.addEventListener('focus', () => {
    if (input.value.trim()) doSearch(input.value.trim());
  });
})();

// Apply saved theme on load
(function() {
  const saved = localStorage.getItem('theme');
  if (saved) {
    document.documentElement.setAttribute('data-theme', saved);
  }
})();

// ─── PWA: Service Worker Registration ──────────────────────────
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).then(reg => {
      console.log('SW registered:', reg.scope);
      // Check for updates every 30s
      setInterval(() => { reg.update(); }, 30000);
      // Auto-reload when new SW takes over
      reg.addEventListener('updatefound', () => {
        const newSW = reg.installing;
        newSW.addEventListener('statechange', () => {
          if (newSW.state === 'installed' && navigator.serviceWorker.controller) {
            console.log('New SW installed, reloading...');
            window.location.reload();
          }
        });
      });
    }).catch(err => {
      console.warn('SW registration failed:', err);
    });
  });
  // Also reload when controller changes after skipWaiting
  let reloading = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (reloading) return;
    reloading = true;
    console.log('SW controller changed, reloading...');
    window.location.reload();
  });
}

// ─── PWA: Install Prompt ───────────────────────────────────────
let _deferredPrompt = null;

window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault();
  _deferredPrompt = e;
  const banner = document.getElementById('pwaInstallBanner');
  if (banner && !localStorage.getItem('pwa_dismissed')) {
    banner.style.display = 'block';
  }
});

window.addEventListener('appinstalled', () => {
  _deferredPrompt = null;
  const banner = document.getElementById('pwaInstallBanner');
  if (banner) banner.style.display = 'none';
  localStorage.setItem('pwa_installed', '1');
  toast('✅ Bog\'cha telefonga o\'rnatildi!', 'success');
});

function installPWA() {
  const banner = document.getElementById('pwaInstallBanner');
  if (!_deferredPrompt) {
    if (banner) banner.style.display = 'none';
    toast('Brauzeringiz o\'rnatishni qo\'llab-quvvatlamaydi', 'warning');
    return;
  }
  _deferredPrompt.prompt();
  _deferredPrompt.userChoice.then(choice => {
    if (choice.outcome === 'accepted') {
      console.log('User accepted PWA install');
    } else {
      console.log('User dismissed PWA install');
    }
    _deferredPrompt = null;
    if (banner) banner.style.display = 'none';
  });
}

function dismissPWA() {
  const banner = document.getElementById('pwaInstallBanner');
  if (banner) banner.style.display = 'none';
  localStorage.setItem('pwa_dismissed', '1');
}

// ─── Custom Select Enhancement ──────────────────────────────────
(function() {
  function enhanceSelect(select) {
    if (select.dataset.csEnhanced) return;
    select.dataset.csEnhanced = '1';

    const wrap = document.createElement('div');
    wrap.className = 'custom-select';
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);

    const trigger = document.createElement('div');
    trigger.className = 'custom-select-trigger';
    const val = document.createElement('span');
    val.className = 'custom-select-value';
    val.textContent = select.options[select.selectedIndex]?.text || '';
    const arrow = document.createElement('span');
    arrow.className = 'custom-select-arrow';
    arrow.innerHTML = '<i class="fas fa-chevron-down"></i>';
    trigger.append(val, arrow);
    wrap.appendChild(trigger);

    const dd = document.createElement('div');
    dd.className = 'custom-select-dropdown';
    wrap.appendChild(dd);

    function buildOptions() {
      dd.innerHTML = '';
      Array.from(select.options).forEach((opt, i) => {
        const item = document.createElement('div');
        item.className = 'custom-select-option' + (opt.selected ? ' selected' : '');
        const iconMatch = opt.text.match(/^([\u{1F000}-\u{1FFFF}]|<i\s[^>]*><\/i>)/u);
        if (iconMatch) {
          const icon = document.createElement('span');
          icon.className = 'opt-icon';
          icon.innerHTML = iconMatch[0];
          item.appendChild(icon);
          const txt = document.createElement('span');
          txt.textContent = opt.text.replace(iconMatch[0], '').trim();
          item.appendChild(txt);
        } else {
          item.textContent = opt.text;
        }
        item.dataset.index = i;
        item.addEventListener('click', function(e) {
          e.stopPropagation();
          select.selectedIndex = i;
          select.dispatchEvent(new Event('change', { bubbles: true }));
          select.dispatchEvent(new Event('input', { bubbles: true }));
          val.textContent = opt.text;
          dd.querySelectorAll('.custom-select-option').forEach(o => o.classList.remove('selected'));
          item.classList.add('selected');
          closeDD();
        });
        dd.appendChild(item);
      });
    }

    function openDD() {
      buildOptions();
      wrap.classList.add('open');
      const sel = dd.querySelector('.selected');
      if (sel) sel.scrollIntoView({ block: 'nearest' });
    }

    function closeDD() {
      wrap.classList.remove('open');
    }

    trigger.addEventListener('click', function(e) {
      e.stopPropagation();
      wrap.classList.contains('open') ? closeDD() : openDD();
    });

    select.addEventListener('change', function() {
      val.textContent = select.options[select.selectedIndex]?.text || '';
    });

    document.addEventListener('click', function(e) {
      if (!wrap.contains(e.target)) closeDD();
    });

    select.addEventListener('focus', function() { wrap.classList.add('focused'); });
    select.addEventListener('blur', function() { wrap.classList.remove('focused'); });

    select.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        wrap.classList.contains('open') ? closeDD() : openDD();
      }
      if (e.key === 'Escape') closeDD();
    });

    select.style.cssText = 'position:absolute;inset:0;opacity:0;width:100%;height:100%;cursor:pointer;z-index:3';
  }

  function init() {
    document.querySelectorAll('select.form-control').forEach(enhanceSelect);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  const observer = new MutationObserver(function() {
    document.querySelectorAll('select.form-control:not([data-cs-enhanced])').forEach(enhanceSelect);
  });
  observer.observe(document.body, { childList: true, subtree: true });
})();
