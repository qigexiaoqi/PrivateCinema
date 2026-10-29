/* =============================================================
   CINEBOX · live source pages
   - #/live  : one source item
   - #/group : one film merged from several sources (pick a source to play)

   Layout rules (per product feedback):
   - no long episode/quality list above the player: the in-player pill is the
     only selector ("清晰度 / 选集");
   - downloads live in their own scroll box and always ask for a quality first
     (single + batch).
   ============================================================= */
(() => {
  'use strict';
  const CB = window.CB;
  const { state, icon, esc, api, toast, navigate, guestWall, triggerDownload, register, openModal } = CB;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  const KIND_LABEL = { hls: 'HLS', mp4: 'MP4', embed: '网页播放' };
  const KIND_RANK = { hls: 0, mp4: 1, embed: 2 };

  document.addEventListener('click', () => {
    const pop = document.getElementById('live-qpop');
    if (pop) pop.hidden = true;
  });

  function kindOf(f) {
    return f.kind || (String(f.url || '').includes('.m3u8') ? 'hls' : 'mp4');
  }

  function imageUrl(u) {
    if (!u) return '';
    return u.startsWith('http') ? '/api/img?u=' + encodeURIComponent(u) : u;
  }

  function orderedFiles(files) {
    return (files || [])
      .map((f, i) => ({ ...f, _idx: i }))
      .sort((a, b) => (KIND_RANK[kindOf(a)] ?? 9) - (KIND_RANK[kindOf(b)] ?? 9));
  }

  function playerBlockHtml(poster) {
    return `
      <div class="player-wrap" id="lpw">
        <div class="stage live-stage" id="lstage">
          <video id="live-video" controls playsinline preload="metadata" poster="${esc(poster || '')}"></video>
          <div class="live-embed" id="live-embed" hidden>
            <iframe id="live-iframe" src="about:blank" allowfullscreen allow="autoplay; fullscreen; encrypted-media"></iframe>
          </div>
          <div class="live-qwrap">
            <button class="live-qpill" id="live-qpill" type="button">清晰度 / 选集 ▾</button>
            <div class="live-qpop" id="live-qpop" hidden></div>
          </div>
        </div>
      </div>`;
  }

  function bindPlayer(view, files) {
    const video = $('#live-video', view);
    const embedBox = $('#live-embed', view);
    const iframe = $('#live-iframe', view);
    let hls = null;

    const stop = () => {
      if (hls) { try { hls.destroy(); } catch (e) {} hls = null; }
      if (video) { try { video.pause(); } catch (e) {} }
      if (iframe) iframe.src = 'about:blank';
    };

    const setFile = (idx, autoplay = true) => {
      const f = files[idx];
      if (!f) return;
      const pill = $('#live-qpill', view);
      if (pill) pill.textContent = `${f.label || f.quality} ▾`;
      const cur = $('#cur-label', view);
      if (cur) cur.textContent = `${f.label || f.quality} · ${KIND_LABEL[kindOf(f)] || ''}`;
      const pop = $('#live-qpop', view);
      if (pop) pop.hidden = true;

      const kind = kindOf(f);
      stop();
      if (kind === 'embed') {
        video.hidden = true;
        embedBox.hidden = false;
        iframe.src = f.url;
        return;
      }
      video.hidden = false;
      embedBox.hidden = true;
      const src = f.playUrl;
      if (kind === 'hls' && window.Hls && window.Hls.isSupported()) {
        hls = new window.Hls({ enableWorker: true, maxBufferLength: 30 });
        state.liveHls = hls;
        hls.loadSource(src);
        hls.attachMedia(video);
        hls.on(window.Hls.Events.ERROR, (_e, d) => {
          if (!d.fatal) return;
          if (d.type === window.Hls.ErrorTypes.NETWORK_ERROR) setTimeout(() => { try { hls.startLoad(); } catch (e) {} }, 1200);
          else if (d.type === window.Hls.ErrorTypes.MEDIA_ERROR) { try { hls.recoverMediaError(); } catch (e) {} }
        });
      } else {
        video.src = src;
      }
      if (autoplay) video.play().catch(() => {});
    };

    const pill = $('#live-qpill', view);
    const pop = $('#live-qpop', view);
    if (pill && pop) {
      pill.onclick = (e) => {
        e.stopPropagation();
        const willOpen = pop.hidden;
        pop.hidden = !willOpen;
        if (!willOpen) return;
        pop.innerHTML = files.map((f, i) => `
          <button data-qi="${i}">
            ${esc(f.label || f.quality)}<span>${esc(KIND_LABEL[kindOf(f)] || '')}</span>
          </button>`).join('');
        $$('button[data-qi]', pop).forEach((b) => {
          b.onclick = (ev) => { ev.stopPropagation(); setFile(Number(b.dataset.qi)); };
        });
      };
      pop.addEventListener('click', (e) => e.stopPropagation());
    }

    if (files.length) setFile(0, false);
    return { setFile, stop, files };
  }

  /* ------------------------------------------------------- download picker */
  function groupByLine(files) {
    const groups = new Map();
    files.forEach((f) => {
      const key = `${f.quality}|${kindOf(f)}`;
      if (!groups.has(key)) {
        groups.set(key, { quality: f.quality, kind: kindOf(f), files: [] });
      }
      groups.get(key).files.push(f);
    });
    return Array.from(groups.values());
  }

  function downloadFiles(src, files) {
    files.forEach((f, i) => {
      setTimeout(() => {
        triggerDownload(`/api/live/download?provider=${encodeURIComponent(src.provider)}`
          + `&uid=${encodeURIComponent(src.uid)}&file=${f._idx}`);
      }, i * 700);
    });
    toast(files.length > 1 ? `已开始 ${files.length} 个下载（浏览器可能提示允许多文件下载）` : '已开始下载', 'ok');
  }

  /* one file: confirm + (implicit) quality info */
  function openConfirmDownload(file, src) {
    const kind = kindOf(file);
    openModal({
      title: '下载确认',
      sub: '确认后开始下载到本机',
      body: `<div class="quality-list">
        <div class="quality-opt on" style="cursor:default">
          <span class="q-tick">${icon('check')}</span>
          <span class="q-main"><b>${esc(file.label || file.quality)}</b>
            <small>${esc(file.quality)} · ${esc(KIND_LABEL[kind] || '')}${file.sizeLabel && file.sizeLabel !== '—' ? ' · ' + esc(file.sizeLabel) : ''}</small></span>
          <span class="q-tag">${kind === 'embed' ? '网页播放' : '可下载'}</span>
        </div>
      </div>
      ${kind === 'embed' ? '<p class="note">该地址是网页播放页，无法直接下载。</p>' : ''}`,
      foot: `<button class="btn ghost" data-x="c">取消</button>
             <button class="btn primary" data-x="s" ${kind === 'embed' ? 'disabled' : ''}>${icon('download')}下载</button>`,
      onMount(wrap, close) {
        wrap.querySelector('[data-x="c"]').onclick = close;
        wrap.querySelector('[data-x="s"]').onclick = () => {
          close();
          downloadFiles(src, [file]);
        };
      },
    });
  }

  /* batch: quality/line selector + checkbox list + 全选/反选 */
  function openBatchDownload(files, preselected = [], src = {}) {
    const downloadable = files.filter((f) => kindOf(f) !== 'embed');
    if (!downloadable.length) return toast('该线路只有网页播放地址，无法下载', 'err');
    const groups = groupByLine(downloadable);
    const pre = new Set(preselected.map(Number));
    let groupIndex = 0;
    const picked = new Set();

    const body = `
      ${groups.length > 1 ? `
        <div class="q-label">清晰度 / 线路</div>
        <div class="seg" id="bq">
          ${groups.map((g, i) => `<button data-g="${i}" class="${i === 0 ? 'on' : ''}">${esc(g.quality)} · ${esc(KIND_LABEL[g.kind] || '')}</button>`).join('')}
        </div>` : ''}
      <div class="flex" style="justify-content:space-between;margin:12px 0 6px">
        <span class="muted" id="bcount">0 项已选</span>
        <span class="flex" style="gap:6px">
          <button class="btn tiny ghost" id="ball">全选</button>
          <button class="btn tiny ghost" id="binv">反选</button>
          <button class="btn tiny ghost" id="bclr">清除</button>
        </span>
      </div>
      <div class="quality-list" id="blist" style="max-height:44vh;overflow:auto"></div>`;

    const modal = openModal({
      title: '批量下载：选择清晰度 / 选集',
      sub: '勾选要下载的条目，先选清晰度再下载',
      body,
      foot: `<button class="btn ghost" data-x="c">取消</button>
             <button class="btn primary" data-x="s" id="bgo" disabled>${icon('download')}下载 0 个</button>`,
      onMount(wrap, close) {
        const list = wrap.querySelector('#blist');
        const count = wrap.querySelector('#bcount');
        const go = wrap.querySelector('#bgo');

        const paint = () => {
          const group = groups[groupIndex];
          list.innerHTML = group.files.map((f) => `
            <label class="quality-opt ${picked.has(f._idx) ? 'on' : ''}" data-file="${f._idx}">
              <span class="q-tick">${icon('check')}</span>
              <span class="q-main"><b>${esc(f.label || f.quality)}</b>
                <small>${esc(f.quality)} · ${esc(KIND_LABEL[kindOf(f)] || '')}${f.sizeLabel && f.sizeLabel !== '—' ? ' · ' + esc(f.sizeLabel) : ''}</small></span>
              <span class="q-tag">${picked.has(f._idx) ? '已选' : ''}</span>
            </label>`).join('');
          list.querySelectorAll('[data-file]').forEach((row) => {
            row.querySelector('input')?.remove();
            row.onclick = (e) => {
              e.preventDefault();
              const idx = Number(row.dataset.file);
              if (picked.has(idx)) picked.delete(idx); else picked.add(idx);
              paint();
            };
          });
          count.textContent = `${picked.size} 项已选`;
          go.disabled = picked.size === 0;
          go.innerHTML = `${icon('download')}下载 ${picked.size} 个`;
          // 默认选中（仅首次进入）
          if (!paint.done) {
            const initial = pre.size ? group.files.filter((f) => pre.has(f._idx)) : group.files;
            initial.forEach((f) => picked.add(f._idx));
            paint.done = true;
            paint();
          }
        };
        paint.done = false;
        paint();

        wrap.querySelectorAll('#bq button').forEach((b) => {
          b.onclick = () => {
            groupIndex = Number(b.dataset.g);
            wrap.querySelectorAll('#bq button').forEach((x) => x.classList.toggle('on', x === b));
            paint.done = true;
            paint();
          };
        });
        wrap.querySelector('#ball').onclick = () => {
          groups[groupIndex].files.forEach((f) => picked.add(f._idx));
          paint();
        };
        wrap.querySelector('#binv').onclick = () => {
          groups[groupIndex].files.forEach((f) => {
            if (picked.has(f._idx)) picked.delete(f._idx); else picked.add(f._idx);
          });
          paint();
        };
        wrap.querySelector('#bclr').onclick = () => {
          picked.clear();
          paint();
        };
        wrap.querySelector('[data-x="c"]').onclick = close;
        go.onclick = () => {
          const chosen = downloadable.filter((f) => picked.has(f._idx));
          close();
          downloadFiles(src, chosen);
        };
      },
    });
    return modal;
  }

  function heroHtml(meta, badges, facts) {
    return `
      <div class="detail-hero">
        <div class="detail-backdrop">
          ${meta.backdrop ? `<img src="${esc(imageUrl(meta.backdrop))}" alt="" style="width:100%;height:100%;object-fit:cover;filter:blur(8px) saturate(.9);transform:scale(1.06);opacity:.5"/>` : ''}
        </div>
        <div class="detail-wrap">
          <div class="detail-poster">
            ${meta.poster ? `<img src="${esc(imageUrl(meta.poster))}" alt="${esc(meta.title)}"/>`
              : `<div style="aspect-ratio:2/3;display:grid;place-items:center;color:#2b3b4f">${icon('film')}</div>`}
          </div>
          <div class="detail-info">
            <div class="flex" style="gap:8px">${badges}</div>
            <h1>${esc(meta.title)}</h1>
            <div class="orig">${esc(meta.originalTitle || '')}</div>
            <div class="detail-meta">
              ${meta.year ? `<span>${meta.year}</span>` : ''}
              ${meta.rating ? `<span class="rating-star">${icon('star')}${esc(meta.rating)}</span>` : ''}
              ${(meta.genres || []).map((g) => `<span class="chip dim">${esc(g)}</span>`).join('')}
            </div>
            <p class="detail-synopsis">${esc(meta.synopsis || '该片源未提供简介。')}</p>
            <div class="detail-facts">${facts}</div>
          </div>
        </div>
      </div>`;
  }

  function watchPanel(files, posterHtml, kind) {
    const maccms = kind === 'maccms';
    return `
      <section class="panel">
        <div class="panel-head">
          <h2>${icon('play')}在线观看</h2>
          <span class="hint">${maccms ? '右上角切换线路 / 选集' : '右上角切换清晰度'}</span>
        </div>
        <div class="panel-body">
          ${playerBlockHtml(posterHtml)}
          <div class="now-playing">
            正在播放：<b id="cur-label">—</b>
            <span id="cur-count">共 ${files.length} 个地址</span>
          </div>
          <p class="note">${maccms
            ? '该资源站只提供单一 HLS 线路（外加一个网页播放页），<b>没有 1080P/720P 多清晰度</b>；右上角选择器用于切换集数/线路。'
            : '该片源提供多档清晰度，右上角选择器可直接切换。'} HLS/MP4 由服务器代理转发（Range 透传）。</p>
        </div>
      </section>`;
  }

  function downloadPanel(files) {
    const rows = files
      .map((f, i) => ({ f, i }))
      .filter((x) => kindOf(x.f) !== 'embed');
    return `
      <section class="panel dl-panel">
        <div class="panel-head">
          <h2>${icon('download')}下载到本机</h2>
          <div class="flex" style="margin-left:auto;gap:6px">
            <button class="btn tiny ghost" id="dl-all">全选</button>
            <button class="btn tiny ghost" id="dl-invert">反选</button>
            <button class="btn tiny ghost" id="dl-clear">清除</button>
            <button class="btn small primary" id="dl-batch" hidden>批量下载</button>
          </div>
        </div>
        <div class="panel-body">
          <div class="dl-scroll">
            ${rows.length ? rows.map(({ f, i }) => `
              <div class="dl-row">
                <input type="checkbox" class="dl-check" data-i="${i}" aria-label="选择 ${esc(f.label || f.quality)}" />
                <div class="dl-main">
                  <b>${esc(f.label || f.quality)}</b>
                  <small>${esc(f.quality)} · ${esc(KIND_LABEL[kindOf(f)] || '')}${f.sizeLabel && f.sizeLabel !== '—' ? ' · ' + esc(f.sizeLabel) : ''}</small>
                </div>
                <button class="btn tiny" data-one="${i}">${icon('download')}下载</button>
              </div>`).join('')
              : '<p class="muted" style="font-size:12px;padding:8px 2px">该线路只有网页播放地址，没有可下载文件。</p>'}
          </div>
          <p class="note">勾选条目后出现「批量下载」；单条「下载」和批量下载都会先确认清晰度/线路，再点「下载」或「取消」。</p>
        </div>
      </section>`;
  }

  function wireDownloads(view, src, files) {
    const boxes = Array.from(view.querySelectorAll('.dl-check'));
    const batchBtn = $('#dl-batch', view);
    const refresh = () => {
      const n = boxes.filter((b) => b.checked).length;
      if (batchBtn) {
        batchBtn.hidden = n === 0;
        batchBtn.textContent = `批量下载 (${n})`;
      }
    };
    boxes.forEach((b) => { b.onchange = refresh; });
    const all = $('#dl-all', view);
    const inv = $('#dl-invert', view);
    const clr = $('#dl-clear', view);
    if (all) all.onclick = () => { boxes.forEach((b) => { b.checked = true; }); refresh(); };
    if (inv) inv.onclick = () => { boxes.forEach((b) => { b.checked = !b.checked; }); refresh(); };
    if (clr) clr.onclick = () => { boxes.forEach((b) => { b.checked = false; }); refresh(); };
    if (batchBtn) {
      batchBtn.onclick = () => {
        const selected = boxes.filter((b) => b.checked).map((b) => files[Number(b.dataset.i)]);
        openBatchDownload(files, selected.map((f) => f._idx), src);
      };
    }
    view.querySelectorAll('[data-one]').forEach((b) => {
      b.onclick = () => openConfirmDownload(files[Number(b.dataset.one)], src);
    });
    refresh();
  }

  /* ------------------------------------------------------------ one source */
  async function renderLive(view, route) {
    if (!state.user) { view.innerHTML = guestWall('在线片源详情需要登录'); return; }
    if (state.liveHls) { try { state.liveHls.destroy(); } catch (e) {} state.liveHls = null; }
    const provider = route.query.provider || '';
    const uid = route.query.uid || '';
    const data = await api(`/api/live/item?provider=${encodeURIComponent(provider)}&uid=${encodeURIComponent(uid)}`);
    if (state.route !== route) return;
    const it = data.item;
    const files = orderedFiles(it.files);
    const poster = imageUrl(it.poster);

    view.innerHTML = `
      ${heroHtml(it, `
        <span class="chip accent">${esc(it.providerName || it.provider)}</span>
        <span class="chip dim">在线片源</span>
        ${it.remark ? `<span class="chip gold">${esc(it.remark)}</span>` : ''}`,
        `<div>片源<b>${esc(it.providerName || it.provider)}</b></div>
         <div>地址<b>${files.length}</b></div>
         <div>许可<b>${esc((it.license || '见源站').slice(0, 40))}</b></div>`)}
      ${files.length ? `
      <div class="split">
        ${watchPanel(files, poster, it.providerKind)}
        ${downloadPanel(files, it.providerKind)}
      </div>` : `
      <div class="empty">${icon('film')}<h3>该片源只提供元数据</h3>
        <p>${esc(it.providerName || it.provider)} 没有可播放地址。</p>
        <a class="btn ghost mt16" href="#/search">返回搜索</a>
      </div>`}`;

    if (!files.length) return;
    if (route.query.nomedia !== '1') bindPlayer(view, files);
    wireDownloads(view, { provider, uid, providerKind: it.providerKind }, files);
  }

  /* --------------------------------------------------------- merged sources */
  async function renderGroup(view, route) {
    if (!state.user) { view.innerHTML = guestWall('播放与下载需要登录后使用'); return; }
    if (state.liveHls) { try { state.liveHls.destroy(); } catch (e) {} state.liveHls = null; }
    const ids = route.query.ids || '';
    const data = await api(`/api/live/group?ids=${encodeURIComponent(ids)}`);
    if (state.route !== route) return;
    const g = data.group;
    const sources = (g.sources || []).filter((s) => (s.files || []).length);
    const metas = (g.sources || []).filter((s) => !(s.files || []).length);
    const first = sources[0];

    view.innerHTML = `
      ${heroHtml(g, `
        <span class="chip accent">${sources.length || metas.length} 个播放源</span>
        <span class="chip dim">聚合结果</span>
        ${g.remark ? `<span class="chip gold">${esc(g.remark)}</span>` : ''}`,
        `<div>播放源<b>${sources.length}</b></div>
         <div>播放地址<b>${sources.reduce((n, s) => n + s.files.length, 0)}</b></div>
         <div>元数据源<b>${metas.length}</b></div>`)}
      ${sources.length ? `
      <div class="split">
        <section class="panel">
          <div class="panel-head">
            <h2>${icon('play')}在线观看</h2>
            <span class="hint">先选播放源，右上角切换清晰度 / 选集</span>
          </div>
          <div class="panel-body">
            <div class="source-row" id="group-sources">
              <span class="label">播放源</span>
              ${sources.map((s, i) => `
                <button class="source-pill ${i === 0 ? 'on' : ''}" data-src="${i}">
                  ${esc(s.providerName)}<span class="src-count">${s.files.length}</span>
                </button>`).join('')}
            </div>
            ${playerBlockHtml(imageUrl(g.poster))}
            <div class="now-playing">
              正在播放：<b id="cur-label">—</b>
              <span>当前播放源：<b id="q-source-name">${esc(first.providerName)}</b></span>
            </div>
            <p class="note">同一部影片在多个资源站都有片源时只显示一张卡片；这里可以逐源切换播放，地址均由本站代理。</p>
          </div>
        </section>
        ${downloadPanel(orderedFiles(first.files), first.providerKind)}
      </div>` : `
      <div class="empty">${icon('film')}<h3>这些来源只提供元数据</h3>
        <p>没有可直接播放的地址，换一个片源或到源站查看。</p>
        <a class="btn ghost mt16" href="#/search">返回搜索</a>
      </div>`}`;

    if (!sources.length) return;

    let player = null;
    const current = { provider: first.provider, uid: first.uid, files: orderedFiles(first.files) };

    const mount = (index, autoplay = false) => {
      const src = sources[index];
      const files = orderedFiles(src.files);
      if (player) player.stop();
      const dl = $('.split .panel:nth-child(2)');
      if (dl) dl.outerHTML = downloadPanel(files, src.providerKind);
      $$('#group-sources .source-pill').forEach((b) => b.classList.toggle('on', Number(b.dataset.src) === index));
      const nameEl = $('#q-source-name');
      if (nameEl) nameEl.textContent = src.providerName;
      if (route.query.nomedia !== '1') player = bindPlayer(view, files);
      current.provider = src.provider;
      current.uid = src.uid;
      current.files = files;
      wireDownloads(view, { provider: src.provider, uid: src.uid, providerKind: src.providerKind }, files);
      if (autoplay) player.setFile(0, true);
    };

    $$('#group-sources .source-pill').forEach((b) => {
      b.onclick = () => mount(Number(b.dataset.src), true);
    });
    mount(0, false);
  }

  register('live', renderLive);
  register('group', renderGroup);
})();
