(function () {
  const PDFJS_SRC  = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js';
  const WORKER_SRC = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  async function renderViewer(container) {
    var src = container.dataset.src;
    var pdf = await pdfjsLib.getDocument(src).promise;

    for (var i = 1; i <= pdf.numPages; i++) {
      var page = await pdf.getPage(i);
      var base = page.getViewport({ scale: 1 });
      var containerWidth = container.clientWidth || 900;
      var scale = (containerWidth / base.width) * 3.5; // 3.5× for sharp retina
      var viewport = page.getViewport({ scale: scale });

      var canvas = document.createElement('canvas');
      canvas.width  = viewport.width;
      canvas.height = viewport.height;

      await page.render({ canvasContext: canvas.getContext('2d'), viewport: viewport }).promise;
      container.appendChild(canvas);
    }
  }

  document.addEventListener('DOMContentLoaded', async function () {
    var viewers = document.querySelectorAll('.pdf-viewer');
    if (!viewers.length) return;

    await loadScript(PDFJS_SRC);
    pdfjsLib.GlobalWorkerOptions.workerSrc = WORKER_SRC;

    for (var v of viewers) {
      await renderViewer(v);
    }
  });
})();
