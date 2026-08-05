import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useT } from "../i18n.jsx";

// Kurulum kontrol listesi: admin ne yapacağını tek bakışta görsün.
export default function OnboardingPanel({ onGoto }) {
  const t = useT();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api("/api/admin/onboarding").then(setData).catch(setError);
  }, []);

  if (error) return <p className="error-inline">{error.message}</p>;
  if (!data) return <p className="desc">{t("Yükleniyor…")}</p>;

  return (
    <section className="section">
      <h2>{t("Başlangıç")} {data.complete ? "✓" : ""}</h2>
      <p className="desc">
        {data.complete
          ? t("Kurulum tamam — sistem gerçek veriyle çalışmaya hazır.")
          : t("Sistemi gerçek veriyle çalıştırmak için aşağıdaki adımları tamamla.")}
      </p>
      <ol className="onboarding">
        {data.steps.map((s, i) => (
          <li key={s.key} className={s.done ? "done" : "todo"}>
            <span className="ob-mark">{s.done ? "✓" : i + 1}</span>
            <div>
              <div className="ob-label">{s.label}</div>
              <div className="ob-hint">{s.hint}</div>
            </div>
          </li>
        ))}
      </ol>
      {data.unlinked > 0 && (
        <p className="desc">
          <strong>{data.unlinked}</strong> {t('hesabın git e-postası eksik — kişi-bazlı kod analizi için "AI Kod Analizi" sekmesinden bağla.')}
          {onGoto && <> <button className="mini" onClick={() => onGoto("code")}>{t("Git kimliğini bağla →")}</button></>}
        </p>
      )}
    </section>
  );
}
