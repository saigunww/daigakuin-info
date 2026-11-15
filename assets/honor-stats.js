/* Aggregate admission results only; poster counts are not admission counts. */
(function () {
  'use strict';

  const SUBJECTS = ['all', 'bio', 'chem', 'ai-research', 'other'];
  const tr = (ja, zh, tw, en) => ({ja, zh, tw, en}[window.globalLang || 'ja'] || ja);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[character]));
  const isCount = value => Number.isSafeInteger(value) && value >= 0;
  const number = value => new Intl.NumberFormat({ja:'ja-JP', zh:'zh-CN', tw:'zh-TW', en:'en-US'}[window.globalLang || 'ja'] || 'ja-JP').format(value);
  const subjectLabel = value => ({
    all: tr('全分野', '全部学科', '全部學科', 'All subjects'),
    bio: tr('生物学', '生物学', '生物學', 'Biology'),
    chem: tr('化学', '化学', '化學', 'Chemistry'),
    'ai-research': tr('研究経験強化', '科研背景提升', '科研背景提升', 'Research experience'),
    other: tr('その他', '其他', '其他', 'Other')
  }[value]);
  const yearLabel = value => value === 'all'
    ? tr('全年度', '全部年度', '全部年度', 'All years')
    : value === '未分年度'
      ? tr('入学年度未確認', '入学年度待确认', '入學年度待確認', 'Entry year unconfirmed')
      : tr(value + '年度', value + '年度', value + '年度', value);

  function bucket(value) {
    if (!value || !isCount(value.total) || !Array.isArray(value.universities)) return null;
    const schools = new Map();
    for (const item of value.universities) {
      if (!item || typeof item.name !== 'string' || !item.name.trim() || !isCount(item.count)) return null;
      const name = item.name.trim();
      schools.set(name, (schools.get(name) || 0) + item.count);
      if (!isCount(schools.get(name))) return null;
    }
    const universities = Array.from(schools, ([name, count]) => ({name, count})).filter(item => item.count > 0);
    if (universities.reduce((sum, item) => sum + item.count, 0) !== value.total) return null;
    return {total:value.total, universities};
  }

  function readStatistics(data, subject) {
    const statistics = data?.statistics;
    if (!statistics || statistics.schema_version !== 1 || statistics.counting_unit !== 'offers' ||
        !Array.isArray(statistics.years) || !isCount(statistics.unassigned_total) ||
        (statistics.pending_review_total !== undefined && !isCount(statistics.pending_review_total))) return null;
    const years = [], seen = new Set();
    let unassigned = null;
    for (const row of statistics.years) {
      if (!row || typeof row.year !== 'string' || (!/^\d{4}$/.test(row.year) && row.year !== '未分年度') || seen.has(row.year)) return null;
      if (row.pending_review !== undefined && !isCount(row.pending_review)) return null;
      seen.add(row.year);
      const aggregate = bucket(row);
      const selected = subject === 'all' ? aggregate : bucket(row.by_subject?.[subject]);
      if (!aggregate || !selected || selected.total > aggregate.total) return null;
      if (row.year === '未分年度') unassigned = selected;
      else years.push({year:row.year, ...selected});
    }
    years.sort((a, b) => a.year.localeCompare(b.year));
    return {years, unassigned, unassignedTotal:statistics.unassigned_total, pendingReviewTotal:statistics.pending_review_total || 0};
  }

  function combine(years) {
    const schools = new Map();
    let total = 0;
    for (const year of years) {
      total += year.total;
      for (const item of year.universities) schools.set(item.name, (schools.get(item.name) || 0) + item.count);
    }
    if (!isCount(total)) return null;
    return {total, universities:Array.from(schools, ([name, count]) => ({name, count}))};
  }

  function updatedAt(value) {
    const date = new Date(value || '');
    if (Number.isNaN(date.getTime())) return '';
    const locale = {ja:'ja-JP', zh:'zh-CN', tw:'zh-TW', en:'en-GB'}[window.globalLang || 'ja'] || 'ja-JP';
    const label = new Intl.DateTimeFormat(locale, {timeZone:'Asia/Tokyo', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hourCycle:'h23'}).format(date);
    return `<p class="honor-stats-updated">${tr('データ更新', '数据更新', '資料更新', 'Data updated')} <time datetime="${esc(date.toISOString())}">${esc(label)} JST</time></p>`;
  }

  function unavailable(mount) {
    mount.innerHTML = `<section class="honor-stats honor-stats-unavailable" aria-label="${tr('年度別合格実績', '年度合格统计', '年度合格統計', 'Annual admission results')}"><h3>${tr('年度別合格実績', '年度合格统计', '年度合格統計', 'Annual admission results')}</h3><p>${tr('集計データを準備しています。合格実績は下の一覧からご覧いただけます。', '统计数据准备中，可先查看下方合格榜。', '統計資料準備中，可先查看下方合格榜。', 'Statistics are being prepared. You can view the admission results below.')}</p></section>`;
  }

  window.validateHonorStatistics = function (statistics) {
    try {
      return SUBJECTS.every(subject => readStatistics({statistics}, subject) !== null);
    } catch (_) {
      return false;
    }
  };

  window.renderHonorStats = function (mount, data, state) {
    if (!mount || typeof mount.innerHTML !== 'string') return;
    const subject = SUBJECTS.includes(state?.subject) ? state.subject : 'all';
    const selectedYear = String(state?.year || 'all');
    const statistics = readStatistics(data, subject);
    if (!statistics) {unavailable(mount); return;}
    const isUnassigned = selectedYear === '未分年度';
    const selection = isUnassigned
      ? statistics.unassigned || (subject === 'all' ? {total:statistics.unassignedTotal, universities:null} : null)
      : selectedYear === 'all' ? combine(statistics.years)
        : statistics.years.find(row => row.year === selectedYear) || {total:0, universities:[]};
    const universities = selection?.universities?.slice().sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'ja')) || null;
    const maxYear = Math.max(1, ...statistics.years.map(row => row.total));
    const maxSchool = universities?.length ? Math.max(...universities.map(row => row.count)) : 1;
    const countLabel = tr('合格件数', '合格份数', '合格份數', 'Admission offers');
    const universitiesLabel = tr('合格先の大学数', '合格大学数', '合格大學數', 'Universities');
    const chartDescription = tr('入学年度ごとの合格件数。年度を選ぶと、その年度の大学別実績を表示します。', '按入学年度展示合格份数。选择年度，可查看当年各大学的合格情况。', '按入學年度展示合格份數。選擇年度，可查看當年各大學的合格情況。', 'Admission offers by entry year. Select a year to see its university breakdown.');
    const pendingLabel = tr('未確認', '待确认', '待確認', 'Unconfirmed');
    const scope = `${yearLabel(selectedYear)} · ${subjectLabel(subject)}`;
    const schoolTitle = tr('大学別の合格実績', '各大学合格统计', '各大學合格統計', 'Offers by university');
    const noSchoolRecords = !selection
      ? tr('年度未確認の記録は、分野別集計を準備中です。', '待确认年度的分科统计暂不可用。', '待確認年度的分科統計暫不可用。', 'Subject statistics for unconfirmed entry years are not yet available.')
      : universities === null
        ? tr('入学年度を確認後、大学別の集計に反映します。', '确认入学年度后，将归入对应年度的大学统计。', '確認入學年度後，將歸入對應年度的大學統計。', 'These offers will appear in the university breakdown after their entry years are confirmed.')
        : tr('この条件に該当する合格記録はありません。', '当前条件下暂无合格记录。', '目前條件下暫無合格紀錄。', 'No admission offers match this selection.');

    mount.innerHTML = `<section class="honor-stats" aria-labelledby="honor-stats-title">
      <div class="honor-stats-heading">
        <div class="honor-stats-intro"><p class="honor-stats-kicker">${tr('入学年度別の実績', '按入学年度统计', '按入學年度統計', 'Results by entry year')}</p><h3 id="honor-stats-title">${tr('年度別合格実績', '年度合格统计', '年度合格統計', 'Annual admission results')}</h3><p class="honor-stats-scope">${esc(scope)}</p></div>
        <dl class="honor-stats-summary" aria-label="${esc(scope)}"><div><dt>${countLabel}</dt><dd data-honor-stat="total" data-value="${selection ? selection.total : ''}">${selection ? number(selection.total) : '—'}</dd></div><div><dt>${universitiesLabel}</dt><dd data-honor-stat="universities" data-value="${universities ? universities.length : ''}">${universities ? number(universities.length) : '—'}</dd></div></dl>
      </div>
      <div class="honor-stats-charts">
        <div class="honor-stats-chart honor-stats-annual"><h4 id="honor-stats-annual-title">${tr('年度ごとの合格件数', '历年合格份数', '歷年合格份數', 'Offers by entry year')}</h4><p class="honor-stats-description" id="honor-stats-annual-description">${chartDescription}</p>
          ${statistics.years.length ? `<div class="honor-stats-years-scroll"><ol class="honor-stats-years" style="--honor-year-count:${statistics.years.length}" aria-labelledby="honor-stats-annual-title" aria-describedby="honor-stats-annual-description">${statistics.years.map(row => `<li><button type="button" class="honor-stats-year${selectedYear === row.year ? ' is-selected' : ''}" data-honor-stat-year="${esc(row.year)}" data-count="${row.total}" aria-pressed="${selectedYear === row.year}" aria-label="${esc(yearLabel(row.year) + ' · ' + countLabel + ' ' + number(row.total))}"><span class="honor-stats-year-count">${number(row.total)}</span><span class="honor-stats-year-plot" aria-hidden="true"><span class="honor-stats-year-bar" style="height:${(row.total / maxYear * 100).toFixed(3)}%"></span></span><span class="honor-stats-year-label">${esc(row.year)}</span></button></li>`).join('')}</ol></div>` : `<p class="honor-stats-empty">${tr('入学年度を確認できた合格記録はまだありません。', '暂无已确认入学年度的合格记录。', '暫無已確認入學年度的合格紀錄。', 'There are no offers with confirmed entry years yet.')}</p>`}
        </div>
        <div class="honor-stats-chart honor-stats-universities"><div class="honor-stats-chart-heading"><h4 id="honor-stats-universities-title">${schoolTitle}</h4><span>${esc(yearLabel(selectedYear))}</span></div>
          ${universities?.length ? `<div class="honor-stats-school-scroll" tabindex="0" role="region" aria-labelledby="honor-stats-universities-title"><ol class="honor-stats-school-list">${universities.map(row => `<li data-honor-stat-university="${esc(row.name)}" data-count="${row.count}"><div class="honor-stats-school-label"><span>${esc(row.name)}</span><strong>${number(row.count)}</strong></div><div class="honor-stats-school-track" aria-hidden="true"><span style="width:${(row.count / maxSchool * 100).toFixed(3)}%"></span></div></li>`).join('')}</ol></div>` : `<p class="honor-stats-empty">${noSchoolRecords}</p>`}
        </div>
      </div>
      ${statistics.unassignedTotal > 0 ? `<p class="honor-stats-unassigned"><span>${pendingLabel}</span>${tr('ほかに入学年度未確認の合格が ' + number(statistics.unassignedTotal) + ' 件あり、上の年度別グラフには含めていません。', '另有 ' + number(statistics.unassignedTotal) + ' 份合格结果待确认入学年度，未计入上方年度图表。', '另有 ' + number(statistics.unassignedTotal) + ' 份合格結果待確認入學年度，未計入上方年度圖表。', number(statistics.unassignedTotal) + ' additional offers have unconfirmed entry years and are excluded from the annual chart.')}</p>` : ''}
      ${statistics.pendingReviewTotal > 0 ? `<p class="honor-stats-review">${tr('全年度を通じて、確認待ちのポスターが ' + number(statistics.pendingReviewTotal) + ' 枚あり、合格件数には追加していません。', '全库另有 ' + number(statistics.pendingReviewTotal) + ' 张海报待核对，未额外计数。', '全庫另有 ' + number(statistics.pendingReviewTotal) + ' 張海報待核對，未額外計數。', number(statistics.pendingReviewTotal) + ' posters across all years await verification and have not been counted as extra offers.')}</p>` : ''}
      <div class="honor-stats-footer"><p>${tr('確認できた合格を入学年度ごとに集計。同一の合格に関する表の重複記録や重複ポスターはまとめ、複数大学・異なる研究科への合格はそれぞれ計上します。集計値のみを表示しています。', '按入学年度统计已确认的合格份数；同一录取的跨表记录与重复海报合并，多校或不同研究科的录取分别计入。仅展示汇总数据。', '按入學年度統計已確認的合格份數；同一錄取的跨表紀錄與重複海報合併，多校或不同研究科的錄取分別計入。僅展示彙總資料。', 'Counts are confirmed admission offers grouped by entry year. Duplicate records across tables and posters are merged; offers from different universities or graduate schools count separately. Only aggregate data is shown.')}</p>${updatedAt(data?.updated_at)}</div>
    </section>`;
    mount.querySelectorAll('[data-honor-stat-year]').forEach(button => {
      button.addEventListener('click', () => {
        if (typeof window.switchHonorYear !== 'function') return;
        const year = button.dataset.honorStatYear;
        const restoreFocus = document.activeElement === button;
        window.switchHonorYear(year);
        if (restoreFocus) {
          const currentMount = mount.isConnected ? mount : document.getElementById(mount.id);
          currentMount?.querySelector(`[data-honor-stat-year="${year}"]`)?.focus({preventScroll:true});
        }
      });
    });
  };
})();
