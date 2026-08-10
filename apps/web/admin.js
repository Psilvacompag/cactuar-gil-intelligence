(function initializeAdminPanel() {
  const state = { users: [], loading: false };
  const elements = {
    users: document.querySelector("#admin-users"),
    search: document.querySelector("#admin-search"),
    status: document.querySelector("#admin-status-filter"),
    refresh: document.querySelector("#admin-refresh"),
    total: document.querySelector("#admin-total"),
    pending: document.querySelector("#admin-pending"),
    active: document.querySelector("#admin-active"),
  };

  function hasAccess() {
    return GilAuth.profile?.status === "ACTIVE" && GilAuth.profile?.role === "ADMIN";
  }

  function formatDate(value) {
    if (!value) return "Sin registro";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "Sin registro" : new Intl.DateTimeFormat("es-CL", { dateStyle: "medium", timeStyle: "short" }).format(date);
  }

  function empty(message) {
    elements.users.replaceChildren();
    const paragraph = document.createElement("p");
    paragraph.className = "admin-empty";
    paragraph.textContent = message;
    elements.users.append(paragraph);
  }

  function filteredUsers() {
    const query = elements.search.value.trim().toLocaleLowerCase("es");
    const status = elements.status.value;
    return state.users.filter((user) => {
      const matchesQuery = !query || `${user.displayName || ""} ${user.email || ""}`.toLocaleLowerCase("es").includes(query);
      return matchesQuery && (status === "ALL" || user.status === status);
    });
  }

  function action(label, changes, className = "") {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.className = className;
    button.dataset.changes = JSON.stringify(changes);
    return button;
  }

  function userRow(user) {
    const row = document.createElement("article");
    row.className = "admin-user";
    if (user.photoURL) {
      const avatar = document.createElement("img");
      avatar.src = user.photoURL;
      avatar.alt = "";
      avatar.referrerPolicy = "no-referrer";
      row.append(avatar);
    } else {
      const avatar = document.createElement("span");
      avatar.className = "admin-avatar-fallback";
      avatar.textContent = (user.displayName || user.email || "?").slice(0, 1).toUpperCase();
      row.append(avatar);
    }

    const identity = document.createElement("div");
    identity.className = "admin-identity";
    const name = document.createElement("strong");
    name.textContent = user.displayName || "Sin nombre";
    const email = document.createElement("small");
    email.textContent = `${user.email || "Sin correo"} · ${user.role === "ADMIN" ? "Administrador" : "Usuario"}`;
    identity.append(name, email);

    const status = document.createElement("span");
    status.className = "user-status";
    status.dataset.status = user.status;
    status.textContent = { ACTIVE: "Activo", PENDING: "Pendiente", SUSPENDED: "Suspendido" }[user.status] || user.status;

    const meta = document.createElement("div");
    meta.className = "admin-meta";
    const favorites = document.createElement("strong");
    favorites.textContent = `${user.favoriteCount || 0} favorito${user.favoriteCount === 1 ? "" : "s"}`;
    const lastLogin = document.createElement("span");
    lastLogin.textContent = `Último acceso: ${formatDate(user.lastLoginAt)}`;
    meta.append(favorites, document.createElement("br"), lastLogin);

    const actions = document.createElement("div");
    actions.className = "admin-actions";
    const isSelf = user.uid === GilAuth.profile?.uid;
    if (user.status === "PENDING") actions.append(action("Aprobar", { status: "ACTIVE" }, "primary"));
    if (user.status === "SUSPENDED") actions.append(action("Reactivar", { status: "ACTIVE" }, "primary"));
    if (user.status === "ACTIVE" && !isSelf) actions.append(action("Suspender", { status: "SUSPENDED" }, "danger"));
    if (user.role === "USER") actions.append(action("Hacer admin", { role: "ADMIN" }));
    if (user.role === "ADMIN" && !isSelf) actions.append(action("Quitar admin", { role: "USER" }));
    actions.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-changes]");
      if (button) void updateUser(user.uid, JSON.parse(button.dataset.changes), button);
    });
    row.append(identity, status, meta, actions);
    return row;
  }

  function render() {
    elements.total.textContent = state.users.length;
    elements.pending.textContent = state.users.filter((user) => user.status === "PENDING").length;
    elements.active.textContent = state.users.filter((user) => user.status === "ACTIVE").length;
    const users = filteredUsers();
    elements.users.replaceChildren(...users.map(userRow));
    if (!users.length) empty(state.loading ? "Cargando usuarios…" : "No hay usuarios que coincidan con el filtro.");
  }

  async function loadUsers() {
    if (!hasAccess()) {
      state.users = [];
      empty(GilAuth.user ? "Esta cuenta no tiene permisos de administrador." : "Ingresa con una cuenta administradora para continuar.");
      if (!GilAuth.user) GilAuth.open();
      return;
    }
    state.loading = true;
    elements.refresh.disabled = true;
    render();
    try {
      const payload = await GilAuth.request("/v1/admin/users");
      state.users = payload.users || [];
    } catch (error) {
      empty(error.message || "No pudimos cargar los usuarios.");
      return;
    } finally {
      state.loading = false;
      elements.refresh.disabled = false;
    }
    render();
  }

  async function updateUser(uid, changes, button) {
    button.disabled = true;
    try {
      const updated = await GilAuth.request(`/v1/admin/users/${encodeURIComponent(uid)}`, { method: "PATCH", body: JSON.stringify(changes) });
      state.users = state.users.map((user) => user.uid === uid ? { ...user, ...updated } : user);
      render();
    } catch (error) {
      GilAuth.reportError(error);
      button.disabled = false;
    }
  }

  elements.search.addEventListener("input", render);
  elements.status.addEventListener("change", render);
  elements.refresh.addEventListener("click", () => void loadUsers());
  window.addEventListener("gil-auth-change", () => void loadUsers());
  GilAuth.ready.then(loadUsers);
})();
