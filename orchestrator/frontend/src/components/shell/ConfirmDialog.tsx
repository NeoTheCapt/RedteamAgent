import { useEffect, useRef } from "react";
import "./ConfirmDialog.css";

type ConfirmDialogProps = {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  destructive?: boolean;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
};

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  destructive = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDialogElement | null>(null);

  useEffect(() => {
    const d = dialogRef.current;
    if (!d) return;
    if (open && !d.open) {
      try { d.showModal(); } catch { d.setAttribute("open", ""); }
    }
    if (!open && d.open) {
      try { d.close(); } catch { d.removeAttribute("open"); }
    }
  }, [open]);

  function handleKey(e: React.KeyboardEvent<HTMLDialogElement>) {
    if (e.key === "Escape") {
      e.preventDefault();
      onCancel();
    }
  }

  return (
    <dialog
      className="confirm-dialog"
      ref={dialogRef}
      onKeyDown={handleKey}
      aria-labelledby="confirm-dialog-title"
      aria-describedby="confirm-dialog-msg"
    >
      <h2 id="confirm-dialog-title" className="confirm-dialog__title">{title}</h2>
      <p id="confirm-dialog-msg" className="confirm-dialog__msg">{message}</p>
      <footer className="confirm-dialog__foot">
        <button type="button" className="confirm-dialog__cancel" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className={`confirm-dialog__confirm ${destructive ? "confirm-dialog__confirm--danger" : ""}`}
          onClick={() => void onConfirm()}
        >
          {confirmLabel}
        </button>
      </footer>
    </dialog>
  );
}
