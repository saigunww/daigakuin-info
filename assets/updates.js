/* Public snapshots only. Source credentials never reach the browser. */
(function () {
  'use strict';
  const feeds = {}, state = {year: '', subject: 'all', scheduleYear: '', scheduleGroup: 'bio', research: 'all'};
  const $ = id => document.getElementById(id);
  const tr = (ja, zh, tw, en) => ({ja, zh, tw, en}[window.globalLang || 'ja'] || ja);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const jstToday = () => new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Tokyo'}).format(new Date());
  const safeURL = value => {try {const u = new URL(value, location.href); return ['http:','https:'].includes(u.protocol) ? u.href : '#';} catch (_) {return '#';}};
  const link = (url, label) => `<a href="${esc(safeURL(url))}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`;
  const meta = data => `${tr('データ更新','数据更新','資料更新','Data updated')}: ${esc((data.updated_at || '').replace('T',' ').replace('+09:00',' JST'))}`;
  const all = () => tr('すべて','全部','全部','All');
  const empty = () => `<p class="feed-empty">${tr('該当する項目はありません。','暂无符合条件的内容。','暫無符合條件的內容。','No matching entries.')}</p>`;
  const subject = s => ({bio:tr('生物学','生物学','生物學','Biology'),chem:tr('化学','化学','化學','Chemistry'),other:tr('その他','其他','其他','Other')}[s]);
  const category = s => ({biology:tr('生物・生化学','生物与生化','生物與生化','Biology & biochemistry'),chemistry:tr('化学','化学','化學','Chemistry'),ai:tr('AI・生命科学','AI 生命科学','AI 生命科學','AI & life sciences')}[s]);
  function years(items, key) {return [...new Set(items.map(r => key(r)))].sort().reverse();}
  function button(label, active, data, value) {return `<button class="feed-button${active?' active':''}" data-${data}="${esc(value)}" aria-pressed="${active}">${esc(label)}</button>`;}

  function renderHonors() {
    const data = feeds.honors; if (!data) return;
    const host = $('honor');
    const available = years(data.items, r => r.year);
    if (!available.includes(state.year) && state.year !== 'all') state.year = available.find(y => /^20\d{2}$/.test(y)) || 'all';
    const rows = data.items.filter(r => (state.year === 'all' || r.year === state.year) && (state.subject === 'all' || r.subject === state.subject));
    host.querySelectorAll(':scope > :not(.section-hero)').forEach(n => n.remove());
    const content = document.createElement('div');
    content.innerHTML = `<p class="feed-meta">${meta(data)} · ${data.items.length} ${tr('件の合格実績','份合格实绩','份合格實績','admission posters')}</p>
      <div class="feed-controls">${button(all(),state.year==='all','honor-year','all')}${available.map(y => button(y==='未分年度'?tr('年度未分類','未分年度','未分年度','Unassigned year'):y,state.year===y,'honor-year',y)).join('')}</div>
      <div class="feed-controls">${['all','bio','chem','other'].map(s => button(s==='all'?all():subject(s),state.subject===s,'honor-subject',s)).join('')}</div>
      <div class="feed-honors">${rows.map(r => `<button class="honor-card" data-poster="${esc(r.image)}" aria-label="${esc(r.name+' '+r.university)}"><img src="${esc(r.image)}" loading="lazy" decoding="async" alt="${esc(r.name+' '+r.university)}"><div class="honor-name">${esc(r.name)}</div><div class="honor-uni">${esc(r.university)}</div></button>`).join('')}</div>${rows.length?'':empty()}`;
    host.append(content);
    content.querySelectorAll('[data-honor-year]').forEach(b => b.onclick = () => window.switchHonorYear(b.dataset.honorYear));
    content.querySelectorAll('[data-honor-subject]').forEach(b => b.onclick = () => window.switchHonorSubject(b.dataset.honorSubject));
    content.querySelectorAll('[data-poster]').forEach(b => b.onclick = () => openLightbox(b.dataset.poster));
  }
  const oldHonorYear = window.switchHonorYear, oldHonorSubject = window.switchHonorSubject;
  window.switchHonorYear = function (year) {
    state.year = String(year); state.subject='all';
    if (feeds.honors) renderHonors(); else if ($('honor-'+year+'-all')) oldHonorYear(year);
    try {localStorage.setItem('honorYear',year);} catch (_) {}
  };
  window.switchHonorSubject = function (group) {
    state.subject = ['all','bio','chem','other'].includes(group)?group:'all';
    if (feeds.honors) renderHonors(); else try {oldHonorSubject(group);} catch (_) {}
    try {localStorage.setItem('honorSub',state.subject);} catch (_) {}
  };

  function renderSchedule() {
    const data = feeds.schedule; if (!data) return;
    const available = years(data.items, r => r.date.slice(0,4));
    if (!available.includes(state.scheduleYear)) state.scheduleYear = available.includes(jstToday().slice(0,4)) ? jstToday().slice(0,4) : available[0];
    const host = $('schedule-live');
    host.innerHTML = `<div class="feed-note">${tr('指定の初回時間割を自動同期しています。元の表には後日の授業変更が反映されません。','自动同步指定的初次排课表；原表不记录后续调课，请结合老师通知确认。','自動同步指定的初次排課表；原表不記錄後續調課，請結合老師通知確認。','Automatically synced from the initial timetable. Later class changes are not recorded in this source; check instructor announcements.')}</div>
      <p class="feed-meta">${meta(data)} · ${link(data.source_url,tr('元の時間割','查看原课表','查看原課表','Source timetable'))}</p>
      <div class="feed-controls"><label>${tr('年度','年份','年份','Year')} <select id="schedule-year">${available.map(y=>`<option${y===state.scheduleYear?' selected':''}>${y}</option>`).join('')}</select></label>
      ${['bio','chem'].map(g=>button(subject(g),state.scheduleGroup===g,'course-group',g)).join('')}<input id="course-query" type="search" aria-label="${tr('授業を検索','搜索课程','搜尋課程','Search courses')}" placeholder="${tr('授業名・内容で検索','搜索课程或内容','搜尋課程或內容','Search courses or topics')}"></div><div id="course-results"></div>`;
    $('schedule-year').onchange = e => {state.scheduleYear=e.target.value;renderScheduleRows();};
    $('course-query').oninput = renderScheduleRows;
    host.querySelectorAll('[data-course-group]').forEach(b=>b.onclick=()=>{state.scheduleGroup=b.dataset.courseGroup;renderSchedule();});
    renderScheduleRows();
  }
  function renderScheduleRows() {
    const q = ($('course-query').value || '').toLowerCase();
    const rows = feeds.schedule.items.filter(r=>r.group===state.scheduleGroup && r.date.startsWith(state.scheduleYear) && (r.course+' '+r.topic).toLowerCase().includes(q));
    const weekdays = tr(['月','火','水','木','金','土','日'],['一','二','三','四','五','六','日'],['一','二','三','四','五','六','日'],['Mon','Tue','Wed','Thu','Fri','Sat','Sun']);
    $('course-results').innerHTML = `<p class="feed-meta">${rows.length} ${tr('授業','节课','節課','classes')}</p>` + (rows.length?`<div class="feed-table-wrap"><table class="feed-table"><thead><tr>${[tr('日付','日期','日期','Date'),tr('時間','时间','時間','Time'),tr('授業','课程','課程','Course'),tr('回','课次','課次','Session'),tr('授業内容','课程内容','課程內容','Topic')].map(t=>`<th scope="col">${t}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr${r.date>=jstToday()?' class="upcoming"':''}><td>${esc(r.date)} (${weekdays[r.weekday]})</td><td>${esc(r.start_time || '—')}${r.end_time?' – '+esc(r.end_time):''}</td><td>${esc(r.course)}</td><td>${esc(r.session || '—')}</td><td>${esc(r.topic || '—')}</td></tr>`).join('')}</tbody></table></div>`:empty());
  }

  function renderResearch() {
    const host = $('daily-research-content'), data = feeds.research;
    if (!data) return;
    host.innerHTML = `<div class="feed-note">${tr('生物・化学・AI生命科学の新着論文を毎日追加。論文タイトルと書誌情報を掲載し、原文へ直接リンクします。','每天新增生物、生化、化学和 AI 生命科学论文，保留原文标题、发表日期及论文链接。','每天新增生物、生化、化學和 AI 生命科學論文，保留原文標題、發表日期及論文連結。','New papers in biology, chemistry and AI for life sciences, added daily with original titles, publication dates and source links.')}</div>
      <p class="feed-meta">${meta(data)} · Europe PMC / PubMed · ${data.items.length} ${tr('件','篇','篇','papers')}</p>
      <div class="feed-controls">${['all','biology','chemistry','ai'].map(c=>button(c==='all'?all():category(c),state.research===c,'research-category',c)).join('')}</div><div class="feed-grid">${data.items.filter(r=>state.research==='all'||r.category===state.research).map(r=>`<article class="feed-card"><span class="feed-tag">${category(r.category)}</span><h3>${link(r.url,r.title)}</h3><p class="feed-meta">${esc(r.source)}<br>${tr('発表','发表','發表','Published')}: ${esc(r.published_at)} · ${tr('掲載','收录','收錄','Added')}: ${esc(r.added_on)}</p>${r.summary?`<p>${esc(r.summary)}</p>`:''}${link(r.url,tr('論文を読む','阅读论文','閱讀論文','Read paper'))}</article>`).join('')}</div>`;
    host.querySelectorAll('[data-research-category]').forEach(b=>b.onclick=()=>{state.research=b.dataset.researchCategory;renderResearch();});
  }

  function sourceCard(source, compact) {
    const programs = (window.DATA || []).filter(r=>source.program_ids.includes(r.id));
    const titles = [...new Set(programs.map(p=>p.u))].join(' / ');
    const unavailable = source.status !== 'ok';
    return `<article class="feed-card"><h3>${link(source.resolved_url || source.url,titles || source.title || source.url)}</h3>
      <p class="feed-meta${unavailable?' feed-unavailable':''}">${unavailable?tr('現在取得できません。大学公式サイトでご確認ください。','暂时无法读取，请直接核对大学官网。','暫時無法讀取，請直接核對大學官網。','Currently unavailable; check the university website.'):tr('公式ページ確認','官网核查','官網核查','Official page checked')+' '+esc(source.checked_on)}${unavailable&&source.checked_on?' · '+esc(source.checked_on):''}</p>
      ${source.application_windows.length?`<p class="feed-meta">${tr('公式掲載の日程候補。専攻・入試区分を原文で確認してください。','官网日程候选，请核对专攻和入试批次；未确认项不会覆盖专攻日期。','官網日程候選，請核對專攻和入試批次；未確認項不會覆蓋專攻日期。','Official date candidates. Check the program and admission round in the source; unverified dates do not replace program deadlines.')}</p>`:''}
      ${source.application_windows.slice(0,compact?3:12).map(w=>`<div class="feed-window"><strong>${esc(w.s)} → ${esc(w.e)}</strong><br>${esc(w.heading)}<br>${link(w.url,w.evidence)}</div>`).join('')}
      <ul>${source.notices.slice(0,compact?3:8).map(n=>`<li>${link(n.url,n.title)}</li>`).join('')}</ul></article>`;
  }
  function renderAdmissions() {
    const data = feeds.admissions; if (!data) return;
    const host = $('official-updates');
    const ok = data.items.filter(r=>r.status==='ok').length;
    host.innerHTML = `<summary>${tr('大学公式サイトの最新情報','大学官网最新信息','大學官網最新資訊','Latest university notices')}</summary><p class="feed-meta">${meta(data)} · ${ok}/${data.items.length} ${tr('ページ取得済み','个官网页面已读取','個官網頁面已讀取','official pages retrieved')}</p><div class="feed-controls"><input id="official-query" type="search" aria-label="${tr('大学名で検索','搜索大学名称','搜尋大學名稱','Search universities')}" placeholder="${tr('大学名で検索','搜索大学名称','搜尋大學名稱','Search universities')}"></div><div class="feed-grid" id="official-results"></div>`;
    function render() {
      const q=$('official-query').value.toLowerCase();
      const rows=data.items.filter(s=>!q||s.title?.toLowerCase().includes(q)||(window.DATA||[]).some(p=>s.program_ids.includes(p.id)&&[p.u,p.uZh,p.uTw,p.uEn,p.d].join(' ').toLowerCase().includes(q))).sort((a,b)=>{
        const score=s=>(s.status==='ok'?10:0)+(s.application_windows.some(w=>w.e>=jstToday())?20:0);
        return score(b)-score(a);
      });
      $('official-results').innerHTML=rows.map(s=>sourceCard(s,true)).join('')||empty();
    }
    $('official-query').oninput=render;render();decorateProgramCards();
  }
  function decorateProgramCards() {
    document.querySelectorAll('#appCards .app-card').forEach(card=>{
      const match=(card.getAttribute('onclick')||'').match(/openAppModal\((\d+)\)/);
      if (!match) return;
      const program=(window.DATA||[]).find(p=>p.id===Number(match[1]));
      if (!program) return;
      const deadline=card.querySelector('.app-card-deadline');
      if (deadline&&!program.date_source) deadline.innerHTML=esc(tr('既存資料の出願締切','原有资料截止日期','原有資料截止日期','Deadline in reference record'))+': <strong>'+esc(program.e||tr('未確認','待确认','待確認','Unconfirmed'))+'</strong>';
      card.querySelector('.feed-program-status')?.remove();
      const source=feeds.admissions?.items.find(s=>s.program_ids.includes(program.id));
      if (source) {
        const status=document.createElement('p');status.className='feed-meta feed-program-status';
        status.textContent=(source.status==='ok'?tr('公式ページ確認','官网核查','官網核查','Official page checked')+' '+source.checked_on:tr('公式サイトの取得待ち','官网暂时无法读取','官網暫時無法讀取','Official source unavailable'))+' · '+tr('詳細から最新の募集情報へ','点击查看最新募集信息','點擊查看最新募集資訊','Open for current guidelines');
        card.append(status);
      }
    });
  }
  const oldFilter=window.filterApp;
  window.filterApp=function(){oldFilter();decorateProgramCards();};
  const oldModal = window.openAppModal;
  window.openAppModal = function (id) {
    oldModal(id);
    const source = feeds.admissions?.items.find(s=>s.program_ids.includes(id));
    if (source) {const panel=document.createElement('div');panel.className='feed-source-panel';panel.innerHTML=sourceCard(source,false)+`<p class="feed-meta">${tr('以下の専攻別の受験科目・出願書類は既存の整理資料です。最新の要件は上記の公式募集要項で確認してください。','下方专攻考试科目、材料要求属于原有整理资料；最新要求请查看上方官方募集要项。','下方專攻考試科目、材料要求屬於原有整理資料；最新要求請查看上方官方募集要項。','Program-specific exam subjects and required documents below are reference records. Check the official guidelines above for current requirements.')}</p>`;$('mBody').prepend(panel);}
  };
  const oldLang = window.switchToLang;
  window.switchToLang = function (lang) {oldLang(lang);renderHonors();renderSchedule();renderResearch();renderAdmissions();};
  const oldTab = window.switchTab;
  window.switchTab = function (name) {if (!$(name)?.classList.contains('section')) name='home';oldTab(name);};
  if (location.hash === '#ai-advisor') history.replaceState(null,'','#home');

  async function fetchFeed(name, file, ready) {
    try {
      const response = await fetch(file,{cache:'no-cache',signal:AbortSignal.timeout(15000)});
      if (!response.ok) throw new Error('Snapshot unavailable');
      const data = await response.json();
      if (!data || !Array.isArray(data.items) || !data.items.length) throw new Error('Invalid snapshot');
      feeds[name] = data; ready(data);
    } catch (_) {
      const status = document.createElement('p');status.className='feed-meta';status.dataset.feedError=name;
      status.textContent=tr('更新データを取得できませんでした。保存済みの内容があれば表示しています。','更新数据暂时无法读取；已有内容仍可查看。','更新資料暫時無法讀取；已有內容仍可查看。','Could not load updates. Saved content remains available where present.');
      const hosts={honors:'honor',schedule:'schedule',research:'daily-research-content',admissions:'official-updates',applications:'application'};
      $(hosts[name]).append(status);
    }
  }
  document.addEventListener('DOMContentLoaded', function () {
    fetchFeed('honors','honors_data.json',()=>{renderHonors();if(window.buildSearchIndex)buildSearchIndex();});
    fetchFeed('schedule','schedule_data.json',()=>{$('schedule').querySelectorAll(':scope > :not(.section-hero):not(#schedule-live)').forEach(n=>n.hidden=true);renderSchedule();});
    fetchFeed('research','research_data.json',renderResearch);
    fetchFeed('applications','applications.json',data=>{window.DATA=data.items;filterApp();if(window.buildSearchIndex)buildSearchIndex();if($('timeline').classList.contains('active'))renderTimeline();if($('calendar').classList.contains('active'))renderCalendar();renderAdmissions();});
    fetchFeed('admissions','admissions_updates.json',renderAdmissions);
  });
})();
