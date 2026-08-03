(function () {
  "use strict";

  if (document.documentElement.lang !== "en") return;

  var catalogElement = document.getElementById("dashboard-i18n-catalog");
  var catalog = {text: {}, patterns: {}};
  try {
    catalog = JSON.parse(catalogElement ? catalogElement.textContent : "{}");
  } catch (error) {
    console.error("Unable to load the dashboard translation catalog.", error);
  }

  var textMap = catalog.text || {};
  var patterns = Object.keys(catalog.patterns || {}).map(function (source) {
    try {
      return [new RegExp(source, "g"), catalog.patterns[source]];
    } catch (error) {
      console.warn("Skipped an invalid dashboard translation pattern:", source);
      return null;
    }
  }).filter(Boolean);
  var ignoredTags = {
    SCRIPT: true,
    STYLE: true,
    PRE: true,
    CODE: true,
    TEXTAREA: true,
  };
  var translatedAttributes = [
    "aria-label",
    "aria-description",
    "placeholder",
    "title",
    "data-confirm",
  ];

  function translate(value) {
    if (typeof value !== "string" || !value) return value;
    var match = value.match(/^(\s*)(.*?)(\s*)$/s);
    if (!match) return value;
    var core = match[2];
    var translated = Object.prototype.hasOwnProperty.call(textMap, core)
      ? textMap[core]
      : core;
    if (translated === core) {
      patterns.forEach(function (entry) {
        translated = translated.replace(entry[0], entry[1]);
      });
    }
    return match[1] + translated + match[3];
  }

  function isIgnored(node) {
    var element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
    return !element ||
      ignoredTags[element.tagName] ||
      Boolean(element.closest("[data-i18n-ignore]"));
  }

  function translateElement(element) {
    if (!(element instanceof Element) || isIgnored(element)) return;
    translatedAttributes.forEach(function (attribute) {
      if (!element.hasAttribute(attribute)) return;
      var current = element.getAttribute(attribute);
      var translated = translate(current);
      if (translated !== current) element.setAttribute(attribute, translated);
    });
  }

  function translateTree(root) {
    if (!root || isIgnored(root)) return;
    if (root.nodeType === Node.TEXT_NODE) {
      var translated = translate(root.nodeValue);
      if (translated !== root.nodeValue) root.nodeValue = translated;
      return;
    }
    if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) {
      return;
    }
    if (root.nodeType === Node.ELEMENT_NODE) translateElement(root);

    var walker = document.createTreeWalker(
      root,
      NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT,
      {
        acceptNode: function (node) {
          return isIgnored(node)
            ? NodeFilter.FILTER_REJECT
            : NodeFilter.FILTER_ACCEPT;
        },
      }
    );
    var node;
    while ((node = walker.nextNode())) {
      if (node.nodeType === Node.TEXT_NODE) {
        var value = translate(node.nodeValue);
        if (value !== node.nodeValue) node.nodeValue = value;
      } else {
        translateElement(node);
      }
    }
  }

  var nativeAlert = window.alert.bind(window);
  var nativeConfirm = window.confirm.bind(window);
  window.alert = function (message) {
    return nativeAlert(translate(String(message)));
  };
  window.confirm = function (message) {
    return nativeConfirm(translate(String(message)));
  };

  translateTree(document.body);
  var observer = new MutationObserver(function (mutations) {
    mutations.forEach(function (mutation) {
      if (mutation.type === "characterData") {
        translateTree(mutation.target);
        return;
      }
      Array.prototype.forEach.call(mutation.addedNodes, translateTree);
    });
  });
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    characterData: true,
  });

  window.DashboardI18n = {
    locale: "en",
    translate: translate,
    translateTree: translateTree,
  };
})();
