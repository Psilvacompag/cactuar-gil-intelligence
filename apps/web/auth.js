(function initializeAuthentication() {
  const FIREBASE_VERSION = "12.17.1";
  const API_BASE = String(window.GIL_INTELLIGENCE_CONFIG?.apiBaseUrl || "").replace(/\/$/, "");
  const listeners = new Set();
  let firebaseAuth = null;
  let authSdk = null;
  let currentUser = null;
  let currentProfile = null;
  let bootError = null;
  let bootComplete = false;
  let resolveReady;
  const ready = new Promise((resolve) => { resolveReady = resolve; });

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "auth-trigger";
  trigger.setAttribute("aria-label", "Abrir cuenta");
  trigger.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 12a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9Zm-8 9a8 8 0 0 1 16 0"/></svg><span>Ingresar</span>';
  document.querySelector(".topbar-meta")?.append(trigger);

  const gate = document.createElement("section");
  gate.className = "auth-gate";
  gate.setAttribute("aria-live", "polite");
  gate.innerHTML = `
    <div class="auth-gate-card">
      <div class="auth-gate-brand"><span class="brand-mark" aria-hidden="true">G</span><div><strong>Gil Intelligence</strong><small>Acceso privado</small></div></div>
      <div id="gate-spinner" class="auth-gate-spinner" aria-label="Comprobando sesión"></div>
      <p class="eyebrow">CUENTA · CACTUAR</p>
      <h1 id="gate-title">Comprobando tu sesión.</h1>
      <p id="gate-copy">Estamos validando tu acceso de forma segura.</p>
      <div id="gate-profile" class="account-profile" hidden>
        <img id="gate-avatar" alt="" referrerpolicy="no-referrer" />
        <div><strong id="gate-name"></strong><small id="gate-email"></small></div>
        <span id="gate-status" class="account-status"></span>
      </div>
      <p id="gate-message" class="account-message" role="status" hidden></p>
      <div class="account-actions">
        <button id="gate-login" class="google-login" type="button" hidden><span aria-hidden="true">G</span> Continuar con Google</button>
        <button id="gate-logout" class="secondary-action" type="button" hidden>Cerrar sesión</button>
      </div>
      <small class="account-privacy">Solo las cuentas aprobadas pueden acceder a los datos y herramientas.</small>
    </div>`;
  document.body.append(gate);

  const dialog = document.createElement("dialog");
  dialog.className = "account-dialog";
  dialog.innerHTML = `
    <div class="account-shell">
      <button class="dialog-close account-close" type="button" aria-label="Cerrar">×</button>
      <div class="account-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24"><path d="M12 12a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9Zm-8 9a8 8 0 0 1 16 0"/></svg>
      </div>
      <p class="eyebrow">CUENTA · GIL INTELLIGENCE</p>
      <h2 id="account-title">Tus favoritos, en cualquier dispositivo.</h2>
      <p id="account-copy" class="account-copy">Ingresa con Google para guardar una lista privada. Las cuentas nuevas deben ser aprobadas por un administrador.</p>
      <div id="account-profile" class="account-profile" hidden>
        <img id="account-avatar" alt="" referrerpolicy="no-referrer" />
        <div><strong id="account-name"></strong><small id="account-email"></small></div>
        <span id="account-status" class="account-status"></span>
      </div>
      <p id="account-message" class="account-message" role="status" hidden></p>
      <div class="account-actions">
        <button id="account-login" class="google-login" type="button"><span aria-hidden="true">G</span> Continuar con Google</button>
        <a id="account-admin" class="account-admin-link" href="./admin.html" hidden>Administrar usuarios</a>
        <button id="account-logout" class="secondary-action" type="button" hidden>Cerrar sesión</button>
      </div>
      <small class="account-privacy">No guardamos contraseñas. Google autentica tu identidad y el servidor conserva solo tu perfil y favoritos.</small>
    </div>`;
  document.body.append(dialog);

  const ui = {
    close: dialog.querySelector(".account-close"),
    title: dialog.querySelector("#account-title"),
    copy: dialog.querySelector("#account-copy"),
    profile: dialog.querySelector("#account-profile"),
    avatar: dialog.querySelector("#account-avatar"),
    name: dialog.querySelector("#account-name"),
    email: dialog.querySelector("#account-email"),
    status: dialog.querySelector("#account-status"),
    message: dialog.querySelector("#account-message"),
    login: dialog.querySelector("#account-login"),
    logout: dialog.querySelector("#account-logout"),
    admin: dialog.querySelector("#account-admin"),
    gateSpinner: gate.querySelector("#gate-spinner"),
    gateTitle: gate.querySelector("#gate-title"),
    gateCopy: gate.querySelector("#gate-copy"),
    gateProfile: gate.querySelector("#gate-profile"),
    gateAvatar: gate.querySelector("#gate-avatar"),
    gateName: gate.querySelector("#gate-name"),
    gateEmail: gate.querySelector("#gate-email"),
    gateStatus: gate.querySelector("#gate-status"),
    gateMessage: gate.querySelector("#gate-message"),
    gateLogin: gate.querySelector("#gate-login"),
    gateLogout: gate.querySelector("#gate-logout"),
  };
  const adminNavLinks = [...document.querySelectorAll(".admin-nav-link")];

  function snapshot() {
    return { user: currentUser, profile: currentProfile, error: bootError };
  }

  function emit() {
    render();
    const detail = snapshot();
    listeners.forEach((listener) => listener(detail));
    window.dispatchEvent(new CustomEvent("gil-auth-change", { detail }));
  }

  function statusLabel(status) {
    return { ACTIVE: "Activa", PENDING: "Pendiente", SUSPENDED: "Suspendida" }[status] || status || "";
  }

  function setMessage(message, tone = "error") {
    [ui.message, ui.gateMessage].forEach((element) => {
      element.hidden = !message;
      element.textContent = message || "";
      element.dataset.tone = tone;
    });
  }

  function render() {
    const signedIn = Boolean(currentUser);
    const profile = currentProfile;
    const canAdmin = profile?.role === "ADMIN" && profile?.status === "ACTIVE";
    trigger.classList.toggle("signed-in", signedIn);
    trigger.querySelector("span").textContent = profile?.displayName?.split(" ")[0] || (signedIn ? "Cuenta" : "Ingresar");
    if (signedIn && profile?.photoURL) {
      trigger.style.setProperty("--avatar", `url("${String(profile.photoURL).replace(/["\\]/g, "")}")`);
      trigger.classList.add("has-avatar");
    } else {
      trigger.style.removeProperty("--avatar");
      trigger.classList.remove("has-avatar");
    }
    ui.profile.hidden = !signedIn;
    ui.login.hidden = signedIn;
    ui.logout.hidden = !signedIn;
    ui.admin.hidden = !canAdmin;
    adminNavLinks.forEach((link) => { link.hidden = !canAdmin; });
    if (signedIn) {
      ui.name.textContent = profile?.displayName || currentUser.displayName || "Cuenta Google";
      ui.email.textContent = profile?.email || currentUser.email || "";
      ui.status.textContent = statusLabel(profile?.status);
      ui.status.dataset.status = profile?.status || "PENDING";
      ui.avatar.src = profile?.photoURL || currentUser.photoURL || "";
      ui.avatar.hidden = !ui.avatar.src;
      ui.title.textContent = profile?.status === "ACTIVE" ? "Tu cuenta está sincronizada." : "Tu acceso está pendiente.";
      ui.copy.textContent = profile?.status === "ACTIVE"
        ? "Tus favoritos se guardan de forma privada y aparecen en cualquier dispositivo donde ingreses."
        : "Un administrador debe aprobar la cuenta antes de que puedas guardar favoritos.";
    } else {
      ui.title.textContent = "Tus favoritos, en cualquier dispositivo.";
      ui.copy.textContent = "Ingresa con Google para guardar una lista privada. Las cuentas nuevas deben ser aprobadas por un administrador.";
    }
    renderGate();
  }

  function renderGate() {
    const profile = currentProfile;
    const signedIn = Boolean(currentUser);
    const active = profile?.status === "ACTIVE";
    const loading = !bootComplete || (signedIn && !profile && !bootError);
    document.documentElement.classList.toggle("auth-granted", active);
    gate.hidden = active;
    if (active) return;
    ui.gateSpinner.hidden = !loading;
    ui.gateLogin.hidden = loading || signedIn || Boolean(bootError);
    ui.gateLogout.hidden = !signedIn;
    ui.gateProfile.hidden = !signedIn;
    if (signedIn) {
      ui.gateName.textContent = profile?.displayName || currentUser.displayName || "Cuenta Google";
      ui.gateEmail.textContent = profile?.email || currentUser.email || "";
      ui.gateStatus.textContent = statusLabel(profile?.status || "PENDING");
      ui.gateStatus.dataset.status = profile?.status || "PENDING";
      ui.gateAvatar.src = profile?.photoURL || currentUser.photoURL || "";
      ui.gateAvatar.hidden = !ui.gateAvatar.src;
    }
    if (loading) {
      ui.gateTitle.textContent = "Comprobando tu sesión.";
      ui.gateCopy.textContent = "Estamos validando tu acceso de forma segura.";
    } else if (bootError) {
      ui.gateTitle.textContent = "El acceso no está disponible.";
      ui.gateCopy.textContent = "No mostramos la aplicación cuando no podemos comprobar la identidad.";
    } else if (!signedIn) {
      ui.gateTitle.textContent = "Ingresa para ver Gil Intelligence.";
      ui.gateCopy.textContent = "El mercado, las proyecciones y tus favoritos requieren una cuenta Google aprobada.";
    } else if (profile?.status === "SUSPENDED") {
      ui.gateTitle.textContent = "Tu cuenta está suspendida.";
      ui.gateCopy.textContent = "Un administrador debe reactivarla antes de que puedas volver a entrar.";
    } else {
      ui.gateTitle.textContent = "Tu acceso está pendiente.";
      ui.gateCopy.textContent = "La cuenta ya fue registrada. Un administrador debe aprobarla para mostrar la aplicación.";
    }
  }

  async function request(path, options = {}, retry = true) {
    if (!currentUser) throw apiError("authentication_required", 401);
    const token = await currentUser.getIdToken(false);
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
        Authorization: `Bearer ${token}`,
      },
    });
    if (response.status === 401 && retry) {
      await currentUser.getIdToken(true);
      return request(path, options, false);
    }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw apiError(payload.error || "request_failed", response.status, payload.detail);
    return payload;
  }

  async function data(path) {
    await ready;
    if (bootError) throw bootError;
    if (currentProfile?.status !== "ACTIVE") {
      throw apiError(currentUser ? "account_pending" : "authentication_required", 403);
    }
    return request(path);
  }

  function apiError(code, status, detail) {
    const error = new Error(detail || code);
    error.code = code;
    error.status = status;
    return error;
  }

  function friendlyError(error) {
    const messages = {
      account_pending: "Tu cuenta todavía está esperando aprobación.",
      account_suspended: "Esta cuenta fue suspendida.",
      authentication_required: "Ingresa con Google para continuar.",
      auth_config_unavailable: "El acceso con Google todavía no está disponible.",
      "auth/popup-closed-by-user": "Se cerró la ventana de Google antes de completar el ingreso.",
      "auth/popup-blocked": "El navegador bloqueó la ventana de Google. Habilita ventanas emergentes e inténtalo otra vez.",
      "auth/operation-not-allowed": "El acceso con Google todavía no está habilitado para este proyecto.",
      "auth/unauthorized-domain": "Este dominio todavía no está autorizado para iniciar sesión.",
    };
    if (error instanceof TypeError) return "No pudimos conectar con el servicio de cuentas.";
    return messages[error?.code] || error?.message || "No pudimos completar la operación.";
  }

  async function syncProfile() {
    currentProfile = await request("/v1/auth/register", { method: "POST", body: "{}" });
    await currentUser.getIdToken(true);
    emit();
    return currentProfile;
  }

  async function login() {
    if (!firebaseAuth || !authSdk) throw apiError("auth_config_unavailable", 503);
    setMessage("");
    ui.login.disabled = true;
    ui.gateLogin.disabled = true;
    try {
      const provider = new authSdk.GoogleAuthProvider();
      provider.setCustomParameters({ prompt: "select_account" });
      const result = await authSdk.signInWithPopup(firebaseAuth, provider);
      currentUser = result.user;
      await syncProfile();
    } catch (error) {
      setMessage(friendlyError(error));
      throw error;
    } finally {
      ui.login.disabled = false;
      ui.gateLogin.disabled = false;
    }
  }

  async function logout() {
    if (firebaseAuth && authSdk) await authSdk.signOut(firebaseAuth);
    currentUser = null;
    currentProfile = null;
    setMessage("");
    emit();
  }

  async function boot() {
    try {
      const configResponse = await fetch(`${API_BASE}/v1/auth/config`, { cache: "no-store" });
      const runtime = await configResponse.json();
      if (!configResponse.ok || !runtime.enabled || !runtime.firebase) throw apiError("auth_config_unavailable", 503);
      const [appSdk, loadedAuthSdk] = await Promise.all([
        import(`https://www.gstatic.com/firebasejs/${FIREBASE_VERSION}/firebase-app.js`),
        import(`https://www.gstatic.com/firebasejs/${FIREBASE_VERSION}/firebase-auth.js`),
      ]);
      authSdk = loadedAuthSdk;
      firebaseAuth = authSdk.getAuth(appSdk.initializeApp(runtime.firebase));
      await authSdk.setPersistence(firebaseAuth, authSdk.browserLocalPersistence);
      await new Promise((resolve) => authSdk.onAuthStateChanged(firebaseAuth, async (user) => {
        currentUser = user;
        currentProfile = null;
        if (user) {
          try { await syncProfile(); }
          catch (error) { setMessage(friendlyError(error)); }
        }
        emit();
        resolve();
      }));
    } catch (error) {
      bootError = error;
      setMessage(friendlyError(error));
      emit();
    } finally {
      bootComplete = true;
      emit();
      resolveReady(snapshot());
    }
  }

  trigger.addEventListener("click", () => dialog.showModal());
  ui.close.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  ui.login.addEventListener("click", () => void login().catch(() => {}));
  ui.logout.addEventListener("click", () => void logout());
  ui.gateLogin.addEventListener("click", () => void login().catch(() => {}));
  ui.gateLogout.addEventListener("click", () => void logout());

  window.GilAuth = {
    ready,
    request,
    data,
    login,
    logout,
    open: () => dialog.showModal(),
    reportError: (error) => { setMessage(friendlyError(error)); dialog.showModal(); },
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    get user() { return currentUser; },
    get profile() { return currentProfile; },
  };
  render();
  void boot();
})();
