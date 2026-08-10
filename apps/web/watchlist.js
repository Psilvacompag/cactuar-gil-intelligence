(function initializeRemoteWatchlist() {
  const LEGACY_KEYS = [
    "gil-intelligence.unified-watchlist.v1",
    "gil-intelligence.market-watchlist",
    "gil-intelligence.opportunity-watchlist",
    "gil-intelligence.watched-signals",
  ];
  const listeners = new Set();
  let records = {};
  let loadSequence = 0;
  let reloadPromise = null;

  // Favorites intentionally start from zero. Legacy browser data is discarded,
  // never read or sent to the server.
  LEGACY_KEYS.forEach((key) => localStorage.removeItem(key));

  function publish() {
    const snapshot = { ...records };
    listeners.forEach((listener) => listener(snapshot));
  }

  function activeAccount() {
    return window.GilAuth?.profile?.status === "ACTIVE";
  }

  async function reload() {
    if (!activeAccount()) {
      loadSequence += 1;
      reloadPromise = null;
      records = {};
      publish();
      return;
    }
    if (reloadPromise) return reloadPromise;
    const sequence = ++loadSequence;
    const currentReload = (async () => {
      try {
        const payload = await window.GilAuth.request("/v1/me/favorites");
        if (sequence !== loadSequence) return;
        records = Object.fromEntries((payload.favorites || []).map((entry) => [entry.key, entry]));
        publish();
      } catch (error) {
        if (sequence !== loadSequence) return;
        records = {};
        publish();
        window.GilAuth.reportError?.(error);
      }
    })();
    reloadPromise = currentReload;
    try {
      return await currentReload;
    } finally {
      if (reloadPromise === currentReload) reloadPromise = null;
    }
  }

  async function persist(key, metadata, shouldAdd, previous) {
    try {
      if (shouldAdd) {
        const saved = await window.GilAuth.request("/v1/me/favorites", {
          method: "PUT",
          body: JSON.stringify({ key, metadata }),
        });
        records[key] = saved;
      } else {
        await window.GilAuth.request("/v1/me/favorites", {
          method: "DELETE",
          body: JSON.stringify({ key }),
        });
      }
      publish();
    } catch (error) {
      if (previous) records[key] = previous;
      else delete records[key];
      publish();
      window.GilAuth.reportError?.(error);
    }
  }

  async function update(key, metadata) {
    if (!activeAccount()) throw new Error("authentication_required");
    const normalizedKey = String(key || "").trim();
    const previous = records[normalizedKey] || null;
    if (!previous) throw new Error("favorite_not_found");
    records[normalizedKey] = { ...previous, ...metadata, updatedAt: new Date().toISOString() };
    publish();
    try {
      const saved = await window.GilAuth.request("/v1/me/favorites", {
        method: "PUT",
        body: JSON.stringify({ key: normalizedKey, metadata }),
      });
      records[normalizedKey] = { ...saved, history: previous.history || [] };
      publish();
      return saved;
    } catch (error) {
      records[normalizedKey] = previous;
      publish();
      throw error;
    }
  }

  async function remove(key) {
    if (!activeAccount()) throw new Error("authentication_required");
    const normalizedKey = String(key || "").trim();
    const previous = records[normalizedKey] || null;
    if (!previous) return false;
    delete records[normalizedKey];
    publish();
    try {
      await window.GilAuth.request("/v1/me/favorites", {
        method: "DELETE",
        body: JSON.stringify({ key: normalizedKey }),
      });
      return true;
    } catch (error) {
      records[normalizedKey] = previous;
      publish();
      throw error;
    }
  }

  window.GilWatchlist = {
    has: (key) => Boolean(records[key]),
    get: (key) => records[key] || null,
    entries: () => Object.values(records),
    keys: () => new Set(Object.keys(records)),
    total: () => Object.keys(records).length,
    reload,
    update,
    remove,
    toggle(key, metadata = {}) {
      if (!activeAccount()) {
        window.GilAuth?.open();
        return false;
      }
      const normalizedKey = String(key || "").trim();
      if (!normalizedKey) return false;
      const previous = records[normalizedKey] || null;
      const shouldAdd = !previous;
      if (shouldAdd) {
        records[normalizedKey] = {
          key: normalizedKey,
          module: metadata.module || normalizedKey.split(":", 1)[0],
          addedAt: new Date().toISOString(),
          ...metadata,
        };
      } else {
        delete records[normalizedKey];
      }
      publish();
      void persist(normalizedKey, metadata, shouldAdd, previous);
      return shouldAdd;
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };

  window.addEventListener("gil-auth-change", () => void reload());
  if (window.GilAuth?.ready) window.GilAuth.ready.then(reload);
})();
