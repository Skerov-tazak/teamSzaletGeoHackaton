// A local account (no backend yet): the profile lives in localStorage.
// The identifier is the e-mail; the password is not stored, only a SHA-256 hash of it.

const KEY = "fup.account.v1";

export interface LocalAccount {
  name: string;
  email: string;
}

interface StoredAccount extends LocalAccount {
  passwordHash: string;
}

async function hash(password: string): Promise<string> {
  const bytes = new TextEncoder().encode(password);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function read(): StoredAccount | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as StoredAccount) : null;
  } catch {
    return null;
  }
}

export function currentAccount(): LocalAccount | null {
  const stored = read();
  return stored ? { name: stored.name, email: stored.email } : null;
}

function normalise(identifier: string): string {
  return identifier.trim().toLowerCase();
}

/** Sign up with the e-mail as the identifier. */
export async function register(email: string, password: string): Promise<LocalAccount> {
  const cleanEmail = email.trim();
  try {
    if (cleanEmail.length === 0) throw new Error("Podaj e-mail.");
    if (password.length < 6) throw new Error("Hasło musi mieć co najmniej 6 znaków.");
    const account: StoredAccount = { name: cleanEmail, email: cleanEmail, passwordHash: await hash(password) };
    localStorage.setItem(KEY, JSON.stringify(account));
  } catch (error) {
    if (error instanceof DOMException) throw new Error("Nie można zapisać konta lokalnie (localStorage zablokowany).");
    throw error;
  }
  return { name: cleanEmail, email: cleanEmail };
}

/** Sign in with the e-mail and the password. */
export async function login(identifier: string, password: string): Promise<LocalAccount> {
  const stored = read();
  const wanted = normalise(identifier);
  const matches =
    stored !== null && (normalise(stored.email) === wanted || normalise(stored.name) === wanted);
  if (!matches || stored.passwordHash !== (await hash(password))) {
    throw new Error("Nieprawidłowy e-mail lub hasło.");
  }
  return { name: stored.name, email: stored.email };
}

export function isLoggedIn(): boolean {
  return read() !== null;
}

export function logout(): void {
  localStorage.removeItem(KEY);
}