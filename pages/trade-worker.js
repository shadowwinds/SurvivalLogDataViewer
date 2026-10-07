"use strict";
globalThis.window = globalThis;
importScripts("cooking.js", "trade.js");
self.onmessage = event => {
  const request = event.data;
  try { self.postMessage({job: request.job, rows: Trade.processing(request.model, request.basket, request.input)}); }
  catch { self.postMessage({job: request.job, error: true}); }
};
