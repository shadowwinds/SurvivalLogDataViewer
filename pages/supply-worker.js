"use strict";
const window = self;
importScripts("cooking.js", "supply.js");
let data;
self.onmessage = event => {
  const request = event.data;
  if (request.data) data = request.data;
  try {
    self.postMessage({id: request.id, result: self.Supply.evaluate(data, request.options)});
  } catch (error) {
    self.postMessage({id: request.id, error: String(error.message || error)});
  }
};
