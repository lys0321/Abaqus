'use strict';

(() => {
  const byId = id => document.getElementById(id);
  const part = byId('part');
  const quantity = byId('quantity');
  const contour = byId('contour');
  const dialog = byId('plot-dialog');
  const expand = byId('expand-plot');
  const viewerImage = byId('viewer-image');
  const viewerCaption = byId('viewer-caption');

  // These endpoints are transcribed from the legends of the unmodified source images.
  const ranges = {
    concrete: {
      u: { min: '−0.1870', max: '+0.02932' }, // image18.png
      s: { min: '−48.38', max: '+25.95' }, // image22.png
    },
    tank: {
      u: { min: '−0.1770', max: '+0.2419' }, // image21.png
      s: { min: '−1277', max: '+1211' }, // image23.png
    },
  };
  const variables = {
    u: { symbol: 'U3', unit: 'mm' },
    s: { symbol: 'S33', unit: 'MPa' },
  };

  function updateLegend() {
    const range = ranges[part.value][quantity.value];
    const variable = variables[quantity.value];
    byId('range-min').textContent = range.min;
    byId('range-max').textContent = range.max;
    byId('range-unit').textContent = variable.unit;
    byId('quantity-symbol').textContent = variable.symbol;
  }

  expand.addEventListener('click', () => {
    if (byId('figure').hidden || dialog.open) return;
    viewerImage.src = contour.src;
    viewerImage.alt = contour.alt;
    viewerCaption.textContent = byId('caption').textContent;
    dialog.showModal();
    byId('close-viewer').focus();
  });
  dialog.addEventListener('close', () => {
    expand.focus({ preventScroll: true });
  });
  part.addEventListener('change', updateLegend);
  quantity.addEventListener('change', updateLegend);
  byId('reset').addEventListener('click', updateLegend);
  updateLegend();
})();
