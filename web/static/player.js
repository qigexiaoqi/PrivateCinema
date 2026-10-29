/* =============================================================
   CINEBOX · player, playlists, history, downloads
   ============================================================= */
(() => {
  'use strict';
  const CB = window.CB;
  const {
    state, icon, esc, api, toast, openModal, confirmDialog, navigate,
    cardHtml, guestWall, fmtTime, fmtDate, fmtBytes, ago, bindCards, triggerDownload, register,
  } = CB;

  const DECODE_LABEL = { auto: '自动', hw: '硬解优先', sw: '软解优先' };

  function destroyPlayer() {
    if (state.player) {
      try { state.player.destroy(); } catch (e) { /* noop */ }
      state.player = null;
    }
    if (state.hls) {
      try { state.hls.destroy(); } catch (e) { /* noop */ }
      state.hls = null;
    }
  }
  CB.destroyPlayer = destroyPlayer;

  async function detectDecode(file) {
    const out = { supported: null, hardware: null, smooth: null, webcodecs: null };
    const w = file.width || 1920, h = file.height || 1080;
    const bitrate = file.sizeBytes && file.duration
      ? Math.round((file.sizeBytes * 8) / file.duration) : 4000000;
    const contentType = 'video/mp4; codecs="avc1.640028"';
    try {
      if (navigator.mediaCapabilities && navigator.mediaCapabilities.decodingInfo) {
        const r = await navigator.mediaCapabilities.decodingInfo({
          type: 'file',
          video: {
            contentType, width: w, height: h,
            bitrate: Math.min(bitrate, 40000000), framerate: 30,
          },
        });
        out.supported = r.supported;
        out.hardware = r.powerEfficient;
        out.smooth = r.smooth;
      }
    } catch (e) { /* noop */ }
    try {
      if (window.VideoDecoder && window.VideoDecoder.isConfigSupported) {
        const r = await window.VideoDecoder.isConfigSupported({ codec: 'avc1.640028', codedWidth: w, codedHeight: h });
        out.webcodecs = !!r.supported;
      }
    } catch (e) { /* noop */ }
    return out;
  }

  /* -------------------------------------------------------------- watch */
  async function renderWatch(view, route) {
    if (!state.user) { view.innerHTML = guestWall('在线观看需要登录'); return; }
    const mid = route.params.id;
    const data = await api(`/api/movies/${mid}`);
    if (state.route !== route) return;  // navigated away while loading
    const m = data.movie;
    const files = m.watchQualities || [];
    if (!files.length) {
      view.innerHTML = `<div class="empty">${icon('film')}<h3>暂无可播放源</h3>
        <p>该影片还没有配置在线清晰度。</p></div>`;
      return;
    }
    let current = files.find((f) => f.id === route.params.file) || files[0];
    let decoding = ['auto', 'hw', 'sw'].includes(route.query.decoding)
      ? route.query.decoding : (state.settings.defaultDecoding || 'auto');
    const resumeAt = data.resume && data.resume.movieId === m.id ? (data.resume.position || 0) : 0;

    view.innerHTML = `
      <div class="watch">
        <div>
          <div class="player-wrap paused" id="pw">
            <div class="stage paused" id="stage">
              <video id="video" playsinline preload="metadata"></video>
              <button class="big-play" id="big-play" aria-label="播放">${icon('play')}</button>
              <div class="spinner" id="spinner" hidden></div>
              <div class="toast-overlay" id="ov-toast"></div>
              <div class="controls" id="controls">
                <div class="timeline" id="timeline">
                  <div class="track">
                    <div class="buf" id="tl-buf"></div>
                    <div class="played" id="tl-played"></div>
                    <div class="knob" id="tl-knob"></div>
                  </div>
                  <div class="hover-time" id="tl-hover">0:00</div>
                </div>
                <div class="ctrl-row">
                  <button class="ctrl-btn" id="btn-play" title="播放/暂停 (空格)">${icon('play')}</button>
                  <div class="vol">
                    <button class="ctrl-btn" id="btn-mute" title="静音 (M)">${icon('volume')}</button>
                    <input type="range" id="vol" min="0" max="1" step="0.01" value="1" aria-label="音量" />
                  </div>
                  <span class="ctrl-time" id="time">0:00 / 0:00</span>
                  <span class="ctrl-spacer"></span>
                  <div class="pill-menu">
                    <button class="pill-btn" id="pill-quality">${icon('play')}<span>${esc(current.quality)}</span></button>
                    <div class="pill-pop" id="pop-quality"></div>
                  </div>
                  <div class="pill-menu">
                    <button class="pill-btn" id="pill-source">${icon('film')}<span>片源</span></button>
                    <div class="pill-pop" id="pop-source"></div>
                  </div>
                  <div class="pill-menu">
                    <button class="pill-btn" id="pill-speed">1.00x</button>
                    <div class="pill-pop" id="pop-speed"></div>
                  </div>
                  <div class="pill-menu">
                    <button class="pill-btn" id="pill-sub">${icon('sub')}<span>字幕</span></button>
                    <div class="pill-pop" id="pop-sub"></div>
                  </div>
                  <div class="pill-menu">
                    <button class="pill-btn" id="pill-decode">${icon('cpu')}<span id="decode-label">${DECODE_LABEL[decoding]}</span></button>
                    <div class="pill-pop" id="pop-decode"></div>
                  </div>
                  <button class="ctrl-btn" id="btn-pip" title="画中画">${icon('pip')}</button>
                  <button class="ctrl-btn" id="btn-fs" title="全屏 (F)">${icon('expand')}</button>
                </div>
              </div>
            </div>
            <div class="player-bar">
              <div>
                <h1>${esc(m.title)} <span class="muted" style="font-weight:400;font-size:12px">${m.year || ''}</span></h1>
                <div class="sub" id="pb-sub">${esc(current.label)}</div>
              </div>
              <div class="acts">
                <a class="btn small ghost" href="#/movie/${m.id}">${icon('film')}影片详情</a>
                <button class="btn small ghost" id="pb-dl">${icon('download')}下载</button>
              </div>
            </div>
          </div>

          <section class="panel mt16">
            <div class="panel-head">
              <h2>${icon('film')}清晰度与片源</h2>
              <span class="hint">切换后保持当前进度</span>
            </div>
            <div class="panel-body">
              <div class="flex" id="watch-sources-inline"></div>
              <div class="quality-list" id="watch-q-inline"></div>
            </div>
          </section>

          <section class="panel mt16">
            <div class="panel-head"><h2>${icon('spark')}影片信息</h2></div>
            <div class="panel-body">
              <p class="detail-synopsis" style="font-size:13px">${esc(m.synopsis || '暂无简介')}</p>
              <div class="detail-facts">
                <div>导演<b>${esc(m.director || '—')}</b></div>
                <div>主演<b>${esc((m.cast || []).join(' / ') || '—')}</b></div>
                <div>字幕<b>${esc((m.subtitles || []).map((s) => s.label).join(' / ') || '无')}</b></div>
                <div>来源<b>${esc(m.license || current.sourceLabel || '—')}</b></div>
              </div>
            </div>
          </section>
        </div>

        <aside class="side-panel">
          <section class="panel decode-panel">
            <div class="panel-head">
              <h2>${icon('cpu')}本机解析</h2>
              <span class="hint">硬件能力探测</span>
            </div>
            <div class="panel-body">
              <div class="field">
                <label>解码模式</label>
                <div class="seg" id="seg-decode">
                  <button data-d="auto" class="${decoding === 'auto' ? 'on' : ''}">自动</button>
                  <button data-d="hw" class="${decoding === 'hw' ? 'on' : ''}">硬解</button>
                  <button data-d="sw" class="${decoding === 'sw' ? 'on' : ''}">软解</button>
                </div>
              </div>
              <div class="field">
                <label>渲染后端</label>
                <div class="seg" id="seg-render">
                  <button data-r="auto" class="on">自动</button>
                  <button data-r="gpu">GPU</button>
                  <button data-r="cpu">CPU</button>
                </div>
              </div>
              <div class="field">
                <label>画面比例</label>
                <div class="seg" id="seg-ratio">
                  <button data-a="contain" class="on">适应</button>
                  <button data-a="cover">填充</button>
                  <button data-a="fill">拉伸</button>
                </div>
              </div>
              <div class="field">
                <label>缓冲策略</label>
                <div class="seg" id="seg-buffer">
                  <button data-b="auto" class="on">自动</button>
                  <button data-b="large">大缓冲</button>
                  <button data-b="low">低延迟</button>
                </div>
              </div>
              <div class="meter" id="diag">
                <div class="meter-row">硬件解码<b id="dg-hw">检测中…</b></div>
                <div class="meter-row">解码能力<b id="dg-cap">检测中…</b></div>
                <div class="meter-row">播放内核<b id="dg-engine">—</b></div>
                <div class="meter-row">分辨率<b id="dg-res">—</b></div>
                <div class="meter-row">掉帧 / 总量<b id="dg-drop">—</b></div>
                <div class="meter-row">缓冲健康<b id="dg-buf">—</b></div>
              </div>
              <p class="note">「硬解优先」请求原始高码率档；「软解优先」请求服务端生成的 Baseline 基准档，降低解码复杂度。浏览器仍可能按自身策略回落。</p>
            </div>
          </section>

          <section class="panel upnext">
            <div class="panel-head"><h2>${icon('list')}接下来播放</h2></div>
            <div class="panel-body" style="gap:4px">
              ${(data.related || []).slice(0, 5).map((r) => `
                <div class="mini" data-mid="${esc(r.id)}">
                  <img src="${esc(r.poster)}" alt="" loading="lazy"/>
                  <div><div class="t">${esc(r.title)}</div>
                    <div class="m">${esc(r.year || '')}${r.genres && r.genres[0] ? ' · ' + esc(r.genres[0]) : ''}</div></div>
                </div>`).join('') || '<p class="muted" style="font-size:12px">暂无推荐</p>'}
            </div>
          </section>
        </aside>
      </div>`;

    CB.$$('.upnext .mini', view).forEach((el) => {
      el.onclick = () => navigate(`#/movie/${el.dataset.mid}`);
    });

    initPlayer(view, m, files, current, decoding, resumeAt);
  }

  function initPlayer(view, m, files, current, decoding, resumeAt) {
    const $ = (s) => view.querySelector(s);
    const $$ = (s) => Array.from(view.querySelectorAll(s));
    const video = $('#video');
    const stage = $('#stage');
    const wrap = $('#pw');
    const spinner = $('#spinner');
    const tlPlayed = $('#tl-played');
    const tlBuf = $('#tl-buf');
    const tlKnob = $('#tl-knob');
    const timeEl = $('#time');
    const ovToast = $('#ov-toast');
    let hls = null;
    let renderer = 'auto';
    let ratio = 'contain';
    let buffer = 'auto';
    let diagTimer = null;
    let overlayTimer = null;
    let lastSaved = 0;

    const flash = (text) => {
      ovToast.textContent = text;
      ovToast.classList.add('show');
      clearTimeout(overlayTimer);
      overlayTimer = setTimeout(() => ovToast.classList.remove('show'), 1400);
    };

    const engineName = () => (hls ? 'hls.js (MSE)' : '原生 <video>');

    function updateDiag() {
      const cap = video.getVideoPlaybackQuality ? video.getVideoPlaybackQuality() : null;
      $('#dg-engine').textContent = engineName();
      $('#dg-res').textContent = video.videoWidth ? `${video.videoWidth}×${video.videoHeight}` : '—';
      $('#dg-drop').textContent = cap ? `${cap.droppedVideoFrames} / ${cap.totalVideoFrames}` : '—';
      let bufSec = 0;
      try {
        for (let i = 0; i < video.buffered.length; i++) {
          if (video.buffered.start(i) <= video.currentTime && video.currentTime <= video.buffered.end(i)) {
            bufSec = video.buffered.end(i) - video.currentTime;
          }
        }
      } catch (e) { /* noop */ }
      const bufEl = $('#dg-buf');
      bufEl.textContent = bufSec ? `${bufSec.toFixed(1)} s` : '等待数据';
      bufEl.className = bufSec > 4 ? 'ok' : bufSec > 1 ? 'warn' : 'bad';
    }

    function paintProgress() {
      const dur = video.duration || 0;
      const pct = dur ? (video.currentTime / dur) * 100 : 0;
      tlPlayed.style.width = `${Math.min(100, pct)}%`;
      tlKnob.style.left = `${Math.min(100, pct)}%`;
      timeEl.textContent = `${fmtTime(video.currentTime)} / ${fmtTime(dur)}`;
      try {
        if (video.buffered.length) {
          const end = video.buffered.end(video.buffered.length - 1);
          tlBuf.style.width = `${Math.min(100, dur ? (end / dur) * 100 : 0)}%`;
        }
      } catch (e) { /* noop */ }
    }

    function setPlayIcon() {
      const playing = !video.paused && !video.ended;
      $('#btn-play').innerHTML = icon(playing ? 'pause' : 'play');
      stage.classList.toggle('paused', !playing);
      wrap.classList.toggle('paused', !playing);
    }

    function saveProgress(force = false) {
      if (!m || !video.duration) return;
      const now = Date.now();
      if (!force && now - lastSaved < 5000) return;
      lastSaved = now;
      api('/api/history', {
        method: 'POST', quiet: true,
        body: {
          movieId: m.id, fileId: current.id, position: video.currentTime,
          duration: video.duration, quality: current.quality,
        },
      }).catch(() => {});
    }

    function hlsConfig() {
      const base = { enableWorker: true };
      if (buffer === 'large') return { ...base, maxBufferLength: 90, maxMaxBufferLength: 240, backBufferLength: 60 };
      if (buffer === 'low') return { ...base, lowLatencyMode: true, maxBufferLength: 8, maxMaxBufferLength: 20, backBufferLength: 10 };
      return { ...base, maxBufferLength: 30, maxMaxBufferLength: 120, backBufferLength: 30 };
    }

    function drawSourceInline() {
      const host = $('#watch-sources-inline');
      if (!host) return;
      const names = [...new Set(files.map((f) => f.sourceLabel))];
      host.innerHTML = `<span class="label">影片源</span>` + names.map((s) => `
        <button class="source-pill ${current.sourceLabel === s ? 'on' : ''}" data-src="${esc(s)}">${esc(s)}</button>`).join('');
      $$('#watch-sources-inline .source-pill').forEach((b) => {
        b.onclick = () => {
          const f = files.find((x) => x.sourceLabel === b.dataset.src);
          if (f) loadSource(f, { time: video.currentTime });
        };
      });
    }

    function drawQualityMenus() {
      const qPop = $('#pop-quality');
      if (!qPop) return;
      qPop.innerHTML = `<h5>清晰度</h5>` + files.map((f) => `
        <button data-fid="${esc(f.id)}" class="${f.id === current.id ? 'on' : ''}">
          ${esc(f.quality)}<span class="k">${esc(f.sizeLabel || '')}</span></button>`).join('');
      $$('button[data-fid]', qPop).forEach ? null : null;
      Array.from(qPop.querySelectorAll('button[data-fid]')).forEach((b) => {
        b.onclick = () => {
          const f = files.find((x) => x.id === b.dataset.fid);
          if (!f) return;
          closeAllPops();
          loadSource(f, { time: video.currentTime });
          flash(`已切换到 ${f.quality}`);
        };
      });
      $('#pill-quality span').textContent = current.quality;

      const inline = $('#watch-q-inline');
      if (inline) {
        inline.innerHTML = files.map((f) => `
          <button class="quality-opt ${f.id === current.id ? 'on' : ''}" data-inline-fid="${esc(f.id)}">
            <span class="q-tick">${icon('check')}</span>
            <span class="q-main"><b>${esc(f.label)}</b>
              <small>${esc(f.sourceLabel)} · ${esc(f.watchType === 'hls' ? 'HLS' : 'MP4')} · ${esc(f.codec)}</small></span>
            <span class="q-tag">${esc(f.sizeLabel || '')}</span>
          </button>`).join('');
        inline.querySelectorAll('button[data-inline-fid]').forEach((b) => {
          b.onclick = () => {
            const f = files.find((x) => x.id === b.dataset.inlineFid);
            if (!f) return;
            loadSource(f, { time: video.currentTime });
            flash(`已切换到 ${f.quality}`);
          };
        });
      }
    }

    function loadSource(file, { time = 0, autoplay = true } = {}) {
      current = file;
      if (hls) { try { hls.destroy(); } catch (e) { /* noop */ } hls = null; }
      state.hls = null;
      const isHls = file.watchType === 'hls';
      // HLS playlists must be loaded from /media/ so relative segment URIs resolve.
      let url = `/api/stream/${m.id}/${file.id}?decoding=${decoding}`;
      if (isHls && decoding !== 'sw' && file.hlsUrl) url = file.hlsUrl;
      spinner.hidden = false;
      const afterMeta = () => {
        let startAt = time;
        if (startAt > 0.5) {
          // finished last time? restart instead of parking on the end frame
          if (isFinite(video.duration) && startAt >= video.duration - 5) startAt = 0;
          try { video.currentTime = startAt; } catch (e) { /* noop */ }
        }
        if (autoplay) video.play().catch(() => {});
        updateDiag();
      };
      video.onloadedmetadata = afterMeta;
      if (isHls && !video.canPlayType('application/vnd.apple.mpegurl') && window.Hls && window.Hls.isSupported()) {
        hls = new window.Hls(hlsConfig());
        state.hls = hls;
        hls.on(window.Hls.Events.MANIFEST_PARSED, () => { spinner.hidden = true; afterMeta(); });
        hls.on(window.Hls.Events.ERROR, (_evt, data) => {
          if (!data.fatal) return;
          if (data.type === window.Hls.ErrorTypes.NETWORK_ERROR) {
            flash('网络错误，正在重试…');
            setTimeout(() => { try { hls.startLoad(); } catch (e) { /* noop */ } }, 1200);
          } else if (data.type === window.Hls.ErrorTypes.MEDIA_ERROR) {
            flash('解码错误，尝试恢复…');
            try { hls.recoverMediaError(); } catch (e) { /* noop */ }
          } else {
            flash('该清晰度播放失败，请切换其它清晰度');
            spinner.hidden = true;
          }
        });
        hls.loadSource(url);
        hls.attachMedia(video);
      } else {
        video.src = url;
        video.load();
      }
      const pbSub = $('#pb-sub');
      if (pbSub) pbSub.textContent = `${file.label} · ${file.codec}${file.width ? ' ' + file.width + '×' + file.height : ''}`;
      const decLabel = $('#decode-label');
      if (decLabel) decLabel.textContent = DECODE_LABEL[decoding];
      drawQualityMenus();
      drawSourceInline();
      detectDecode(file).then((info) => {
        const hwEl = $('#dg-hw'), capEl = $('#dg-cap');
        if (!hwEl || !capEl) return;
        if (info.hardware === true) { hwEl.textContent = '可用 · 硬件加速'; hwEl.className = 'ok'; }
        else if (info.hardware === false) { hwEl.textContent = '不可用 · 软件解码'; hwEl.className = 'warn'; }
        else { hwEl.textContent = info.supported === false ? '不支持该编码' : '未知'; hwEl.className = 'warn'; }
        const bits = [];
        if (info.supported != null) bits.push(info.supported ? '可解码' : '不支持');
        if (info.smooth != null) bits.push(info.smooth ? '流畅' : '可能卡顿');
        if (info.webcodecs != null) bits.push(info.webcodecs ? 'WebCodecs ✓' : 'WebCodecs ✗');
        capEl.textContent = bits.join(' · ') || '—';
        capEl.className = info.supported === false ? 'bad' : 'ok';
      });
    }

    /* menus */
    function closeAllPops() { $$('.pill-pop').forEach((p) => p.classList.remove('open')); }

    function bindPill(btnSel, popSel, draw) {
      const btn = $(btnSel), pop = $(popSel);
      btn.onclick = (e) => {
        e.stopPropagation();
        const open = pop.classList.contains('open');
        closeAllPops();
        if (!open) { draw(); pop.classList.add('open'); }
      };
      pop.addEventListener('click', (e) => e.stopPropagation());
    }

    bindPill('#pill-quality', '#pop-quality', drawQualityMenus);

    bindPill('#pill-source', '#pop-source', () => {
      const pop = $('#pop-source');
      const names = [...new Set(files.map((f) => f.sourceLabel))];
      pop.innerHTML = `<h5>影片源</h5>` + names.map((s) => `
        <button data-src="${esc(s)}" class="${current.sourceLabel === s ? 'on' : ''}">${esc(s)}</button>`).join('');
      Array.from(pop.querySelectorAll('button[data-src]')).forEach((b) => {
        b.onclick = () => {
          const f = files.find((x) => x.sourceLabel === b.dataset.src);
          closeAllPops();
          if (f) { loadSource(f, { time: video.currentTime }); flash(`片源：${b.dataset.src}`); }
        };
      });
    });

    bindPill('#pill-speed', '#pop-speed', () => {
      const pop = $('#pop-speed');
      pop.innerHTML = `<h5>播放速度</h5>` + [0.5, 0.75, 1, 1.25, 1.5, 2].map((s) => `
        <button data-rate="${s}" class="${Math.abs(video.playbackRate - s) < 0.01 ? 'on' : ''}">${s.toFixed(2)}x</button>`).join('');
      Array.from(pop.querySelectorAll('button[data-rate]')).forEach((b) => {
        b.onclick = () => {
          video.playbackRate = Number(b.dataset.rate);
          $('#pill-speed').textContent = `${Number(b.dataset.rate).toFixed(2)}x`;
          closeAllPops();
        };
      });
    });

    bindPill('#pill-sub', '#pop-sub', () => {
      const pop = $('#pop-sub');
      const subs = m.subtitles || [];
      pop.innerHTML = `<h5>字幕</h5><button data-track="off">关闭字幕</button>` +
        subs.map((s) => `<button data-track="${esc(s.id)}">${esc(s.label || s.lang)}</button>`).join('');
      Array.from(pop.querySelectorAll('button[data-track]')).forEach((b) => {
        b.onclick = () => {
          const id = b.dataset.track;
          Array.from(video.querySelectorAll('track')).forEach((t) => t.remove());
          if (id !== 'off') {
            const sub = subs.find((s) => String(s.id) === String(id));
            if (sub) {
              const track = document.createElement('track');
              track.kind = 'subtitles';
              track.label = sub.label || sub.lang;
              track.srclang = sub.lang || 'zh';
              track.src = sub.url;
              track.default = true;
              video.appendChild(track);
              setTimeout(() => {
                if (video.textTracks && video.textTracks.length) {
                  video.textTracks[video.textTracks.length - 1].mode = 'showing';
                }
              }, 60);
              flash('字幕已开启');
            }
          } else {
            flash('字幕已关闭');
          }
          closeAllPops();
        };
      });
    });

    bindPill('#pill-decode', '#pop-decode', () => {
      const pop = $('#pop-decode');
      pop.innerHTML = `<h5>本机解析</h5>` + ['auto', 'hw', 'sw'].map((d) => `
        <button data-dec="${d}" class="${decoding === d ? 'on' : ''}">${DECODE_LABEL[d]}
          <span class="k">${d === 'sw' ? 'Baseline' : d === 'hw' ? 'High' : '自适应'}</span></button>`).join('');
      Array.from(pop.querySelectorAll('button[data-dec]')).forEach((b) => {
        b.onclick = () => {
          decoding = b.dataset.dec;
          closeAllPops();
          $$('#seg-decode button').forEach((x) => x.classList.toggle('on', x.dataset.d === decoding));
          $('#decode-label').textContent = DECODE_LABEL[decoding];
          loadSource(current, { time: video.currentTime });
          flash(`解析模式：${DECODE_LABEL[decoding]}`);
        };
      });
    });

    $$('#seg-decode button').forEach((b) => {
      b.onclick = () => {
        decoding = b.dataset.d;
        $$('#seg-decode button').forEach((x) => x.classList.toggle('on', x === b));
        $('#decode-label').textContent = DECODE_LABEL[decoding];
        loadSource(current, { time: video.currentTime });
        flash(`解析模式：${DECODE_LABEL[decoding]}`);
      };
    });

    $$('#seg-render button').forEach((b) => {
      b.onclick = () => {
        renderer = b.dataset.r;
        $$('#seg-render button').forEach((x) => x.classList.toggle('on', x === b));
        stage.classList.toggle('render-gpu', renderer === 'gpu');
        stage.classList.toggle('render-cpu', renderer === 'cpu');
        flash(`渲染后端：${b.textContent.trim()}`);
      };
    });

    $$('#seg-ratio button').forEach((b) => {
      b.onclick = () => {
        ratio = b.dataset.a;
        $$('#seg-ratio button').forEach((x) => x.classList.toggle('on', x === b));
        stage.classList.toggle('ratio-cover', ratio === 'cover');
        stage.classList.toggle('ratio-fill', ratio === 'fill');
      };
    });

    $$('#seg-buffer button').forEach((b) => {
      b.onclick = () => {
        buffer = b.dataset.b;
        $$('#seg-buffer button').forEach((x) => x.classList.toggle('on', x === b));
        flash('缓冲策略将在切换清晰度后生效');
      };
    });

    /* transport */
    $('#btn-play').onclick = () => { if (video.paused) video.play(); else video.pause(); };
    $('#big-play').onclick = () => video.play();
    video.addEventListener('click', () => { if (video.paused) video.play(); else video.pause(); });
    video.addEventListener('play', () => { setPlayIcon(); startDiag(); });
    video.addEventListener('pause', () => { setPlayIcon(); saveProgress(true); });
    video.addEventListener('ended', () => { setPlayIcon(); saveProgress(true); });
    video.addEventListener('timeupdate', paintProgress);
    video.addEventListener('progress', paintProgress);
    video.addEventListener('waiting', () => { spinner.hidden = false; });
    video.addEventListener('playing', () => { spinner.hidden = true; });
    video.addEventListener('canplay', () => { spinner.hidden = true; });
    video.addEventListener('volumechange', () => {
      $('#btn-mute').innerHTML = icon(video.muted || video.volume === 0 ? 'mute' : 'volume');
    });
    $('#btn-mute').onclick = () => { video.muted = !video.muted; };
    $('#vol').oninput = (e) => { video.volume = Number(e.target.value); video.muted = false; };

    const timeline = $('#timeline');
    const seekTo = (clientX) => {
      const rect = timeline.querySelector('.track').getBoundingClientRect();
      const pct = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
      if (video.duration) video.currentTime = pct * video.duration;
    };
    timeline.addEventListener('click', (e) => seekTo(e.clientX));
    timeline.addEventListener('mousemove', (e) => {
      const rect = timeline.querySelector('.track').getBoundingClientRect();
      const pct = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
      const hover = $('#tl-hover');
      hover.style.left = `${pct * 100}%`;
      hover.textContent = video.duration ? fmtTime(pct * video.duration) : '0:00';
    });

    $('#btn-fs').onclick = () => {
      if (document.fullscreenElement) document.exitFullscreen();
      else if (stage.requestFullscreen) stage.requestFullscreen();
    };
    $('#btn-pip').onclick = async () => {
      try {
        if (document.pictureInPictureElement) await document.exitPictureInPicture();
        else if (video.requestPictureInPicture) await video.requestPictureInPicture();
      } catch (e) { toast('当前浏览器不支持画中画', 'err'); }
    };
    $('#pb-dl').onclick = () => navigate(`#/movie/${m.id}?panel=download`);

    document.addEventListener('click', () => closeAllPops());

    function onKey(e) {
      if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
      if (state.route.name !== 'watch') return;
      switch (e.key) {
        case ' ': case 'k': e.preventDefault(); if (video.paused) video.play(); else video.pause(); break;
        case 'ArrowLeft': video.currentTime -= 5; flash('« 5s'); break;
        case 'ArrowRight': video.currentTime += 5; flash('5s »'); break;
        case 'j': video.currentTime -= 10; flash('« 10s'); break;
        case 'l': video.currentTime += 10; flash('10s »'); break;
        case 'ArrowUp': e.preventDefault(); video.volume = Math.min(1, video.volume + 0.05); break;
        case 'ArrowDown': e.preventDefault(); video.volume = Math.max(0, video.volume - 0.05); break;
        case 'm': video.muted = !video.muted; flash(video.muted ? '静音' : '取消静音'); break;
        case 'f': $('#btn-fs').click(); break;
        default: break;
      }
    }
    document.addEventListener('keydown', onKey);

    function startDiag() {
      if (diagTimer) return;
      diagTimer = setInterval(() => {
        if (state.route.name !== 'watch') return;
        updateDiag();
        saveProgress();
      }, 2000);
    }

    state.player = {
      destroy() {
        clearInterval(diagTimer);
        clearTimeout(overlayTimer);
        document.removeEventListener('keydown', onKey);
        if (hls) { try { hls.destroy(); } catch (e) { /* noop */ } }
        try { video.pause(); video.removeAttribute('src'); video.load(); } catch (e) { /* noop */ }
      },
    };

    drawSourceInline();
    drawQualityMenus();
    loadSource(current, { time: resumeAt, autoplay: true });
    if (resumeAt > 3) flash(`已从 ${fmtTime(resumeAt)} 继续播放`);
  }

  /* --------------------------------------------------------- playlists */
  async function renderPlaylists(view) {
    if (!state.user) { view.innerHTML = guestWall('播放列表需要登录'); return; }
    const data = await api('/api/playlists');
    view.innerHTML = `
      <div class="page-head">
        <h1>播放列表</h1>
        <p class="grow">${data.items.length} 个片单</p>
        <button class="btn primary" id="new-list">${icon('plus')}新建片单</button>
      </div>
      <div id="pl-body"></div>`;
    const body = view.querySelector('#pl-body');
    if (!data.items.length) {
      body.innerHTML = `<div class="empty">${icon('list')}<h3>还没有片单</h3>
        <p>在影片详情页点击「加入片单」，或用右上角新建一个。</p></div>`;
    } else {
      body.innerHTML = data.items.map((p) => `
        <section class="panel" style="margin-bottom:18px">
          <div class="panel-head">
            <h2>${icon('list')}${esc(p.name)}</h2>
            <span class="hint">${p.count} 部 · 创建于 ${fmtDate(p.createdAt)}</span>
            <div class="flex right">
              <button class="btn small ghost" data-rename="${esc(p.id)}">${icon('edit')}重命名</button>
              <button class="btn small danger" data-del="${esc(p.id)}">${icon('trash')}删除</button>
            </div>
          </div>
          <div class="panel-body">
            ${p.movies.length ? `<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(150px,1fr))">
              ${p.movies.map((m) => cardHtml(m)).join('')}</div>`
              : '<p class="muted" style="font-size:12.5px">片单还是空的。</p>'}
          </div>
        </section>`).join('');
      bindCards(body);
      body.querySelectorAll('[data-del]').forEach((b) => {
        b.onclick = async () => {
          if (!(await confirmDialog('删除片单', '片单将被删除，影片本身不受影响。', true))) return;
          await api(`/api/playlists/${b.dataset.del}`, { method: 'DELETE' });
          toast('已删除', 'ok');
          CB.render();
        };
      });
      body.querySelectorAll('[data-rename]').forEach((b) => {
        b.onclick = () => {
          const current = (data.items.find((x) => x.id === b.dataset.rename) || {}).name || '';
          openModal({
            title: '重命名片单',
            body: `<input id="pl-name" type="text" style="width:100%" value="${esc(current)}"/>`,
            foot: `<button class="btn ghost" data-x="c">取消</button><button class="btn primary" data-x="s">保存</button>`,
            onMount(wrap, close) {
              wrap.querySelector('[data-x="c"]').onclick = close;
              wrap.querySelector('[data-x="s"]').onclick = async () => {
                const name = wrap.querySelector('#pl-name').value.trim();
                if (!name) return;
                await api(`/api/playlists/${b.dataset.rename}`, { method: 'PATCH', body: { name } });
                close(); toast('已更新', 'ok'); CB.render();
              };
            },
          });
        };
      });
    }
    view.querySelector('#new-list').onclick = () => {
      openModal({
        title: '新建片单',
        body: `<input id="pl-new" type="text" placeholder="例如：周末科幻马拉松" style="width:100%"/>`,
        foot: `<button class="btn ghost" data-x="c">取消</button><button class="btn primary" data-x="s">创建</button>`,
        onMount(wrap, close) {
          wrap.querySelector('[data-x="c"]').onclick = close;
          wrap.querySelector('[data-x="s"]').onclick = async () => {
            const name = wrap.querySelector('#pl-new').value.trim() || '我的片单';
            await api('/api/playlists', { method: 'POST', body: { name } });
            close(); toast('片单已创建', 'ok'); CB.render();
          };
        },
      });
    };
  }

  /* ----------------------------------------------------------- history */
  async function renderHistory(view) {
    if (!state.user) { view.innerHTML = guestWall('播放记录需要登录'); return; }
    const data = await api('/api/history');
    view.innerHTML = `
      <div class="page-head">
        <h1>最近播放</h1>
        <p class="grow">${data.items.length} 条记录</p>
        ${data.items.length ? `<button class="btn small danger" id="clear-all">${icon('trash')}清空记录</button>` : ''}
      </div>
      <div class="list" id="hist-list"></div>`;
    const list = view.querySelector('#hist-list');
    if (!data.items.length) {
      list.innerHTML = `<div class="empty">${icon('clock')}<h3>还没有播放记录</h3>
        <p>开始观看后，这里会记录进度，方便下次接着看。</p></div>`;
      return;
    }
    list.innerHTML = data.items.map((m) => `
      <div class="row-item" data-mid="${esc(m.id)}">
        <img src="${esc(m.poster)}" alt="" loading="lazy"/>
        <div class="r-main">
          <div class="r-t">${esc(m.title)}</div>
          <div class="r-m">
            <span>${esc(m.year || '')}</span>
            <span class="chip accent">${esc(m.quality || '')}</span>
            <span>${fmtTime(m.position)} / ${fmtTime(m.duration)}</span>
            <span>${ago(m.at)}</span>
          </div>
          <div class="card-progress" style="position:relative;margin-top:8px;height:3px;border-radius:2px">
            <i style="width:${Math.min(100, m.progress || 0)}%"></i>
          </div>
        </div>
        <div class="r-acts">
          <button class="btn small primary" data-resume="${esc(m.id)}" data-file="${esc(m.fileId || '')}">${icon('play')}继续</button>
          <button class="btn small ghost" data-rm="${esc(m.id)}">${icon('trash')}</button>
        </div>
      </div>`).join('');
    list.querySelectorAll('[data-resume]').forEach((b) => {
      b.onclick = (e) => { e.stopPropagation(); navigate(`#/watch/${b.dataset.resume}${b.dataset.file ? '/' + b.dataset.file : ''}`); };
    });
    list.querySelectorAll('[data-rm]').forEach((b) => {
      b.onclick = async (e) => {
        e.stopPropagation();
        await api(`/api/history/${b.dataset.rm}`, { method: 'DELETE' });
        toast('已移除该记录');
        CB.render();
      };
    });
    const clear = view.querySelector('#clear-all');
    if (clear) clear.onclick = async () => {
      if (!(await confirmDialog('清空播放记录', '所有进度记录都会被删除。', true))) return;
      await api('/api/history', { method: 'DELETE' });
      toast('已清空', 'ok'); CB.render();
    };
    list.querySelectorAll('.row-item').forEach((row) => {
      row.onclick = (e) => { if (!e.target.closest('button')) navigate(`#/movie/${row.dataset.mid}`); };
    });
  }

  /* --------------------------------------------------------- downloads */
  async function renderDownloads(view) {
    if (!state.user) { view.innerHTML = guestWall('下载记录需要登录'); return; }
    const data = await api('/api/downloads');
    view.innerHTML = `
      <div class="page-head">
        <h1>下载</h1>
        <p class="grow">${data.items.length} 条下载记录</p>
        <a class="btn small" href="#/search">${icon('search')}去找片</a>
      </div>
      <section class="panel" style="margin-bottom:20px">
        <div class="panel-head"><h2>${icon('download')}下载说明</h2></div>
        <div class="panel-body">
          <p class="note" style="font-size:12.5px">
            · 下载请求由服务端流式转发，文件<b>直接保存到当前访问设备</b>，不落在服务器磁盘上。<br/>
            · 在影片详情页可选择清晰度，并勾选海报、NFO、JSON、字幕、校验清单等元数据；勾选后自动打包为 ZIP。<br/>
            · 记录保留最近 40 次，可随时重新下载。
          </p>
        </div>
      </section>
      <div class="list" id="dl-list"></div>`;
    const list = view.querySelector('#dl-list');
    if (!data.items.length) {
      list.innerHTML = `<div class="empty">${icon('download')}<h3>还没有下载记录</h3>
        <p>打开任意影片详情页，选择清晰度后即可下载。</p></div>`;
      return;
    }
    list.innerHTML = data.items.map((m) => `
      <div class="row-item" data-mid="${esc(m.id)}">
        <img src="${esc(m.poster)}" alt="" loading="lazy"/>
        <div class="r-main">
          <div class="r-t">${esc(m.title)}</div>
          <div class="r-m">
            <span class="chip accent">${esc(m.quality || '')}</span>
            <span>${fmtBytes(m.sizeBytes)}</span>
            <span>${(m.extras || []).length ? `含 ${m.extras.length} 项元数据` : '仅正片'}</span>
            <span>${ago(m.at)}</span>
          </div>
        </div>
        <div class="r-acts">
          <button class="btn small" data-again="${esc(m.id)}" data-file="${esc(m.fileId || '')}"
            data-extras="${esc((m.extras || []).join(','))}">${icon('download')}重新下载</button>
          <button class="btn small ghost" data-open="${esc(m.id)}">${icon('film')}详情</button>
        </div>
      </div>`).join('');
    list.querySelectorAll('[data-again]').forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();
        const ex = b.dataset.extras;
        triggerDownload(`/api/download/${b.dataset.again}/${b.dataset.file}${ex ? '?extras=' + ex : ''}`);
        toast('已开始下载', 'ok');
      };
    });
    list.querySelectorAll('[data-open]').forEach((b) => {
      b.onclick = (e) => { e.stopPropagation(); navigate(`#/movie/${b.dataset.open}`); };
    });
    list.querySelectorAll('.row-item').forEach((row) => {
      row.onclick = (e) => { if (!e.target.closest('button')) navigate(`#/movie/${row.dataset.mid}`); };
    });
  }

  register('watch', renderWatch);
  register('playlists', renderPlaylists);
  register('history', renderHistory);
  register('downloads', renderDownloads);
})();
