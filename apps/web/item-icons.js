(function initializeItemIcons() {
  const assetOrigin = "https://v2.xivapi.com";
  const fallbacks = {
    item: '<svg viewBox="0 0 24 24"><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z"/><path d="m4.5 7.8 7.5 4.3 7.5-4.3M12 12v8.5"/></svg>',
    coin: '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="7" rx="7" ry="3.5"/><path d="M5 7v5c0 1.9 3.1 3.5 7 3.5s7-1.6 7-3.5V7M5 12v5c0 1.9 3.1 3.5 7 3.5s7-1.6 7-3.5v-5"/></svg>',
    leaf: '<svg viewBox="0 0 24 24"><path d="M20 4C11 4 5.5 8.4 5.5 14.3c0 2.7 1.8 4.7 4.5 4.7 5.9 0 9.3-6.4 10-15Z"/><path d="M4 21c2.7-5.4 6.5-8.7 12-11"/></svg>',
    craft: '<svg viewBox="0 0 24 24"><path d="m14.5 5.5 4 4M13 7l4 4-8.5 8.5-4-4L13 7Z"/><path d="m15.5 4.5 2-2 4 4-2 2M3 21l4.5-1.5"/></svg>',
    route: '<svg viewBox="0 0 24 24"><path d="M4 7h10M10 3l4 4-4 4M20 17H10M14 13l-4 4 4 4"/></svg>',
    signal: '<svg viewBox="0 0 24 24"><path d="M4 18h3l3-8 4 10 3-7h3"/></svg>',
  };

  function normalizedId(value) {
    const id = Number(value);
    return Number.isSafeInteger(id) && id > 0 ? id : null;
  }

  function url(value) {
    const id = normalizedId(value);
    if (!id) return null;
    const file = String(id).padStart(6, "0");
    const folder = String(Math.floor(id / 1000) * 1000).padStart(6, "0");
    const path = `ui/icon/${folder}/${file}_hr1.tex`;
    return `${assetOrigin}/api/asset?path=${encodeURIComponent(path)}&format=png`;
  }

  function fallback(kind) { return fallbacks[kind] || fallbacks.item; }

  function markup(iconId, options = {}) {
    const source = url(iconId);
    const tone = options.tone ? ` ${options.tone}` : "";
    const image = source
      ? `<img class="item-icon-image" src="${source}" alt="" loading="lazy" decoding="async" />`
      : "";
    return `<span class="item-icon${tone}" aria-hidden="true">${image}${fallback(options.fallback)}</span>`;
  }

  function element(iconId, options = {}) {
    const wrapper = document.createElement("span");
    wrapper.className = `item-icon${options.tone ? ` ${options.tone}` : ""}`;
    wrapper.setAttribute("aria-hidden", "true");
    const source = url(iconId);
    if (source) {
      const image = document.createElement("img");
      image.className = "item-icon-image";
      image.src = source;
      image.alt = "";
      image.loading = "lazy";
      image.decoding = "async";
      wrapper.append(image);
    }
    wrapper.insertAdjacentHTML("beforeend", fallback(options.fallback));
    return wrapper;
  }

  document.addEventListener("load", (event) => {
    if (event.target instanceof HTMLImageElement && event.target.classList.contains("item-icon-image")) {
      event.target.parentElement?.classList.add("has-original");
    }
  }, true);
  document.addEventListener("error", (event) => {
    if (event.target instanceof HTMLImageElement && event.target.classList.contains("item-icon-image")) {
      event.target.hidden = true;
      event.target.parentElement?.classList.add("icon-fallback");
    }
  }, true);

  window.GilItemIcons = { element, markup, url };
})();
