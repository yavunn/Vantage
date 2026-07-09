import { useState } from "react";
import { changePassword } from "../api.js";
import Modal from "./Modal.jsx";

// Çalışanın kendi parolasını değiştirmesi.
export default function ChangePassword({ onClose }) {
  const [cur, setCur] = useState("");
  const [nw, setNw] = useState("");
  const [nw2, setNw2] = useState("");
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    if (nw.length < 6) {
      setError("Yeni parola en az 6 karakter olmalı");
      return;
    }
    if (nw !== nw2) {
      setError("Yeni parolalar eşleşmiyor");
      return;
    }
    try {
      await changePassword(cur, nw);
      setDone(true);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <Modal title="Parola değiştir" onClose={onClose}>
      {done ? (
        <>
          <div className="admin-ok">Parola güncellendi.</div>
          <button className="login-btn" onClick={onClose}>Kapat</button>
        </>
      ) : (
        <form onSubmit={submit}>
          <label>
            Mevcut parola
            <input type="password" value={cur} onChange={(e) => setCur(e.target.value)} required />
          </label>
          <label>
            Yeni parola
            <input type="password" value={nw} onChange={(e) => setNw(e.target.value)} minLength={6} required />
          </label>
          <label>
            Yeni parola (tekrar)
            <input type="password" value={nw2} onChange={(e) => setNw2(e.target.value)} minLength={6} required />
          </label>
          {error && <div className="login-error">{error}</div>}
          <div className="modal-actions">
            <button type="button" className="mini ghost" onClick={onClose}>Vazgeç</button>
            <button type="submit" className="login-btn">Kaydet</button>
          </div>
        </form>
      )}
    </Modal>
  );
}
