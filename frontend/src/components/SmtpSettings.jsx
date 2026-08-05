import { useEffect, useState } from "react";
import { getSmtpSettings, sendTestEmail, updateSmtpSettings } from "../api.js";
import { toast } from "../toast.js";
import { useT } from "../i18n.jsx";

// Giden e-posta (SMTP). Tek kullanıcısı "şifremi unuttum": yeni parola
// kullanıcının kendi kutusuna gönderilir. Kapalıysa sıfırlama da kapalıdır —
// parolayı iletemeden değiştirmek kullanıcıyı hesabından kilitlerdi.
// Parola config'e YAZILMAZ, .secrets.env'e gider (sunucudan hiç dönmez).
export default function SmtpSettings() {
  const t = useT();
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [password, setPassword] = useState("");
  const [testTo, setTestTo] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState(null);

  function load() {
    getSmtpSettings()
      .then((d) => {
        setData(d);
        setForm({
          enabled: d.enabled,
          host: d.host || "",
          port: d.port ?? 587,
          security: d.security || "starttls",
          username: d.username || "",
          from_address: d.from_address || "",
          from_name: d.from_name || "Vantage",
        });
      })
      .catch((e) => setError(e.message));
  }
  useEffect(load, []);

  if (error && !data) return <div className="login-error">{error}</div>;
  if (!form) return <p className="desc">{t("Yükleniyor…")}</p>;

  const upd = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  async function save(e) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const payload = { ...form, port: Number(form.port) };
      // Sır YALNIZCA yeni girildiyse gönderilir (boş göndermek mevcudu silerdi).
      if (password.trim()) payload.password = password.trim();
      await updateSmtpSettings(payload);
      setPassword("");
      toast(t("E-posta ayarları kaydedildi"), "ok");
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function test() {
    setError(null);
    setTesting(true);
    try {
      const res = await sendTestEmail(testTo.trim());
      toast(t("Deneme e-postası gönderildi: {to}", { to: res.to }), "ok");
    } catch (err) {
      // Sebep burada AÇIKÇA gösterilir: bu ekran yalnız yöneticiye açık ve
      // "gönderilemedi" tek başına teşhis için yetersiz.
      setError(err.message);
    } finally {
      setTesting(false);
    }
  }

  return (
    <section className="section">
      <div className="section-head">
        <h2>{t("E-posta (SMTP)")}</h2>
        <span className={`key-pill ${data?.ready ? "on" : "off"}`}>
          {data?.ready ? t("hazır") : t("kurulmadı")}
        </span>
      </div>
      <p className="desc">
        {t("Şifremi unuttum akışı bunu kullanır: yeni geçici parola kullanıcının kendi e-posta adresine gönderilir, ekranda gösterilmez. Kapalıyken kullanıcılar parolalarını kendileri sıfırlayamaz — yalnızca yönetici sıfırlayabilir.")}
      </p>

      <form className="admin-form" onSubmit={save}>
        <label className="switch-row span-2">
          <input type="checkbox" checked={form.enabled}
                 onChange={(e) => upd("enabled", e.target.checked)} />
          <span>
            <strong>{t("E-posta gönderimi açık")}</strong>
            <em>{t("Kapalıyken kullanıcılar \"şifremi unuttum\" ile parola sıfırlayamaz.")}</em>
          </span>
        </label>

        <label>{t("Sunucu (host)")}
          <input value={form.host} onChange={(e) => upd("host", e.target.value)}
                 placeholder="smtp.sirket.local" />
        </label>
        <label>{t("Port")}
          <input type="number" min={1} max={65535} value={form.port}
                 onChange={(e) => upd("port", e.target.value)} />
          <span className="field-hint">{t("STARTTLS için 587, SSL için 465.")}</span>
        </label>
        <label>{t("Güvenlik")}
          <select value={form.security} onChange={(e) => upd("security", e.target.value)}>
            {(data?.security_options || ["starttls", "ssl", "none"]).map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
        <label>{t("Kullanıcı adı")}
          <input value={form.username} onChange={(e) => upd("username", e.target.value)}
                 autoComplete="off" placeholder="vantage@sirket.local" />
          <span className="field-hint">{t("İç relay kimlik doğrulaması istemiyorsa boş bırakın.")}</span>
        </label>
        <label>{t("Parola")}
          <input type="password" autoComplete="new-password" value={password}
                 onChange={(e) => setPassword(e.target.value)}
                 placeholder={data?.password?.configured
                   ? t("•••• (tanımlı — değiştirmek için yaz)")
                   : t("değiştirmek için gir · boş = dokunma")} />
          <span className="field-hint">{t("Config dosyasına yazılmaz; .secrets.env'e gider.")}</span>
        </label>
        <label>{t("Gönderen adresi")}
          <input value={form.from_address} onChange={(e) => upd("from_address", e.target.value)}
                 placeholder="vantage@sirket.local" />
          <span className="field-hint">{t("Boşsa kullanıcı adı kullanılır.")}</span>
        </label>
        <label>{t("Gönderen adı")}
          <input value={form.from_name} onChange={(e) => upd("from_name", e.target.value)} />
        </label>

        <button type="submit" className="login-btn" disabled={saving}>
          {saving ? t("Kaydediliyor…") : t("E-posta ayarlarını kaydet")}
        </button>
      </form>

      <div className="ca-row" style={{ marginTop: 12 }}>
        <input value={testTo} onChange={(e) => setTestTo(e.target.value)}
               placeholder={t("Deneme adresi (boşsa kendi adresiniz)")} />
        <button className="mini" onClick={test} disabled={testing || !data?.ready}
                title={data?.ready ? "" : t("Önce ayarları kaydedin")}>
          {testing ? t("Gönderiliyor…") : t("Deneme e-postası gönder")}
        </button>
      </div>
      <p className="field-hint">{t("Deneme, KAYDEDİLMİŞ ayarları kullanır — önce kaydedin.")}</p>

      {error && <div className="login-error">{error}</div>}
    </section>
  );
}
