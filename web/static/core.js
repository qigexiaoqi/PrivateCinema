/* =============================================================
   CINEBOX · core client (helpers, auth, router, home, search, detail)
   ============================================================= */
window.CB = (function () {
  'use strict';

  /* ---------------------------------------------------------- helpers */
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const icon = (name, cls = '') => `<svg class="${cls}"><use href="#i-${name}"></use></svg>`;
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
  const pad = (n) => String(Math.floor(n)).padStart(2, '0');
  const fmtTime = (s) => {
    if (!isFinite(s) || s < 0) s = 0;
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
    return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
  };
  const fmtBytes = (n) => {
    if (!n) return '—';
    const u = ['B', 'KB', 'MB', 'GB', 'TB'];
    let v = n, i = 0;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
  };
  const fmtDate = (ts) => {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  const ago = (ts) => {
    if (!ts) return '—';
    const diff = Date.now() / 1000 - ts;
    if (diff < 60) return '刚刚';
    if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
    if (diff < 86400 * 30) return `${Math.floor(diff / 86400)} 天前`;
    return fmtDate(ts).slice(0, 10);
  };

  const state = {
    user: null,
    settings: {},
    csrf: '',
    route: { name: 'home', params: {}, query: {} },
    hls: null,
    player: null,
    health: null,
    heroTimer: null,
    liveSources: null,
    liveHls: null,
  };

  const ROUTES = {};
  const register = (name, fn) => { ROUTES[name] = fn; };

  /* ------------------------------------------------------------- xhr */
  async function api(path, { method = 'GET', body, headers = {}, quiet = false } = {}) {
    const h = { Accept: 'application/json', ...headers };
    let payload;
    if (body !== undefined) {
      h['Content-Type'] = 'application/json';
      payload = JSON.stringify(body);
    }
    if (method !== 'GET' && method !== 'HEAD' && state.csrf) h['X-CSRF'] = state.csrf;
    let res;
    try {
      res = await fetch(path, { method, headers: h, body: payload, credentials: 'same-origin' });
    } catch (err) {
      if (!quiet) toast('网络连接失败，请检查服务是否在线', 'err');
      throw err;
    }
    const ct = res.headers.get('content-type') || '';
    const data = ct.includes('json') ? await res.json().catch(() => null) : await res.text();
    if (!res.ok) {
      const msg = (data && (data.error || data.message)) || `请求失败 (${res.status})`;
      const err = new Error(msg);
      err.status = res.status;
      err.code = data && data.code;
      if (res.status === 401 && !quiet) openAuth('登录后即可使用该功能');
      if (!quiet && res.status !== 401) toast(msg, 'err');
      throw err;
    }
    return data;
  }

  /* ----------------------------------------------------------- toast */
  let toastId = 0;
  function toast(msg, type = 'info', ms = 3200) {
    const host = $('#toasts');
    const el = document.createElement('div');
    el.className = `toast ${type === 'err' ? 'err' : type === 'ok' ? 'ok' : ''}`;
    el.innerHTML = `${icon(type === 'err' ? 'close' : type === 'ok' ? 'check' : 'spark')}<span>${esc(msg)}</span>`;
    el.dataset.id = String(++toastId);
    host.appendChild(el);
    setTimeout(() => {
      el.classList.add('out');
      setTimeout(() => el.remove(), 240);
    }, ms);
  }

  /* ----------------------------------------------------------- modal */
  function openModal({ title, sub = '', body, foot = '', size = '', onMount }) {
    const root = $('#modals');
    const wrap = document.createElement('div');
    wrap.className = 'modal-wrap';
    wrap.innerHTML = `
      <div class="modal-backdrop"></div>
      <div class="modal ${size}" role="dialog" aria-modal="true">
        <div class="modal-head">
          <div><h3>${esc(title)}</h3>${sub ? `<div class="sub">${sub}</div>` : ''}</div>
          <button class="close" aria-label="关闭">${icon('close')}</button>
        </div>
        <div class="modal-body">${body}</div>
        ${foot ? `<div class="modal-foot">${foot}</div>` : ''}
      </div>`;
    root.appendChild(wrap);
    const close = () => {
      wrap.querySelector('.modal').classList.remove('in');
      wrap.querySelector('.modal-backdrop').classList.remove('in');
      setTimeout(() => wrap.remove(), 220);
    };
    requestAnimationFrame(() => {
      wrap.querySelector('.modal').classList.add('in');
      wrap.querySelector('.modal-backdrop').classList.add('in');
    });
    wrap.querySelector('.close').addEventListener('click', close);
    wrap.querySelector('.modal-backdrop').addEventListener('click', close);
    document.addEventListener('keydown', function onEsc(e) {
      if (e.key === 'Escape') { close(); document.removeEventListener('keydown', onEsc); }
    });
    if (onMount) onMount(wrap, close);
    return { wrap, close };
  }

  function confirmDialog(title, text, danger = false) {
    return new Promise((resolve) => {
      const m = openModal({
        title,
        body: `<p class="muted" style="font-size:13px;line-height:1.7">${esc(text)}</p>`,
        foot: `<button class="btn ghost" data-x="no">取消</button>
               <button class="btn ${danger ? 'danger' : 'primary'}" data-x="yes">确定</button>`,
        onMount(wrap, close) {
          wrap.querySelector('[data-x="no"]').onclick = () => { close(); resolve(false); };
          wrap.querySelector('[data-x="yes"]').onclick = () => { close(); resolve(true); };
        },
      });
      m.wrap.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal-backdrop')) resolve(false);
      });
    });
  }

  /* ------------------------------------------------------------ auth */
  function openAuth(message = '', mode = 'login') {
    if (state.user) return;
    const body = `
      <div class="auth-wrap">
        <div class="auth-brand">
          <span class="brand-mark">${icon('film')}</span>
          <div><h3>${esc(state.settings.siteName || 'CINEBOX')}</h3>
          <p>${esc(message || '登录后解锁播放、下载与片单')}</p></div>
        </div>
        <div class="auth-tabs">
          <button data-tab="login" class="${mode === 'login' ? 'on' : ''}">登录</button>
          ${state.settings.allowSignup ? `<button data-tab="register" class="${mode === 'register' ? 'on' : ''}">注册</button>` : ''}
        </div>
        <form class="auth-form" id="auth-form" autocomplete="on">
          <div class="inp"><label>账号</label><input name="username" type="text" autocomplete="username" placeholder="输入账号" required /></div>
          <div class="inp reg-only" ${mode === 'login' ? 'hidden' : ''}><label>昵称（可选）</label><input name="displayName" type="text" placeholder="显示名称" /></div>
          <div class="inp"><label>密码</label><input name="password" type="password" autocomplete="current-password" placeholder="输入密码" required /></div>
          <div class="auth-err" id="auth-err"></div>
          <button class="btn primary" type="submit" style="width:100%;padding:12px">${mode === 'login' ? '登录' : '创建账号'}</button>
        </form>
        <p class="auth-hint">未登录状态仅开放搜索；播放、下载、片单与播放记录需要账号。${state.settings.allowSignup ? '' : '注册已由管理员关闭。'}</p>
      </div>`;
    let current = mode;
    return openModal({
      title: '账号中心', sub: '安全会话 · 服务端加密校验', body, size: '',
      onMount(wrap, close) {
        const form = $('#auth-form', wrap);
        const errBox = $('#auth-err', wrap);
        $$('.auth-tabs button', wrap).forEach((btn) => {
          btn.onclick = () => {
            if (btn.disabled) return;
            current = btn.dataset.tab;
            $$('.auth-tabs button', wrap).forEach((b) => b.classList.toggle('on', b === btn));
            $$('.reg-only', wrap).forEach((el) => { el.hidden = current === 'login'; });
            form.querySelector('button[type=submit]').textContent = current === 'login' ? '登录' : '创建账号';
            errBox.textContent = '';
          };
        });
        form.onsubmit = async (e) => {
          e.preventDefault();
          const fd = new FormData(form);
          const btn = form.querySelector('button[type=submit]');
          btn.disabled = true;
          errBox.textContent = '';
          try {
            const res = await api(current === 'login' ? '/api/auth/login' : '/api/auth/register', {
              method: 'POST',
              body: {
                username: (fd.get('username') || '').trim(),
                password: fd.get('password') || '',
                displayName: (fd.get('displayName') || '').trim(),
              },
              quiet: true,
            });
            state.user = res.user;
            state.csrf = res.csrf;
            state.settings = res.settings || state.settings;
            applyIdentity();
            close();
            toast(`欢迎回来，${res.user.displayName || res.user.username}`, 'ok');
            if (location.hash === '#/login' || !location.hash) navigate('#/');
            else render();
          } catch (err) {
            errBox.textContent = err.message;
          } finally {
            btn.disabled = false;
          }
        };
        setTimeout(() => form.querySelector('input[name=username]').focus(), 120);
      },
    });
  }

  function logout() {
    api('/api/auth/logout', { method: 'POST', quiet: true }).catch(() => {});
    state.user = null;
    state.csrf = '';
    applyIdentity();
    toast('已退出登录');
    if (state.route.name !== 'search') navigate('#/search');
    else render();
  }

  /* ---------------------------------------------------------- identity */
  function applyIdentity() {
    const authed = !!state.user;
    const isAdmin = authed && state.user.role === 'admin';
    document.body.classList.toggle('authed', authed);
    document.body.classList.toggle('is-admin', isAdmin);
    // hard guarantee: the admin entry points never render for non-admins,
    // independent of any cached CSS.
    $$('.nav-admin, .admin-only').forEach((el) => { el.hidden = !isAdmin; });
    // signed-out guests only keep 首页 / 搜索 / 登录
    $$('[data-auth]').forEach((el) => { el.hidden = !authed; });
    $('#u-name').textContent = authed ? (state.user.displayName || state.user.username) : '访客';
    $('#um-name').textContent = authed ? (state.user.displayName || state.user.username) : '访客';
    $('#um-role').textContent = authed ? (state.user.role === 'admin' ? '管理员' : '普通用户') : '未登录';
    const guestHint = $('#guest-hint');
    if (guestHint) guestHint.hidden = authed;
    const av = $('#avatar');
    av.innerHTML = icon('user');
    if (authed) av.style.background = `linear-gradient(145deg, ${state.user.avatarColor || '#48d6c8'}33, #16202f)`;
    const name = state.settings.siteName || 'CINEBOX';
    $('#brand-name').textContent = name;
    $('#brand-tag').textContent = state.settings.tagline || '私人影库';
    document.title = `${name} · ${state.settings.tagline || '私人影库'}`;
  }

  /* ----------------------------------------------------------- router */
  function parseHash() {
    const raw = (location.hash || '#/').replace(/^#/, '') || '/';
    const [pathPart, qs] = raw.split('?');
    const parts = pathPart.split('/').filter(Boolean);
    const query = {};
    new URLSearchParams(qs || '').forEach((v, k) => { query[k] = v; });
    const name = parts[0] || 'home';
    const params = {};
    if (name === 'movie' || name === 'watch') params.id = parts[1] || '';
    if (name === 'watch') params.file = parts[2] || '';
    return { name, params, query, raw };
  }

  function navigate(hash) {
    if (location.hash === hash) { render(); return; }
    location.hash = hash;
  }

  function setActiveNav(name) {
    $$('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.route === name));
  }

  async function render() {
    if (CB.destroyPlayer) CB.destroyPlayer();
    if (state.heroTimer) { clearInterval(state.heroTimer); state.heroTimer = null; }
    state.route = parseHash();
    setActiveNav(state.route.name);
    const view = $('#view');
    view.innerHTML = '';
    view.scrollTop = 0;
    window.scrollTo(0, 0);
    const fn = ROUTES[state.route.name] || renderNotFound;
    try {
      await fn(view, state.route);
    } catch (err) {
      if (err && err.status === 401) { view.innerHTML = guestWall('登录后查看此内容'); return; }
      console.error(err);
      view.innerHTML = errorBlock(err.message || '页面加载失败');
    }
    document.body.classList.remove('booting');
  }

  /* ------------------------------------------------------- view states */
  const errorBlock = (msg) => `
    <div class="empty">${icon('close')}<h3>出了点问题</h3><p>${esc(msg)}</p>
      <button class="btn mt16" data-cb="reload">重新加载</button></div>`;

  const guestWall = (title = '访问受限') => `
    <div class="empty" style="padding:90px 20px">
      ${icon('user')}
      <h3>${esc(title)}</h3>
      <p>当前为访客模式，只有搜索功能开放。<br/>登录后可播放、下载、管理片单与播放记录。</p>
      <div class="flex center mt16" style="justify-content:center">
        <button class="btn primary" data-cb="login">立即登录</button>
        <button class="btn ghost" data-cb="search">先去搜索</button>
      </div>
    </div>`;

  const renderNotFound = (view) => {
    view.innerHTML = `<div class="empty">${icon('film')}<h3>页面不存在</h3>
      <p>链接可能已失效。</p><a class="btn mt16" href="#/">回到首页</a></div>`;
  };

  const skeletonRail = () => `
    <div class="section">
      <div class="section-head"><div class="sk sk-line" style="width:180px;height:20px"></div></div>
      <div class="sk-row">${Array.from({ length: 6 }, () => '<div class="sk sk-card"></div>').join('')}</div>
    </div>`;

  /* --------------------------------------------------------- card view */
  const qualityChips = (m, max = 3) => (m.qualities || []).slice(0, max)
    .map((q) => `<span>${esc(q)}</span>`).join('');

  function cardHtml(m, opts = {}) {
    const posterSrc = opts.wide ? (m.backdrop || m.poster) : m.poster;
    const poster = posterSrc
      ? `<img loading="lazy" src="${esc(posterSrc)}" alt="${esc(m.title)}" onerror="this.style.display='none'"/>` : '';
    const progress = opts.progress != null && opts.progress > 0
      ? `<div class="card-progress"><i style="width:${Math.min(100, opts.progress)}%"></i></div>` : '';
    const sub = opts.subtitle
      ? `<div class="card-sub">${esc(opts.subtitle)}</div>`
      : `<div class="card-sub">${m.year ? `<span>${m.year}</span>` : ''}
          ${m.rating ? `<span class="dot-sep"></span><span class="rating-star">${icon('star')}${esc(m.rating)}</span>` : ''}
          ${m.genres && m.genres.length ? `<span class="dot-sep"></span><span>${esc(m.genres[0])}</span>` : ''}</div>`;
    return `
      <article class="card ${opts.wide ? 'wide' : ''}" data-mid="${esc(m.id)}" tabindex="0">
        <div class="card-poster">
          ${poster}
          ${!poster ? `<div class="ph">${icon('film')}</div>` : ''}
          <div class="card-overlay">
            <div class="card-badge">${qualityChips(m)}${m.featured ? '<span style="color:#f5c26b">精选</span>' : ''}</div>
            <div class="card-play">${icon('play')}</div>
          </div>
          ${progress}
        </div>
        <div class="card-body">
          <div class="card-title" title="${esc(m.title)}">${esc(m.title)}</div>
          ${sub}
        </div>
      </article>`;
  }

  function railHtml(title, items, opts = {}) {
    if (!items || !items.length) return '';
    const id = `rail_${Math.random().toString(36).slice(2, 8)}`;
    return `
      <section class="section">
        <div class="section-head">
          <h2>${esc(title)}</h2>
          ${opts.sub ? `<span class="sub">${esc(opts.sub)}</span>` : ''}
          ${opts.more ? `<a class="more" href="${opts.more}">全部${icon('chevron')}</a>` : ''}
        </div>
        <div class="rail">
          <button class="rail-nav prev" data-rail="${id}" aria-label="上一页">${icon('chevron')}</button>
          <div class="rail-track" id="${id}">
            ${items.map((m) => cardHtml(m, { wide: opts.wide, progress: m.progress })).join('')}
          </div>
          <button class="rail-nav next" data-rail="${id}" aria-label="下一页">${icon('chevron')}</button>
        </div>
      </section>`;
  }

  function bindRails(root) {
    $$('.rail', root).forEach((rail) => {
      const track = $('.rail-track', rail);
      $$('.rail-nav', rail).forEach((btn) => {
        btn.onclick = () => {
          const amount = Math.max(320, track.clientWidth * 0.8);
          track.scrollBy({ left: btn.classList.contains('prev') ? -amount : amount, behavior: 'smooth' });
        };
      });
    });
  }

  function bindCards(root, { guestLock = false } = {}) {
    $$('.card[data-mid]', root).forEach((card) => {
      const go = () => {
        if (guestLock || !state.user) { openAuth('登录后可播放与下载这部影片'); return; }
        navigate(`#/movie/${card.dataset.mid}`);
      };
      card.addEventListener('click', go);
      card.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
    });
  }

  /* -------------------------------------------------------------- home */
  async function renderHome(view, route) {
    view.innerHTML = skeletonRail() + skeletonRail();
    const data = await api('/api/home');
    if (state.route !== route) return;
    const featured = data.featured && data.featured.length ? data.featured : data.recent;
    view.innerHTML = `
      ${data.announcement ? `<div class="announce">${icon('spark')}<span>${esc(data.announcement)}</span></div>` : ''}
      ${featured && featured.length ? heroHtml(featured) : ''}
      ${data.continue && data.continue.length ? railHtml('继续观看', data.continue, { wide: true, sub: '接着上次看到的位置' }) : ''}
      ${railHtml('热门播放', data.trending, { sub: `${data.counts.movies} 部影片在库` })}
      ${railHtml('最新入库', data.recent)}
      ${railHtml('高分推荐', data.topRated, { more: '#/search?sort=rating' })}
      <section class="section">
        <div class="section-head"><h2>按类型浏览</h2></div>
        <div class="tag-list">
          ${(data.genres || []).map((g) => `<a class="chip" href="#/search?genre=${encodeURIComponent(g)}">${esc(g)}</a>`).join('')}
          ${(data.genres || []).length ? '' : '<span class="muted" style="font-size:12px">暂无类型数据</span>'}
        </div>
      </section>`;
    bindRails(view);
    bindCards(view, { guestLock: !state.user });
    bindHero(view, featured);
    const play = $('#hero-play', view);
    const dl = $('#hero-dl', view);
    if (!state.user && play) {
      play.addEventListener('click', (e) => { e.preventDefault(); openAuth('登录后可查看影片详情'); });
    }
  }

  function heroHtml(items) {
    const m = items[0];
    return `
      <section class="hero" id="hero" data-index="0">
        <div class="hero-bg" id="hero-bg">
          ${m.backdrop ? `<img src="${esc(m.backdrop)}" alt=""/>` : ''}
        </div>
        <div class="hero-inner">
          <div class="hero-eyebrow">精选推荐</div>
          <h1 id="hero-title">${esc(m.title)}</h1>
          <div class="orig" id="hero-orig">${esc(m.originalTitle || '')}</div>
          <div class="meta-row" id="hero-meta">
            ${m.year ? `<span>${m.year}</span>` : ''}
            ${m.rating ? `<span class="rating-star">${icon('star')}${esc(m.rating)}</span>` : ''}
            ${(m.genres || []).map((g) => `<span class="chip dim">${esc(g)}</span>`).join('')}
            ${(m.qualities || []).slice(0, 3).map((q) => `<span class="chip accent">${esc(q)}</span>`).join('')}
          </div>
          <p class="synopsis" id="hero-plot">${esc(m.synopsis || '影片简介即将补全。')}</p>
          <div class="cta">
            <a class="btn primary" id="hero-play" href="#/movie/${esc(m.id)}">${icon('play')}查看详情</a>
            <button class="btn ghost" id="hero-dl" data-mid="${esc(m.id)}">${icon('download')}下载</button>
          </div>
        </div>
        <div class="hero-dots">
          ${items.slice(0, 6).map((_, i) => `<button data-dot="${i}" class="${i === 0 ? 'on' : ''}"></button>`).join('')}
        </div>
      </section>`;
  }

  function bindHero(view, items) {
    const hero = $('#hero', view);
    if (!hero || !items || !items.length) return;
    let idx = 0;
    const show = (i) => {
      idx = i;
      const m = items[i];
      $('#hero-title', view).textContent = m.title;
      $('#hero-orig', view).textContent = m.originalTitle || '';
      $('#hero-plot', view).textContent = m.synopsis || '影片简介即将补全。';
      $('#hero-bg', view).innerHTML = m.backdrop ? `<img src="${esc(m.backdrop)}" alt=""/>` : '';
      $('#hero-meta', view).innerHTML = [
        m.year ? `<span>${m.year}</span>` : '',
        m.rating ? `<span class="rating-star">${icon('star')}${esc(m.rating)}</span>` : '',
        ...(m.genres || []).map((g) => `<span class="chip dim">${esc(g)}</span>`),
        ...(m.qualities || []).slice(0, 3).map((q) => `<span class="chip accent">${esc(q)}</span>`),
      ].join('');
      $('#hero-play', view).href = `#/movie/${m.id}`;
      $('#hero-dl', view).dataset.mid = m.id;
      $$('.hero-dots button', hero).forEach((b, bi) => b.classList.toggle('on', bi === i));
    };
    $$('.hero-dots button', hero).forEach((b) => { b.onclick = () => show(Number(b.dataset.dot)); });
    const dl = $('#hero-dl', view);
    if (dl) dl.onclick = () => { if (!state.user) { openAuth('登录后可播放与下载'); return; } navigate(`#/movie/${dl.dataset.mid}?panel=download`); };
    if (items.length > 1) {
      state.heroTimer = setInterval(() => {
        if (document.hidden || state.route.name !== 'home' || !document.body.contains(hero)) return;
        show((idx + 1) % Math.min(items.length, 6));
      }, 9000);
    }
  }

  /* ------------------------------------------------------------ search */
  const LIVE_PROVIDERS = [
    { id: 'archive', name: 'Internet Archive' },
    { id: 'itunes', name: 'iTunes' },
    { id: 'tvmaze', name: 'TVMaze' },
    { id: 'wiki', name: 'Wikipedia' },
    { id: 'tmdb', name: 'TMDB' },
  ];

  const imgUrl = (u) => (!u ? '' : (u.startsWith('http') ? '/api/img?u=' + encodeURIComponent(u) : u));

  function liveCardHtml(it) {
    const poster = it.poster
      ? `<img loading="lazy" src="${esc(imgUrl(it.poster))}" alt="${esc(it.title)}" onerror="this.style.display='none'"/>`
      : '';
    const quals = (it.files || []).slice(0, 2).map((f) => `<span>${esc(f.quality)}</span>`).join('');
    const meta = [
      it.year ? `<span>${it.year}</span>` : '',
      it.rating ? `<span class="rating-star">${icon('star')}${esc(it.rating)}</span>` : '',
      ((it.files && it.files.length) || it.canPlay) ? '<span class="live-ok">可播放</span>' : '<span class="live-meta">仅元数据</span>',
    ].filter(Boolean).join('<span class="dot-sep"></span>');
    return `
      <article class="card live-card" data-provider="${esc(it.provider)}" data-uid="${esc(it.uid)}" tabindex="0">
        <div class="card-poster">
          ${poster}
          ${!poster ? `<div class="ph">${icon('film')}</div>` : ''}
          <div class="card-overlay">
            <div class="card-badge"><span class="src-badge">${esc(it.providerName || it.provider)}</span>${quals}</div>
            <div class="card-play">${icon('play')}</div>
          </div>
        </div>
        <div class="card-body">
          <div class="card-title" title="${esc(it.title)}">${esc(it.title)}</div>
          <div class="card-sub">${meta}</div>
        </div>
      </article>`;
  }

  function groupCardHtml(g) {
    const poster = g.poster
      ? `<img loading="lazy" src="${esc(imgUrl(g.poster))}" alt="${esc(g.title)}" onerror="this.style.display='none'"/>`
      : '';
    const n = (g.sources || []).length;
    const names = (g.sources || []).map((s) => s.providerName).join(' / ');
    const ids = (g.sources || []).map((s) => `${s.provider}|${s.uid}`).join(',');
    return `
      <article class="card live-card group-card" data-ids="${esc(ids)}" data-title="${esc(g.title)}" tabindex="0">
        <div class="card-poster">
          ${poster}
          ${!poster ? `<div class="ph">${icon('film')}</div>` : ''}
          <div class="card-overlay">
            <div class="card-badge">
              <span class="src-badge">${n} 个源</span>
              ${(g.qualities || []).slice(0, 3).map((q) => `<span>${esc(q)}</span>`).join('')}
            </div>
            <div class="card-play">${icon('play')}</div>
          </div>
        </div>
        <div class="card-body">
          <div class="card-title" title="${esc(g.title)}">${esc(g.title)}</div>
          <div class="card-sub">
            ${g.year ? `<span>${g.year}</span><span class="dot-sep"></span>` : ''}
            <span class="${g.canPlay ? 'live-ok' : 'live-meta'}">${g.canPlay ? '可播放' : '仅元数据'}</span>
          </div>
          <div class="card-src" title="${esc(names)}">${esc(names)}</div>
        </div>
      </article>`;
  }

  function srcTabsHtml(source, localTotal, live, groupCount) {
    const counts = {};
    if (live && live.sources) live.sources.forEach((s) => { counts[s.id] = s.count; });
    const liveTotal = groupCount != null ? groupCount
      : Object.values(counts).reduce((a, b) => a + b, 0);
    const registry = (state.liveSources && state.liveSources.length) ? state.liveSources : LIVE_PROVIDERS;
    const tabs = [
      { id: 'all', name: '全部', count: (localTotal || 0) + liveTotal },
      { id: 'local', name: '本地片库', count: localTotal },
    ].concat(registry.map((p) => ({ ...p, count: counts[p.id] })));
    return tabs.map((t) => `
      <button data-source="${esc(t.id)}" class="${t.id === source ? 'on' : ''}">
        ${esc(t.name)}${t.count != null ? `<i>${t.count}</i>` : ''}
      </button>`).join('');
  }

  async function renderSearch(view, route) {
    const q = route.query.q || '';
    const source = route.query.source || 'all';
    const genre = route.query.genre || '';
    const year = route.query.year || '';
    const sort = route.query.sort || 'relevance';
    const quality = route.query.quality || '';
    const page = Number(route.query.page || 1);
    const showLocal = source === 'all' || source === 'local';
    const showLive = source !== 'local';
    $('#q').value = q;
    if (!state.liveSources) {
      const reg = await api('/api/live/sources', { quiet: true }).catch(() => null);
      state.liveSources = (reg && reg.sources && reg.sources.length)
        ? reg.sources
        : LIVE_PROVIDERS.map((p) => ({ ...p, playable: p.id === 'archive' || p.id === 'itunes' }));
      if (state.route !== route) return;
    }

    view.innerHTML = `
      <div class="page-head">
        <h1>${q ? `搜索 “${esc(q)}”` : '搜索片库与在线片源'}</h1>
        <p class="grow" id="search-meta">${q ? '正在检索…' : '输入片名、导演或演员开始搜索'}</p>
        ${state.user ? '' : '<span class="chip gold">访客模式 · 仅搜索</span>'}
      </div>
      <div class="src-tabs" id="src-tabs">${srcTabsHtml(source)}</div>
      <div class="filters" id="local-filters" ${source === 'local' ? '' : 'hidden'}>
        <div class="filter-group"><label>类型</label><select id="f-genre"><option value="">全部</option></select></div>
        <div class="filter-group"><label>年份</label><select id="f-year"><option value="">全部</option></select></div>
        <div class="filter-group"><label>画质</label>
          <select id="f-quality"><option value="">全部</option>
            ${['2160p', '1440p', '1080p', '720p', '480p', '360p', '240p'].map((x) => `<option value="${x}">${x}</option>`).join('')}
          </select></div>
        <div class="filter-group"><label>排序</label>
          <select id="f-sort">
            <option value="relevance">综合</option>
            <option value="rating">评分</option>
            <option value="year">年份</option>
            <option value="views">热度</option>
            <option value="title">片名</option>
          </select></div>
        <button class="btn ghost small" id="f-reset">重置</button>
      </div>

      <section class="section">
        <div class="section-head">
          <h2 id="res-title">${source === 'local' ? '本地片库' : '搜索结果'}</h2>
          <span class="sub" id="res-sub"></span>
          ${showLive ? `<button class="btn tiny ghost right" id="live-reload">${icon('refresh')}刷新在线结果</button>` : ''}
        </div>
        <div id="results-grid" class="grid"></div>
        <div class="flex mt16" id="pager" style="justify-content:center"></div>
        <div id="live-errors" class="note mt12"></div>
      </section>
      ${showLive ? '<p class="note mt8">「全部」会把本地片库与各在线片源的命中合并显示；在线结果直接来自片源 API，点开即可查看清晰度并播放/下载。</p>' : ''}`;

    const goSource = (src) => {
      const u = new URLSearchParams();
      if (q) u.set('q', q);
      if (genre) u.set('genre', genre);
      if (year) u.set('year', year);
      if (quality) u.set('quality', quality);
      if (sort !== 'relevance') u.set('sort', sort);
      if (src !== 'all') u.set('source', src);
      navigate(`#/search${u.toString() ? '?' + u.toString() : ''}`);
    };
    $$('#src-tabs button').forEach((b) => { b.onclick = () => goSource(b.dataset.source); });

    const grid = $('#results-grid');

    /* ---------------- loading state ---------------- */
    if (!q) {
      grid.innerHTML = `<div class="empty" style="grid-column:1/-1;padding:48px 20px">${icon('search')}
        <h3>输入关键词开始搜索</h3><p>会同时检索本地片库与 Internet Archive / iTunes / TVMaze / Wikipedia 等在线片源。</p></div>`;
      return;
    }
    grid.innerHTML = Array.from({ length: 8 }, () =>
      '<div class="sk" style="height:300px;border-radius:14px"></div>').join('');

    /* ---------------- requests ---------------- */
    let localPromise = Promise.resolve(null);
    if (showLocal) {
      const params = new URLSearchParams();
      params.set('q', q);
      if (genre) params.set('genre', genre);
      if (year) params.set('year', year);
      if (quality) params.set('quality', quality);
      if (sort) params.set('sort', sort);
      params.set('page', String(page));
      localPromise = api(`/api/search?${params.toString()}`).catch(() => null);
    }

    let livePromise = Promise.resolve(null);
    if (showLive) {
      const srcParam = source === 'all' ? '' : `&sources=${encodeURIComponent(source)}`;
      livePromise = api(`/api/live/search?q=${encodeURIComponent(q)}${srcParam}`)
        .catch((err) => ({ error: err.message, items: [], sources: [], counts: {}, errors: [] }));
    }

    const [localRes, liveRes] = await Promise.all([localPromise, livePromise]);
    if (state.route !== route) return;

    const localItems = (localRes && localRes.items) || [];
    const liveItems = (liveRes && liveRes.items) || [];
    const groups = (liveRes && liveRes.groups) || [];
    const mergedForAll = source === 'all';
    const cards = mergedForAll
      ? [...localItems.map((m) => cardHtml(m)), ...groups.map(groupCardHtml)]
      : (source === 'local' ? localItems.map((m) => cardHtml(m)) : liveItems.map(liveCardHtml));

    /* ---------------- render cards ---------------- */
    if (cards.length) {
      grid.innerHTML = cards.join('');
    } else if (liveRes && liveRes.error) {
      grid.innerHTML = `<div class="empty" style="grid-column:1/-1;padding:44px 20px">${icon('close')}
        <h3>在线片源查询失败</h3><p>${esc(liveRes.error)}</p></div>`;
    } else {
      grid.innerHTML = `<div class="empty" style="grid-column:1/-1;padding:44px 20px">${icon('search')}
        <h3>没有匹配结果</h3><p>换个关键词，或切换上方的来源标签；也可在「后台 → 站点设置」检查代理与 Key。</p></div>`;
    }

    bindCards(view, { guestLock: !state.user });
    $$('.group-card', grid).forEach((card) => {
      const open = () => {
        if (!state.user) { openAuth('登录后可播放与下载这部影片'); return; }
        navigate(`#/group?ids=${encodeURIComponent(card.dataset.ids)}&q=${encodeURIComponent(q)}`);
      };
      card.addEventListener('click', open);
      card.addEventListener('keydown', (e) => { if (e.key === 'Enter') open(); });
    });
    $$('.live-card:not(.group-card)', grid).forEach((card) => {
      const open = () => {
        if (!state.user) { openAuth('登录后可播放在线片源'); return; }
        navigate(`#/live?provider=${encodeURIComponent(card.dataset.provider)}&uid=${encodeURIComponent(card.dataset.uid)}`);
      };
      card.addEventListener('click', open);
      card.addEventListener('keydown', (e) => { if (e.key === 'Enter') open(); });
    });

    /* ---------------- meta + tabs ---------------- */
    const localTotal = localRes ? localRes.total : 0;
    const liveTotal = liveItems.length;
    const groupTotal = groups.length;
    const sub = $('#res-sub');
    if (sub) {
      if (source === 'local') sub.textContent = `${localTotal} 部`;
      else if (mergedForAll) sub.textContent = `本地 ${localTotal} 部 · 在线 ${groupTotal} 部（${liveTotal} 个来源条目）${liveRes && liveRes.cached ? ' · 缓存' : (liveRes && liveRes.took ? ` · ${liveRes.took} ms` : '')}`;
      else sub.textContent = `${liveItems.length} 条在线结果${liveRes && liveRes.cached ? ' · 缓存' : (liveRes && liveRes.took ? ` · ${liveRes.took} ms` : '')}`;
    }
    $('#search-meta').textContent = `共 ${mergedForAll ? localTotal + groupTotal : (source === 'local' ? localTotal : liveTotal)} 条结果`;
    $('#src-tabs').innerHTML = srcTabsHtml(source, localTotal, liveRes, mergedForAll ? groupTotal : null);
    $$('#src-tabs button').forEach((b) => { b.onclick = () => goSource(b.dataset.source); });

    /* ---------------- local filters + pager ---------------- */
    if (source === 'local' && localRes) {
      const pages = Math.max(1, Math.ceil(localRes.total / localRes.pageSize));
      if (pages > 1) {
        $('#pager').innerHTML = `
          <button class="btn small" ${page <= 1 ? 'disabled' : ''} data-page="${page - 1}">上一页</button>
          <span class="muted" style="font-size:12px">第 ${page} / ${pages} 页</span>
          <button class="btn small" ${page >= pages ? 'disabled' : ''} data-page="${page + 1}">下一页</button>`;
        $$('#pager [data-page]').forEach((b) => {
          b.onclick = () => {
            const u = new URLSearchParams(location.hash.split('?')[1] || '');
            u.set('page', b.dataset.page);
            navigate(`#/search?${u.toString()}`);
          };
        });
      }
      const gs = $('#f-genre'), ys = $('#f-year');
      if (gs && gs.options.length === 1) {
        localRes.genres.forEach((g) => { const o = document.createElement('option'); o.value = g; o.textContent = g; gs.appendChild(o); });
        localRes.years.forEach((y) => { const o = document.createElement('option'); o.value = y; o.textContent = y; ys.appendChild(o); });
        gs.value = genre; ys.value = year;
        $('#f-quality').value = quality;
        $('#f-sort').value = sort;
        const apply = () => {
          const u = new URLSearchParams();
          if ($('#q').value.trim()) u.set('q', $('#q').value.trim());
          if (gs.value) u.set('genre', gs.value);
          if (ys.value) u.set('year', ys.value);
          if ($('#f-quality').value) u.set('quality', $('#f-quality').value);
          if ($('#f-sort').value !== 'relevance') u.set('sort', $('#f-sort').value);
          u.set('source', 'local');
          navigate(`#/search?${u.toString()}`);
        };
        ['f-genre', 'f-year', 'f-quality', 'f-sort'].forEach((id) => { $('#' + id).onchange = apply; });
        $('#f-reset').onclick = () => navigate('#/search?source=local');
      }
    }

    /* ---------------- errors + reload ---------------- */
    const errBox = $('#live-errors');
    if (errBox) {
      errBox.innerHTML = (liveRes && liveRes.errors && liveRes.errors.length)
        ? '部分片源暂不可用：' + liveRes.errors.map((e) => esc(String(e).slice(0, 120))).join('；')
        : '';
    }
    const reload = $('#live-reload');
    if (reload) reload.onclick = () => render();
  }

  /* ------------------------------------------------------------ detail */
  async function renderDetail(view, route) {
    if (!state.user) { view.innerHTML = guestWall('影片详情需要登录'); return; }
    const data = await api(`/api/movies/${route.params.id}`);
    if (state.route !== route) return;
    const m = data.movie;
    const wantDownload = route.query.panel === 'download';
    view.innerHTML = `
      <div class="detail-hero">
        <div class="detail-backdrop">
          ${m.backdrop ? `<img src="${esc(m.backdrop)}" alt="" style="width:100%;height:100%;object-fit:cover;filter:blur(6px) saturate(.9);transform:scale(1.06);opacity:.55"/>` : ''}
        </div>
        <div class="detail-wrap">
          <div class="detail-poster">
            ${m.poster ? `<img src="${esc(m.poster)}" alt="${esc(m.title)}"/>`
              : `<div style="aspect-ratio:2/3;display:grid;place-items:center;color:#2b3b4f">${icon('film')}</div>`}
          </div>
          <div class="detail-info">
            <h1>${esc(m.title)}</h1>
            <div class="orig">${esc(m.originalTitle || '')}</div>
            <div class="detail-meta">
              ${m.year ? `<span>${m.year}</span>` : ''}
              ${m.rating ? `<span class="rating-star">${icon('star')}${esc(m.rating)}</span>` : ''}
              ${m.runtime ? `<span>${m.runtime} 分钟</span>` : ''}
              ${(m.genres || []).map((g) => `<span class="chip dim">${esc(g)}</span>`).join('')}
              ${(m.tags || []).map((t) => `<span class="chip">${esc(t)}</span>`).join('')}
            </div>
            <p class="detail-synopsis">${esc(m.synopsis || '暂无简介。')}</p>
            <div class="detail-facts">
              <div>导演<b>${esc(m.director || '—')}</b></div>
              <div>主演<b>${esc((m.cast || []).join(' / ') || '—')}</b></div>
              <div>编码<b>${esc((m.files[0] && m.files[0].codec) || 'h264')}</b></div>
              <div>来源<b>${esc(m.license || m.sourceName || '本地片源')}</b></div>
            </div>
            <div class="detail-actions">
              <button class="btn primary" id="to-play">${icon('play')}立即观看</button>
              <button class="btn" id="to-dl">${icon('download')}下载影片</button>
              <button class="btn ghost" id="to-pl">${icon('plus')}加入片单</button>
              ${m.sourceUrl ? `<a class="btn ghost" href="${esc(m.sourceUrl)}" target="_blank" rel="noopener">${icon('spark')}源站</a>` : ''}
            </div>
          </div>
        </div>
      </div>

      <div class="split">
        <section class="panel" id="panel-watch">
          <div class="panel-head">
            <h2>${icon('play')}在线观看</h2>
            <div class="tabs" style="margin-left:auto">
              <button class="on" data-tab="watch">${icon('play')}播放</button>
              <button data-tab="download">${icon('download')}下载</button>
            </div>
          </div>
          <div class="panel-body">
            <div class="source-row" id="watch-sources"></div>
            <div class="quality-list" id="watch-qualities"></div>
            <div class="field">
              <label>本机解析模式<span class="tip">决定解码路径，播放器内可随时切换</span></label>
              <div class="seg" id="decode-pick">
                <button data-d="auto" class="${(state.settings.defaultDecoding || 'auto') === 'auto' ? 'on' : ''}">自动</button>
                <button data-d="hw" class="${state.settings.defaultDecoding === 'hw' ? 'on' : ''}">硬解优先</button>
                <button data-d="sw" class="${state.settings.defaultDecoding === 'sw' ? 'on' : ''}">软解优先</button>
              </div>
            </div>
            <div class="flex">
              <button class="btn primary" id="play-btn">${icon('play')}开始播放</button>
              <span class="muted" style="font-size:11.5px">支持 HLS / MP4 · 记忆播放进度</span>
            </div>
          </div>
        </section>

        <section class="panel" id="panel-download">
          <div class="panel-head">
            <h2>${icon('download')}下载到本机</h2>
            <span class="hint">直连保存到访问端</span>
          </div>
          <div class="panel-body">
            <div class="quality-list" id="dl-qualities"></div>
            <div>
              <div class="field" style="margin-bottom:8px">
                <label>附加元数据<span class="tip">勾选后打包为 ZIP</span></label>
              </div>
              <div class="extras" id="dl-extras">
                ${(m.downloadExtras || []).map((x) => `
                  <label class="extra" data-extra="${x.id}">
                    <input type="checkbox" value="${x.id}" />
                    <span class="box">${icon('check')}</span>
                    <span><span class="e-t">${esc(x.label)}</span><span class="e-d">${esc(x.detail)}</span></span>
                  </label>`).join('')}
              </div>
            </div>
            <div class="dl-summary" id="dl-summary"></div>
            <div class="flex">
              <button class="btn primary" id="dl-btn">${icon('download')}开始下载</button>
              <button class="btn ghost" id="dl-clear">清空元数据</button>
            </div>
            <p class="note">下载由浏览器直接保存到你的设备；勾选元数据时服务端实时打包 ZIP（正片 + 所选文件）。</p>
          </div>
        </section>
      </div>

      ${data.related && data.related.length ? railHtml('相关推荐', data.related) : ''}`;

    bindRails(view);
    bindCards(view);

    const watchFiles = m.watchQualities || [];
    const dlFiles = m.downloadQualities || [];
    const sources = [...new Set(watchFiles.map((f) => f.sourceLabel))];
    let activeSource = sources[0] || '';
    let watchFile = watchFiles[0] || null;
    let dlFile = dlFiles[0] || null;
    let decoding = state.settings.defaultDecoding || 'auto';

    const drawSources = () => {
      $('#watch-sources').innerHTML = sources.length
        ? `<span class="label">影片源</span>${sources.map((s) => `<button class="source-pill ${s === activeSource ? 'on' : ''}" data-src="${esc(s)}">${esc(s)}</button>`).join('')}`
        : '<span class="muted" style="font-size:12px">该影片暂无在线源</span>';
      $$('#watch-sources .source-pill').forEach((b) => {
        b.onclick = () => {
          activeSource = b.dataset.src;
          watchFile = watchFiles.filter((f) => f.sourceLabel === activeSource)[0] || null;
          drawSources(); drawWatchFiles();
        };
      });
    };

    const drawWatchFiles = () => {
      const list = watchFiles.filter((f) => f.sourceLabel === activeSource);
      $('#watch-qualities').innerHTML = list.length ? list.map((f) => `
        <button class="quality-opt ${watchFile && f.id === watchFile.id ? 'on' : ''}" data-fid="${esc(f.id)}">
          <span class="q-tick">${icon('check')}</span>
          <span class="q-main"><b>${esc(f.label)}</b>
            <small>${esc(f.watchType === 'hls' ? 'HLS 自适应' : 'MP4 直读')} · ${esc(f.codec)} ${f.width ? `${f.width}×${f.height}` : ''}</small></span>
          <span class="q-tag">${esc(f.sizeLabel || '')}<br/>${esc(f.quality)}</span>
        </button>`).join('') : '<div class="muted" style="font-size:12px">暂无可用清晰度</div>';
      $$('#watch-qualities .quality-opt').forEach((b) => {
        b.onclick = () => {
          watchFile = list.find((f) => f.id === b.dataset.fid) || null;
          drawWatchFiles();
        };
      });
    };

    const drawDlFiles = () => {
      $('#dl-qualities').innerHTML = dlFiles.length ? dlFiles.map((f) => `
        <button class="quality-opt ${dlFile && f.id === dlFile.id ? 'on' : ''}" data-fid="${esc(f.id)}">
          <span class="q-tick">${icon('check')}</span>
          <span class="q-main"><b>${esc(f.label)}</b>
            <small>${esc(f.quality)} · ${esc(f.sizeLabel || '未知大小')} · ${esc(f.sourceLabel)}</small></span>
          <span class="q-tag">${f.height ? `${f.width}×${f.height}` : ''}</span>
        </button>`).join('') : '<div class="muted" style="font-size:12px">该影片未开放下载</div>';
      $$('#dl-qualities .quality-opt').forEach((b) => {
        b.onclick = () => {
          dlFile = dlFiles.find((f) => f.id === b.dataset.fid) || null;
          drawDlFiles(); updateSummary();
        };
      });
    };

    const selectedExtras = () => $$('#dl-extras .extra.on').map((el) => el.dataset.extra);
    const updateSummary = () => {
      const ex = selectedExtras();
      $('#dl-summary').innerHTML = !dlFile
        ? '请选择清晰度'
        : `清晰度 <b>${esc(dlFile.quality)}</b> · 正片 ${esc(fmtBytes(dlFile.sizeBytes))} · 元数据 <b>${ex.length}</b> 项
           ${ex.length ? '· 打包为 <b>ZIP</b>' : '· 直接下载 <b>MP4</b>'}`;
    };

    $$('#dl-extras .extra').forEach((el) => {
      el.onclick = (e) => {
        e.preventDefault();
        el.classList.toggle('on');
        el.querySelector('input').checked = el.classList.contains('on');
        updateSummary();
      };
    });
    $('#dl-clear').onclick = () => {
      $$('#dl-extras .extra.on').forEach((el) => {
        el.classList.remove('on');
        el.querySelector('input').checked = false;
      });
      updateSummary();
    };

    $$('#decode-pick button').forEach((b) => {
      b.onclick = () => {
        decoding = b.dataset.d;
        $$('#decode-pick button').forEach((x) => x.classList.toggle('on', x === b));
      };
    });

    const goPlay = () => {
      if (!watchFile) return toast('该影片暂无可播放的清晰度', 'err');
      navigate(`#/watch/${m.id}/${watchFile.id}?decoding=${decoding}`);
    };
    $('#to-play').onclick = goPlay;
    $('#play-btn').onclick = goPlay;
    $('#to-dl').onclick = () => {
      $('#panel-download').scrollIntoView({ behavior: 'smooth', block: 'center' });
    };
    if (wantDownload) setTimeout(() => $('#panel-download').scrollIntoView({ behavior: 'smooth', block: 'center' }), 260);

    $('#dl-btn').onclick = () => {
      if (!dlFile) return toast('请选择下载清晰度', 'err');
      const ex = selectedExtras();
      triggerDownload(`/api/download/${m.id}/${dlFile.id}${ex.length ? '?extras=' + ex.join(',') : ''}`);
      toast(ex.length ? '已开始打包下载（正片 + 元数据）' : '已开始下载正片', 'ok');
    };

    $$('.tabs [data-tab]').forEach((b) => {
      b.onclick = () => {
        $$('.tabs [data-tab]').forEach((x) => x.classList.toggle('on', x === b));
        $(b.dataset.tab === 'download' ? '#panel-download' : '#panel-watch')
          .scrollIntoView({ behavior: 'smooth', block: 'center' });
      };
    });

    $('#to-pl').onclick = () => openPlaylistPicker(m, data.playlists || []);
    drawSources(); drawWatchFiles(); drawDlFiles(); updateSummary();
  }

  function triggerDownload(url) {
    const a = document.createElement('a');
    a.href = url;
    a.rel = 'noopener';
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => a.remove(), 1500);
  }

  async function openPlaylistPicker(movie, playlists) {
    const list = playlists || [];
    const body = `
      <div class="list">
        ${list.length ? list.map((p) => `
          <div class="row-item">
            <div class="r-main"><div class="r-t">${esc(p.name)}</div>
            <div class="r-m">${p.has ? '已在本片单中' : '点击加入'}</div></div>
            <button class="btn small" data-add="${esc(p.id)}" ${p.has ? 'disabled' : ''}>
              ${p.has ? icon('check') : icon('plus')}${p.has ? '已加入' : '加入'}</button>
          </div>`).join('') : '<p class="muted" style="font-size:13px">还没有片单，先创建一个吧。</p>'}
      </div>
      <div class="hr"></div>
      <div class="flex">
        <input id="new-pl-name" type="text" placeholder="新片单名称" style="flex:1" />
        <button class="btn primary" id="new-pl">${icon('plus')}新建并加入</button>
      </div>`;
    openModal({
      title: '加入播放列表', sub: esc(movie.title), body,
      onMount(wrap, close) {
        $$('[data-add]', wrap).forEach((b) => {
          b.onclick = async () => {
            await api(`/api/playlists/${b.dataset.add}`, { method: 'PATCH', body: { addMovieId: movie.id } });
            toast('已加入片单', 'ok');
            b.disabled = true;
            b.innerHTML = `${icon('check')}已加入`;
          };
        });
        $('#new-pl', wrap).onclick = async () => {
          const name = $('#new-pl-name', wrap).value.trim() || '我的片单';
          await api('/api/playlists', { method: 'POST', body: { name, movieId: movie.id } });
          toast('片单已创建', 'ok');
          close();
        };
      },
    });
  }

  /* ------------------------------------------------------------- shell */
  function bindShell() {
    $('#menu-btn').onclick = () => $('#sidebar').classList.toggle('open');
    const userBtn = $('#user-btn'), menu = $('#user-menu');
    userBtn.onclick = (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; };
    document.addEventListener('click', (e) => {
      if (!e.target.closest('#user-chip')) menu.hidden = true;
      if (!e.target.closest('#sidebar') && !e.target.closest('#menu-btn')) $('#sidebar').classList.remove('open');
    });
    menu.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-act]');
      if (!btn) return;
      menu.hidden = true;
      const act = btn.dataset.act;
      if (act === 'login') openAuth('登录后解锁全部功能');
      if (act === 'logout') logout();
      if (act === 'playlists') navigate('#/playlists');
      if (act === 'history') navigate('#/history');
      if (act === 'admin') navigate('#/admin');
      if (act === 'account') openAccount();
    });

    // CSP-safe inline actions
    document.addEventListener('click', (e) => {
      const t = e.target.closest('[data-cb]');
      if (!t) return;
      const act = t.dataset.cb;
      if (act === 'login') openAuth('登录后解锁全部功能');
      if (act === 'reload') location.reload();
      if (act === 'search') navigate('#/search');
    });

    // nav guard for guests
    $$('#nav a[data-auth]').forEach((a) => {
      a.addEventListener('click', (e) => {
        if (!state.user) {
          e.preventDefault();
          openAuth('该功能需要登录后使用');
        }
      });
    });

    $('#searchbar').addEventListener('submit', (e) => {
      e.preventDefault();
      const q = $('#q').value.trim();
      navigate(`#/search${q ? '?q=' + encodeURIComponent(q) : ''}`);
      $('#suggest').hidden = true;
    });

    // suggest
    let suggestTimer = null;
    const qEl = $('#q');
    qEl.addEventListener('input', () => {
      clearTimeout(suggestTimer);
      const q = qEl.value.trim();
      if (!q) { $('#suggest').hidden = true; return; }
      suggestTimer = setTimeout(async () => {
        try {
          const res = await api(`/api/suggest?q=${encodeURIComponent(q)}`, { quiet: true });
          const box = $('#suggest');
          if (!res.items.length) { box.hidden = true; return; }
          box.innerHTML = res.items.map((m) => `
            <div class="s-item" data-mid="${esc(m.id)}">
              <img src="${esc(m.poster)}" alt=""/>
              <div><div class="s-t">${esc(m.title)}</div>
                <div class="s-m">${esc(m.year || '')} · ${esc((m.genres || []).join(' / '))}</div></div>
            </div>`).join('');
          box.hidden = false;
          $$('.s-item', box).forEach((it) => {
            it.onclick = () => {
              box.hidden = true;
              if (!state.user) openAuth('登录后查看影片详情');
              else navigate(`#/movie/${it.dataset.mid}`);
            };
          });
        } catch (e) { /* noop */ }
      }, 220);
    });
    qEl.addEventListener('blur', () => setTimeout(() => { $('#suggest').hidden = true; }, 180));

    document.addEventListener('keydown', (e) => {
      if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
        e.preventDefault(); qEl.focus();
      }
    });
  }

  function openAccount() {
    if (!state.user) { openAuth(); return; }
    openModal({
      title: '账号设置',
      sub: `${esc(state.user.username)} · ${state.user.role === 'admin' ? '管理员' : '普通用户'}`,
      body: `
        <div class="form-grid">
          <label class="fl">显示昵称
            <input id="ac-name" type="text" value="${esc(state.user.displayName || '')}" />
          </label>
          <label class="fl">主题色
            <input id="ac-color" type="color" value="${esc(state.user.avatarColor || '#48d6c8')}" />
          </label>
        </div>
        <div class="hr"></div>
        <div class="form-grid">
          <label class="fl">当前密码<input id="ac-cur" type="password" autocomplete="current-password" /></label>
          <label class="fl">新密码<input id="ac-new" type="password" autocomplete="new-password" /></label>
        </div>
        <p class="note">修改密码后，其它设备上的会话会被同时注销。</p>`,
      foot: `<button class="btn ghost" data-x="c">关闭</button>
             <button class="btn primary" data-x="s">保存</button>`,
      onMount(wrap, close) {
        wrap.querySelector('[data-x="c"]').onclick = close;
        wrap.querySelector('[data-x="s"]').onclick = async () => {
          const name = $('#ac-name', wrap).value.trim();
          const color = $('#ac-color', wrap).value;
          const cur = $('#ac-cur', wrap).value;
          const nxt = $('#ac-new', wrap).value;
          try {
            const r = await api('/api/me', { method: 'PATCH', body: { displayName: name, avatarColor: color } });
            state.user = r.user;
            applyIdentity();
            if (cur && nxt) {
              await api('/api/me/password', { method: 'POST', body: { current: cur, next: nxt } });
              toast('密码已更新', 'ok');
            } else {
              toast('资料已保存', 'ok');
            }
            close();
          } catch (e) { /* toast handled */ }
        };
      },
    });
  }

  /* ------------------------------------------------------------- boot */
  async function boot() {
    bindShell();
    try {
      const me = await api('/api/auth/me', { quiet: true });
      state.user = me.user;
      state.settings = me.settings || {};
      state.csrf = me.csrf || '';
    } catch (e) { /* offline */ }
    applyIdentity();
    window.addEventListener('hashchange', render);
    await render();
    // health pill: online / offline only
    api('/api/health', { quiet: true }).then((h) => {
      state.health = h;
      const pill = $('#server-pill');
      pill.classList.remove('offline');
      pill.classList.add('online');
      pill.innerHTML = '<i class="dot"></i><span>服务在线</span>';
    }).catch(() => {
      const pill = $('#server-pill');
      pill.classList.remove('online');
      pill.classList.add('offline');
      pill.innerHTML = '<i class="dot"></i><span>服务离线</span>';
    });
  }

  /* ----------------------------------------------------------- exports */
  const CB = {
    $, $$, state, api, icon, esc, fmtTime, fmtBytes, fmtDate, ago,
    toast, openModal, confirmDialog, openAuth, logout, applyIdentity,
    navigate, render, cardHtml, railHtml, bindCards, bindRails,
    guestWall, triggerDownload, register, boot, renderNotFound, skeletonRail,
    ROUTES,
  };

  register('home', renderHome);
  register('search', renderSearch);
  register('movie', renderDetail);
  register('login', () => { openAuth('请登录以继续'); navigate('#/'); });

  window.__cinebox = {
    login: () => openAuth('登录后解锁全部功能'),
    logout,
    state,
  };

  return CB;
})();
