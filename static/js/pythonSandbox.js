// SPDX-License-Identifier: AGPL-3.0-or-later
// `B1474`. The runner inside static/python-sandbox.html — an opaque-origin
// frame. Python runs in a Worker the frame starts, so a block that never ends
// blocks that thread and not the page: Chromium runs a sandboxed frame on its
// parent's thread, and an in-frame `while True` froze the whole app before the
// timeout could fire. The page stops a run that overstays by removing the
// frame, which ends the worker with it. Pyodide loads once per worker; the code
// arrives as a value (`globals.set`), never spliced into Python source.
(function () {
  'use strict';

  var indexURL = new URL('static/lib/pyodide/', location.href).href;

  function workerMain(INDEX) {
    /* global importScripts, loadPyodide */
    try {
      importScripts(INDEX + 'pyodide.js');
    } catch (e) {
      // Vendored, so this is a missing file rather than a network problem,
      // and the sentence says which: nobody guesses the fix from "failed".
      self.postMessage({ type: 'failed', error: 'Pyodide is not installed. Expected it at '
        + '/static/lib/pyodide/ — run scripts/fetch-pyodide.py to vendor it.' });
      return;
    }
    var WRAPPER = [
      'import sys, io, traceback',
      '_out, _err = io.StringIO(), io.StringIO()',
      'sys.stdout, sys.stderr = _out, _err',
      'try:',
      '    exec(_pantheon_code, {"__name__": "__main__"})',
      'except BaseException:',
      '    traceback.print_exc()',
      'finally:',
      '    sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__',
      '(_out.getvalue(), _err.getvalue())',
    ].join('\n');
    var py = null;
    var loading = null;
    function load() {
      if (py) return Promise.resolve(py);
      if (!loading) loading = loadPyodide({ indexURL: INDEX }).then(function (p) { py = p; return p; });
      return loading;
    }
    self.onmessage = function (e) {
      var msg = e.data || {};
      if (msg.type !== 'run' || typeof msg.code !== 'string') return;
      load().then(function (p) {
        self.postMessage({ type: 'started', id: msg.id });
        p.globals.set('_pantheon_code', msg.code);
        return p.runPythonAsync(WRAPPER);
      }).then(function (out) {
        var pair = out.toJs();
        if (out.destroy) out.destroy();
        self.postMessage({ type: 'result', id: msg.id,
                           stdout: String(pair[0] || ''), stderr: String(pair[1] || '') });
      }).catch(function (err) {
        self.postMessage({ type: 'result', id: msg.id, error: String((err && err.message) || err) });
      });
    };
  }

  var source = '(' + workerMain.toString() + ')(' + JSON.stringify(indexURL) + ');';
  var worker = new Worker(URL.createObjectURL(new Blob([source], { type: 'text/javascript' })));
  worker.onmessage = function (e) { window.parent.postMessage(e.data, '*'); };
  worker.onerror = function (e) {
    window.parent.postMessage({ type: 'failed', error: String((e && e.message) || 'The Python worker failed to start.') }, '*');
  };

  window.addEventListener('message', function (e) {
    if (e.source !== window.parent) return;
    var msg = e.data || {};
    if (msg.type === 'run' && typeof msg.code === 'string') worker.postMessage(msg);
  });

  window.parent.postMessage({ type: 'ready' }, '*');
})();
