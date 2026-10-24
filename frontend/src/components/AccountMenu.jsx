import { useEffect, useRef, useState } from "react";

// Small account chip next to the other corner buttons: who is playing, the weekly report, log out.
export default function AccountMenu({ user, onReport, onLogout }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const close = (event) => {
      if (event.type === "keydown" ? event.key === "Escape" : !rootRef.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  return (
    <div className="account-menu" ref={rootRef}>
      <button type="button" className="account-menu__chip" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="menu">
        <span aria-hidden="true">👤</span> {user.username}
      </button>
      {open && (
        <div className="account-menu__list" role="menu">
          {!user.guest && (
            <button type="button" role="menuitem" onClick={() => { setOpen(false); onReport(); }}>
              📊 Weekly report
            </button>
          )}
          <button type="button" role="menuitem" onClick={() => { setOpen(false); onLogout(); }}>
            {user.guest ? "🔑 Log in / sign up" : "⎋ Log out"}
          </button>
        </div>
      )}
    </div>
  );
}
