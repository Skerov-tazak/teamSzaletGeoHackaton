// Local account UI: sign in / sign up / sign out. No backend call yet — the profile lives in
// localStorage (see ../account.ts). It gates nothing: every section opens without an account.
// Two inputs only: "E-mail lub nazwa użytkownika" and "Hasło"; "Załóż konto" creates the account.

import { currentAccount, isLoggedIn, login, logout, register } from "../account";
import type { AppContext } from "../app-context";
import { byId, el } from "../ui/dom";

export function initAccount(ctx: AppContext): void {
  const dialog = byId<HTMLDialogElement>("account-dialog");
  const form = byId<HTMLFormElement>("account-form");
  const identifierInput = byId<HTMLInputElement>("account-identifier");
  const passwordInput = byId<HTMLInputElement>("account-password");
  const message = byId("account-message");
  const submit = byId<HTMLButtonElement>("account-submit");
  const registerButton = byId<HTMLButtonElement>("account-register");
  const logoutButton = byId<HTMLButtonElement>("account-logout");
  const button = byId<HTMLButtonElement>("account-button");

  const showError = (text: string): void => {
    message.replaceChildren(el("span", "error", text));
  };

  const renderUser = (): void => {
    const account = currentAccount();
    button.textContent = account ? account.name : "Konto";
    button.classList.toggle("is-logged-in", account !== null);
    ctx.shell.emit("user:changed", { name: account ? account.name : null });
  };

  const open = (): void => {
    const signedIn = isLoggedIn();
    form.hidden = signedIn;
    logoutButton.hidden = !signedIn;
    message.textContent = "";
    if (!signedIn) {
      identifierInput.focus();
    }
    dialog.showModal();
  };

  button.addEventListener("click", open);
  byId<HTMLButtonElement>("account-close").addEventListener("click", () => dialog.close());

  ctx.shell.on("user:changed", ({ name }) => {
    byId("account-label").textContent = name ? `Konto: ${name}` : "Konto";
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const identifier = identifierInput.value.trim();
    const password = passwordInput.value;
    if (!identifier) {
      showError("Podaj e-mail lub nazwę użytkownika.");
      return;
    }
    message.textContent = "";
    login(identifier, password)
      .then(() => {
        renderUser();
        dialog.close();
        form.reset();
      })
      .catch((error: unknown) => showError(error instanceof Error ? error.message : String(error)));
  });

  registerButton.addEventListener("click", () => {
    const identifier = identifierInput.value.trim();
    const password = passwordInput.value;
    if (!identifier) {
      showError("Podaj e-mail lub nazwę użytkownika.");
      return;
    }
    message.textContent = "";
    register(identifier, password)
      .then(() => {
        renderUser();
        dialog.close();
        form.reset();
      })
      .catch((error: unknown) => showError(error instanceof Error ? error.message : String(error)));
  });

  logoutButton.addEventListener("click", () => {
    logout();
    renderUser();
    dialog.close();
  });

  renderUser();
}