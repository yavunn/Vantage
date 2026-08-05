import { useEffect, useState } from "react";
import { getSettings, updateSettings } from "../api.js";
import { toast } from "../toast.js";
import { useT } from "../i18n.jsx";

// Kimlik görünürlüğü — hesapların yanında durur, çünkü "kimin adı görünsün"
// bir hesap/İK kararıdır. Eşik ve kural değerleri BİLİNÇLİ olarak burada yok:
// onlar yöneticinin bilebileceği sayılar değil, sistemin kendi çıkarması gereken
// şeyler.
export default function VisibilitySettings() {
  const t = useT();
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getSettings().then((d) => setForm(d.app)).catch(() => setForm(null));
  }, []);

  if (!form) return null;

  async function save(e) {
    e.preventDefault();
    setSaving(true);
    try {
      await updateSettings({
        individual_view_enabled: form.individual_view_enabled,
        anonymize_individuals: form.anonymize_individuals,
      });
      toast(t("Görünürlük ayarları kaydedildi"), "ok");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setSaving(false);
    }
  }

  const upd = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <section className="section">
      <h2>{t("Görünürlük ve gizlilik")}</h2>
      <p className="desc">
        {t("Bu iki anahtar ürünün etik çerçevesini belirler ve İK talebiyle değişebilir.")}
      </p>
      <form onSubmit={save}>
        <label className="switch-row">
          <input type="checkbox" checked={form.individual_view_enabled}
                 onChange={(e) => upd("individual_view_enabled", e.target.checked)} />
          <span>
            <strong>{t("Bireysel görünüm açık")}</strong>
            <em>{t("Kapalıyken kişisel sayfa kimseye görünmez — kişinin kendisine bile.")}</em>
          </span>
        </label>
        <label className="switch-row">
          <input type="checkbox" checked={form.anonymize_individuals}
                 onChange={(e) => upd("anonymize_individuals", e.target.checked)} />
          <span>
            <strong>{t("Anonimleştirme modu")}</strong>
            <em>{t('Açıkken isimler maskelenir ("Geliştirici #7") ve bireysel uçlar kapanır.')}</em>
          </span>
        </label>
        <div className="settings-actions">
          <button className="login-btn" type="submit" disabled={saving}>
            {saving ? t("Kaydediliyor…") : t("Görünürlüğü kaydet")}
          </button>
        </div>
      </form>
    </section>
  );
}
