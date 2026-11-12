/* The directory is rendered as static HTML; filtering never depends on a feed. */
(function () {
  'use strict';

  var subject = null;
  var selected = Object.create(null);
  var initialized = false;
  var searchText = new WeakMap();

  function readSetting(key) {
    try { return localStorage.getItem(key); } catch (_) { return null; }
  }
  function writeSetting(key, value) {
    try { localStorage.setItem(key, value); } catch (_) { /* Browsing still works. */ }
  }
  function normalize(value) {
    return String(value || '').normalize('NFKC').toLowerCase().replace(/\s+/g, ' ').trim();
  }
  function directory() {
    var root = document.getElementById('research');
    if (!root) return null;
    var fields = Array.from(root.querySelectorAll('#research-content > .research-field[data-field][data-subject]'));
    if (!fields.length) return null;
    return {root: root, fields: fields, input: root.querySelector('#research-lab-query')};
  }
  function fieldFor(data, id) {
    return data.fields.find(function (field) { return field.dataset.field === id; });
  }
  function initializeState(data) {
    var subjects = Array.from(new Set(data.fields.map(function (field) { return field.dataset.subject; })));
    if (subjects.indexOf(subject) === -1) {
      var savedMain = readSetting('researchMain');
      subject = subjects.indexOf(savedMain) !== -1 ? savedMain : subjects[0];
    }
    subjects.forEach(function (name) {
      var candidates = data.fields.filter(function (field) { return field.dataset.subject === name; });
      var saved = selected[name] || readSetting('researchFilter-' + name) || readSetting('researchFilter');
      selected[name] = candidates.some(function (field) { return field.dataset.field === saved; }) ? saved : candidates[0].dataset.field;
    });
  }
  function currentLanguage() {
    var classes = document.body.classList;
    return ['zh', 'tw', 'ja', 'en'].find(function (lang) { return classes.contains('lang-' + lang); }) || 'ja';
  }
  function updateCount(data, count, total, searching) {
    var output = data.root.querySelector('#research-match-count');
    if (!output) return;
    var lang = currentLanguage();
    var messages = {
      zh: (searching ? '全目录匹配 ' : '当前显示 ') + count + ' 个研究室 · 共 ' + total + ' 个',
      tw: (searching ? '全目錄符合 ' : '目前顯示 ') + count + ' 個研究室 · 共 ' + total + ' 個',
      ja: (searching ? '全分野の検索結果：' : '表示中：') + count + ' 研究室 / 全 ' + total + ' 研究室',
      en: (searching ? 'Directory matches: ' : 'Showing ') + count + (count === 1 ? ' lab' : ' labs') + ' · ' + total + ' total'
    };
    output.dataset.count = String(count);
    output.dataset.total = String(total);
    output.setAttribute('role', 'status');
    output.setAttribute('aria-live', 'polite');
    Object.keys(messages).forEach(function (key) {
      var span = output.querySelector('.lang-text[data-lang="' + key + '"]');
      if (!span) {
        span = document.createElement('span');
        span.className = 'lang-text';
        span.dataset.lang = key;
        output.appendChild(span);
      }
      span.textContent = messages[key];
      span.style.display = key === lang ? '' : 'none';
    });
  }
  function render() {
    var data = directory();
    if (!data) return;
    initializeState(data);
    var query = normalize(data.input && data.input.value);
    var tokens = query ? query.split(' ') : [];
    var count = 0;
    var total = 0;
    data.root.classList.toggle('research-searching', Boolean(query));
    data.root.querySelectorAll('.research-main-tab[data-rmt]').forEach(function (button) {
      var active = !query && button.dataset.rmt === subject;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    data.root.querySelectorAll('.research-filter-btn[data-rf]').forEach(function (button) {
      var field = fieldFor(data, button.dataset.rf);
      var active = !query && field && field.dataset.subject === subject && button.dataset.rf === selected[subject];
      button.classList.toggle('active', Boolean(active));
      button.setAttribute('aria-pressed', String(Boolean(active)));
    });
    data.root.querySelectorAll('[id^="research-"][id$="-filters"]').forEach(function (group) {
      var show = group.id === 'research-' + subject + '-filters';
      group.hidden = !show;
      group.style.display = show ? 'flex' : 'none';
    });
    data.fields.forEach(function (field) {
      var inCategory = field.dataset.subject === subject && field.dataset.field === selected[subject];
      var matches = 0;
      field.querySelectorAll('.research-card').forEach(function (card) {
        total += 1;
        if (!searchText.has(card)) {
          var title = field.querySelector('.research-field-title');
          searchText.set(card, normalize((card.dataset.search || '') + ' ' + card.textContent + ' ' + (title ? title.textContent : '')));
        }
        var visible = query ? tokens.every(function (token) { return searchText.get(card).includes(token); }) : inCategory;
        card.hidden = !visible;
        card.style.display = visible ? '' : 'none';
        if (visible) matches += 1;
      });
      var visible = query ? matches > 0 : inCategory;
      field.hidden = !visible;
      field.style.display = visible ? 'block' : 'none';
      if (visible) count += matches;
    });
    var empty = data.root.querySelector('#research-empty');
    if (empty) {
      empty.hidden = count !== 0;
      empty.style.display = count === 0 ? 'block' : 'none';
    }
    updateCount(data, count, total, Boolean(query));
  }

  window.switchResearchMain = function (name) {
    var data = directory();
    if (!data || !data.fields.some(function (field) { return field.dataset.subject === name; })) return;
    initializeState(data);
    subject = name;
    writeSetting('researchMain', subject);
    if (data.input) data.input.value = '';
    render();
  };
  window.filterResearch = function (id) {
    var data = directory();
    if (!data) return;
    var field = fieldFor(data, id);
    if (!field) return;
    initializeState(data);
    subject = field.dataset.subject;
    selected[subject] = id;
    writeSetting('researchMain', subject);
    writeSetting('researchFilter-' + subject, id);
    if (data.input) data.input.value = '';
    render();
  };
  function initialize() {
    var data = directory();
    if (!data) return;
    if (!initialized) {
      initialized = true;
      if (data.input) {
        data.input.addEventListener('input', render);
        data.input.addEventListener('search', render);
        data.input.addEventListener('keydown', function (event) {
          if (event.key === 'Escape') { data.input.value = ''; render(); }
        });
      }
      // Existing markup can keep its inline handlers; generated markup need not.
      data.root.addEventListener('click', function (event) {
        var button = event.target.closest('.research-main-tab[data-rmt], .research-filter-btn[data-rf]');
        if (!button || !data.root.contains(button) || button.hasAttribute('onclick')) return;
        if (button.dataset.rmt) window.switchResearchMain(button.dataset.rmt);
        else window.filterResearch(button.dataset.rf);
      });
    }
    render();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
  else initialize();
  window.addEventListener('pageshow', initialize);
}());
