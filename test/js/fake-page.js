// A tiny stand-in for a browser tab: just enough DOM for the live-call snippet.
// Elements register the simple selectors they answer to; a group 'a, b'
// matches elements registered for 'a' or 'b'. Queries search all descendants
// in document order, as a real querySelectorAll does.
const vm = require('node:vm');
const { PAGE_EXPRESSION } = require('../../capture/live-call-snippet');

const descendants = (elements) => elements.flatMap((e) => [e, ...descendants(e.children)]);

function matching(elements, group) {
  const wanted = group.split(/,\s*/).map((s) => s.trim());
  return descendants(elements).filter((e) => e.sel.some((s) => wanted.includes(s)));
}

function el({ sel = [], attrs = {}, text = '', children = [] } = {}) {
  return {
    sel,
    children,
    innerText: text,
    getAttribute: (name) => (name in attrs ? attrs[name] : null),
    querySelector: (group) => matching(children, group)[0] || null,
    querySelectorAll: (group) => matching(children, group),
  };
}

/** Runs the detector's page expression in a fake tab; returns the raw answer string. */
function runPage(hostname, elements = []) {
  const document = { querySelector: (g) => matching(elements, g)[0] || null, querySelectorAll: (g) => matching(elements, g) };
  return vm.runInNewContext(PAGE_EXPRESSION, { document, location: { hostname } });
}

module.exports = { el, runPage };
