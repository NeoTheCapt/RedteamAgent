import { FormEvent, useState } from "react";
import "./LoginPage.css";

type LoginPageProps = {
  onLogin: (username: string, password: string) => Promise<void>;
  onRegister: (username: string, password: string) => Promise<void>;
};

export function LoginPage({ onLogin, onRegister }: LoginPageProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [mode, setMode] = useState<"login" | "register">("login");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      if (mode === "login") {
        await onLogin(username, password);
      } else {
        await onRegister(username, password);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : `${mode} failed`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login">
      <section className="login__hero">
        <div className="login__brand">RED<span>TEAM</span></div>
        <p className="login__eyebrow">Orchestrator</p>
        <h1 className="login__title">Multi-user red team control plane</h1>
        <p className="login__lead">
          Sign in to manage isolated projects, follow live workflow phases,
          and inspect every engagement artifact without leaving the browser.
        </p>
      </section>
      <section className="login__panel">
        <header className="login__panel-head">
          <h2 className="login__h2">{mode === "login" ? "Sign in" : "Create first user"}</h2>
          <button
            type="button"
            className="login__switch"
            onClick={() => {
              setError(null);
              setMode((current) => (current === "login" ? "register" : "login"));
            }}
          >
            {mode === "login" ? "Need an account?" : "Already have an account?"}
          </button>
        </header>
        <form onSubmit={handleSubmit} className="login__form">
          <label className="login__field">
            <span className="login__label">Username</span>
            <input
              className="login__input"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
              autoFocus
            />
          </label>
          <label className="login__field">
            <span className="login__label">Password</span>
            <input
              className="login__input"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              minLength={mode === "register" ? 8 : 1}
              required
            />
          </label>
          {mode === "register" && (
            <p className="login__hint">Password must be at least 8 characters.</p>
          )}
          {error && <p className="login__error" role="alert">{error}</p>}
          <button type="submit" className="login__submit" disabled={submitting}>
            {submitting ? "Working..." : mode === "login" ? "Sign in" : "Create user"}
          </button>
        </form>
      </section>
    </main>
  );
}
