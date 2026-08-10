(function initializeAdminPanel() {
  const state = { users: [], invitations: [], loading: false };
  const elements = {
    users: document.querySelector("#admin-users"),
    search: document.querySelector("#admin-search"),
    status: document.querySelector("#admin-status-filter"),
    refresh: document.querySelector("#admin-refresh"),
    total: document.querySelector("#admin-total"),
    pending: document.querySelector("#admin-pending"),
    active: document.querySelector("#admin-active"),
    invited: document.querySelector("#admin-invited"),
    accessForm: document.querySelector("#admin-access-form"),
    accessEmail: document.querySelector("#admin-access-email"),
    accessSubmit: document.querySelector("#admin-access-submit"),
    accessMessage: document.querySelector("#admin-access-message"),
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

  function filteredInvitations() {
    const query = elements.search.value.trim().toLocaleLowerCase("es");
    const status = elements.status.value;
    if (status !== "ALL" && status !== "INVITED") return [];
    return state.invitations.filter((invitation) => (
      !query || invitation.email.toLocaleLowerCase("es").includes(query)
    ));
  }

  function setAccessMessage(message, tone = "success") {
    elements.accessMessage.hidden = !message;
    elements.accessMessage.textContent = message || "";
    elements.accessMessage.dataset.tone = tone;
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
    status.textContent = { ACTIVE: "Con acceso", PENDING: "Solicita acceso", SUSPENDED: "Sin acceso" }[user.status] || user.status;

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
    if (user.status === "PENDING") actions.append(action("Dar acceso", { status: "ACTIVE" }, "primary"));
    if (user.status === "SUSPENDED") actions.append(action("Restaurar acceso", { status: "ACTIVE" }, "primary"));
    if (user.status === "ACTIVE" && !isSelf) actions.append(action("Quitar acceso", { status: "SUSPENDED" }, "danger"));
    if (user.role === "USER" && user.status === "ACTIVE") actions.append(action("Hacer admin", { role: "ADMIN" }));
    if (user.role === "ADMIN" && !isSelf) actions.append(action("Quitar admin", { role: "USER" }));
    actions.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-changes]");
      if (button) void updateUser(user.uid, JSON.parse(button.dataset.changes), button);
    });
    row.append(identity, status, meta, actions);
    return row;
  }

  function invitationRow(invitation) {
    const row = document.createElement("article");
    row.className = "admin-user admin-invitation";
    const avatar = document.createElement("span");
    avatar.className = "admin-avatar-fallback";
    avatar.textContent = invitation.email.slice(0, 1).toUpperCase();
    const identity = document.createElement("div");
    identity.className = "admin-identity";
    const name = document.createElement("strong");
    name.textContent = "Correo preautorizado";
    const email = document.createElement("small");
    email.textContent = `${invitation.email} · Usuario`;
    identity.append(name, email);
    const status = document.createElement("span");
    status.className = "user-status";
    status.dataset.status = "INVITED";
    status.textContent = "Preautorizado";
    const meta = document.createElement("div");
    meta.className = "admin-meta";
    meta.textContent = `Aún no ingresa · autorizado ${formatDate(invitation.createdAt)}`;
    const actions = document.createElement("div");
    actions.className = "admin-actions";
    const revoke = document.createElement("button");
    revoke.type = "button";
    revoke.className = "danger";
    revoke.textContent = "Cancelar acceso";
    revoke.addEventListener("click", () => void revokeInvitation(invitation.id, revoke));
    actions.append(revoke);
    row.append(avatar, identity, status, meta, actions);
    return row;
  }

  function render() {
    elements.total.textContent = state.users.length;
    elements.pending.textContent = state.users.filter((user) => user.status === "PENDING").length;
    elements.active.textContent = state.users.filter((user) => user.status === "ACTIVE").length;
    elements.invited.textContent = state.invitations.length;
    const users = filteredUsers();
    const invitations = filteredInvitations();
    elements.users.replaceChildren(...invitations.map(invitationRow), ...users.map(userRow));
    if (!users.length && !invitations.length) empty(state.loading ? "Cargando accesos…" : "No hay accesos que coincidan con el filtro.");
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
      state.invitations = payload.invitations || [];
    } catch (error) {
      empty(error.message || "No pudimos cargar los usuarios.");
      return;
    } finally {
      state.loading = false;
      elements.refresh.disabled = false;
    }
    render();
  }

  async function grantAccess(event) {
    event.preventDefault();
    if (!hasAccess()) return;
    const email = elements.accessEmail.value.trim();
    if (!email || !elements.accessEmail.reportValidity()) return;
    elements.accessSubmit.disabled = true;
    setAccessMessage("");
    try {
      const result = await GilAuth.request("/v1/admin/invitations", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      elements.accessForm.reset();
      setAccessMessage(result.kind === "USER"
        ? "Acceso concedido a la cuenta registrada."
        : "Correo preautorizado. Tendrá acceso cuando ingrese con Google.");
      await loadUsers();
    } catch (error) {
      setAccessMessage(error.message || "No pudimos autorizar ese correo.", "error");
    } finally {
      elements.accessSubmit.disabled = false;
    }
  }

  async function revokeInvitation(invitationId, button) {
    button.disabled = true;
    try {
      await GilAuth.request("/v1/admin/invitations", {
        method: "DELETE",
        body: JSON.stringify({ id: invitationId }),
      });
      state.invitations = state.invitations.filter((invitation) => invitation.id !== invitationId);
      setAccessMessage("Preautorización cancelada.");
      render();
    } catch (error) {
      setAccessMessage(error.message || "No pudimos cancelar ese acceso.", "error");
      button.disabled = false;
    }
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
  elements.accessForm.addEventListener("submit", (event) => void grantAccess(event));
  window.addEventListener("gil-auth-change", () => void loadUsers());
  GilAuth.ready.then(loadUsers);
})();
