import { FormEvent, useState } from "react";

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
    <main className="shell auth-shell">
      <section className="hero-card">
        <p className="eyebrow">Redteam Orchestrator</p>
        <h1>Multi-user red team control plane</h1>
        <p className="lead">
          Sign in to manage isolated projects, follow live workflow phases, and inspect every
          engagement artifact without leaving the browser.
        </p>
      </section>
      <section className="panel auth-panel">
        <div className="panel-header">
          <h2>{mode === "login" ? "Sign in" : "Create first user"}</h2>
          <button
            type="button"
            className="ghost-button"
            onClick={() => {
              setError(null);
              setMode((current) => (current === "login" ? "register" : "login"));
            }}
          >
            {mode === "login" ? "Need an account?" : "Already have an account?"}
          </button>
        </div>
        <form onSubmit={handleSubmit} className="stack">
          <label className="field">
            <span>Username</span>
            <input value={username} onChange={(event) => setUsername(event.target.value)} required />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              minLength={mode === "register" ? 8 : 1}
              required
            />
          </label>
          {mode === "register" ? <p className="muted-text">Password must be at least 8 characters.</p> : null}
          {error ? <p className="error-text">{error}</p> : null}
          <button type="submit" className="primary-button" disabled={submitting}>
            {submitting ? "Working..." : mode === "login" ? "Sign in" : "Create user"}
          </button>
        </form>
      </section>
    </main>
  );
}
