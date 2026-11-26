'use strict';

const form = document.querySelector('#form');
const byId = id => document.getElementById(id);
const defaults = Object.fromEntries([...new FormData(form)].map(([key, value]) => [key, Number(value)]));
const record = {
  concrete: { u: [18, '混凝土 Z 向位移'], s: [22, '混凝土 Z 向应力'] },
  tank: { u: [21, '加压水箱 Z 向位移'], s: [23, '加压水箱 Z 向应力'] },
};
const tabs = [...document.querySelectorAll('[data-view]')];
const views = new Set(tabs.map(button => button.dataset.view));

function selectView(view) {
  for (const button of tabs) {
    const selected = button.dataset.view === view;
    button.setAttribute('aria-pressed', selected);
    byId(button.dataset.view).hidden = !selected;
  }
}

function navigate(view) {
  selectView(view);
  const hash = '#' + view;
  if (location.hash !== hash) history.pushState(null, '', hash);
}

function syncViewFromHash() {
  const view = location.hash.slice(1) || 'cloud';
  if (views.has(view)) selectView(view);
}

function drawComparison() {
  const table = byId('comparison-table');
  const columns = [[], []];
  for (const row of table.tBodies[0].rows) {
    for (const [index, column] of columns.entries()) {
      const cell = row.cells[index + 1];
      const text = cell.textContent.trim();
      const value = Math.abs(Number(text.replace('−', '-')));
      column.push({ cell, text, value });
    }
  }

  const maxima = columns.map(column => Math.max(...column.map(point => point.value)));
  const scale = Math.max(...maxima) || 1;
  for (const column of columns) {
    for (const { cell, text, value } of column) {
      const track = document.createElement('span');
      track.className = 'compare-track';
      track.setAttribute('aria-hidden', 'true');
      const bar = document.createElement('span');
      bar.className = 'compare-bar';
      bar.style.width = (value / scale * 100) + '%';
      track.append(bar);
      const label = document.createElement('span');
      label.className = 'compare-value';
      label.textContent = text;
      cell.replaceChildren(track, label);
    }
  }
  for (const [index, id] of ['max32', 'max16'].entries()) {
    byId(id).textContent = String(maxima[index]);
  }
}

function drawLayout(parameters, matched) {
  const {count, length, width, diameter} = parameters;
  const intervals = count / 2;
  let horizontal = 1;
  let best = Infinity;
  for (let x = 1; x < intervals; x++) {
    const variation = Math.abs(length / x - width / (intervals - x));
    if (variation < best) {
      horizontal = x;
      best = variation;
    }
  }
  if (matched) horizontal = 10;
  const vertical = intervals - horizontal;
  const flange = byId('flange');
  flange.style.setProperty('--bolt-cap-x', (62 / horizontal) + 'cqw');
  flange.style.setProperty('--bolt-cap-y', (60 / vertical) + 'cqh');
  flange.querySelectorAll('.bolt').forEach(bolt => bolt.remove());
  const shortRatio = Math.min(length, width) / Math.max(length, width);
  flange.style.width = (length >= width ? 82 : Math.max(25, 82 * shortRatio)) + '%';
  flange.style.height = (width >= length ? 74 : Math.max(24, 74 * shortRatio * 1.6)) + '%';

  const place = (x, y) => {
    const bolt = document.createElement('span');
    bolt.className = 'bolt';
    bolt.style.left = (8 + 84 * x) + '%';
    bolt.style.top = (10 + 80 * y) + '%';
    flange.append(bolt);
  };
  for (let x = 0; x <= horizontal; x++) {
    place(x / horizontal, 0);
    place(x / horizontal, 1);
  }
  for (let y = 1; y < vertical; y++) {
    place(0, y / vertical);
    place(1, y / vertical);
  }
  const summary = count + ' 根 / 上下各 ' + (horizontal + 1) + ' 根 / 左右各 ' + (vertical - 1) + ' 根（不重复计角点）';
  byId('layout-summary').textContent = summary;
  byId('diagram').setAttribute('aria-label', summary);
  const note = matched ? '依据附件水箱正视图重画，孔位为示意。' : '以试件长宽比为参考，在矩形周边对称排布，并使长短边间距尽量接近。';
  byId('layout-note').textContent = note + ' 实际孔距、边距、预紧力及承载能力需结合水箱法兰尺寸和求解结果复核。';
  const largestPossibleSpacing = Math.min(length / horizontal, width / vertical);
  if (largestPossibleSpacing <= diameter) {
    byId('layout-note').textContent += ' 按输入试件尺寸估算，至少一侧的可用间距已不大于螺栓直径，请检查参数。';
  }
}

function updateContour() {
  const [asset, label] = record[byId('part').value][byId('quantity').value];
  const url = 'assets/image' + asset + '.png';
  const image = byId('contour');
  image.src = url;
  image.alt = 'Abaqus ' + label + '存档云图';
  byId('original').href = url;
  byId('image-link').href = url;
  byId('caption').textContent = label;
}

function submitParameters(goToResult) {
  const parameters = Object.fromEntries([...new FormData(form)].map(([key, value]) => [key, Number(value)]));
  if (parameters.crackL > parameters.length || parameters.crackH > parameters.depth || parameters.crackW > parameters.width) {
    byId('form-note').textContent = '请检查裂缝尺寸，裂缝各方向应在试件尺寸范围内。';
    return;
  }
  const difference = Object.keys(defaults).filter(key => defaults[key] !== parameters[key]);
  const matched = difference.length === 0;
  byId('subtitle').textContent = parameters.count + ' 根螺栓 / ' + parameters.pressure + ' MPa' + (matched ? ' / jieguo2' : ' / 自定义工况');
  byId('badge').textContent = matched ? '已匹配存档' : '待求解';
  byId('badge').classList.toggle('pending', !matched);
  for (const id of ['figure', 'source', 'part', 'quantity', 'image-link']) {
    const element = byId(id);
    if (element.tagName === 'SELECT') element.disabled = !matched;
    else element.hidden = !matched;
  }
  byId('empty').hidden = matched;
  byId('empty-text').textContent = '已生成周边对称布置。该参数组合需要在 Abaqus 中重新建模或求解，才能得到应力和位移云图。';
  byId('form-note').textContent = matched ? '已匹配基准工况。C40 混凝土，底端固定。' : '已生成候选布置，可查看测点对比作为参考。';
  drawLayout(parameters, matched);
  if (goToResult) {
    const view = matched ? 'cloud' : 'layout';
    navigate(view);
    const resultTabs = byId('results').querySelector('.tabs');
    const activeTab = tabs.find(button => button.dataset.view === view);
    if (resultTabs.getBoundingClientRect().bottom < 0) {
      resultTabs.scrollIntoView({ block: 'start' });
      activeTab.focus({ preventScroll: true });
    }
  }
}

form.addEventListener('input', () => {
  byId('form-note').textContent = '参数已修改。提交后更新布置与结果。';
});
form.addEventListener('submit', event => {
  event.preventDefault();
  submitParameters(true);
});
byId('reset').addEventListener('click', () => {
  form.reset();
  byId('part').value = 'concrete';
  byId('quantity').value = 'u';
  updateContour();
  submitParameters(true);
});
for (const id of ['part', 'quantity']) byId(id).addEventListener('change', updateContour);
for (const button of tabs) button.addEventListener('click', () => navigate(button.dataset.view));
byId('show-layout').addEventListener('click', () => navigate('layout'));
window.addEventListener('hashchange', syncViewFromHash);
drawComparison();
submitParameters(false);
syncViewFromHash();
