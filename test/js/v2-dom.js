// A small fake DOM for the v2 shell's renderer tests (spec seam 2): parses
// the HTML the shell writes, answers the selectors it uses, bubbles events,
// and runs the shell's classic scripts in a Node `vm` context with canned API
// replies. Not a browser: no layout, no CSS. Enough to check what a person
// would see and what a click calls.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr']);
const RAW = new Set(['script', 'style', 'textarea']);
const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'", apos: "'", nbsp: ' ' };
const decode = (s) => s.replace(/&(#x?[0-9a-f]+|[a-z0-9]+);/gi, (m, e) => {
  if (ENTITIES[e.toLowerCase()] !== undefined) return ENTITIES[e.toLowerCase()];
  if (e[0] === '#') return String.fromCodePoint(e[1].toLowerCase() === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10));
  return m;
});
const escText = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const escAttr = (s) => escText(s).replace(/"/g, '&quot;');
const camel = (s) => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
const kebab = (s) => s.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase());

class Text {
  constructor(text) { this.nodeType = 3; this.data = text; this.parentNode = null; }
  get textContent() { return this.data; }
  set textContent(v) { this.data = String(v); }
  remove() { if (this.parentNode) this.parentNode._detach(this); }
}

class Event {
  constructor(type, init = {}) {
    Object.assign(this, { type, bubbles: init.bubbles !== false, key: init.key, metaKey: !!init.metaKey, ctrlKey: !!init.ctrlKey, shiftKey: !!init.shiftKey, altKey: !!init.altKey });
    this.defaultPrevented = false; this._stop = false;
  }
  preventDefault() { this.defaultPrevented = true; }
  stopPropagation() { this._stop = true; }
}

class Element {
  constructor(tag, doc) {
    this.nodeType = 1; this.tagName = tag.toUpperCase(); this.localName = tag.toLowerCase();
    this.attributes = new Map(); this.childNodes = []; this.parentNode = null; this.ownerDocument = doc;
    this._listeners = {}; this._value = undefined; this._checked = undefined; this.style = {};
    const self = this;
    this.dataset = new Proxy({}, {
      get: (_, k) => (typeof k === 'string' ? self.getAttribute('data-' + kebab(k)) ?? undefined : undefined),
      set: (_, k, v) => { self.setAttribute('data-' + kebab(k), v); return true; },
      deleteProperty: (_, k) => { self.removeAttribute('data-' + kebab(k)); return true; },
      has: (_, k) => self.hasAttribute('data-' + kebab(k)),
      ownKeys: () => [...self.attributes.keys()].filter((a) => a.startsWith('data-')).map((a) => camel(a.slice(5))),
      getOwnPropertyDescriptor: (_, k) => (self.hasAttribute('data-' + kebab(k)) ? { enumerable: true, configurable: true, value: self.getAttribute('data-' + kebab(k)) } : undefined),
    });
    this.classList = {
      _list: () => (self.getAttribute('class') || '').split(/\s+/).filter(Boolean),
      contains: (c) => self.classList._list().includes(c),
      add: (...cs) => self.setAttribute('class', [...new Set([...self.classList._list(), ...cs])].join(' ')),
      remove: (...cs) => self.setAttribute('class', self.classList._list().filter((x) => !cs.includes(x)).join(' ')),
      toggle: (c, force) => {
        const on = force === undefined ? !self.classList.contains(c) : !!force;
        on ? self.classList.add(c) : self.classList.remove(c);
        return on;
      },
    };
  }
  get children() { return this.childNodes.filter((n) => n.nodeType === 1); }
  get firstElementChild() { return this.children[0] || null; }
  get parentElement() { return this.parentNode && this.parentNode.nodeType === 1 ? this.parentNode : null; }
  get id() { return this.getAttribute('id') || ''; }
  set id(v) { this.setAttribute('id', v); }
  get className() { return this.getAttribute('class') || ''; }
  set className(v) { this.setAttribute('class', v); }
  get hidden() { return this.hasAttribute('hidden'); }
  set hidden(v) { v ? this.setAttribute('hidden', '') : this.removeAttribute('hidden'); }
  get disabled() { return this.hasAttribute('disabled'); }
  set disabled(v) { v ? this.setAttribute('disabled', '') : this.removeAttribute('disabled'); }
  get title() { return this.getAttribute('title') || ''; }
  set title(v) { this.setAttribute('title', v); }
  get href() { return this.getAttribute('href') || ''; }
  get type() { return this.getAttribute('type') || (this.localName === 'button' ? 'submit' : 'text'); }
  get name() { return this.getAttribute('name') || ''; }
  get tabIndex() { const t = this.getAttribute('tabindex'); return t === null ? -1 : Number(t); }
  get checked() { return this._checked !== undefined ? this._checked : this.hasAttribute('checked'); }
  set checked(v) { this._checked = !!v; }
  get options() { return this.querySelectorAll('option'); }
  get selectedOptions() {
    const opts = this.options; const v = this.value;
    return opts.filter((o) => o.value === v).slice(0, 1);
  }
  get value() {
    if (this.localName === 'textarea') return this._value !== undefined ? this._value : this.textContent;
    if (this.localName === 'select') {
      if (this._value !== undefined) return this._value;
      const opts = this.options;
      const sel = opts.find((o) => o.hasAttribute('selected')) || opts[0];
      return sel ? sel.value : '';
    }
    if (this.localName === 'option') return this.hasAttribute('value') ? this.getAttribute('value') : this.textContent;
    return this._value !== undefined ? this._value : (this.getAttribute('value') || '');
  }
  set value(v) { this._value = String(v ?? ''); }
  get isContentEditable() { return this.getAttribute('contenteditable') === 'true'; }
  getAttribute(n) { return this.attributes.has(n) ? this.attributes.get(n) : null; }
  setAttribute(n, v) { this.attributes.set(n, String(v)); }
  removeAttribute(n) { this.attributes.delete(n); }
  hasAttribute(n) { return this.attributes.has(n); }
  toggleAttribute(n, force) { const on = force === undefined ? !this.hasAttribute(n) : !!force; on ? this.setAttribute(n, '') : this.removeAttribute(n); return on; }
  _detach(child) { this.childNodes = this.childNodes.filter((c) => c !== child); child.parentNode = null; }
  appendChild(child) { if (child.parentNode) child.parentNode._detach(child); this.childNodes.push(child); child.parentNode = this; return child; }
  append(...nodes) { nodes.forEach((n) => this.appendChild(typeof n === 'string' ? new Text(n) : n)); }
  prepend(child) { if (child.parentNode) child.parentNode._detach(child); this.childNodes.unshift(child); child.parentNode = this; return child; }
  insertBefore(child, ref) {
    if (!ref) return this.appendChild(child);
    if (child.parentNode) child.parentNode._detach(child);
    this.childNodes.splice(this.childNodes.indexOf(ref), 0, child); child.parentNode = this; return child;
  }
  replaceChildren(...nodes) { this.childNodes.forEach((c) => { c.parentNode = null; }); this.childNodes = []; this.append(...nodes); }
  remove() { if (this.parentNode) this.parentNode._detach(this); }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(''); }
  set textContent(v) { this.childNodes = []; if (v !== '' && v != null) this.appendChild(new Text(String(v))); this._value = undefined; }
  get innerText() { return this.textContent; }
  set innerText(v) { this.textContent = v; }
  get innerHTML() { return this.childNodes.map(serialize).join(''); }
  set innerHTML(html) { this.childNodes.forEach((c) => { c.parentNode = null; }); this.childNodes = []; parseInto(this, String(html), this.ownerDocument); }
  get outerHTML() { return serialize(this); }
  insertAdjacentHTML(where, html) {
    const tmp = new Element('div', this.ownerDocument); parseInto(tmp, html, this.ownerDocument);
    const nodes = [...tmp.childNodes];
    if (where === 'beforeend') nodes.forEach((n) => this.appendChild(n));
    else if (where === 'afterbegin') nodes.reverse().forEach((n) => this.prepend(n));
    else if (where === 'beforebegin') nodes.forEach((n) => this.parentNode.insertBefore(n, this));
    else if (where === 'afterend') { const sib = this.parentNode.childNodes[this.parentNode.childNodes.indexOf(this) + 1]; nodes.forEach((n) => this.parentNode.insertBefore(n, sib)); }
  }
  querySelectorAll(sel) { return queryAll(this, sel); }
  querySelector(sel) { return queryAll(this, sel)[0] || null; }
  matches(sel) { return parseGroup(sel).some((chain) => matchChain(this, chain)); }
  closest(sel) { let n = this; while (n && n.nodeType === 1) { if (n.matches(sel)) return n; n = n.parentNode; } return null; }
  contains(other) { let n = other; while (n) { if (n === this) return true; n = n.parentNode; } return false; }
  addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) { this._listeners[type] = (this._listeners[type] || []).filter((f) => f !== fn); }
  dispatchEvent(event) { return dispatch(this, event); }
  click() { if (!this.disabled) this.dispatchEvent(new Event('click')); }
  focus() { this.ownerDocument.activeElement = this; this.dispatchEvent(new Event('focus', { bubbles: false })); }
  blur() { if (this.ownerDocument.activeElement === this) this.ownerDocument.activeElement = this.ownerDocument.body; }
  select() {}
  scrollIntoView() {}
  getBoundingClientRect() { return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }; }
}

function serialize(n) {
  if (n.nodeType === 3) return escText(n.data);
  const attrs = [...n.attributes].map(([k, v]) => (v === '' ? ` ${k}` : ` ${k}="${escAttr(v)}"`)).join('');
  if (VOID.has(n.localName)) return `<${n.localName}${attrs}>`;
  return `<${n.localName}${attrs}>${n.innerHTML}</${n.localName}>`;
}

function parseInto(parent, html, doc) {
  const stack = [parent];
  const top = () => stack[stack.length - 1];
  let i = 0;
  while (i < html.length) {
    if (html.startsWith('<!--', i)) { const e = html.indexOf('-->', i); i = e < 0 ? html.length : e + 3; continue; }
    if (html[i] === '<' && html[i + 1] === '/') {
      const e = html.indexOf('>', i); const tag = html.slice(i + 2, e).trim().toLowerCase();
      for (let k = stack.length - 1; k > 0; k--) if (stack[k].localName === tag) { stack.length = k; break; }
      i = e + 1; continue;
    }
    if (html[i] === '<' && /[a-zA-Z!]/.test(html[i + 1] || '')) {
      if (html[i + 1] === '!') { i = html.indexOf('>', i) + 1; continue; }
      const m = /^<([a-zA-Z][\w-]*)/.exec(html.slice(i)); const tag = m[1].toLowerCase();
      let j = i + m[0].length; const el = new Element(tag, doc);
      for (;;) {
        while (/\s/.test(html[j])) j++;
        if (html[j] === '>' || html.startsWith('/>', j)) { j += html[j] === '>' ? 1 : 2; break; }
        const am = /^([^\s=>/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/.exec(html.slice(j));
        if (!am) { j++; continue; }
        el.attributes.set(am[1].toLowerCase(), decode(am[2] ?? am[3] ?? am[4] ?? ''));
        j += am[0].length;
      }
      top().appendChild(el); i = j;
      if (VOID.has(tag)) continue;
      if (RAW.has(tag)) {
        const end = html.toLowerCase().indexOf(`</${tag}`, i);
        const raw = html.slice(i, end < 0 ? html.length : end);
        if (raw) el.appendChild(new Text(tag === 'textarea' ? decode(raw) : raw));
        i = end < 0 ? html.length : html.indexOf('>', end) + 1; continue;
      }
      stack.push(el); continue;
    }
    const next = html.indexOf('<', i + 1); const text = html.slice(i, next < 0 ? html.length : next);
    top().appendChild(new Text(decode(text))); i = next < 0 ? html.length : next;
  }
}

// ---- selectors: compound (tag#id.cls[attr][attr=v]:not(x)) with ' ' and '>' ----
function splitTop(s, sep) {
  const out = []; let depth = 0, quote = null, cur = '';
  for (const ch of s) {
    if (quote) { cur += ch; if (ch === quote) quote = null; continue; }
    if (ch === '"' || ch === "'") { quote = ch; cur += ch; continue; }
    if (ch === '[' || ch === '(') depth++;
    if (ch === ']' || ch === ')') depth--;
    if (ch === sep && depth === 0) { out.push(cur); cur = ''; continue; }
    cur += ch;
  }
  out.push(cur); return out;
}
const cache = new Map();
function parseGroup(sel) {
  if (cache.has(sel)) return cache.get(sel);
  const chains = splitTop(sel, ',').map((part) => {
    const tokens = []; let s = part.trim().replace(/\s*>\s*/g, ' > ');
    for (const t of splitTop(s, ' ').filter(Boolean)) tokens.push(t === '>' ? { comb: '>' } : parseCompound(t));
    return tokens;
  });
  cache.set(sel, chains); return chains;
}
function parseCompound(t) {
  const c = { tag: null, ids: [], cls: [], attrs: [], nots: [], pseudo: [] };
  const re = /^(\*|[a-zA-Z][\w-]*)|#([\w-]+)|\.([\w-]+)|\[([^\]=~^$*]+)(?:([~^$*]?=)"?([^"\]]*)"?)?\]|:not\(([^)]*)\)|:([\w-]+)/g;
  let m;
  while ((m = re.exec(t))) {
    if (m[1]) c.tag = m[1] === '*' ? null : m[1].toLowerCase();
    else if (m[2]) c.ids.push(m[2]);
    else if (m[3]) c.cls.push(m[3]);
    else if (m[4]) c.attrs.push({ name: m[4].trim(), op: m[5], value: m[6] });
    else if (m[7] !== undefined) c.nots.push(m[7]);
    else if (m[8]) c.pseudo.push(m[8]);
  }
  return c;
}
function matchCompound(el, c) {
  if (el.nodeType !== 1) return false;
  if (c.tag && el.localName !== c.tag) return false;
  if (c.ids.some((id) => el.id !== id)) return false;
  if (c.cls.some((x) => !el.classList.contains(x))) return false;
  for (const a of c.attrs) {
    const v = el.getAttribute(a.name);
    if (v === null) return false;
    if (a.op === '=' && v !== a.value) return false;
    if (a.op === '^=' && !v.startsWith(a.value)) return false;
    if (a.op === '*=' && !v.includes(a.value)) return false;
    if (a.op === '~=' && !v.split(/\s+/).includes(a.value)) return false;
  }
  if (c.nots.some((n) => el.matches(n))) return false;
  for (const p of c.pseudo) {
    if (p === 'checked' && !el.checked) return false;
    if (p === 'disabled' && !el.disabled) return false;
    if (p === 'first-child' && el.parentNode?.children[0] !== el) return false;
  }
  return true;
}
function matchChain(el, chain) {
  let i = chain.length - 1;
  if (!matchCompound(el, chain[i])) return false;
  let node = el; i--;
  while (i >= 0) {
    const child = chain[i].comb === '>'; if (child) i--;
    const want = chain[i];
    if (child) { node = node.parentNode; if (!node || !matchCompound(node, want)) return false; }
    else { node = node.parentNode; while (node && !matchCompound(node, want)) node = node.parentNode; if (!node) return false; }
    i--;
  }
  return true;
}
function descendants(root) { const out = []; const walk = (n) => n.children.forEach((c) => { out.push(c); walk(c); }); walk(root); return out; }
function queryAll(root, sel) { const chains = parseGroup(sel); return descendants(root).filter((el) => chains.some((ch) => matchChain(el, ch))); }

function dispatch(target, event) {
  event.target = target;
  const path = []; let n = target; while (n) { path.push(n); n = n.parentNode; }
  const doc = target.ownerDocument; if (doc && !path.includes(doc)) path.push(doc);
  if (doc && doc.defaultView) path.push(doc.defaultView);
  for (const node of event.bubbles ? path : [target]) {
    event.currentTarget = node;
    for (const fn of [...(node._listeners?.[event.type] || [])]) fn.call(node, event);
    if (event._stop) break;
  }
  return !event.defaultPrevented;
}

function makeDocument() {
  const doc = { nodeType: 9, _listeners: {}, defaultView: null, cookie: '' };
  const html = new Element('html', doc); doc.documentElement = html; html.parentNode = doc;
  doc.head = html.appendChild(new Element('head', doc)); doc.body = html.appendChild(new Element('body', doc));
  doc.activeElement = doc.body;
  Object.assign(doc, {
    createElement: (t) => new Element(t, doc),
    createTextNode: (t) => new Text(t),
    getElementById: (id) => queryAll(html, `#${id}`)[0] || null,
    querySelector: (s) => queryAll(html, s)[0] || null,
    querySelectorAll: (s) => queryAll(html, s),
    addEventListener: (t, fn) => (doc._listeners[t] ||= []).push(fn),
    removeEventListener: (t, fn) => { doc._listeners[t] = (doc._listeners[t] || []).filter((f) => f !== fn); },
    dispatchEvent: (e) => dispatch(html, e),
    hasFocus: () => true,
    execCommand: () => true,
  });
  html.parentNode = doc; doc.children = [html]; doc.childNodes = [html];
  return doc;
}

/**
 * Load a page of the web UI into a fresh context.
 * page: path under src/ui/web (e.g. 'v2/index.html'); its <body> markup is
 * parsed and its <script src> files run in order.
 * replies: { 'GET /api/x': value | (url, body) => value, '/api/x': … } (exact
 * path with query first, then the path without query, then prefix keys ending in '*').
 */
function loadPage(page, { replies = {}, settings = {}, dark = false, scripts, before } = {}) {
  const web = path.join(__dirname, '..', '..', 'src', 'ui', 'web');
  const html = fs.readFileSync(path.join(web, page), 'utf8');
  const doc = makeDocument();
  const bodyMatch = /<body[^>]*>([\s\S]*)<\/body>/i.exec(html);
  const bodyAttrs = /<body([^>]*)>/i.exec(html);
  const htmlAttrs = /<html([^>]*)>/i.exec(html);
  if (htmlAttrs) { const tmp = new Element('div', doc); parseInto(tmp, `<i${htmlAttrs[1]}></i>`, doc); for (const [k, v] of tmp.children[0].attributes) doc.documentElement.setAttribute(k, v); }
  if (bodyAttrs) { const tmp = new Element('div', doc); parseInto(tmp, `<i${bodyAttrs[1]}></i>`, doc); for (const [k, v] of tmp.children[0].attributes) doc.body.setAttribute(k, v); }
  const body = (bodyMatch ? bodyMatch[1] : html).replace(/<script[\s\S]*?<\/script>/gi, '');
  doc.body.innerHTML = body;
  const srcs = scripts || [...html.matchAll(/<script src="\/([^"?]+)[^"]*"><\/script>/g)].map((m) => m[1]);

  const calls = [];
  const store = { ...settings };
  const timers = [];
  const win = { _listeners: {}, nodeType: 0 };
  doc.defaultView = win;
  const respond = (method, url, body) => {
    const bare = url.split('?')[0];
    const keys = [`${method} ${url}`, url, `${method} ${bare}`, bare];
    let reply;
    for (const k of keys) if (k in replies) { reply = replies[k]; break; }
    if (reply === undefined) {
      const prefix = Object.keys(replies).find((k) => k.endsWith('*') && (`${method} ${url}`.startsWith(k.slice(0, -1)) || url.startsWith(k.slice(0, -1))));
      if (prefix) reply = replies[prefix];
    }
    if (bare === '/api/settings' && reply === undefined) {
      if (method === 'POST') { const b = JSON.parse(body || '{}'); if ('value' in b && b.value !== null) { store[b.key] = b.value; return { ok: true }; } return { value: store[b.key] ?? null }; }
      const key = decodeURIComponent((/key=([^&]*)/.exec(url) || [])[1] || '');
      return { value: store[key] ?? null };
    }
    if (typeof reply === 'function') reply = reply(url, body ? JSON.parse(body) : undefined, method);
    return reply === undefined ? {} : reply;
  };
  const fetch = async (url, opts = {}) => {
    const method = (opts.method || 'GET').toUpperCase();
    calls.push({ method, url, body: opts.body ? JSON.parse(opts.body) : undefined });
    let value; let status = 200;
    try { value = respond(method, url, opts.body); } catch (e) { value = { error: e.message }; status = e.status || 400; }
    if (value && value.__status) { status = value.__status; value = value.body || { error: 'failed' }; }
    return { ok: status < 400, status, json: async () => JSON.parse(JSON.stringify(value)) };
  };
  const mql = (q) => ({ matches: /dark/.test(q) ? dark : false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {} });
  const memory = {};
  const location = { href: 'http://127.0.0.1:8765/' + page.replace(/index\.html$/, ''), pathname: '/' + page.replace(/index\.html$/, ''), search: '', hash: '', assigned: [], reload() { location.reloaded = true; }, assign(u) { location.assigned.push(u); } };
  const context = vm.createContext({
    console, Promise, JSON, Math, Date, Map, Set, URL, URLSearchParams, Array, Object, String, Number, Boolean, RegExp, Error, Symbol, Intl,
    encodeURIComponent, decodeURIComponent, structuredClone, queueMicrotask,
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
    requestAnimationFrame: (fn) => { fn(); return 0; },
    document: doc, fetch, matchMedia: mql, location,
    localStorage: { getItem: (k) => (k in memory ? memory[k] : null), setItem: (k, v) => { memory[k] = String(v); }, removeItem: (k) => { delete memory[k]; } },
    navigator: { clipboard: { writeText: async (t) => { context.__clipboard = t; } }, platform: 'MacIntel', userAgent: 'fake' },
    confirm: () => true, alert: () => {}, prompt: () => null,
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
    Event, KeyboardEvent: Event, CustomEvent: Event, Element, HTMLElement: Element, Node: Element,
  });
  Object.assign(win, context);
  context.window = context; context.globalThis = context; context.self = context;
  context.addEventListener = (t, fn) => (win._listeners[t] ||= []).push(fn);
  context.removeEventListener = (t, fn) => { win._listeners[t] = (win._listeners[t] || []).filter((f) => f !== fn); };
  context.dispatchEvent = (e) => dispatch(doc.documentElement, e);
  doc.defaultView = win;
  win.addEventListener = context.addEventListener;
  if (before) before(context);
  for (const src of srcs) vm.runInContext(fs.readFileSync(path.join(web, src), 'utf8'), context, { filename: src });

  const flush = async (n = 30) => { for (let k = 0; k < n; k++) await new Promise((r) => setImmediate(r)); };
  const $ = (s) => doc.querySelector(s);
  const $$ = (s) => doc.querySelectorAll(s);
  const click = async (target) => { const el = typeof target === 'string' ? $(target) : target; if (!el) throw new Error(`nothing matches ${target}`); el.click(); await flush(); return el; };
  const key = async (k, mods = {}, target = doc.activeElement || doc.body) => { target.dispatchEvent(new Event('keydown', { key: k, ...mods })); await flush(); };
  const input = async (target, value, type = 'input') => { const el = typeof target === 'string' ? $(target) : target; el.value = value; el.dispatchEvent(new Event(type)); await flush(); return el; };
  const change = (target, value) => input(target, value, 'change');
  const run = (code) => vm.runInContext(code, context);
  const runTimers = async () => { const due = timers.splice(0); due.forEach((t) => t.fn()); await flush(); };
  return { doc, context, calls, store, $, $$, click, key, input, change, flush, run, runTimers, location, posts: () => calls.filter((c) => c.method === 'POST') };
}

const text = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');

module.exports = { loadPage, text, Element, Event };
