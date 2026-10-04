"use strict";
(() => {
  const languages = Object.freeze({
    pl: "Polski",
    en: "English",
    es: "Español",
    fr: "Français",
    de: "Deutsch",
    uk: "Українська",
    hu: "Magyar",
    cs: "Čeština",
    sl: "Slovenščina",
    sk: "Slovenčina",
  });
  const storageKey = "msr-admin-language-v1";
  const packs = new Map([["pl", {}]]);
  const bindings = new WeakMap();
  const references = new Set();
  let language = "pl",
    request = 0,
    cleanupQueued = false,
    operationBusy = false,
    languageLoading = false;

  class Message {
    constructor(render) {
      this.render = render;
    }
    toString() {
      return this.render();
    }
    toJSON() {
      return String(this);
    }
    toLowerCase() {
      return String(this).toLowerCase();
    }
  }
  const m = (source) =>
    new Message(() => packs.get(language)?.[source] ?? source);
  const join = (...parts) => new Message(() => parts.map(String).join(""));
  const list = (parts, separator) =>
    parts.length ? new Message(() => parts.map(String).join(separator)) : "";
  const isMessage = (value) => value instanceof Message;

  function apply(node, key, value) {
    const text = String(value ?? "");
    if (key.startsWith("attr:")) node.setAttribute(key.slice(5), text);
    else node[key] = text;
  }
  function prune() {
    cleanupQueued = false;
    for (const ref of references) {
      const node = ref.deref();
      if (!node?.isConnected || !bindings.get(node)?.size)
        references.delete(ref);
    }
  }
  function bind(node, key, value) {
    let values = bindings.get(node);
    if (isMessage(value)) {
      if (!values) {
        values = new Map();
        bindings.set(node, values);
      }
      values.set(key, value);
      // One reference per node; the WeakMap never keeps detached UI alive.
      if (!values.reference || !references.has(values.reference)) {
        values.reference = new WeakRef(node);
        references.add(values.reference);
      }
    } else values?.delete(key);
    apply(node, key, value);
    if (references.size > 1024 && !cleanupQueued) {
      cleanupQueued = true;
      queueMicrotask(prune);
    }
  }
  function refresh() {
    document.documentElement.lang = language;
    for (const ref of references) {
      const node = ref.deref();
      if (!node?.isConnected) {
        references.delete(ref);
        continue;
      }
      for (const [key, value] of bindings.get(node) || [])
        apply(node, key, value);
    }
    prune();
  }
  function registerStatic() {
    // Register the authored shell once, before API data or operator input exists.
    // Runtime profile names, publication contents and identifiers are never scanned.
    const walker = document.createTreeWalker(
      document.documentElement,
      NodeFilter.SHOW_TEXT,
    );
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      if (
        node.parentElement?.closest(
          "script,style,noscript,textarea,pre,code,#ui-language",
        )
      )
        continue;
      const raw = node.nodeValue;
      if (!raw.trim()) continue;
      const source = raw.trim().replace(/\s+/g, " ");
      bind(
        node,
        "nodeValue",
        join(raw.match(/^\s*/)[0], m(source), raw.match(/\s*$/)[0]),
      );
    }
    for (const node of document.querySelectorAll(
      "[title],[aria-label],[placeholder],[alt]",
    ))
      for (const key of ["title", "aria-label", "placeholder", "alt"])
        if (node.hasAttribute(key))
          bind(node, "attr:" + key, m(node.getAttribute(key)));
  }
  function detect() {
    try {
      const value = localStorage.getItem(storageKey);
      if (Object.hasOwn(languages, value)) return value;
    } catch {}
    for (const tag of navigator.languages || [navigator.language]) {
      const code = String(tag || "")
        .toLowerCase()
        .split("-")[0];
      if (Object.hasOwn(languages, code)) return code;
    }
    return "pl";
  }
  async function setLanguage(code, persist = true) {
    if (!Object.hasOwn(languages, code)) return false;
    const epoch = ++request,
      select = document.getElementById("ui-language"),
      status = document.getElementById("language-status");
    languageLoading = true;
    select.disabled = true;
    status.hidden = false;
    bind(status, "textContent", m("Ładowanie języka…"));
    try {
      if (!packs.has(code)) {
        const response = await fetch("lang-" + code + ".json", {
          signal: AbortSignal.timeout(15000),
          cache: "no-cache",
        });
        if (!response.ok) throw new Error("Language unavailable");
        const pack = await response.json();
        if (
          !pack ||
          Array.isArray(pack) ||
          typeof pack !== "object" ||
          !Object.keys(pack).length ||
          Object.values(pack).some((v) => typeof v !== "string")
        )
          throw new Error("Invalid language pack");
        packs.set(code, pack);
      }
      if (epoch !== request) return false;
      language = code;
      if (persist) {
        try {
          localStorage.setItem(storageKey, code);
        } catch {}
      }
      refresh();
      select.value = code;
      status.hidden = true;
      return true;
    } catch {
      if (epoch === request) {
        select.value = language;
        bind(
          status,
          "textContent",
          m("Nie udało się wczytać języka. Spróbuj ponownie."),
        );
      }
      return false;
    } finally {
      if (epoch === request) {
        languageLoading = false;
        select.disabled = operationBusy;
      }
    }
  }
  async function init() {
    const select = document.getElementById("ui-language");
    for (const [code, name] of Object.entries(languages))
      select.add(new Option(name, code));
    registerStatic();
    select.addEventListener("change", () => setLanguage(select.value));
    await setLanguage(detect(), false);
  }
  function date(value, options = { dateStyle: "medium", timeStyle: "short" }) {
    const instant = new Date(value).getTime();
    return Number.isNaN(instant)
      ? m("Brak daty")
      : new Message(() =>
          new Intl.DateTimeFormat(language, options).format(instant),
        );
  }
  class LocalizedError extends Error {
    constructor(message) {
      super(String(message));
      this.localizedMessage = message;
    }
  }
  window.MSR_ADMIN_I18N = Object.freeze({
    init,
    setLanguage,
    m,
    join,
    list,
    isMessage,
    busy: (value) => {
      operationBusy = value;
      document.getElementById("ui-language").disabled =
        operationBusy || languageLoading;
    },
    get language() {
      return language;
    },
    text: (node, value) => bind(node, "textContent", value),
    attr: (node, key, value) => bind(node, "attr:" + key, value),
    title: (value) =>
      bind(document.querySelector("title"), "textContent", value),
    date,
    number: (value, options) =>
      new Message(() => new Intl.NumberFormat(language, options).format(value)),
    option: (text, ...args) => {
      const node = new Option("", ...args);
      bind(node, "textContent", text);
      return node;
    },
    Error: LocalizedError,
    errorMessage: (error) => error.localizedMessage ?? error.message,
  });
})();
