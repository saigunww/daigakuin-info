/* Public snapshots only. Source credentials never reach the browser. */
(function () {
  'use strict';
  const feeds = {}, state = {year: '', subject: 'all', schedulePeriod: '', scheduleLoadedPeriod: '', scheduleRefreshPending: false, scheduleError: false, scheduleGroup: 'bio', scheduleQuery: '', research: 'all', officialQuery: '', admissionsGroup: 'all'};
  const $ = id => document.getElementById(id);
  const tr = (ja, zh, tw, en) => ({ja, zh, tw, en}[window.globalLang || 'ja'] || ja);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const jstToday = () => new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Tokyo'}).format(new Date());
  const safeURL = value => {try {const u = new URL(value, location.href); return ['http:','https:'].includes(u.protocol) ? u.href : '#';} catch (_) {return '#';}};
  const link = (url, label) => `<a href="${esc(safeURL(url))}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`;
  const meta = data => `${tr('データ更新','数据更新','資料更新','Data updated')}: ${esc((data.updated_at || '').replace('T',' ').replace('+09:00',' JST'))}`;
  const all = () => tr('すべて','全部','全部','All');
  const empty = () => `<p class="feed-empty">${tr('該当する項目はありません。','暂无符合条件的内容。','暫無符合條件的內容。','No matching entries.')}</p>`;
  const subject = s => ({bio:tr('生物学','生物学','生物學','Biology'),chem:tr('化学','化学','化學','Chemistry'),'ai-research':tr('AI研究経験強化','AI科研背景提升','AI科研背景提升','AI Research Experience'),other:tr('その他','其他','其他','Other')}[s]);
  const category = s => ({biology:tr('生物・生化学','生物与生化','生物與生化','Biology & biochemistry'),chemistry:tr('化学','化学','化學','Chemistry'),ai:tr('AI・生命科学','AI 生命科学','AI 生命科學','AI & life sciences')}[s]);
  function years(items, key) {return [...new Set(items.map(r => key(r)))].sort().reverse();}
  function button(label, active, data, value) {return `<button class="feed-button${active?' active':''}" data-${data}="${esc(value)}" aria-pressed="${active}">${esc(label)}</button>`;}

  function renderHonors() {
    const data = feeds.honors; if (!data) return;
    const host = $('honor');
    const available = years(data.items, r => r.year);
    if (!available.includes(state.year) && state.year !== 'all') state.year = available.find(y => /^20\d{2}$/.test(y)) || 'all';
    const availableSubjects = ['bio','chem','ai-research','other'].filter(s => data.items.some(r => r.subject === s));
    if (state.subject !== 'all' && !availableSubjects.includes(state.subject)) state.subject = 'all';
    const rows = data.items.filter(r => (state.year === 'all' || r.year === state.year) && (state.subject === 'all' || r.subject === state.subject));
    host.querySelectorAll(':scope > :not(.section-hero)').forEach(n => n.remove());
    const content = document.createElement('div');
    content.innerHTML = `<p class="feed-meta">${meta(data)} · ${data.items.length} ${tr('件の合格実績','份合格实绩','份合格實績','admission posters')}</p>
      <div class="feed-controls">${button(all(),state.year==='all','honor-year','all')}${available.map(y => button(y==='未分年度'?tr('年度未分類','未分年度','未分年度','Unassigned year'):tr(y+'年度',y+'年度',y+'年度',y),state.year===y,'honor-year',y)).join('')}</div>
      <div class="feed-controls">${['all',...availableSubjects].map(s => button(s==='all'?all():subject(s),state.subject===s,'honor-subject',s)).join('')}</div>
      ${state.subject==='ai-research'?`<h3 class="honor-category-title">${subject('ai-research')}</h3>`:''}
      <div class="feed-honors">${rows.map(r => `<button class="honor-card" data-poster="${esc(r.image)}" aria-label="${esc(r.name+' '+r.university)}"><img src="${esc(r.image)}" loading="lazy" decoding="async" alt="${esc(r.name+' '+r.university)}"><div class="honor-name">${esc(r.name)}</div><div class="honor-uni">${esc(r.university)}</div>${r.subject==='ai-research'?`<span class="honor-category-label">${subject(r.subject)}</span>`:''}</button>`).join('')}</div>${rows.length?'':empty()}`;
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
    state.subject = ['all','bio','chem','ai-research','other'].includes(group)?group:'all';
    if (feeds.honors) renderHonors(); else try {oldHonorSubject(group);} catch (_) {}
    try {localStorage.setItem('honorSub',state.subject);} catch (_) {}
  };

  function schedulePeriod() {
    const today=jstToday(), year=Number(today.slice(0,4)), month=Number(today.slice(5,7));
    if(month>=10)return {start:`${year}-10-01`,end:`${year+1}-04-01`,lastMonth:`${year+1}-03`};
    if(month>=4)return {start:`${year}-04-01`,end:`${year}-10-01`,lastMonth:`${year}-09`};
    return {start:`${year-1}-10-01`,end:`${year}-04-01`,lastMonth:`${year}-03`};
  }
  function refreshSchedulePeriod() {
    const period=schedulePeriod().start;
    if(feeds.schedule && state.schedulePeriod!==period)renderSchedule();
    if(!state.scheduleRefreshPending && state.scheduleLoadedPeriod!==period)fetchFeed('schedule','schedule_data.json',renderSchedule);
  }
  function renderSchedule() {
    const data = feeds.schedule; if (!data) return;
    const period=schedulePeriod();
    state.schedulePeriod=period.start;
    const monthLabel=value=>tr(`${value.slice(0,4)}年${Number(value.slice(5,7))}月`,`${value.slice(0,4)}年${Number(value.slice(5,7))}月`,`${value.slice(0,4)}年${Number(value.slice(5,7))}月`,value.slice(0,7));
    const host = $('schedule-live');
    host.innerHTML = `<div class="feed-note">${tr('指定の初回時間割を自動同期しています。元の表には後日の授業変更が反映されません。','自动同步指定的初次排课表；原表不记录后续调课，请结合老师通知确认。','自動同步指定的初次排課表；原表不記錄後續調課，請結合老師通知確認。','Automatically synced from the initial timetable. Later class changes are not recorded in this source; check instructor announcements.')}</div>
      <p class="feed-meta">${meta(data)} · ${link(data.source_url,tr('元の時間割','查看原课表','查看原課表','Source timetable'))}</p>
      <div class="schedule-period" id="schedule-period" data-start="${period.start}" data-end="${period.end}"><strong>${monthLabel(period.start)} — ${monthLabel(period.lastMonth)}</strong><span>${tr('毎年4月・10月に次の半年へ自動切替','每年4月、10月自动切换至下一期','每年4月、10月自動切換至下一期','Automatically switches to the next half-year every April and October')}</span></div>
      <div class="feed-controls">${['bio','chem'].map(g=>button(subject(g),state.scheduleGroup===g,'course-group',g)).join('')}<input id="course-query" type="search" value="${esc(state.scheduleQuery)}" aria-label="${tr('授業を検索','搜索课程','搜尋課程','Search courses')}" placeholder="${tr('科目名・クラス・内容で検索','搜索科目、班期或内容','搜尋科目、班期或內容','Search subjects, classes or topics')}"></div><div id="course-results" aria-live="polite"></div>`;
    $('course-query').oninput = e => {state.scheduleQuery=e.target.value;renderScheduleRows();};
    host.querySelectorAll('[data-course-group]').forEach(b=>b.onclick=()=>{state.scheduleGroup=b.dataset.courseGroup;renderSchedule();});
    renderScheduleRows();
    if(state.scheduleError)host.insertAdjacentHTML('beforeend',`<p class="feed-meta" data-feed-error="schedule">${tr('更新できませんでした。自動で再試行します。','课表暂时更新失败，正在自动重试。','課表暫時更新失敗，正在自動重試。','The timetable could not be refreshed. Retrying automatically.')} ${link(data.source_url,tr('元の時間割','查看原课表','查看原課表','Source timetable'))}</p>`);
  }
  function courseSubject(course) {
    const original = String(course || '').trim().replace(/\s+/g,' ');
    const withoutTerm = original.replace(/^\d{2,4}年(?:\d{1,2}月期|春期|秋期|冬季)\s*/,'');
    const named = withoutTerm.match(/^(?:生物学|生物|化学|化)\s*[-－—]\s*(.+)$/);
    const basic = withoutTerm.match(/^(?:生物学|化学)\s*(必修课程|入门课程)$/);
    let name = named ? named[1].trim() : basic ? basic[1] : original;
    if (/^入门班第\d+期$/.test(original)) name = '入门课程';
    if (withoutTerm === '生化升学指导课程') name = withoutTerm;
    // Only explicit subject aliases are merged; old A/B/TA class names stay distinct.
    const aliases = new Map([
      ['有机化学','有機化学'], ['无机化学','無機化学'], ['过去问','過去問'],
      ['有机化学过去问','有機化学過去問'], ['无机化学过去问','無機化学過去問'],
      ['入门','入门课程'], ['入門','入门课程'], ['必修课','必修课程']
    ]);
    return aliases.get(name) || name;
  }
  function renderScheduleRows() {
    const q = state.scheduleQuery.trim().toLowerCase();
    const canonicalQuery = courseSubject(q).toLowerCase();
    const period=schedulePeriod();
    const termRows=feeds.schedule.items.filter(r=>r.date>=period.start && r.date<period.end);
    const rows = termRows.filter(r=>r.group===state.scheduleGroup && [q,canonicalQuery].some(query=>(r.course+' '+r.topic+' '+courseSubject(r.course)).toLowerCase().includes(query)));
    const grouped = new Map();
    rows.forEach(r => {const name=courseSubject(r.course);if(!grouped.has(name))grouped.set(name,[]);grouped.get(name).push(r);});
    const compareName = new Intl.Collator(({zh:'zh-CN',tw:'zh-TW',en:'en',ja:'ja'})[window.globalLang] || 'ja',{numeric:true});
    const groups = [...grouped].sort((a,b)=>compareName.compare(a[0],b[0]));
    groups.forEach(([,items])=>items.sort((a,b)=>a.date.localeCompare(b.date) || (a.start_time || '99:99').localeCompare(b.start_time || '99:99')));
    const weekdays = tr(['月','火','水','木','金','土','日'],['一','二','三','四','五','六','日'],['一','二','三','四','五','六','日'],['Mon','Tue','Wed','Thu','Fri','Sat','Sun']);
    const headers = [tr('日付','日期','日期','Date'),tr('時間','时间','時間','Time'),tr('クラス・開講期','原课程／班期','原課程／班期','Original course / term'),tr('回','课次','課次','Session'),tr('授業内容','课程内容','課程內容','Topic')];
    const today = jstToday();
    const noClasses=termRows.length ? empty() : `<p class="feed-empty">${tr('今期の授業はまだ掲載されていません。元の時間割の更新後に自動表示されます。','本期暂无课程，排课表更新后会自动显示。','本期暫無課程，排課表更新後會自動顯示。','No classes are listed for this half-year yet. They will appear when the source timetable is updated.')}</p>`;
    $('course-results').innerHTML = `<p class="feed-meta">${tr('科目別','按科目分组','按科目分組','Grouped by subject')} · ${groups.length} ${tr('科目','门科目','門科目','subjects')} · ${rows.length} ${tr('授業','节课','節課','classes')}</p>` + (rows.length ? groups.map(([name,items],index)=>`<section class="course-subject-group" data-course-subject="${esc(name)}" aria-labelledby="course-subject-${index}"><div class="course-subject-heading"><h3 id="course-subject-${index}">${esc(name)}</h3><span>${items.length} ${tr('授業','节课','節課','classes')}</span></div><div class="feed-table-wrap"><table class="feed-table" aria-labelledby="course-subject-${index}"><thead><tr>${headers.map(t=>`<th scope="col">${t}</th>`).join('')}</tr></thead><tbody>${items.map(r=>`<tr${r.date>=today?' class="upcoming"':''}><td>${esc(r.date)} (${weekdays[r.weekday]})</td><td>${esc(r.start_time || '—')}${r.end_time?' – '+esc(r.end_time):''}</td><td>${esc(r.course)}</td><td>${esc(r.session || '—')}</td><td>${esc(r.topic || '—')}</td></tr>`).join('')}</tbody></table></div></section>`).join('') : noClasses);
  }

  function renderStudents() {
    const data=feeds.students;if(!data)return;
    const host=$('students-live');
    const unit=tr('名','人','人','students');
    const schools=data.schools.map(r=>({...r}));
    if(data.unknown_school_count)schools.push({school:tr('未記入','未填写','未填寫','Not provided'),count:data.unknown_school_count});
    const maximum=Math.max(1,...schools.map(r=>r.count));
    const checked=String(data.checked_at || data.updated_at || '').replace('T',' ').replace('+09:00',' JST');
    const stale=Date.now()-Date.parse(data.checked_at || data.updated_at)>3*60*60*1000;
    host.innerHTML=`<div class="students-banner"><h3>${tr('在籍学生数','在籍学生人数','在籍學生人數','Enrolled students')}</h3><div class="students-total">${data.total}</div><div class="students-total-label">${unit}</div></div>
      <p class="feed-meta">${tr('集計確認','统计截至','統計截至','Verified as of')}: ${esc(checked)} · ${tr('毎時自動更新','每小时自动更新','每小時自動更新','Updated hourly')}</p>
      ${stale?`<p class="feed-meta feed-unavailable">${tr('更新を確認できていないため、前回の集計を表示しています。','尚未获取新的统计，当前显示上次成功更新的数据。','尚未取得新的統計，目前顯示上次成功更新的資料。','Showing the last verified summary while awaiting a new update.')}</p>`:''}
      <div class="feed-note">${tr('受講中・直接受験の受講中・卒業予定の学生を集計し、休学中は含みません。人数と出身校の集計のみを掲載します。','统计在读、直考在读及待毕业学生，不含休学；仅展示人数与出身校汇总。','統計在讀、直考在讀及待畢業學生，不含休學；僅展示人數與出身校彙總。','Includes enrolled students, direct-exam students and students awaiting graduation; excludes students on leave. Only counts and origin-school totals are shown.')}</div>
      <div class="students-cards">${data.items.map(r=>`<div class="student-stat-card ${esc(r.group)}"><div class="student-stat-icon" aria-hidden="true">${r.group==='bio'?'🧬':'⚗️'}</div><div class="student-stat-label">${subject(r.group)}</div><div class="student-stat-num">${r.count}</div><div class="student-stat-unit">${unit}</div></div>`).join('')}</div>
      ${data.items.reduce((n,r)=>n+r.count,0)>data.total?`<p class="feed-meta">${tr('複数科目の受講者は総人数で重複を除いています。','跨科学生在总人数中去重统计。','跨科學生在總人數中去重統計。','Students in both subjects are counted once in the total.')}</p>`:''}
      <section class="student-school-panel" aria-labelledby="student-schools-title"><h3 id="student-schools-title">${tr('出身校分布','出身校分布','出身校分布','Origin-school distribution')}</h3><p class="feed-meta">${tr('全在籍学生の出身校別人数','全体在籍学生按出身校汇总','全體在籍學生按出身校彙總','Origin schools across all enrolled students')}</p>
      ${schools.length?`<ul class="student-schools">${schools.map(r=>`<li><div class="student-school-label"><span>${esc(r.school)}</span><strong>${r.count} ${unit}</strong></div><div class="student-school-track" aria-hidden="true"><span style="width:${100*r.count/maximum}%"></span></div></li>`).join('')}</ul>`:empty()}</section>`;
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
    const value = (p,key) => p[key+({ja:'',zh:'Zh',tw:'Tw',en:'En'}[window.globalLang] || '')] || p[key] || '';
    const titles = [...new Set(programs.map(p=>value(p,'u')))].join(' / ');
    const departments = [...new Set(programs.map(p=>value(p,'d')+' / '+value(p,'m')))].join(' · ');
    const windows = (source.application_windows || []).filter(w=>w.e>=jstToday());
    const unavailable = source.status !== 'ok';
    return `<article class="feed-card" data-source-url="${esc(source.url)}"><h3>${link(source.resolved_url || source.url,titles || source.title || source.url)}</h3>
      ${departments?`<p class="feed-meta">${esc(departments)}</p>`:''}
      <p class="feed-meta${unavailable?' feed-unavailable':''}">${unavailable?tr('現在取得できません。大学公式サイトでご確認ください。','暂时无法读取，请直接核对大学官网。','暫時無法讀取，請直接核對大學官網。','Currently unavailable; check the university website.'):tr('公式ページ確認','官网核查','官網核查','Official page checked')+' '+esc(source.checked_on)}${unavailable&&source.checked_on?' · '+esc(source.checked_on):''}</p>
      ${windows.length?`<p class="feed-meta">${tr('公式掲載の出願日程。専攻・入試区分を原文で確認してください。','官网出愿日程，具体专攻和入试批次请核对原文。','官網出願日程，具體專攻和入試批次請核對原文。','Official application windows. Check the program and admission round in the source.')}</p>`:''}
      ${windows.slice(0,compact?3:12).map(w=>`<div class="feed-window" data-deadline="${esc(w.e)}"><strong>${esc(w.s)} → ${esc(w.e)}</strong><br>${esc(w.heading)}<br>${link(w.url,w.evidence)}</div>`).join('')}
      <ul>${source.notices.slice(0,compact?3:8).map(n=>`<li>${link(n.url,n.title)}</li>`).join('')}</ul></article>`;
  }
  function renderAdmissions() {
    let data = feeds.admissions;
    const directory = window.DATA || [];
    if (!data) {
      if (!directory.length) return;
      const sources = {};
      directory.forEach(p=>{(sources[p.url] ||= {url:p.url,program_ids:[],status:'unavailable',notices:[],application_windows:[]}).program_ids.push(p.id);});
      data = {items:Object.values(sources)};
    }
    const host = $('official-updates');
    const ok = data.items.filter(r=>r.status==='ok').length;
    host.innerHTML = `<summary>${tr('大学公式サイトの募集情報','大学官网募集信息','大學官網募集資訊','University admissions notices')}</summary>
      <p class="feed-note">${tr('大学公式サイトの通知・募集要項を毎日確認しています。必要書類や試験要件はリンク先の最新要項をご確認ください。','每天核查大学官网的通知与募集要项；材料和考试要求请查看链接中的最新原文。','每天核查大學官網的通知與募集要項；資料和考試要求請查看連結中的最新原文。','University notices and guidelines are checked daily. Follow the source links for current documents and exam requirements.')}</p>
      ${feeds.admissions?`<p class="feed-meta">${meta(data)} · ${ok}/${data.items.length} ${tr('ページ取得済み','个官网页面已读取','個官網頁面已讀取','official pages retrieved')}</p>`:`<p class="feed-meta" data-feed-error="admissions">${tr('更新データを取得できません。大学公式サイトのリンクをご利用ください。','更新数据暂时无法读取，可通过下方链接访问大学官网。','更新資料暫時無法讀取，可透過下方連結造訪大學官網。','Updates are unavailable. Use the university links below.')}</p>`}
      <div class="feed-controls">${['all','bio','chem'].map(g=>button(g==='all'?all():subject(g),state.admissionsGroup===g,'admissions-group',g)).join('')}<input id="official-query" type="search" value="${esc(state.officialQuery)}" aria-label="${tr('大学・専攻で検索','搜索大学或专攻','搜尋大學或專攻','Search universities or programs')}" placeholder="${tr('大学・専攻で検索','搜索大学或专攻','搜尋大學或專攻','Search universities or programs')}"></div><div class="feed-grid" id="official-results"></div>`;
    function render() {
      const q=$('official-query').value.toLowerCase();
      state.officialQuery=$('official-query').value;
      const rows=data.items.filter(s=>{
        const programs=directory.filter(p=>s.program_ids.includes(p.id));
        if(state.admissionsGroup!=='all'&&!programs.some(p=>p.g===(state.admissionsGroup==='bio'?'生物':'化学')))return false;
        return !q||s.title?.toLowerCase().includes(q)||programs.some(p=>[p.u,p.uZh,p.uTw,p.uEn,p.d,p.dZh,p.dTw,p.dEn,p.m,p.mZh,p.mTw,p.mEn].join(' ').toLowerCase().includes(q));
      }).sort((a,b)=>{
        const score=s=>(s.status==='ok'?10:0)+(s.application_windows.some(w=>w.e>=jstToday())?20:0);
        return score(b)-score(a);
      });
      $('official-results').innerHTML=rows.map(s=>sourceCard(s,true)).join('')||empty();
    }
    $('official-query').oninput=render;
    host.querySelectorAll('[data-admissions-group]').forEach(b=>b.onclick=()=>{state.admissionsGroup=b.dataset.admissionsGroup;renderAdmissions();});
    render();
  }
  window.openOfficialProgram = function (id) {
    const program=(window.DATA || []).find(p=>p.id===id);if(!program)return;
    state.officialQuery=program.u;state.admissionsGroup='all';renderAdmissions();$('official-updates').open=true;
    const card=Array.from($('official-updates').querySelectorAll('[data-source-url]')).find(c=>c.dataset.sourceUrl===program.url);
    card?.scrollIntoView({block:'center'});
  };
  const oldLang = window.switchToLang;
  window.switchToLang = function (lang) {oldLang(lang);renderHonors();renderSchedule();renderResearch();renderAdmissions();renderStudents();};
  const oldTab = window.switchTab;
  window.switchTab = function (name) {if(['timeline','calendar'].includes(name))name='application';if (!$(name)?.classList.contains('section')) name='home';oldTab(name);if(name==='schedule')refreshSchedulePeriod();};
  if (location.hash === '#ai-advisor') history.replaceState(null,'','#home');

  async function fetchFeed(name, file, ready) {
    const requestedPeriod=name==='schedule'?schedulePeriod().start:'';
    if(name==='schedule'){
      if(state.scheduleRefreshPending)return;
      state.scheduleRefreshPending=true;
    }
    try {
      const response = await fetch(file,{cache:'no-cache',signal:AbortSignal.timeout(15000)});
      if (!response.ok) throw new Error('Snapshot unavailable');
      const data = await response.json();
      if (!data || !Array.isArray(data.items) || !data.items.length) throw new Error('Invalid snapshot');
      if(name==='schedule'){
        if(requestedPeriod!==schedulePeriod().start)return;
        state.scheduleLoadedPeriod=requestedPeriod;state.scheduleError=false;
      }
      feeds[name] = data; ready(data);
    } catch (_) {
      if(name==='schedule'){
        if(requestedPeriod!==schedulePeriod().start)return;
        state.scheduleError=true;
        if(feeds.schedule){renderSchedule();return;}
        $('schedule-live').querySelectorAll('[data-feed-error="schedule"]').forEach(el=>el.remove());
      }
      const status = document.createElement('p');status.className='feed-meta';status.dataset.feedError=name;
      status.textContent=tr('更新データを取得できませんでした。しばらくしてから再度お試しください。','更新数据暂时无法读取，请稍后重试。','更新資料暫時無法讀取，請稍後重試。','Could not load updates. Please try again later.');
      if(name==='admissions'&&(window.DATA || []).length){renderAdmissions();return;}
      if(name==='schedule')status.innerHTML=esc(status.textContent)+' '+link('https://docs.google.com/spreadsheets/d/1-lwvv7fsI4gu5S0bmaNG28gZmwriSFsKboMcT7MQ848/edit',tr('元の時間割','查看原课表','查看原課表','Source timetable'));
      const hosts={honors:'honor',schedule:'schedule-live',research:'daily-research-content',admissions:'official-updates',applications:'application',students:'students-live'};
      $(hosts[name]).append(status);
    } finally {
      if(name==='schedule'){
        state.scheduleRefreshPending=false;
        if(requestedPeriod!==schedulePeriod().start)refreshSchedulePeriod();
      }
    }
  }
  document.addEventListener('DOMContentLoaded', function () {
    fetchFeed('honors','honors_data.json',()=>{renderHonors();if(window.buildSearchIndex)buildSearchIndex();});
    fetchFeed('schedule','schedule_data.json',renderSchedule);
    fetchFeed('students','students_data.json',renderStudents);
    fetchFeed('research','research_data.json',renderResearch);
    fetchFeed('applications','applications.json',data=>{window.DATA=data.items;if(window.buildSearchIndex)buildSearchIndex();renderAdmissions();});
    fetchFeed('admissions','admissions_updates.json',renderAdmissions);
  });
  setInterval(refreshSchedulePeriod,60000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshSchedulePeriod();});
  window.addEventListener('pageshow',refreshSchedulePeriod);
})();
