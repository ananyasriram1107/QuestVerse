import { useState } from "react";
import { login, register } from "../api";

// The login / create-account page shown before anything else. Passwords go straight to the
// server (which stores only a salted hash); nothing about the password is kept in the browser.
export default function AuthScreen({ onAuthed, onGuest, notice }) {
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ username: "", password: "", email: "" });
  const [state, setState] = useState({ busy: false, error: null });
  const creating = mode === "register";

  const update = (field) => (event) => setForm((prev) => ({ ...prev, [field]: event.target.value }));

  async function submit(event) {
    event.preventDefault();
    if (state.busy) return;
    setState({ busy: true, error: null });
    try {
      const user = creating
        ? await register(form.username.trim(), form.password, form.email.trim())
        : await login(form.username.trim(), form.password);
      onAuthed(user);
    } catch (error) {
      setState({ busy: false, error: error.message });
    }
  }

  return (
    <main className="auth-screen">
      <form className="auth-card" onSubmit={submit}>
        <p className="eyebrow">Adaptive Learning Quest</p>
        <h1>QuestVerse</h1>

        <div className="auth-tabs" role="tablist">
          {[["login", "Log in"], ["register", "Create account"]].map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={mode === id}
              className={mode === id ? "is-active" : ""}
              onClick={() => setMode(id)}
            >
              {label}
            </button>
          ))}
        </div>

        {notice && <p className="auth-note">{notice}</p>}

        <label>
          Username
          <input
            value={form.username}
            onChange={update("username")}
            autoComplete="username"
            autoFocus
            required
            minLength={3}
            maxLength={32}
          />
        </label>

        <label>
          Password
          <input
            type="password"
            value={form.password}
            onChange={update("password")}
            autoComplete={creating ? "new-password" : "current-password"}
            required
            minLength={creating ? 8 : 1}
          />
          {creating && <small>At least 8 characters.</small>}
        </label>

        {creating && (
          <label>
            Email <em>(optional, for your weekly progress update)</em>
            <input type="email" value={form.email} onChange={update("email")} autoComplete="email" />
          </label>
        )}

        {state.error && (
          <p className="auth-error" role="alert">
            {state.error}
          </p>
        )}

        <button type="submit" className="auth-submit" disabled={state.busy}>
          {state.busy ? "One moment…" : creating ? "Create account" : "Log in"} <span aria-hidden="true">→</span>
        </button>

        {onGuest && (
          <button type="button" className="auth-guest" onClick={onGuest}>
            Play offline without an account
          </button>
        )}
      </form>
    </main>
  );
}
