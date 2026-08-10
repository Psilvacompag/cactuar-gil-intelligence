(function initializeUnifiedWatchlist() {
  const KEY = "gil-intelligence.unified-watchlist.v1";
  const listeners = new Set();

  function read() {
    try {
      const value = JSON.parse(localStorage.getItem(KEY) || "{}");
      return value && typeof value === "object" && !Array.isArray(value) ? value : {};
    } catch { return {}; }
  }

  function write(value) {
    localStorage.setItem(KEY, JSON.stringify(value));
    listeners.forEach((listener) => listener(value));
  }

  function migrate() {
    const current = read();
    const migrations = [
      ["gil-intelligence.market-watchlist", "market"],
      ["gil-intelligence.opportunity-watchlist", "opportunity"],
    ];
    migrations.forEach(([legacyKey, module]) => {
      try {
        const entries = JSON.parse(localStorage.getItem(legacyKey) || "[]");
        if (!Array.isArray(entries)) return;
        entries.forEach((entry) => {
          const key = `${module}:${entry}`;
          current[key] ||= { key, module, migratedAt: new Date().toISOString() };
        });
      } catch { /* Invalid legacy data is ignored. */ }
    });
    try {
      const signals = JSON.parse(localStorage.getItem("gil-intelligence.watched-signals") || "{}");
      Object.entries(signals || {}).forEach(([key, value]) => {
        current[key] ||= { key, module: key.split(":")[0], ...(value || {}), migratedAt: new Date().toISOString() };
      });
    } catch { /* Invalid legacy data is ignored. */ }
    write(current);
  }

  migrate();
  window.GilWatchlist = {
    has: (key) => Boolean(read()[key]),
    get: (key) => read()[key] || null,
    entries: () => Object.values(read()),
    keys: () => new Set(Object.keys(read())),
    total: () => Object.keys(read()).length,
    toggle(key, metadata = {}) {
      const current = read();
      if (current[key]) delete current[key];
      else current[key] = { key, module: key.split(":")[0], addedAt: new Date().toISOString(), ...metadata };
      write(current);
      return Boolean(current[key]);
    },
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
  };
})();
