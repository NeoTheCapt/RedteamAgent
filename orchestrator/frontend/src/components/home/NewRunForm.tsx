import type { Project } from "../../lib/api";

type NewRunFormProps = {
  projects: Project[];
  onCreateRun: (projectId: number, target: string) => Promise<void>;
};

// Stub — full implementation in Task C1.
export function NewRunForm({ projects, onCreateRun: _onCreateRun }: NewRunFormProps) {
  return (
    <div style={{ color: "var(--c-text-muted)" }}>
      NewRunForm — implemented in Task C1. Projects: {projects.length}
    </div>
  );
}
