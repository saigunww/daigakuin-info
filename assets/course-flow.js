/* Annual course preparation plans from the course PDFs. */
(function () {
  'use strict';
  const LANGUAGES = ['ja', 'zh', 'tw', 'en'];
  const panels = Array.from(document.querySelectorAll('[data-course-flow]'));
  if (!panels.length) return;
  let template;
  let renderedYear;
  let refreshPending = false;
  const escapeHTML = value => String(value).replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);
  function language() {
    return typeof globalLang === 'string' && LANGUAGES.includes(globalLang) ? globalLang : 'ja';
  }
  function localized(values, dateRange = false) {
    const active = language();
    return LANGUAGES.map(lang => '<span class="lang-text" data-lang="' + lang + '"' +
      (lang === active ? '' : ' style="display:none"') + '>' +
      (dateRange ? escapeHTML(values[lang]).replace('～', '～<br>').replace(' – ', ' – <br>') :
        escapeHTML(values[lang])) + '</span>').join('');
  }
  function entryYear() {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'Asia/Tokyo', year: 'numeric', month: 'numeric'
    }).formatToParts(new Date());
    const value = type => Number(parts.find(part => part.type === type).value);
    return Math.max(template.base_entry_year, value('year') + (value('month') >= 4 ? 1 : 0));
  }
  function pointText(point, year, lang) {
    const actual = year + point.year_offset;
    if (lang === 'en') {
      const month = new Intl.DateTimeFormat('en-US', {month: 'long', timeZone: 'UTC'})
        .format(new Date(Date.UTC(actual, point.month - 1, 1)));
      return (point.part === 'late' ? 'Late ' : '') + month + ' ' + actual;
    }
    return actual + '年' + point.month + '月' + (point.part === 'late' ? '下旬' : '');
  }
  function timingText(timing, year) {
    return Object.fromEntries(LANGUAGES.map(lang => [lang,
      pointText(timing.start, year, lang) + (timing.end ?
        (lang === 'en' ? ' – ' : '～') + pointText(timing.end, year, lang) : '')]));
  }
  function valid(data) {
    return data && data.base_entry_year === 2027 && data.rollover?.timezone === 'Asia/Tokyo' &&
      data.rollover.month === 4 && data.rollover.day === 1 &&
      ['bio', 'chem'].every(course => data.source_documents?.[course]?.file) &&
      Array.isArray(data.items) && data.items.length === 2 &&
      data.items.every((cycle, index) => cycle.id === ['summer', 'winter'][index] &&
        LANGUAGES.every(lang => typeof cycle.title?.[lang] === 'string') &&
        cycle.stages?.length === 6 && cycle.stages.every(step =>
          LANGUAGES.every(lang => typeof step.title?.[lang] === 'string') &&
          Array.isArray(step.details) && step.details.length &&
          step.details.every(detail => LANGUAGES.every(lang => typeof detail[lang] === 'string')) &&
          step.timing?.start && Object.values(step.timing).every(point =>
            Number.isInteger(point.year_offset) && point.year_offset >= -2 && point.year_offset <= 0 &&
            Number.isInteger(point.month) && point.month >= 1 && point.month <= 12 &&
            (!point.part || point.part === 'late'))));
  }
  function render(source) {
    const year = entryYear();
    for (const panel of panels) {
      const course = panel.dataset.courseFlow;
      const badge = localized({ja: year + '年度入学', zh: year + '年度入学',
        tw: year + '年度入學', en: year + ' Entry'});
      let html = '<p class="course-flow-year">' + badge + '</p>';
      for (const cycle of template.items) {
        html += '<section class="info-card course-flow-card" data-flow-cycle="' + cycle.id +
          '"><h3>' + localized(cycle.title) + '</h3><ol class="exam-flow">';
        for (const step of cycle.stages) {
          html += '<li class="exam-flow-step" data-flow-stage="' + escapeHTML(step.id) +
            '"><div class="exam-flow-head"><div class="exam-flow-icon" aria-hidden="true">' +
            escapeHTML(step.icon) + '</div><div class="exam-flow-heading"><h4 class="exam-flow-title">' +
            localized(step.title) + '</h4><div class="exam-flow-date">' +
            localized(timingText(step.timing, year), true) + '</div></div></div><ul class="exam-flow-desc">';
          html += step.details.map(detail => '<li>' + localized(detail) + '</li>').join('');
          html += '</ul></li>';
        }
        html += '</ol></section>';
      }
      const file = template.source_documents[course].file;
      html += '<p class="course-flow-source">' + localized({ja: '出典：' + file + ' 8–9ページ',
        zh: '来源：' + file + ' 第8–9页', tw: '來源：' + file + ' 第8–9頁',
        en: 'Source: ' + file + ', pages 8–9'}) + '</p>';
      panel.innerHTML = html;
      panel.dataset.entryYear = String(year);
      panel.dataset.flowSource = source || panel.dataset.flowSource || 'inline';
    }
    renderedYear = year;
    if (typeof buildSearchIndex === 'function') buildSearchIndex();
  }
  async function refresh() {
    if (refreshPending) return;
    refreshPending = true;
    try {
      const response = await fetch('course_flow_data.json', {cache: 'no-store'});
      if (!response.ok) throw new Error('Course flow source unavailable');
      const data = await response.json();
      if (!valid(data)) throw new Error('Invalid course flow source');
      template = data;
      // Relative year fields remain unchanged in the feed. Compute from Tokyo
      // time even when the server's entry_year still belongs to the prior cycle.
      render('feed');
    } catch (_) {
      // The full, source-verified template remains in the HTML on fetch failure.
    } finally {
      refreshPending = false;
    }
  }
  function checkYear() {
    if (entryYear() !== renderedYear) {
      render();
      refresh();
    }
  }
  try {
    template = JSON.parse(document.getElementById('course-flow-baseline').textContent);
    if (!valid(template)) return;
    render('inline');
  } catch (_) { return; }
  refresh();
  window.addEventListener('pageshow', checkYear);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') checkYear();
  });
  function scheduleCheck() {
    setTimeout(() => { checkYear(); scheduleCheck(); }, 60000 - Date.now() % 60000 + 50);
  }
  scheduleCheck();
}());
