/* =============================================================
   CINEBOX · admin console (movies / users / site / sources)
   ============================================================= */
(() => {
  'use strict';
  const CB = window.CB;
  const { state, icon, esc, api, toast, openModal, confirmDialog, navigate, fmtDate, fmtBytes, ago, register } = CB;

  const TABS = [
    { id: 'dashboard', label: '概览', icon: 'spark' },
    { id: 'movies', label: '影片库', icon: 'film' },
    { id: 'users', label: '用户', icon: 'user' },
    { id: 'site', label: '站点设置', icon: 'gear' },
    { id: 'sources', label: '片源与元数据', icon: 'download' },
    { id: 'api', label: '片源接口', icon: 'gear' },
  ];

  async function renderAdmin(view, route) {
    if (!state.user) { view.innerHTML = CB.guestWall('管理后台需要管理员登录'); return; }
    if (state.user.role !== 'admin') {
      toast('需要管理员权限');
      navigate('#/');
      return;
    }
    const tab = TABS.some((t) => t.id === route.query.tab) ? route.query.tab : 'dashboard';
    view.innerHTML = `
      <div class="page-head">
        <h1>管理后台</h1>
        <p class="grow">${esc(state.settings.siteName || 'CINEBOX')} · ${esc(state.user.displayName || state.user.username)}</p>
        <span class="chip accent">管理员</span>
      </div>
      <div class="admin-tabs">
        ${TABS.map((t) => `<button data-tab="${t.id}" class="${t.id === tab ? 'on' : ''}">
          ${icon(t.icon)}${t.label}</button>`).join('')}
      </div>
      <div id="admin-body"></div>`;
    view.querySelectorAll('.admin-tabs button').forEach((b) => {
      b.onclick = () => navigate(`#/admin?tab=${b.dataset.tab}`);
    });
    const body = view.querySelector('#admin-body');
    if (tab === 'dashboard') await drawDashboard(body);
    if (tab === 'movies') await drawMovies(body);
    if (tab === 'users') await drawUsers(body);
    if (tab === 'site') await drawSite(body);
    if (tab === 'sources') await drawSources(body);
    if (tab === 'api') await drawApiSources(body);
  }

  /* ---------------------------------------------------------- dashboard */
  async function drawDashboard(body) {
    body.innerHTML = `<div class="sk sk-line" style="width:220px"></div>`;
    const s = await api('/api/admin/stats');
    body.innerHTML = `
      <div class="stat-grid">
        <div class="stat"><span>影片总数</span><b>${s.counts.movies}</b><small>${s.counts.published} 部已发布</small></div>
        <div class="stat"><span>片源文件</span><b>${s.counts.files}</b><small>本地 ${fmtBytes(s.storage.localBytes)} · 远端 ${fmtBytes(s.storage.remoteBytes)}</small></div>
        <div class="stat"><span>用户</span><b>${s.counts.users}</b><small>${s.counts.playlists} 个片单</small></div>
        <div class="stat"><span>播放次数</span><b>${s.counts.plays}</b><small>搜索 ${s.counts.searches} 次</small></div>
        <div class="stat"><span>下载次数</span><b>${s.counts.downloads}</b><small>播放记录 ${s.counts.history} 条</small></div>
        <div class="stat"><span>转码能力</span><b>${s.ffmpeg ? '就绪' : '缺失'}</b><small>ffmpeg ${s.ffmpeg ? '可用' : '未安装'}</small></div>
      </div>
      <div class="split">
        <section class="panel">
          <div class="panel-head"><h2>${icon('spark')}热门影片</h2><span class="hint">按播放量</span></div>
          <div class="panel-body" style="gap:8px">
            ${s.top.length ? s.top.map((m) => `
              <div class="row-item" style="padding:8px 10px">
                <div class="r-main"><div class="r-t">${esc(m.title)}</div>
                  <div class="r-m">${m.views} 次播放</div></div>
                <button class="btn tiny ghost" data-open="${esc(m.id)}">${icon('film')}查看</button>
              </div>`).join('') : '<p class="muted" style="font-size:12px">暂无数据</p>'}
          </div>
        </section>
        <section class="panel">
          <div class="panel-head"><h2>${icon('clock')}操作日志</h2></div>
          <div class="panel-body" style="gap:6px">
            ${s.audit.length ? s.audit.map((a) => `
              <div class="meter-row" style="font-size:11.5px">
                <span style="color:var(--text-dim)">${esc(a.action)}</span>
                <span>${esc(a.user || '')}</span>
                <b>${ago(a.at)}</b>
              </div>`).join('') : '<p class="muted" style="font-size:12px">暂无日志</p>'}
          </div>
        </section>
      </div>`;
    body.querySelectorAll('[data-open]').forEach((b) => {
      b.onclick = () => navigate(`#/movie/${b.dataset.open}`);
    });
  }

  /* -------------------------------------------------------------- movies */
  async function drawMovies(body) {
    body.innerHTML = `
      <div class="flex" style="margin-bottom:14px">
        <button class="btn primary" id="m-new">${icon('plus')}新建影片</button>
        <button class="btn ghost" id="m-scan">${icon('refresh')}重新探测本地文件</button>
        <span class="grow"></span>
        <input id="m-filter" type="text" placeholder="筛选片名…" style="width:200px" />
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>影片</th><th>年份</th><th>清晰度</th><th>来源</th><th>状态</th><th>播放</th><th style="text-align:right">操作</th></tr></thead>
        <tbody id="m-tbody"></tbody>
      </table></div>`;
    const rows = (await api('/api/admin/movies')).items;
    const tbody = body.querySelector('#m-tbody');
    const paint = (list) => {
      tbody.innerHTML = list.length ? list.map((m) => `
        <tr data-id="${esc(m.id)}">
          <td><div class="t-title">
            ${m.poster ? `<img src="${esc(m.poster)}" alt=""/>` : `<div style="width:34px;height:50px;border-radius:5px;background:#16202f"></div>`}
            <div><div style="font-weight:600">${esc(m.title)}</div>
            <div class="muted" style="font-size:11px">${esc((m.genres || []).join(' / ') || '未分类')}</div></div>
          </div></td>
          <td>${esc(m.year || '—')}</td>
          <td>${(m.sizes || []).map((q) => `<span class="chip dim" style="margin:1px">${esc(q)}</span>`).join('') || '—'}</td>
          <td><span class="chip">${esc(m.source)}</span></td>
          <td><span class="dot-status ${m.status === 'draft' ? 'draft' : ''}"><i></i>${m.status === 'draft' ? '草稿' : '已发布'}</span></td>
          <td>${m.views}</td>
          <td style="text-align:right;white-space:nowrap">
            <button class="btn tiny" data-edit="${esc(m.id)}">${icon('edit')}编辑</button>
            <button class="btn tiny ghost" data-enrich="${esc(m.id)}">${icon('spark')}补全</button>
            <button class="btn tiny danger" data-del="${esc(m.id)}">${icon('trash')}</button>
          </td>
        </tr>`).join('') : '<tr><td colspan="7" class="center muted" style="padding:40px">暂无影片</td></tr>';
      tbody.querySelectorAll('[data-edit]').forEach((b) => {
        b.onclick = async () => {
          const data = await api(`/api/admin/movies/${b.dataset.edit}`);
          openMovieEditor(data.movie);
        };
      });
      tbody.querySelectorAll('[data-del]').forEach((b) => {
        b.onclick = async () => {
          if (!(await confirmDialog('删除影片', '影片与其配置会被删除（服务器上的视频文件保留）。', true))) return;
          await api(`/api/admin/movies/${b.dataset.del}`, { method: 'DELETE' });
          toast('已删除', 'ok'); drawMovies(body);
        };
      });
      tbody.querySelectorAll('[data-enrich]').forEach((b) => {
        b.onclick = () => openEnrich(b.dataset.enrich, () => drawMovies(body));
      });
    };
    paint(rows);
    body.querySelector('#m-filter').oninput = (e) => {
      const q = e.target.value.trim().toLowerCase();
      paint(rows.filter((m) => (m.title || '').toLowerCase().includes(q)));
    };
    body.querySelector('#m-new').onclick = () => openMovieEditor(null);
    body.querySelector('#m-scan').onclick = async () => {
      const r = await api('/api/admin/rescan', { method: 'POST' });
      toast(`已更新 ${r.updated} 个本地片源`, 'ok', 4000);
      drawMovies(body);
    };
  }

  function openMovieEditor(movie) {
    const isNew = !movie;
    const m = movie || { title: '', files: [], subtitles: [], genres: [], cast: [], status: 'published' };
    const fileRow = (f = {}) => `
      <div class="file-row" data-file-id="${esc(f.id || '')}">
        <label class="fl">清晰度<input class="f-quality" value="${esc(f.quality || '1080p')}" placeholder="1080p" /></label>
        <label class="fl">标注<input class="f-label" value="${esc(f.label || '')}" placeholder="1080P · 蓝光" /></label>
        <label class="fl">类型<select class="f-type">
          <option value="remote" ${f.watch && f.watch.type === 'remote' ? 'selected' : ''}>远端 URL</option>
          <option value="local" ${f.watch && f.watch.type === 'local' ? 'selected' : ''}>本地文件</option>
          <option value="hls" ${f.watch && f.watch.type === 'hls' ? 'selected' : ''}>HLS 播放列表</option>
        </select></label>
        <label class="fl f-url">播放地址<input class="f-watch" value="${esc((f.watch && f.watch.value) || '')}" placeholder="https://… 或 local/{id}/{fid}.mp4" /></label>
        <button class="btn tiny danger f-del" type="button">${icon('trash')}</button>
        <label class="fl" style="grid-column:1/3">下载地址（留空＝同播放地址）<input class="f-dl" value="${esc((f.download && f.download.value) || '')}" /></label>
        <label class="fl" style="grid-column:3/5">片源标注<input class="f-src" value="${esc(f.sourceLabel || '')}" placeholder="本地片源 / Internet Archive" /></label>
        <label class="switch" style="grid-column:5/6;margin-top:12px">
          <input type="checkbox" class="f-dlen" ${f.download && f.download.enabled === false ? '' : 'checked'} /><i></i>允许下载
        </label>
      </div>`;

    const body = `
      <div class="form-grid">
        <label class="fl">片名 *<input id="f-title" value="${esc(m.title || '')}" /></label>
        <label class="fl">原始片名<input id="f-orig" value="${esc(m.originalTitle || '')}" /></label>
        <label class="fl">年份<input id="f-year" type="number" value="${esc(m.year || '')}" /></label>
        <label class="fl">评分<input id="f-rating" type="number" step="0.1" value="${esc(m.rating || '')}" /></label>
        <label class="fl">片长（分钟）<input id="f-runtime" type="number" value="${esc(m.runtime || '')}" /></label>
        <label class="fl">类型（逗号分隔）<input id="f-genres" value="${esc((m.genres || []).join(','))}" /></label>
        <label class="fl">导演<input id="f-director" value="${esc(m.director || '')}" /></label>
        <label class="fl">主演（逗号分隔）<input id="f-cast" value="${esc((m.cast || []).join(','))}" /></label>
        <label class="fl">海报 URL<input id="f-poster" value="${esc(m.poster || '')}" /></label>
        <label class="fl">背景图 URL<input id="f-backdrop" value="${esc(m.backdrop || '')}" /></label>
        <label class="fl">状态<select id="f-status">
          <option value="published" ${m.status !== 'draft' ? 'selected' : ''}>已发布</option>
          <option value="draft" ${m.status === 'draft' ? 'selected' : ''}>草稿</option>
        </select></label>
        <label class="switch" style="margin-top:20px"><input id="f-featured" type="checkbox" ${m.featured ? 'checked' : ''}/><i></i>首页精选</label>
        <label class="fl full">简介<textarea id="f-synopsis">${esc(m.synopsis || '')}</textarea></label>
      </div>
      <div class="hr"></div>
      <div class="flex"><strong style="font-size:13px">清晰度 / 片源</strong>
        <button class="btn tiny" id="f-add" type="button">${icon('plus')}添加一行</button>
        <span class="muted" style="font-size:11px">保存后可为本地文件生成 HLS 阶梯</span></div>
      <div id="files-box" style="display:flex;flex-direction:column;gap:8px">
        ${(m.files || []).map(fileRow).join('')}
      </div>
      ${isNew ? '' : `
      <div class="hr"></div>
      <div class="flex">
        <strong style="font-size:13px">上传本地视频</strong>
        <input type="file" id="up-file" accept="video/*" />
        <select id="up-quality">
          <option>1080p</option><option>720p</option><option>480p</option><option>2160p</option><option>360p</option>
        </select>
        <button class="btn small" id="up-go" type="button">${icon('upload')}上传</button>
        <div class="grow"></div>
        <span class="muted" id="up-tip" style="font-size:11px"></span>
      </div>`}`;

    openModal({
      title: isNew ? '新建影片' : `编辑：${m.title}`,
      sub: isNew ? '先创建影片，再添加上传文件或远端地址' : `${(m.files || []).length} 个片源`,
      size: 'xl', body,
      foot: `<button class="btn ghost" data-x="c">取消</button>
             <button class="btn primary" data-x="s">${isNew ? '创建影片' : '保存修改'}</button>`,
      onMount(wrap, close) {
        const filesBox = wrap.querySelector('#files-box');
        const rebind = () => {
          filesBox.querySelectorAll('.f-del').forEach((b) => {
            b.onclick = () => { b.closest('.file-row').remove(); };
          });
        };
        rebind();
        wrap.querySelector('#f-add').onclick = () => {
          const div = document.createElement('div');
          div.innerHTML = fileRow();
          filesBox.appendChild(div.firstElementChild);
          rebind();
        };
        wrap.querySelector('[data-x="c"]').onclick = close;

        const uploadBtn = wrap.querySelector('#up-go');
        if (uploadBtn) {
          uploadBtn.onclick = () => {
            const input = wrap.querySelector('#up-file');
            const file = input.files[0];
            if (!file) return toast('请选择视频文件', 'err');
            const quality = wrap.querySelector('#up-quality').value;
            const tip = wrap.querySelector('#up-tip');
            const xhr = new XMLHttpRequest();
            const qs = new URLSearchParams({
              movieId: m.id, quality, label: `${quality.toUpperCase()} · 本地上传`,
              filename: file.name, sourceLabel: '本地片源',
            });
            xhr.open('PUT', `/api/admin/upload?${qs.toString()}`);
            xhr.setRequestHeader('X-CSRF', state.csrf);
            xhr.upload.onprogress = (e) => {
              if (e.lengthComputable) tip.textContent = `上传中 ${(e.loaded / e.total * 100).toFixed(0)}%`;
            };
            xhr.onload = async () => {
              if (xhr.status >= 200 && xhr.status < 300) {
                tip.textContent = '上传完成';
                toast('上传完成，已写入片库', 'ok');
                const data = await api(`/api/admin/movies/${m.id}`);
                close();
                openMovieEditor(data.movie);
              } else {
                let msg = '上传失败';
                try { msg = JSON.parse(xhr.responseText).error || msg; } catch (e) { /* noop */ }
                tip.textContent = msg;
                toast(msg, 'err');
              }
            };
            xhr.onerror = () => { tip.textContent = '网络错误'; };
            xhr.send(file);
          };
        }

        wrap.querySelector('[data-x="s"]').onclick = async () => {
          const val = (sel) => { const el = wrap.querySelector(sel); return el ? el.value.trim() : ''; };
          const payload = {
            title: val('#f-title'),
            originalTitle: val('#f-orig'),
            year: val('#f-year'),
            rating: val('#f-rating'),
            runtime: val('#f-runtime'),
            genres: val('#f-genres'),
            director: val('#f-director'),
            cast: val('#f-cast'),
            poster: val('#f-poster'),
            backdrop: val('#f-backdrop'),
            status: val('#f-status'),
            featured: wrap.querySelector('#f-featured').checked,
            synopsis: wrap.querySelector('#f-synopsis'),
            files: Array.from(filesBox.querySelectorAll('.file-row')).map((row) => {
              const type = row.querySelector('.f-type').value;
              const watchValue = row.querySelector('.f-watch').value.trim();
              if (!watchValue) return null;
              const dlValue = row.querySelector('.f-dl').value.trim();
              return {
                id: row.dataset.fileId || undefined,
                quality: row.querySelector('.f-quality').value.trim() || '1080p',
                label: row.querySelector('.f-label').value.trim(),
                watchType: type, watchValue,
                downloadEnabled: row.querySelector('.f-dlen').checked,
                downloadType: type, downloadValue: dlValue || watchValue,
                sourceLabel: row.querySelector('.f-src').value.trim() || undefined,
              };
            }).filter(Boolean),
          };
          if (!payload.title) return toast('请填写片名', 'err');
          try {
            if (isNew) {
              const r = await api('/api/admin/movies', { method: 'POST', body: payload });
              toast('影片已创建', 'ok');
              close();
              const data = await api(`/api/admin/movies/${r.id}`);
              openMovieEditor(data.movie);
            } else {
              await api(`/api/admin/movies/${m.id}`, { method: 'PATCH', body: payload });
              toast('已保存', 'ok');
              close();
              CB.render();
            }
          } catch (e) { /* toast handled */ }
        };
      },
    });
  }

  function openEnrich(mid, after) {
    const body = `
      <p class="note">从公共元数据源补全海报、简介、评分、演职员等信息。已有字段会被覆盖。</p>
      <label class="fl">数据源<select id="en-provider">
        <option value="itunes">iTunes（无需 Key）</option>
        <option value="archive">Internet Archive（无需 Key）</option>
        <option value="tmdb">TMDB（需在站点设置填 Key）</option>
        <option value="omdb">OMDb（需 Key）</option>
      </select></label>`;
    openModal({
      title: '元数据补全', body,
      foot: `<button class="btn ghost" data-x="c">取消</button><button class="btn primary" data-x="s">${icon('spark')}开始补全</button>`,
      onMount(wrap, close) {
        wrap.querySelector('[data-x="c"]').onclick = close;
        wrap.querySelector('[data-x="s"]').onclick = async () => {
          const provider = wrap.querySelector('#en-provider').value;
          try {
            const r = await api(`/api/admin/movies/${mid}/enrich`, { method: 'POST', body: { provider } });
            toast('元数据已更新', 'ok');
            close();
            if (after) after();
          } catch (e) { /* handled */ }
        };
      },
    });
  }

  /* --------------------------------------------------------------- users */
  async function drawUsers(body) {
    const data = await api('/api/admin/users');
    const settings = (await api('/api/admin/settings')).settings;
    body.innerHTML = `
      <div class="flex" style="margin-bottom:14px;flex-wrap:wrap;gap:12px">
        <button class="btn primary" id="u-new">${icon('plus')}新建用户</button>
        <label class="switch"><input id="u-signup" type="checkbox" ${settings.allowSignup ? 'checked' : ''}/><i></i>允许注册</label>
        <span class="muted" style="font-size:11.5px">关闭后登录框不再显示「注册」，注册接口也会拒绝</span>
        <span class="grow"></span>
        <span class="muted" style="font-size:12px">共 ${data.items.length} 个账号</span>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>账号</th><th>角色</th><th>状态</th><th>注册时间</th><th>最近登录</th><th style="text-align:right">操作</th></tr></thead>
        <tbody>${data.items.map((u) => `
          <tr>
            <td><div style="font-weight:600">${esc(u.displayName || u.username)}</div>
              <div class="muted" style="font-size:11px">@${esc(u.username)}</div></td>
            <td><span class="chip ${u.role === 'admin' ? 'accent' : ''}">${u.role === 'admin' ? '管理员' : '用户'}</span></td>
            <td><span class="dot-status ${u.status !== 'active' ? 'off' : ''}"><i></i>${u.status === 'active' ? '正常' : '已禁用'}</span></td>
            <td class="muted">${fmtDate(u.createdAt)}</td>
            <td class="muted">${u.lastLoginAt ? ago(u.lastLoginAt) : '—'}</td>
            <td style="text-align:right;white-space:nowrap">
              <button class="btn tiny" data-uedit="${esc(u.id)}">${icon('edit')}编辑</button>
              <button class="btn tiny danger" data-udel="${esc(u.id)}">${icon('trash')}</button>
            </td>
          </tr>`).join('')}</tbody>
      </table></div>`;

    body.querySelector('#u-signup').onchange = async (e) => {
      try {
        await api('/api/admin/settings', { method: 'PUT', body: { allowSignup: e.target.checked } });
        state.settings = { ...state.settings, allowSignup: e.target.checked };
        CB.applyIdentity();
        toast(e.target.checked ? '已开放注册' : '已关闭注册', 'ok');
      } catch (err) {
        e.target.checked = !e.target.checked;
      }
    };

    body.querySelector('#u-new').onclick = () => {
      openModal({
        title: '新建用户',
        body: `<div class="form-grid">
          <label class="fl">账号<input id="nu-name" /></label>
          <label class="fl">初始密码<input id="nu-pass" type="password" /></label>
          <label class="fl">昵称<input id="nu-display" /></label>
          <label class="fl">角色<select id="nu-role"><option value="user">普通用户</option><option value="admin">管理员</option></select></label>
        </div>`,
        foot: `<button class="btn ghost" data-x="c">取消</button><button class="btn primary" data-x="s">创建</button>`,
        onMount(wrap, close) {
          wrap.querySelector('[data-x="c"]').onclick = close;
          wrap.querySelector('[data-x="s"]').onclick = async () => {
            try {
              await api('/api/admin/users', {
                method: 'POST',
                body: {
                  username: wrap.querySelector('#nu-name').value.trim(),
                  password: wrap.querySelector('#nu-pass').value,
                  displayName: wrap.querySelector('#nu-display').value.trim(),
                  role: wrap.querySelector('#nu-role').value,
                },
              });
              close(); toast('用户已创建', 'ok'); drawUsers(body);
            } catch (e) { /* handled */ }
          };
        },
      });
    };

    body.querySelectorAll('[data-uedit]').forEach((b) => {
      b.onclick = () => {
        const u = data.items.find((x) => x.id === b.dataset.uedit);
        openModal({
          title: `编辑用户：${u.username}`,
          body: `<div class="form-grid">
            <label class="fl">昵称<input id="eu-display" value="${esc(u.displayName || '')}" /></label>
            <label class="fl">角色<select id="eu-role">
              <option value="user" ${u.role === 'user' ? 'selected' : ''}>普通用户</option>
              <option value="admin" ${u.role === 'admin' ? 'selected' : ''}>管理员</option></select></label>
            <label class="fl">状态<select id="eu-status">
              <option value="active" ${u.status === 'active' ? 'selected' : ''}>正常</option>
              <option value="disabled" ${u.status !== 'active' ? 'selected' : ''}>禁用</option></select></label>
            <label class="fl">重置密码（留空不改）<input id="eu-pass" type="password" /></label>
          </div>`,
          foot: `<button class="btn ghost" data-x="c">取消</button><button class="btn primary" data-x="s">保存</button>`,
          onMount(wrap, close) {
            wrap.querySelector('[data-x="c"]').onclick = close;
            wrap.querySelector('[data-x="s"]').onclick = async () => {
              try {
                await api(`/api/admin/users/${u.id}`, {
                  method: 'PATCH',
                  body: {
                    displayName: wrap.querySelector('#eu-display').value.trim(),
                    role: wrap.querySelector('#eu-role').value,
                    status: wrap.querySelector('#eu-status').value,
                    password: wrap.querySelector('#eu-pass').value || undefined,
                  },
                });
                close(); toast('已保存', 'ok'); drawUsers(body);
              } catch (e) { /* handled */ }
            };
          },
        });
      };
    });

    body.querySelectorAll('[data-udel]').forEach((b) => {
      b.onclick = async () => {
        if (!(await confirmDialog('删除用户', '该账号的片单与播放记录会一并删除。', true))) return;
        await api(`/api/admin/users/${b.dataset.udel}`, { method: 'DELETE' });
        toast('已删除', 'ok'); drawUsers(body);
      };
    });
  }

  /* ---------------------------------------------------------------- site */
  async function drawSite(body) {
    const data = await api('/api/admin/settings');
    const probe = await api('/api/admin/transcode/probe').catch(() => null);
    const gpus = (probe && probe.gpus) || [];
    const s = data.settings;
    body.innerHTML = `
      <div class="split">
        <section class="panel">
          <div class="panel-head"><h2>${icon('gear')}站点信息</h2></div>
          <div class="panel-body">
            <div class="form-grid">
              <label class="fl">站名<input id="s-name" value="${esc(s.siteName || '')}" /></label>
              <label class="fl">副标题<input id="s-tag" value="${esc(s.tagline || '')}" /></label>
              <label class="fl full">公告<textarea id="s-announce">${esc(s.announcement || '')}</textarea></label>
              <label class="fl">主题色<input id="s-accent" type="color" value="${esc(s.themeAccent || '#48d6c8')}" /></label>
              <label class="fl">默认解析模式<select id="s-decoding">
                ${['auto', 'hw', 'sw'].map((d) => `<option value="${d}" ${s.defaultDecoding === d ? 'selected' : ''}>${{ auto: '自动', hw: '硬解优先', sw: '软解优先' }[d]}</option>`).join('')}
              </select></label>
            </div>
            <div class="hr"></div>
            <label class="switch"><input id="s-signup" type="checkbox" ${s.allowSignup ? 'checked' : ''}/><i></i>开放注册</label>
            <label class="switch"><input id="s-guest" type="checkbox" ${s.allowGuestSearch ? 'checked' : ''}/><i></i>允许访客搜索</label>
            <label class="switch"><input id="s-maint" type="checkbox" ${s.maintenance ? 'checked' : ''}/><i></i>维护模式（仅管理员可登录）</label>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head"><h2>${icon('spark')}外网与元数据</h2><span class="hint">国内网络建议开启代理</span></div>
          <div class="panel-body">
            <label class="switch"><input id="s-proxy-on" type="checkbox" ${s.proxyEnabled ? 'checked' : ''}/><i></i>启用服务端代理</label>
            <div class="form-grid">
              <label class="fl full">代理地址<input id="s-proxy" value="${esc(s.proxyUrl || '')}" placeholder="http://127.0.0.1:7897" /></label>
              <label class="fl full">TMDB API Key（v3）<input id="s-tmdb" value="${esc(s.tmdbKey || '')}" placeholder="留空则只用免费源" /></label>
              <label class="fl full">OMDb API Key<input id="s-omdb" value="${esc(s.omdbKey || '')}" /></label>
              <label class="fl">上传上限（MB）<input id="s-maxup" type="number" value="${esc(s.maxUploadMb || 4096)}" /></label>
            </div>
            <p class="note">代理仅用于服务端访问片源/元数据与图片；下载与播放仍通过本站转发。</p>
          </div>
        </section>
      </div>

      <section class="panel mt16">
        <div class="panel-head">
          <h2>${icon('cpu')}转码与编码</h2>
          <span class="hint">ffmpeg ${data.ffmpeg ? '可用' : '未检测到（HLS/软解档不可用）'}</span>
        </div>
        <div class="panel-body">
          <label class="switch"><input id="s-transcode" type="checkbox" ${s.transcodeEnabled !== false ? 'checked' : ''}/><i></i>启用服务端转码（HLS 阶梯 / 软解基准档）</label>
          <div class="form-grid">
            <label class="fl">HLS 档位（逗号分隔，像素高）
              <input id="s-hls-heights" value="${esc(s.hlsHeights || '1080,720,480')}" placeholder="1080,720,480" /></label>
            <label class="fl">HLS 编码预设
              <select id="s-hls-preset">
                ${['ultrafast', 'veryfast', 'fast', 'medium', 'slow'].map((p) => `<option value="${p}" ${(s.hlsPreset || 'veryfast') === p ? 'selected' : ''}>${p}</option>`).join('')}
              </select></label>
            <label class="fl">HLS CRF（越小越清晰，18–30）
              <input id="s-hls-crf" type="number" min="16" max="34" value="${esc(s.hlsCrf || 23)}" /></label>
            <label class="fl">软解基准档 CRF
              <input id="s-soft-crf" type="number" min="16" max="34" value="${esc(s.softCrf || 26)}" /></label>
            <label class="fl">软解档时长上限（分钟）
              <input id="s-soft-max" type="number" min="1" max="600" value="${esc(s.softMaxMinutes || 30)}" /></label>
          </div>
          <p class="note">HLS 阶梯用于「本地片源」多码率播放；软解基准档在用户选择「软解优先」时按需生成。修改后对之后生成的任务生效，已生成的文件不会被重转。</p>
          <div class="hr"></div>
          <label class="switch"><input id="s-gpu" type="checkbox" ${s.gpuTranscodeEnabled ? 'checked' : ''}/><i></i>启用 GPU 加速转码</label>
          <div class="form-grid" style="margin-top:10px">
            <label class="fl">首选 GPU
              <select id="s-gpu-device">
                <option value="auto" ${(s.gpuDevice || 'auto') === 'auto' ? 'selected' : ''}>自动（优先第一块可用 GPU）</option>
                ${gpus.map((g) => `<option value="${esc(g.id)}" ${s.gpuDevice === g.id ? 'selected' : ''}>${esc(g.name)} · ${esc(g.encoder)}</option>`).join('')}
              </select>
            </label>
            <label class="switch" style="margin-top:22px"><input id="s-gpu-fallback" type="checkbox" ${s.gpuAutoFallback !== false ? 'checked' : ''}/><i></i>GPU 不支持该格式时自动切换 CPU</label>
          </div>
          <p class="note">检测到的硬件编码器：${gpus.length ? gpus.map((g) => esc(g.name)).join('、') : '无（将始终使用 CPU libx264）'}。GPU 编码失败且开启自动回退时，会改用 CPU 重新生成该档。</p>
        </div>
      </section>

      <div class="flex mt16">
        <button class="btn primary" id="s-save">${icon('check')}保存设置</button>
        <span class="muted" style="font-size:11.5px">ffmpeg：${data.ffmpeg ? '可用' : '未检测到'}</span>
      </div>`;

    body.querySelector('#s-save').onclick = async () => {
      const payload = {
        siteName: body.querySelector('#s-name').value.trim(),
        tagline: body.querySelector('#s-tag').value.trim(),
        announcement: body.querySelector('#s-announce').value,
        themeAccent: body.querySelector('#s-accent').value,
        defaultDecoding: body.querySelector('#s-decoding').value,
        allowSignup: body.querySelector('#s-signup').checked,
        allowGuestSearch: body.querySelector('#s-guest').checked,
        maintenance: body.querySelector('#s-maint').checked,
        proxyEnabled: body.querySelector('#s-proxy-on').checked,
        proxyUrl: body.querySelector('#s-proxy').value.trim(),
        tmdbKey: body.querySelector('#s-tmdb').value.trim(),
        omdbKey: body.querySelector('#s-omdb').value.trim(),
        maxUploadMb: Number(body.querySelector('#s-maxup').value) || 4096,
        transcodeEnabled: body.querySelector('#s-transcode').checked,
        hlsHeights: body.querySelector('#s-hls-heights').value.trim() || '1080,720,480',
        hlsPreset: body.querySelector('#s-hls-preset').value,
        hlsCrf: Number(body.querySelector('#s-hls-crf').value) || 23,
        softCrf: Number(body.querySelector('#s-soft-crf').value) || 26,
        softMaxMinutes: Number(body.querySelector('#s-soft-max').value) || 30,
        gpuTranscodeEnabled: body.querySelector('#s-gpu').checked,
        gpuDevice: body.querySelector('#s-gpu-device').value,
        gpuAutoFallback: body.querySelector('#s-gpu-fallback').checked,
      };
      await api('/api/admin/settings', { method: 'PUT', body: payload });
      state.settings = { ...state.settings, ...payload };
      CB.applyIdentity();
      toast('设置已保存', 'ok');
    };
  }

  /* ------------------------------------------------------------- sources */
  async function drawSources(body) {
    const data = await api('/api/admin/providers');
    body.innerHTML = `
      <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(240px,1fr));margin-bottom:24px">
        ${data.items.map((p) => `
          <div class="provider-card">
            <h4>${esc(p.name)} <span class="chip ${p.key ? 'gold' : 'accent'}">${p.key ? '需 Key' : '免 Key'}</span></h4>
            <div class="pc-note">${esc(p.kind)} · ${esc(p.note)}<br/><span class="mono" style="font-size:10.5px">${esc(p.site)}</span></div>
            <div class="pc-foot">
              <button class="btn tiny" data-test="${p.id}">${icon('refresh')}测试连接</button>
              <span class="muted" style="font-size:11px" data-result="${p.id}"></span>
            </div>
          </div>`).join('')}
      </div>

      <section class="panel" style="margin-bottom:22px">
        <div class="panel-head">
          <h2>${icon('search')}在线检索并导入</h2>
          <span class="hint">Internet Archive 可直接导入可播可下的多码率影片</span>
        </div>
        <div class="panel-body">
          <div class="flex">
            <select id="pr-provider">
              ${data.items.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}
            </select>
            <input id="pr-q" type="text" placeholder="输入片名，例如 chaplin / sita" style="flex:1;min-width:220px" />
            <button class="btn primary" id="pr-go">${icon('search')}检索</button>
          </div>
          <div class="cand-grid" id="pr-results"></div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><h2>${icon('spark')}批量补全元数据</h2></div>
        <div class="panel-body">
          <div class="flex">
            <select id="en-provider2">
              ${data.items.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}
            </select>
            <button class="btn" id="en-refresh">${icon('refresh')}刷新影片列表</button>
            <span class="grow"></span>
            <span class="muted" style="font-size:11.5px">逐部补全，或到「影片库」点单部补全</span>
          </div>
          <div id="en-list" class="list mt12"></div>
        </div>
      </section>`;

    body.querySelectorAll('[data-test]').forEach((b) => {
      b.onclick = async () => {
        const out = body.querySelector(`[data-result="${b.dataset.test}"]`);
        out.textContent = '测试中…';
        try {
          const r = await api('/api/admin/providers/test', { method: 'POST', body: { provider: b.dataset.test } });
          out.textContent = `${r.count} 条 · ${r.ms}ms`;
          out.style.color = 'var(--ok)';
        } catch (e) {
          out.textContent = '失败';
          out.style.color = 'var(--danger)';
        }
      };
    });

    body.querySelector('#pr-go').onclick = async () => {
      const provider = body.querySelector('#pr-provider').value;
      const q = body.querySelector('#pr-q').value.trim();
      const host = body.querySelector('#pr-results');
      if (!q) return toast('请输入关键词', 'err');
      host.innerHTML = `<div class="muted" style="font-size:12px;grid-column:1/-1">检索中…</div>`;
      try {
        const r = await api('/api/admin/providers/search', { method: 'POST', body: { provider, q } });
        host.innerHTML = r.items.length ? r.items.map((c, i) => `
          <div class="cand">
            ${c.poster ? `<img src="${esc(CB.state.settings && c.poster.startsWith('http') ? '/api/img?u=' + encodeURIComponent(c.poster) : c.poster)}" alt="" loading="lazy"/>`
              : `<div style="aspect-ratio:2/3;background:#16202f"></div>`}
            <div class="c-body">
              <div class="c-t">${esc(c.title)}</div>
              <div class="c-m"><span>${esc(c.year || '—')}</span>
                ${(c.files || []).length ? `<span>· ${c.files.length} 个片源</span>` : '<span>· 仅元数据</span>'}
                <span>· ${esc(c.provider)}</span></div>
              <div class="c-acts">
                <button class="btn tiny primary" data-import="${i}">${icon('plus')}导入</button>
                <a class="btn tiny ghost" href="${esc(c.sourceUrl || '#')}" target="_blank" rel="noopener">源站</a>
              </div>
            </div>
          </div>`).join('') : `<div class="muted" style="font-size:12px;grid-column:1/-1">没有结果</div>`;
        host.querySelectorAll('[data-import]').forEach((b) => {
          b.onclick = async () => {
            const c = r.items[Number(b.dataset.import)];
            b.disabled = true;
            try {
              const res = await api('/api/admin/import', {
                method: 'POST',
                body: { provider: c.provider, uid: c.uid, candidate: c },
              });
              toast(`已导入《${c.title}》${res.files ? `（${res.files} 个片源）` : '（仅元数据）'}`, 'ok');
              b.textContent = '已导入';
            } catch (e) {
              b.disabled = false;
            }
          };
        });
      } catch (e) {
        host.innerHTML = `<div class="muted" style="font-size:12px;grid-column:1/-1">检索失败：${esc(e.message)}</div>`;
      }
    };

    const enList = body.querySelector('#en-list');
    const loadEnrichList = async () => {
      const movies = (await api('/api/admin/movies')).items;
      enList.innerHTML = movies.slice(0, 12).map((m) => `
        <div class="row-item">
          <div class="r-main"><div class="r-t">${esc(m.title)}</div>
            <div class="r-m"><span>${esc(m.year || '—')}</span><span>${esc(m.source)}</span></div></div>
          <button class="btn small" data-en="${esc(m.id)}">${icon('spark')}补全</button>
        </div>`).join('') || '<p class="muted" style="font-size:12px">还没有影片</p>';
      enList.querySelectorAll('[data-en]').forEach((b) => {
        b.onclick = async () => {
          const provider = body.querySelector('#en-provider2').value;
          b.disabled = true;
          b.textContent = '补全中…';
          try {
            await api(`/api/admin/movies/${b.dataset.en}/enrich`, { method: 'POST', body: { provider } });
            toast('已补全', 'ok');
            b.textContent = '完成';
          } catch (e) {
            b.disabled = false;
            b.textContent = '失败';
          }
        };
      });
    };
    body.querySelector('#en-refresh').onclick = loadEnrichList;
    loadEnrichList();
  }


  /* ------------------------------------------------------------ api sources */
  async function drawApiSources(body) {
    body.innerHTML = `<div class="sk sk-line" style="width:220px"></div>`;
    const data = await api('/api/admin/sources');
    const kinds = data.kinds || {};
    const rows = data.items || [];
    body.innerHTML = `
      <div class="flex" style="margin-bottom:14px;flex-wrap:wrap;gap:10px">
        <button class="btn primary" id="src-new">${icon('plus')}添加片源接口</button>
        <span class="muted" style="font-size:12px">新增默认「启用 + 在搜索展示」；内置源可停用但不可删除。</span>
        <span class="grow"></span>
        <span class="chip">${rows.length} 个接口</span>
      </div>
      <div class="table-wrap"><table>
        <thead><tr>
          <th>片源</th><th>类型</th><th>接口地址</th><th>启用</th><th>搜索展示</th><th style="text-align:right">操作</th>
        </tr></thead>
        <tbody>
          ${rows.map((r) => `
            <tr data-id="${esc(r.id)}">
              <td>
                <div style="font-weight:600">${esc(r.name)}</div>
                <div class="muted" style="font-size:11px">${esc(r.note || '')}${r.builtin ? ' · 内置' : ''}</div>
              </td>
              <td><span class="chip ${r.kind === 'maccms' ? 'accent' : ''}">${esc(kinds[r.kind] || r.kind)}</span></td>
              <td><span class="mono muted" style="font-size:11px;word-break:break-all">${esc(r.endpoint || '—')}</span></td>
              <td><label class="switch"><input type="checkbox" data-toggle="enabled" ${r.enabled ? 'checked' : ''}/><i></i></label></td>
              <td><label class="switch"><input type="checkbox" data-toggle="show" ${r.show ? 'checked' : ''}/><i></i></label></td>
              <td style="text-align:right;white-space:nowrap">
                <button class="btn tiny" data-test="${esc(r.id)}">${icon('refresh')}测试</button>
                <button class="btn tiny ghost" data-edit="${esc(r.id)}">${icon('edit')}编辑</button>
                ${r.builtin ? '' : `<button class="btn tiny danger" data-del="${esc(r.id)}">${icon('trash')}</button>`}
                <span class="muted" data-result="${esc(r.id)}" style="font-size:11px;margin-left:4px"></span>
              </td>
            </tr>`).join('')}
        </tbody>
      </table></div>
      <p class="note mt12">「片源接口」决定搜索页出现哪些来源标签；「片源与元数据」页负责把某部片导入本地片库。MacCMS 接口格式：<span class="mono">https://站点/api.php/provide/vod/</span>。</p>`;

    const refresh = () => { CB.state.liveSources = null; drawApiSources(body); };
    const byId = (id) => rows.find((r) => r.id === id);

    body.querySelectorAll('[data-toggle]').forEach((el) => {
      el.onchange = async () => {
        const tr = el.closest('tr');
        const payload = {};
        payload[el.dataset.toggle] = el.checked;
        try {
          await api(`/api/admin/sources/${tr.dataset.id}`, { method: 'PATCH', body: payload });
          CB.state.liveSources = null;
          toast(`${el.dataset.toggle === 'enabled' ? '启用状态' : '搜索展示'}已更新`, 'ok');
        } catch (e) {
          el.checked = !el.checked;
        }
      };
    });

    body.querySelectorAll('[data-test]').forEach((b) => {
      b.onclick = async () => {
        const row = byId(b.dataset.test);
        const out = body.querySelector(`[data-result="${b.dataset.test}"]`);
        out.textContent = '测试中…';
        try {
          const r = await api('/api/admin/sources/test', {
            method: 'POST',
            body: { kind: row.kind, endpoint: row.endpoint, keyword: '流浪地球' },
          });
          out.textContent = `${r.count} 条 · ${r.ms}ms${r.files ? ` · ${r.files} 播放地址` : ''}`;
          out.style.color = 'var(--ok)';
        } catch (e) {
          out.textContent = '失败';
          out.style.color = 'var(--danger)';
        }
      };
    });

    body.querySelectorAll('[data-edit]').forEach((b) => {
      b.onclick = () => openSourceEditor(byId(b.dataset.edit), refresh);
    });
    body.querySelectorAll('[data-del]').forEach((b) => {
      b.onclick = async () => {
        const row = byId(b.dataset.del);
        if (!(await confirmDialog('删除片源接口', `将从搜索页移除「${row.name}」，可随时重新添加。`, true))) return;
        await api(`/api/admin/sources/${row.id}`, { method: 'DELETE' });
        toast('已删除', 'ok');
        refresh();
      };
    });
    body.querySelector('#src-new').onclick = () => openSourceEditor(null, refresh);
  }

  function openSourceEditor(row, after) {
    const isNew = !row;
    const src = row || { name: '', kind: 'maccms', endpoint: '', show: true };
    const kinds = {
      maccms: 'MacCMS 资源接口（m3u8）',
      archive: 'Internet Archive',
      itunes: 'iTunes',
      tvmaze: 'TVMaze',
      wiki: 'Wikipedia',
      tmdb: 'TMDB',
    };
    openModal({
      title: isNew ? '添加片源接口' : `编辑：${src.name}`,
      sub: isNew ? '新增后默认启用并显示在搜索页' : '',
      body: `
        <div class="form-grid">
          <label class="fl">名称<input id="src-name" value="${esc(src.name || '')}" placeholder="例如：卧龙资源"/></label>
          <label class="fl">类型<select id="src-kind" ${src.builtin ? 'disabled' : ''}>
            ${Object.entries(kinds).map(([k, v]) => `<option value="${k}" ${src.kind === k ? 'selected' : ''}>${v}</option>`).join('')}
          </select></label>
          <label class="fl full">接口地址<input id="src-endpoint" value="${esc(src.endpoint || '')}" placeholder="https://example.com/api.php/provide/vod/"/></label>
          <label class="switch"><input id="src-show" type="checkbox" ${src.show ? 'checked' : ''}/><i></i>在搜索页展示</label>
        </div>
        <div class="hr"></div>
        <div class="flex">
          <button class="btn small" id="src-test" type="button">${icon('refresh')}测试接口</button>
          <span class="muted" id="src-test-out" style="font-size:11.5px"></span>
        </div>
        <p class="note">MacCMS 接口需支持 <span class="mono">?ac=videolist&wd=关键词</span> 与 <span class="mono">?ac=detail&ids=</span>，返回 JSON（vod_play_url 内含 m3u8/网页播放地址）。</p>`,
      foot: `<button class="btn ghost" data-x="c">取消</button>
             <button class="btn primary" data-x="s">${isNew ? '添加' : '保存'}</button>`,
      onMount(wrap, close) {
        wrap.querySelector('[data-x="c"]').onclick = close;
        wrap.querySelector('#src-test').onclick = async () => {
          const out = wrap.querySelector('#src-test-out');
          out.textContent = '测试中…';
          try {
            const r = await api('/api/admin/sources/test', {
              method: 'POST',
              body: {
                kind: wrap.querySelector('#src-kind').value,
                endpoint: wrap.querySelector('#src-endpoint').value.trim(),
                keyword: '流浪地球',
              },
            });
            out.textContent = `命中 ${r.count} 条${r.sample ? ` · ${r.sample}` : ''}${r.files ? ` · ${r.files} 个播放地址` : ''} · ${r.ms}ms`;
            out.style.color = 'var(--ok)';
          } catch (e) {
            out.textContent = e.message;
            out.style.color = 'var(--danger)';
          }
        };
        wrap.querySelector('[data-x="s"]').onclick = async () => {
          const payload = {
            name: wrap.querySelector('#src-name').value.trim(),
            kind: wrap.querySelector('#src-kind').value,
            endpoint: wrap.querySelector('#src-endpoint').value.trim(),
            show: wrap.querySelector('#src-show').checked,
          };
          try {
            if (isNew) await api('/api/admin/sources', { method: 'POST', body: payload });
            else await api(`/api/admin/sources/${src.id}`, { method: 'PATCH', body: payload });
            CB.state.liveSources = null;
            close(); toast(isNew ? '已添加' : '已保存', 'ok');
            if (after) after();
          } catch (e) { /* toast handled */ }
        };
      },
    });
  }

  register('admin', renderAdmin);
})();
