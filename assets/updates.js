/* Public snapshots only. Source credentials never reach the browser. */
(function () {
  'use strict';
  const feeds = {}, state = {year: '', field: 'all', subject: 'all', honorMoreFilters: false, schedulePeriod: '', scheduleLoadedPeriod: '', scheduleRefreshPending: false, scheduleLastFetch: 0, scheduleError: false, scheduleGroup: 'bio', scheduleQuery: '', research: 'all', officialQuery: '', admissionsGroup: 'all'};
  const $ = id => document.getElementById(id);
  const tr = (ja, zh, tw, en) => ({ja, zh, tw, en}[window.globalLang || 'ja'] || ja);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const jstToday = () => new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Tokyo'}).format(new Date());
  const safeURL = value => {try {const u = new URL(value, location.href); return ['http:','https:'].includes(u.protocol) ? u.href : '#';} catch (_) {return '#';}};
  const link = (url, label) => `<a href="${esc(safeURL(url))}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`;
  const meta = data => `${tr('データ更新','数据更新','資料更新','Data updated')}: ${esc((data.updated_at || '').replace('T',' ').replace('+09:00',' JST'))}`;
  const all = () => tr('すべて','全部','全部','All');
  const empty = () => `<p class="feed-empty">${tr('該当する項目はありません。','暂无符合条件的内容。','暫無符合條件的內容。','No matching entries.')}</p>`;
  const subject = s => ({bio:tr('生物学','生物学','生物學','Biology'),chem:tr('化学','化学','化學','Chemistry'),'ai-research':tr('研究経験強化','科研背景提升','科研背景提升','Research experience'),other:tr('その他','其他','其他','Other')}[s]);
  const category = s => ({biology:tr('生物・生化学','生物与生化','生物與生化','Biology & biochemistry'),chemistry:tr('化学','化学','化學','Chemistry'),ai:tr('AI・生命科学','AI 生命科学','AI 生命科學','AI & life sciences')}[s]);
  const noticesState = {visible:20, pending:false, error:false};
  const honorsState = {pending:false, error:false};
  const originalNotices = window.renderNotices;
  const noticeTargets = new Set(['home','daily-research','application','honor','schedule','students','intro']);
  function renderAnnouncements() {
    const host=$('noticeBoard'), data=feeds.notices;
    if(!host)return;
    if(!data){
      if(originalNotices)originalNotices();
    }else{
      const language=window.globalLang || 'ja';
      const localized=value=>value?.[language] || value?.ja || '';
      const rows=[...data.items,...(window.NOTICES || []).map((r,i)=>({...r,id:'history:'+i}))]
        .sort((a,b)=>b.date.localeCompare(a.date));
      host.innerHTML=`<p class="feed-meta notice-sync-note">${tr('各ページの公開内容を毎時確認し、変更がある場合に更新します。','每小时检查各栏目公开内容，有实际变化时更新公告。','每小時檢查各欄目公開內容，有實際變化時更新公告。','Published content is checked hourly; announcements appear when it changes.')}</p>
        <p class="feed-meta">${meta(data)}</p><div class="notice-list">${rows.slice(0,noticesState.visible).map(row=>{
          const tag=['new','update','info'].includes(row.tag)?row.tag:'info';
          const tagLabel=tag==='new'?tr('新機能','新功能','新功能','New'):tag==='update'?tr('更新','更新','更新','Update'):tr('ご案内','信息','資訊','Info');
          const body=esc(localized(row.body)).replace(/&lt;br\s*\/?&gt;/gi,'<br>');
          return `<article class="notice-item${tag==='new'?' new':''}" data-notice-id="${esc(row.id)}"><div class="notice-date">${esc(row.date)} <span class="notice-tag ${tag}">${tagLabel}</span></div><h3 class="notice-title">${esc(localized(row.title))}</h3><div class="notice-body">${body}</div>${noticeTargets.has(row.target)&&row.target!=='home'?`<a class="notice-detail" href="#${row.target}" data-notice-target="${row.target}">${tr('詳細を見る','查看详情','查看詳情','View details')} →</a>`:''}</article>`;
        }).join('')}</div>${rows.length>noticesState.visible?`<button type="button" class="feed-button notice-more">${tr('以前のお知らせを表示','查看更多历史公告','查看更多歷史公告','Show earlier announcements')}</button>`:''}`;
      host.querySelector('.notice-more')?.addEventListener('click',()=>{noticesState.visible+=20;renderAnnouncements();});
      host.querySelectorAll('[data-notice-target]').forEach(anchor=>anchor.addEventListener('click',event=>{
        event.preventDefault();const target=anchor.dataset.noticeTarget;window.switchTab(target);
        // An open homepage may receive a new announcement hours after loading.
        // Refresh its destination rather than displaying an older in-memory feed.
        const targets={
          'daily-research':['research','research_data.json',renderResearch],
          application:['admissions','admissions_updates.json',renderAdmissions],
          honor:['honors','honors_data.json',renderHonors],
          schedule:['schedule','schedule_data.json',renderSchedule],
          students:['students','students_data.json',renderStudents]
        };
        if(targets[target])fetchFeed(...targets[target]);
      }));
    }
    host.querySelector('[data-feed-error="notices"]')?.remove();
    if(noticesState.error){
      const status=document.createElement('p');status.className='feed-meta';status.dataset.feedError='notices';
      status.textContent=tr('最新のお知らせを取得できないため、前回の内容を表示しています。自動で再試行します。','最新公告暂时无法读取，当前显示此前内容，将自动重试。','最新公告暫時無法讀取，目前顯示先前內容，將自動重試。','Showing previous announcements while the latest updates are unavailable. Retrying automatically.');
      host.prepend(status);
    }
  }
  window.renderNotices=renderAnnouncements;
  async function refreshNotices(){
    if(noticesState.pending)return;
    noticesState.pending=true;
    let needsRender=false;
    try{
      const response=await fetch('notices_data.json',{cache:'no-cache',signal:AbortSignal.timeout(15000)});
      if(!response.ok)throw new Error('Announcements unavailable');
      const data=await response.json();
      if(!data?.updated_at || !Array.isArray(data.items) || !data.items.length || !data.items.every(row=>
        /^\d{4}-\d{2}-\d{2}$/.test(row.date) && noticeTargets.has(row.target) &&
        ['ja','zh','tw','en'].every(lang=>typeof row.title?.[lang]==='string' && typeof row.body?.[lang]==='string')))
        throw new Error('Invalid announcements');
      needsRender=noticesState.error || JSON.stringify(feeds.notices)!==JSON.stringify(data);
      feeds.notices=data;noticesState.error=false;
    }catch(_){needsRender=!noticesState.error;noticesState.error=true;}
    finally{noticesState.pending=false;if(needsRender)renderAnnouncements();}
  }
  function years(items, key) {return [...new Set(items.map(r => key(r)))].sort().reverse();}
  function button(label, active, data, value) {return `<button class="feed-button${active?' active':''}" data-${data}="${esc(value)}" aria-pressed="${active}">${esc(label)}</button>`;}
  const honorFields = data => data.statistics?.schema_version === 2 && Array.isArray(data.statistics.fields) ? data.statistics.fields : [];
  const honorFieldLabel = (data, id) => id === 'all' ? tr('全専攻','全部专业','全部專業','All fields')
    : honorFields(data).find(field => field.id === id)?.labels[window.globalLang || 'ja'] || tr('専攻未確認','专业待确认','專業待確認','Field unconfirmed');
  const honorYearLabel = year => year === 'all' ? tr('全年度','全部年度','全部年度','All years')
    : year === '未分年度' ? tr('入学年度未確認','入学年度待确认','入學年度待確認','Entry year unconfirmed') : tr(year+'年度',year+'年度',year+'年度',year);
  function honorFieldCount(data, field) {
    return (data.statistics?.years || []).filter(row => state.year === 'all' ? row.year !== '未分年度' : row.year === state.year).reduce((total,row) => {
      const value = field === 'all' ? row : row.by_field?.[field];
      const selected = state.subject === 'all' ? value : value?.by_subject?.[state.subject];
      return total + (Number.isSafeInteger(selected?.total) ? selected.total : 0);
    },0);
  }

  function renderHonors() {
    const data = feeds.honors; if (!data) return;
    const host = $('honor');
    const statisticYears = Array.isArray(data.statistics?.years) ? data.statistics.years : [];
    const available = [...new Set([...data.items.map(r=>r.year),...statisticYears.map(r=>r.year)])].sort().reverse();
    if (!available.includes(state.year) && state.year !== 'all') state.year = available.find(y => /^20\d{2}$/.test(y)) || 'all';
    const availableSubjects = ['bio','chem','ai-research','other'].filter(s => data.items.some(r => r.subject === s) || statisticYears.some(r=>r.by_subject?.[s]?.total>0));
    if (state.subject !== 'all' && !availableSubjects.includes(state.subject)) state.subject = 'all';
    const catalogue = honorFields(data);
    if (state.field !== 'all' && !catalogue.some(field => field.id === state.field)) state.field = 'all';
    const availableFields = catalogue.filter(field => state.field === field.id || statisticYears.some(row => row.by_field?.[field.id]?.total > 0) || data.items.some(row => row.field === field.id));
    const rows = data.items.filter(r => (state.year === 'all' || r.year === state.year) && (state.field === 'all' || r.field === state.field) && (state.subject === 'all' || r.subject === state.subject));
    const focus = host.contains(document.activeElement) ? ['honorYear','honorField','honorSubject'].find(key => document.activeElement.dataset?.[key] !== undefined) : null;
    const focusValue = focus ? document.activeElement.dataset[focus] : null;
    const scope = `${honorYearLabel(state.year)} · ${honorFieldLabel(data,state.field)}${state.subject === 'all' ? '' : ' · '+subject(state.subject)}`;
    const fieldButton = field => {
      const count = honorFieldCount(data,field), label = honorFieldLabel(data,field);
      return `<button type="button" class="feed-button honor-field-button${state.field === field ? ' active' : ''}" data-honor-field="${esc(field)}" aria-pressed="${state.field === field}" aria-label="${esc(label+' · '+tr('合格件数','合格份数','合格份數','Admission offers')+' '+count)}"><span>${esc(label)}</span><span class="honor-field-count" aria-hidden="true">${count}</span></button>`;
    };
    host.querySelectorAll(':scope > :not(.section-hero)').forEach(n => n.remove());
    const content = document.createElement('div');
    content.innerHTML = `<p class="feed-meta">${meta(data)}</p>
      <div class="honor-filters" aria-label="${tr('合格実績の絞り込み','合格结果筛选','合格結果篩選','Filter admission results')}">
        <div class="honor-filter-row"><span class="honor-filter-label" id="honor-year-filter-label">${tr('入学年度','入学年度','入學年度','Entry year')}</span><div class="feed-controls" role="group" aria-labelledby="honor-year-filter-label">${button(honorYearLabel('all'),state.year==='all','honor-year','all')}${available.map(y => button(honorYearLabel(y),state.year===y,'honor-year',y)).join('')}</div></div>
        <div class="honor-filter-row"><span class="honor-filter-label" id="honor-field-filter-label">${tr('専攻','专业','專業','Field')}</span><div class="feed-controls" role="group" aria-labelledby="honor-field-filter-label">${catalogue.length ? ['all',...availableFields.map(field => field.id)].map(fieldButton).join('') : `<p class="honor-filter-pending">${tr('専攻別のデータを更新しています。全専攻の実績をご覧いただけます。','专业分类更新中，目前展示全部专业的合格结果。','專業分類更新中，目前展示全部專業的合格結果。','Field data is being updated. Results for all fields are available.')}</p>`}</div></div>
        <p class="honor-filter-help">${tr('数字は選択した年度の合格件数です。専攻を選ぶと、大学別集計と合格一覧が同時に切り替わります。','专业旁的数字为所选年度的合格份数。点击专业，即可同时查看各校统计与合格榜。','專業旁的數字為所選年度的合格份數。點擊專業，即可同時查看各校統計與合格榜。','Numbers show offers for the selected year. Choose a field to update both the university statistics and admission posters.')}</p>
        <details class="honor-more-filters"${state.honorMoreFilters ? ' open' : ''}><summary>${tr('その他の絞り込み','更多筛选','更多篩選','More filters')}${state.subject !== 'all' ? ' · '+esc(subject(state.subject)) : ''}</summary><div class="honor-filter-row"><span class="honor-filter-label" id="honor-subject-filter-label">${tr('受講コース','课程类别','課程類別','Course group')}</span><div class="feed-controls" role="group" aria-labelledby="honor-subject-filter-label">${['all',...availableSubjects].map(s => button(s==='all'?all():subject(s),state.subject===s,'honor-subject',s)).join('')}</div></div></details>
      </div>
      <div id="honor-stats"></div>
      <div class="honor-gallery-heading"><div><h3 class="honor-gallery-title">${tr('合格一覧','合格榜','合格榜','Admission posters')}</h3><p class="honor-gallery-scope">${esc(scope)}</p></div><span class="honor-gallery-count">${rows.length} ${tr('枚の公開ポスター','张公开海报','張公開海報','published posters')}</span></div>
      <div class="feed-honors">${rows.map(r => `<button type="button" class="honor-card" data-poster="${esc(r.image)}" data-honor-field-id="${esc(r.field || '')}" aria-label="${esc(r.name+' '+r.university)}"><img src="${esc(r.image)}" loading="lazy" decoding="async" alt="${esc(r.name+' '+r.university)}"><div class="honor-name">${esc(r.name)}</div><div class="honor-uni">${esc(r.university)}</div>${catalogue.length ? `<span class="honor-field-tag">${esc(honorFieldLabel(data,r.field))}</span>` : ''}${r.subject==='ai-research'?`<span class="honor-category-label">${subject(r.subject)}</span>`:''}</button>`).join('')}</div>${rows.length?'':`<p class="feed-empty">${tr('この条件の公開ポスターはまだありません。統計には表の合格記録も含まれます。','此筛选下暂无公开海报；上方统计仍包含表格中的合格记录。','此篩選下暫無公開海報；上方統計仍包含表格中的合格紀錄。','No published posters for this selection. Statistics also include offers recorded in the source sheets.')}</p>`}`;
    host.append(content);
    if(window.renderHonorStats)window.renderHonorStats(content.querySelector('#honor-stats'),data,state);
    if(honorsState.error)honorsError();
    content.querySelectorAll('[data-honor-year]').forEach(b => b.onclick = () => window.switchHonorYear(b.dataset.honorYear));
    content.querySelectorAll('[data-honor-subject]').forEach(b => b.onclick = () => window.switchHonorSubject(b.dataset.honorSubject));
    content.querySelectorAll('[data-honor-field]').forEach(b => b.onclick = () => window.switchHonorField(b.dataset.honorField));
    content.querySelector('.honor-more-filters')?.addEventListener('toggle',event => {state.honorMoreFilters = event.currentTarget.open;});
    content.querySelectorAll('[data-poster]').forEach(b => b.onclick = () => openLightbox(b.dataset.poster));
    if (focus) Array.from(content.querySelectorAll('[data-honor-year],[data-honor-field],[data-honor-subject]')).find(control => control.dataset[focus] === focusValue)?.focus({preventScroll:true});
  }
  const oldHonorYear = window.switchHonorYear, oldHonorSubject = window.switchHonorSubject;
  window.switchHonorYear = function (year) {
    state.year = String(year);
    if (feeds.honors) renderHonors(); else if ($('honor-'+year+'-all')) oldHonorYear(year);
    try {localStorage.setItem('honorYear',year);} catch (_) {}
  };
  window.switchHonorSubject = function (group) {
    state.subject = ['all','bio','chem','ai-research','other'].includes(group)?group:'all';
    if (feeds.honors) renderHonors(); else try {oldHonorSubject(group);} catch (_) {}
    try {localStorage.setItem('honorSub',state.subject);} catch (_) {}
  };
  window.switchHonorField = function (field) {
    state.field = field === 'all' || honorFields(feeds.honors || {}).some(item => item.id === field) ? field : 'all';
    if (feeds.honors) renderHonors();
  };

  function honorsError(){
    const host=$('honor');if(!host)return;
    host.querySelectorAll('[data-feed-error="honors"]').forEach(n=>n.remove());
    const message=document.createElement('p');message.className='feed-meta';message.dataset.feedError='honors';
    message.textContent=tr('最新の合格データを取得できません。前回の内容を保持し、自動で再試行します。','最新合格数据暂时无法读取，保留此前内容并自动重试。','最新合格資料暫時無法讀取，保留先前內容並自動重試。','The latest admission data is unavailable. Keeping previous results and retrying automatically.');
    host.append(message);
  }

  async function refreshHonors(){
    if(honorsState.pending)return;
    honorsState.pending=true;
    try{
      const response=await fetch('honors_data.json',{cache:'no-cache',signal:AbortSignal.timeout(15000)});
      if(!response.ok)throw new Error('Admission data unavailable');
      const data=await response.json();
      if(!data?.updated_at || !Array.isArray(data.items) || !data.items.length ||
        !data.items.every(row=>typeof row.id==='string' && typeof row.year==='string' && typeof row.image==='string'))throw new Error('Invalid admission data');
      if((feeds.honors?.statistics && !data.statistics) ||
        (feeds.honors?.statistics?.schema_version === 2 && data.statistics?.schema_version !== 2) ||
        (data.statistics && window.validateHonorStatistics && !window.validateHonorStatistics(data.statistics)))throw new Error('Invalid admission statistics');
      if(data.statistics?.schema_version === 2 && !data.items.every(row => honorFields(data).some(field => field.id === row.field)))throw new Error('Invalid admission fields');
      const changed=honorsState.error || JSON.stringify(feeds.honors)!==JSON.stringify(data);
      feeds.honors=data;honorsState.error=false;
      if(changed){renderHonors();if(window.buildSearchIndex)buildSearchIndex();}
    }catch(_){honorsState.error=true;honorsError();}
    finally{honorsState.pending=false;}
  }

  function schedulePeriod() {
    const today=jstToday(), year=Number(today.slice(0,4)), month=Number(today.slice(5,7));
    const january={start:`${year}-01-01`,end:`${year}-10-01`,lastMonth:`${year}-09`};
    const winterYear=month>=10?year:year-1;
    const winter={start:`${winterYear}-10-01`,end:`${winterYear+1}-04-01`,lastMonth:`${winterYear+1}-03`};
    const terms=month>=10?[winter]:month>=4?[january]:[winter,january];
    const start=terms[0].start, end=terms[terms.length-1].end;
    // January–March belongs to both terms. Filter their overlapping windows
    // once so each source row appears once, including distinct class cohorts.
    return {start,end,terms,key:start+'/'+end};
  }
  function refreshSchedulePeriod(force=false) {
    const period=schedulePeriod().key;
    if(feeds.schedule && state.schedulePeriod!==period)renderSchedule();
    refreshScheduleHighlights();
    if(!state.scheduleRefreshPending && (force===true || state.scheduleLoadedPeriod!==period || state.scheduleError || Date.now()-state.scheduleLastFetch>=300000))fetchFeed('schedule','schedule_data.json',renderSchedule);
  }
  function isUpcomingCourse(date, startTime, currentTime=Date.now(), today=jstToday()) {
    if(date!==today)return date>today;
    const time=String(startTime || '').trim().match(/^([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?$/);
    // Without a scheduled start time, retain today's date-based indication.
    if(!time)return true;
    const start=Date.parse(`${date}T${time[1].padStart(2,'0')}:${time[2]}:${time[3] || '00'}+09:00`);
    return currentTime<start;
  }
  function refreshScheduleHighlights() {
    const currentTime=Date.now(), today=jstToday();
    document.querySelectorAll('#course-results tr[data-course-date]').forEach(row=>{
      row.classList.toggle('upcoming',isUpcomingCourse(row.dataset.courseDate,row.dataset.courseStart,currentTime,today));
    });
  }
  function renderSchedule() {
    const data = feeds.schedule; if (!data) return;
    const period=schedulePeriod();
    state.schedulePeriod=period.key;
    const monthLabel=value=>tr(`${value.slice(0,4)}年${Number(value.slice(5,7))}月`,`${value.slice(0,4)}年${Number(value.slice(5,7))}月`,`${value.slice(0,4)}年${Number(value.slice(5,7))}月`,value.slice(0,7));
    const host = $('schedule-live');
    const rooms=data.source_type==='rooms_schedule';
    const covered=!rooms || (data.coverage_start<=period.start && data.coverage_end>=period.end);
    const lastSuccess=String(data.last_success_at || data.updated_at || '').replace('T',' ').replace('+09:00',' JST');
    const stale=rooms && (data.sync_status!=='ok' || Date.now()-Date.parse(data.last_success_at)>90*60000);
    const note=rooms?tr('日時・変更・キャンセルはRoomsから毎時同期。授業内容は元の時間割と照合しています。「当初予定」は元の順序から推定した対応で、実際の授業内容は講師の案内をご確認ください。','每小时同步Rooms的日期、时间、调课与取消；课程内容对照原排课表补充。“原计划”表示内容按原排课顺序推定，实际授课内容以老师通知为准。','每小時同步Rooms的日期、時間、調課與取消；課程內容對照原排課表補充。「原計畫」表示內容按原排課順序推定，實際授課內容以老師通知為準。','Dates, times, changes and cancellations sync hourly from Rooms. Topics come from the original timetable. “Original plan” marks an inferred match by original timetable order; check instructor announcements for actual content.'):tr('指定の初回時間割を自動同期しています。元の表には後日の授業変更が反映されません。','自动同步指定的初次排课表；原表不记录后续调课，请结合老师通知确认。','自動同步指定的初次排課表；原表不記錄後續調課，請結合老師通知確認。','Automatically synced from the initial timetable. Later class changes are not recorded in this source; check instructor announcements.');
    host.innerHTML = `<div class="feed-note">${note}</div>
      <p class="feed-meta">${rooms?tr('最終同期成功','最近成功同步','最近成功同步','Last successful sync')+': '+esc(lastSuccess)+' · '+tr('毎時自動同期','每小时自动同步','每小時自動同步','Synced hourly'):meta(data)}</p>
      ${stale?`<p class="feed-meta feed-unavailable" data-rooms-stale>${tr('最新の同期を確認できないため、上記時点の予定を表示しています。','最新同步尚未成功，当前显示上述时间的课表。','最新同步尚未成功，目前顯示上述時間的課表。','The latest sync is unavailable; showing the timetable verified at the time above.')}</p>`:''}
      ${rooms && data.metadata_status==='cached'?`<p class="feed-meta" data-metadata-cached>${tr('授業内容は前回の照合結果を表示しています。','课程内容暂沿用上次对照结果。','課程內容暫沿用上次對照結果。','Topics use the previous timetable comparison.')}</p>`:''}
      ${!covered?`<p class="feed-meta feed-unavailable" data-rooms-period-pending>${tr('新しい表示期間の時間割は次回の同期で確認します。','新展示期间的课表将在下一次同步时确认。','新展示期間的課表將在下一次同步時確認。','The new display period is awaiting the next timetable sync.')}</p>`:''}
      <div class="schedule-period" id="schedule-period" data-start="${period.start}" data-end="${period.end}"><strong>${period.terms.map(term=>monthLabel(term.start)+' — '+monthLabel(term.lastMonth)).join(' ＋ ')}</strong><span>${tr('毎年1月・4月・10月に自動切替。1〜3月は両期の授業を併せて表示','每年1月、4月、10月自动切换；1—3月同时显示两期课程','每年1月、4月、10月自動切換；1—3月同時顯示兩期課程','Automatically switches in January, April and October; both terms are shown together in January–March')}</span></div>
      <p class="schedule-legend"><span class="schedule-legend-swatch" aria-hidden="true"></span>${tr('淡い緑色：これから始まる授業（日本時間で自動更新）','浅色背景：尚未开始的课程（按日本时间自动更新）','淺色背景：尚未開始的課程（按日本時間自動更新）','Pale green: classes that have not started (updated in Japan time).')}</p>
      <div class="feed-controls">${['bio','chem'].map(g=>button(subject(g),state.scheduleGroup===g,'course-group',g)).join('')}<input id="course-query" type="search" value="${esc(state.scheduleQuery)}" aria-label="${tr('授業を検索','搜索课程','搜尋課程','Search courses')}" placeholder="${tr('科目名・クラス・内容で検索','搜索科目、班期或内容','搜尋科目、班期或內容','Search subjects, classes or topics')}"></div><div id="course-results" aria-live="polite"></div>`;
    $('course-query').oninput = e => {state.scheduleQuery=e.target.value;renderScheduleRows();};
    host.querySelectorAll('[data-course-group]').forEach(b=>b.onclick=()=>{state.scheduleGroup=b.dataset.courseGroup;renderSchedule();});
    renderScheduleRows();
    if(state.scheduleError)host.insertAdjacentHTML('beforeend',`<p class="feed-meta" data-feed-error="schedule">${tr('更新できませんでした。自動で再試行します。','课表暂时更新失败，正在自动重试。','課表暫時更新失敗，正在自動重試。','The timetable could not be refreshed. Retrying automatically.')}</p>`);
  }
  function courseSubject(course) {
    const original = String(course || '').trim().replace(/\s+/g,' ');
    const withoutTerm = original.replace(/^\d{2,4}年(?:\d{1,2}月期|春期|秋期|冬季)\s*/,'');
    const named = withoutTerm.match(/^(?:生物学|生物|化学|化)\s*(?:[-－—]\s*)?(.+)$/);
    const basic = withoutTerm.match(/^(?:生物学|化学)\s*(必修课程|入门课程)$/);
    let name = named ? named[1].trim() : basic ? basic[1] : original;
    if(!['入门课程','必修课程'].includes(name))name=name.replace(/课程$/,'');
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
    const data=feeds.schedule;
    const covered=data.source_type!=='rooms_schedule' || (data.coverage_start<=period.start && data.coverage_end>=period.end);
    const termRows=covered?data.items.filter(r=>r.date>=period.start && r.date<period.end):[];
    const rows = termRows.filter(r=>r.group===state.scheduleGroup && [q,canonicalQuery].some(query=>(r.course+' '+r.topic+' '+courseSubject(r.course)).toLowerCase().includes(query)));
    const grouped = new Map();
    rows.forEach(r => {const name=courseSubject(r.course);if(!grouped.has(name))grouped.set(name,[]);grouped.get(name).push(r);});
    const compareName = new Intl.Collator(({zh:'zh-CN',tw:'zh-TW',en:'en',ja:'ja'})[window.globalLang] || 'ja',{numeric:true});
    const groups = [...grouped].sort((a,b)=>compareName.compare(a[0],b[0]));
    groups.forEach(([,items])=>items.sort((a,b)=>a.date.localeCompare(b.date) || (a.start_time || '99:99').localeCompare(b.start_time || '99:99')));
    const weekdays = tr(['月','火','水','木','金','土','日'],['一','二','三','四','五','六','日'],['一','二','三','四','五','六','日'],['Mon','Tue','Wed','Thu','Fri','Sat','Sun']);
    const headers = [tr('日付','日期','日期','Date'),tr('時間','时间','時間','Time'),tr('クラス・開講期','原课程／班期','原課程／班期','Original course / term'),tr('授業内容','课程内容','課程內容','Topic')];
    const today = jstToday(), currentTime=Date.now();
    const noClasses=termRows.length ? empty() : `<p class="feed-empty">${!covered?tr('今期の時間割を確認中です。','正在等待本期课表同步。','正在等待本期課表同步。','Awaiting the timetable for this period.'):tr('今期の授業はまだ掲載されていません。元の時間割の更新後に自動表示されます。','本期暂无课程，排课表更新后会自动显示。','本期暫無課程，排課表更新後會自動顯示。','No classes are listed for this period yet. They will appear when the source timetable is updated.')}</p>`;
    $('course-results').innerHTML = `<p class="feed-meta">${tr('科目別','按科目分组','按科目分組','Grouped by subject')} · ${groups.length} ${tr('科目','门科目','門科目','subjects')} · ${rows.length} ${tr('授業','节课','節課','classes')}</p>` + (rows.length ? groups.map(([name,items],index)=>`<section class="course-subject-group" data-course-subject="${esc(name)}" aria-labelledby="course-subject-${index}"><div class="course-subject-heading"><h3 id="course-subject-${index}">${esc(name)}</h3><span>${items.length} ${tr('授業','节课','節課','classes')}</span></div><div class="feed-table-wrap"><table class="feed-table" aria-labelledby="course-subject-${index}"><thead><tr>${headers.map(t=>`<th scope="col">${t}</th>`).join('')}</tr></thead><tbody>${items.map(r=>`<tr data-course-date="${esc(r.date)}" data-course-start="${esc(r.start_time || '')}" data-course-status="${esc(r.status || 'scheduled')}" data-metadata-basis="${esc(r.metadata_basis || '')}"${isUpcomingCourse(r.date,r.start_time,currentTime,today)?' class="upcoming"':''}><td>${esc(r.date)} (${weekdays[r.weekday]})</td><td>${esc(r.start_time || '—')}${r.end_time?' – '+esc(r.end_time):''}</td><td>${esc(r.course)}</td><td class="course-topic">${esc(r.topic || '—')}</td></tr>`).join('')}</tbody></table></div></section>`).join('') : noClasses);
    $('course-results').querySelectorAll('tr[data-course-status="rescheduling"] td:nth-child(2)').forEach(cell=>{
      const badge=document.createElement('span');badge.className='course-adjustment';
      badge.textContent=tr('時間調整中','时间调整中','時間調整中','Time being rescheduled');
      cell.append(document.createElement('br'),badge);
    });
    $('course-results').querySelectorAll('tr[data-metadata-basis="plan_estimate"] .course-topic').forEach(cell=>{
      const label=document.createElement('span');label.className='course-plan-label';
      label.textContent=tr('当初予定','原计划','原計畫','Original plan');
      label.title=tr('授業内容は元の時間割の順序から推定しています。','课程内容按原排课顺序推定。','課程內容按原排課順序推定。','Topic inferred from the original timetable order.');
      cell.append(document.createElement('br'),label);
    });
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
    const resultSummary = row => typeof row.summary === 'string' ? row.summary : row.summary?.[window.globalLang || 'ja'] || row.summary?.zh || row.summary?.en || '';
    host.innerHTML = `<div class="feed-note">${tr('生物・化学・AI生命科学の新着論文を毎日追加。各論文の成果を原文の抄録に基づく2文で紹介し、原文へリンクします。','每天新增生物、生化、化学和 AI 生命科学论文，每篇以两句话介绍研究成果，依据原文摘要整理并附论文链接。','每天新增生物、生化、化學和 AI 生命科學論文，每篇以兩句話介紹研究成果，依據原文摘要整理並附論文連結。','New papers in biology, chemistry and AI for life sciences, with two-sentence result summaries based on the original abstracts and links to the papers.')}</div>
      <p class="feed-meta">${meta(data)} · Europe PMC / PubMed · ${data.items.length} ${tr('件','篇','篇','papers')}</p>
      <div class="feed-controls">${['all','biology','chemistry','ai'].map(c=>button(c==='all'?all():category(c),state.research===c,'research-category',c)).join('')}</div><div class="feed-grid">${data.items.filter(r=>state.research==='all'||r.category===state.research).map(r=>`<article class="feed-card"><span class="feed-tag">${category(r.category)}</span><h3>${link(r.url,r.title)}</h3><p class="feed-meta">${esc(r.source)}<br>${tr('発表','发表','發表','Published')}: ${esc(r.published_at)} · ${tr('掲載','收录','收錄','Added')}: ${esc(r.added_on)}</p>${resultSummary(r)?`<div class="research-result"><h4>${tr('研究成果','成果介绍','成果介紹','Research findings')}</h4><p>${esc(resultSummary(r))}</p></div>`:''}${link(r.url,tr('論文を読む','阅读论文','閱讀論文','Read paper'))}</article>`).join('')}</div>`;
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
  window.switchTab = function (name) {if(['timeline','calendar'].includes(name))name='application';if (!$(name)?.classList.contains('section')) name='home';oldTab(name);if(name==='schedule')refreshSchedulePeriod();if(name==='honor')refreshHonors();};
  if (location.hash === '#ai-advisor') history.replaceState(null,'','#home');

  async function fetchFeed(name, file, ready) {
    if(name==='honors')return refreshHonors();
    const requestedPeriod=name==='schedule'?schedulePeriod().key:'';
    if(name==='schedule'){
      if(state.scheduleRefreshPending)return;
      state.scheduleRefreshPending=true;
    }
    try {
      const response = await fetch(file,{cache:'no-cache',signal:AbortSignal.timeout(15000)});
      if (!response.ok) throw new Error('Snapshot unavailable');
      const data = await response.json();
      if (!data || !Array.isArray(data.items) || (!data.items.length && !(name==='schedule' && data.source_type==='rooms_schedule'))) throw new Error('Invalid snapshot');
      if(name==='schedule'){
        if(requestedPeriod!==schedulePeriod().key)return;
        if(data.source_type==='rooms_schedule' && (!data.last_success_at || !data.coverage_start || !data.coverage_end || !['ok','error'].includes(data.sync_status)))throw new Error('Invalid Rooms snapshot');
        const stale=data.source_type==='rooms_schedule' && (data.sync_status!=='ok' || Date.now()-Date.parse(data.last_success_at)>90*60000);
        const unchanged=!state.scheduleError && JSON.stringify(feeds.schedule)===JSON.stringify(data) && Boolean($('schedule-live').querySelector('[data-rooms-stale]'))===stale;
        state.scheduleLoadedPeriod=requestedPeriod;state.scheduleError=false;state.scheduleLastFetch=Date.now();
        if(unchanged)return;
      }
      const preserve=name==='schedule' && Boolean(feeds.schedule);
      const input=preserve && document.activeElement?.id==='course-query';
      const selection=input?[$('course-query').selectionStart,$('course-query').selectionEnd]:null;
      const position=preserve?[window.scrollX,window.scrollY]:null;
      feeds[name] = data; ready(data);
      if(input){$('course-query').focus({preventScroll:true});$('course-query').setSelectionRange(...selection);}
      if(position)window.scrollTo(...position);
    } catch (_) {
      if(name==='schedule'){
        if(requestedPeriod!==schedulePeriod().key)return;
        state.scheduleError=true;
        if(feeds.schedule){renderSchedule();return;}
        $('schedule-live').querySelectorAll('[data-feed-error="schedule"]').forEach(el=>el.remove());
      }
      const status = document.createElement('p');status.className='feed-meta';status.dataset.feedError=name;
      status.textContent=tr('更新データを取得できませんでした。しばらくしてから再度お試しください。','更新数据暂时无法读取，请稍后重试。','更新資料暫時無法讀取，請稍後重試。','Could not load updates. Please try again later.');
      if(name==='admissions'&&(window.DATA || []).length){renderAdmissions();return;}
      const hosts={honors:'honor',schedule:'schedule-live',research:'daily-research-content',admissions:'official-updates',applications:'application',students:'students-live'};
      $(hosts[name]).append(status);
    } finally {
      if(name==='schedule'){
        state.scheduleRefreshPending=false;
        if(requestedPeriod!==schedulePeriod().key)refreshSchedulePeriod();
      }
    }
  }
  document.addEventListener('DOMContentLoaded', function () {
    refreshNotices();
    refreshHonors();
    fetchFeed('schedule','schedule_data.json',renderSchedule);
    fetchFeed('students','students_data.json',renderStudents);
    fetchFeed('research','research_data.json',renderResearch);
    fetchFeed('applications','applications.json',data=>{window.DATA=data.items;if(window.buildSearchIndex)buildSearchIndex();renderAdmissions();});
    fetchFeed('admissions','admissions_updates.json',renderAdmissions);
  });
  setInterval(refreshSchedulePeriod,60000);
  setInterval(()=>{if(!document.hidden){refreshNotices();refreshHonors();refreshSchedulePeriod(true);}},300000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshSchedulePeriod(true);});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshNotices();});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshHonors();});
  window.addEventListener('pageshow',()=>refreshSchedulePeriod(true));
  window.addEventListener('pageshow',refreshNotices);
  window.addEventListener('pageshow',refreshHonors);
})();
