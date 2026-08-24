import { useEffect, useMemo, useState } from "react";
import {
  decideDocument, deleteDocument, documentChecklist, documentSummary, documentTypes,
  downloadDocument, leavesByUser, listDocuments, listEmployees, myDocumentSummary,
  myLeaveRequests, uploadDocument,
} from "../api.js";
import { monthKey } from "../dates.js";
import { useT } from "../i18n.jsx";
import { toast } from "../toast.js";

// Bordro / özlük evrakı paneli.
//
// İKİ AYRI EKRAN, TEK BİLEŞEN: çalışan "benim evraklarım"ı görür (kendi eksik
// listesi + yükleme formu); admin/İK ayrıca inceleme kuyruğunu, dönem özetini
// ve kimde ne eksik tablosunu görür. Rol ayrımı sunucuda da zorlanır (403);
// buradaki gizleme kolaylıktır, güvenlik sınırı değil.
//
// TÜR KATALOĞU SUNUCUDAN: hangi belgenin bordroyu etkilediği, hangisinin dönem
// ya da tarih istediği mevzuata bağlı — burada sabitlenirse iki kaynak ayrışır.
//
// İZİN (Leave) SENKRONU: "izin" kategorisindeki bir belge (rapor, izin formu…)
// aynı başlangıç/bitiş tarihini taşır İzin panosundaki kayıtla. İki yerde ayrı
// ayrı YAZILMASIN diye: (a) var olan bir izin isteği seçilirse tarihler ordan
// gelir, elle tekrar girilmez; (b) hiçbiri seçilmezse belge onaylanınca ilgili
// izin kaydı KENDİLİĞİNDEN oluşur (bkz. backend decide_document). Sunucu bunu
// zorunlu kılar; burası yalnız aynı veriyi iki kere yazdırmayan bir kolaylık.

const STATUS_LABEL = { pending: "İncelemede", approved: "Kabul edildi", rejected: "Kabul edilmedi" };
const LEAVE_TYPE_LABEL = { annual: "Yıllık", sick: "Rapor", other: "Diğer" };

function fileSize(bytes) {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Yükleme formu — seçilen türe göre zorunlu alanlar açılır/kapanır. */
function UploadForm({ user, types, canManage, employees, onUploaded }) {
  const t = useT();
  const [docType, setDocType] = useState("");
  const [file, setFile] = useState(null);
  const [period, setPeriod] = useState(() => monthKey(new Date()));
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [note, setNote] = useState("");
  const [targetUser, setTargetUser] = useState("");
  const [leaveId, setLeaveId] = useState("");
  const [leaveOptions, setLeaveOptions] = useState([]);
  const [busy, setBusy] = useState(false);

  const meta = types.types?.find((x) => x.key === docType);
  const isLeaveDoc = meta?.category === "leave";

  // "İzin" kategorisi seçilince o kişinin izin isteklerini getir — var olan
  // bir kayda bağlanabilsin diye (aksi hâlde İK aynı tarihi burada da elle
  // yazardı). Kişi/tür değişince liste ve seçim sıfırlanır: eski seçim başka
  // birinin izin kaydına yanlışlıkla bağlı kalmasın.
  useEffect(() => {
    setLeaveId("");
    if (!isLeaveDoc) { setLeaveOptions([]); return; }
    const loader = canManage
      ? leavesByUser(targetUser ? Number(targetUser) : user.id)
      : myLeaveRequests();
    loader.then(setLeaveOptions).catch(() => setLeaveOptions([]));
  }, [isLeaveDoc, targetUser, canManage]);

  function pickLeave(id) {
    setLeaveId(id);
    const found = leaveOptions.find((l) => String(l.id) === id);
    if (found) { setStartDate(found.start_date); setEndDate(found.end_date); }
  }

  async function submit(e) {
    e.preventDefault();
    if (!file || !meta) return;
    setBusy(true);
    try {
      await uploadDocument(file, {
        doc_type: docType,
        period: meta.needs_period ? period : "",
        start_date: meta.needs_dates ? startDate : "",
        end_date: meta.needs_dates ? endDate : "",
        note,
        target_user_id: canManage ? targetUser : "",
        leave_id: isLeaveDoc ? leaveId : "",
      });
      toast(
        leaveId
          ? t("Belge yüklendi, İK incelemesine gönderildi. Onaylanınca bağlı izin kaydı da onaylanır.")
          : isLeaveDoc
            ? t("Belge yüklendi, İK incelemesine gönderildi. Onaylanınca izin takvimine otomatik işlenir.")
            : t("Belge yüklendi, İK incelemesine gönderildi."),
        "success"
      );
      setFile(null);
      setNote("");
      setStartDate("");
      setEndDate("");
      setLeaveId("");
      // Dosya girdisi kontrollü değil (güvenlik gereği value atanamaz); formu
      // sıfırlamak için DOM'dan temizlenir.
      e.target.reset();
      setDocType("");
      onUploaded();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="doc-upload" onSubmit={submit}>
      <div className="doc-upload-row">
        <label className="doc-field">
          <span>{t("Belge türü")}</span>
          <select value={docType} onChange={(e) => setDocType(e.target.value)} required>
            <option value="">{t("Seçiniz…")}</option>
            {types.categories?.map((cat) => (
              <optgroup key={cat.key} label={cat.label}>
                {types.types.filter((x) => x.category === cat.key).map((x) => (
                  <option key={x.key} value={x.key}>{x.label}</option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>

        <label className="doc-field">
          <span>{t("Dosya")}</span>
          <input type="file" onChange={(e) => setFile(e.target.files[0] || null)} required />
        </label>

        {canManage && (
          <label className="doc-field">
            <span>{t("Kimin adına")}</span>
            <select value={targetUser} onChange={(e) => setTargetUser(e.target.value)}>
              <option value="">{t("Kendim")}</option>
              {employees.filter((u) => u.is_active).map((u) => (
                <option key={u.id} value={u.id}>{u.display_name}</option>
              ))}
            </select>
          </label>
        )}
      </div>

      {/* Türe özel alanlar: neyin neden istendiği görünsün diye etki cümlesiyle. */}
      {meta && (
        <>
          <div className={`doc-effect${meta.affects_payroll ? " payroll" : ""}`}>
            {meta.affects_payroll && <strong>{t("Bordroyu etkiler")} · </strong>}
            {meta.effect}
          </div>
          <div className="doc-upload-row">
            {meta.needs_period && (
              <label className="doc-field">
                <span>{t("Bordro dönemi")}</span>
                <input type="month" value={period} onChange={(e) => setPeriod(e.target.value)} required />
              </label>
            )}
            {isLeaveDoc && (
              <label className="doc-field">
                <span>{t("İlgili izin kaydı")}</span>
                <select value={leaveId} onChange={(e) => pickLeave(e.target.value)}>
                  <option value="">{t("Bağlantısız (onaylanınca yeni izin kaydı oluşturulur)")}</option>
                  {leaveOptions.map((l) => (
                    <option key={l.id} value={l.id}>
                      {(l.start_date === l.end_date ? l.start_date : `${l.start_date} → ${l.end_date}`)}
                      {" · "}{t(LEAVE_TYPE_LABEL[l.leave_type]) || l.leave_type}
                      {" · "}{t(STATUS_LABEL[l.status]) || l.status}
                      {l.has_document ? ` · ${t("belge var")}` : ""}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {meta.needs_dates && (
              <>
                <label className="doc-field">
                  <span>{t("Başlangıç")}</span>
                  <input type="date" value={startDate} disabled={!!leaveId}
                         onChange={(e) => setStartDate(e.target.value)} required />
                </label>
                <label className="doc-field">
                  <span>{t("Bitiş")}</span>
                  <input type="date" value={endDate} disabled={!!leaveId}
                         onChange={(e) => setEndDate(e.target.value)} required />
                </label>
              </>
            )}
            <label className="doc-field grow">
              <span>{t("Açıklama (opsiyonel)")}</span>
              <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
            </label>
          </div>
          {leaveId && (
            <div className="field-hint">{t("Tarihler seçilen izin kaydından alınıyor.")}</div>
          )}
        </>
      )}

      <div className="doc-upload-actions">
        <button className="mini" type="submit" disabled={busy || !file || !docType}>
          {busy ? t("Yükleniyor…") : t("Yükle")}
        </button>
      </div>
    </form>
  );
}

/** Tek belge satırı — indirme, karar, silme. */
function DocumentRow({ doc, onChanged }) {
  const t = useT();
  const [busy, setBusy] = useState(false);

  async function run(fn) {
    setBusy(true);
    try {
      await fn();
      onChanged();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  function decide(decision) {
    // Redde gerekçe ZORUNLU (sunucu da zorlar): çalışan neyi düzeltmesi
    // gerektiğini bilmeden aynı belgeyi tekrar yükler.
    let note = "";
    if (decision === "rejected") {
      note = (window.prompt(t("Kabul edilmeme gerekçesi (çalışan görecek):")) || "").trim();
      if (!note) return;
    }
    run(() => decideDocument(doc.id, decision, note));
  }

  const span = doc.start_date
    ? (doc.start_date === doc.end_date ? doc.start_date : `${doc.start_date} → ${doc.end_date}`)
    : null;

  return (
    <li className={`doc-item ${doc.status}`}>
      <div className="doc-item-main">
        <div className="doc-item-top">
          <strong>{doc.doc_label}</strong>
          {doc.affects_payroll && <span className="doc-badge payroll">{t("Bordro")}</span>}
          <span className={`doc-badge ${doc.status}`}>{t(STATUS_LABEL[doc.status])}</span>
          {!doc.own && <span className="doc-person">{doc.person}</span>}
        </div>
        <div className="doc-item-meta">
          {doc.period && <span>{doc.period}</span>}
          {span && <span>{span}</span>}
          <span>{doc.file_name} · {fileSize(doc.size_bytes)}</span>
          {doc.note && <span className="doc-note">“{doc.note}”</span>}
        </div>
        {doc.review_note && (
          <div className="doc-review-note">{t("İK notu")}: {doc.review_note}</div>
        )}
        {doc.linked_leave && (
          <div className="doc-item-meta">
            <span className="doc-badge">
              {t("İzin kaydına bağlı")} · {t(STATUS_LABEL[doc.linked_leave.status]) || doc.linked_leave.status}
            </span>
          </div>
        )}
      </div>
      <div className="doc-item-actions">
        <button
          className="mini ghost"
          disabled={busy}
          onClick={() => run(() => downloadDocument(doc.id, doc.file_name))}
        >
          {t("İndir")}
        </button>
        {doc.can_decide && (
          <>
            <button className="mini" disabled={busy} onClick={() => decide("approved")}>{t("Kabul et")}</button>
            <button className="mini danger" disabled={busy} onClick={() => decide("rejected")}>{t("Kabul etme")}</button>
          </>
        )}
        {doc.can_delete && (
          <button
            className="mini danger"
            disabled={busy}
            onClick={() => {
              if (!window.confirm(t("Bu belge kalıcı olarak silinecek. Emin misiniz?"))) return;
              run(() => deleteDocument(doc.id));
            }}
          >
            {t("Sil")}
          </button>
        )}
      </div>
    </li>
  );
}

export default function DocumentsPanel({ user, canManage }) {
  const t = useT();
  const [types, setTypes] = useState({ categories: [], types: [] });
  const [docs, setDocs] = useState([]);
  const [mine, setMine] = useState(null);
  const [checklist, setChecklist] = useState(null);
  const [summary, setSummary] = useState(null);
  const [employees, setEmployees] = useState([]);
  const [period, setPeriod] = useState(() => monthKey(new Date()));
  const [filterUser, setFilterUser] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [area, setArea] = useState("upload");
  const [error, setError] = useState(null);

  // Katalog rol/veri değişiminden bağımsız — bir kez çekilir.
  useEffect(() => {
    documentTypes().then(setTypes).catch((e) => setError(e.message));
  }, []);

  function load() {
    listDocuments({ user_id: canManage ? filterUser : "", status: filterStatus })
      .then(setDocs)
      .catch((e) => setError(e.message));
    myDocumentSummary().then(setMine).catch(() => setMine(null));
    if (canManage) {
      documentChecklist().then(setChecklist).catch(() => setChecklist(null));
      documentSummary(period).then(setSummary).catch(() => setSummary(null));
      listEmployees().then(setEmployees).catch(() => setEmployees([]));
    }
  }
  useEffect(load, [canManage, filterUser, filterStatus, period]);

  const pendingCount = useMemo(() => docs.filter((d) => d.status === "pending").length, [docs]);

  const AREAS = [
    { key: "upload", label: t("Belge yükle") },
    ...(canManage
      ? [
          { key: "period", label: t("Dönem özeti") },
          { key: "gaps", label: t("Özlük dosyası eksikleri") },
        ]
      : []),
    { key: "list", label: canManage ? t("Tüm belgeler") : t("Belgelerim") },
  ];

  return (
    <div className="doc-panel">
      <div className="hr-toolbar">
        <h2>{t("Bordro ve özlük evrakı")}</h2>
        <span style={{ flex: 1 }} />
        {canManage && pendingCount > 0 && (
          <span className="doc-badge pending">{t("{n} belge incelemede", { n: pendingCount })}</span>
        )}
      </div>
      <p className="desc">
        {t("Rapor, izin belgesi, icra yazısı ve özlük evrakını buradan yükleyin. "
          + "Belgeler yalnız size ve İK'ya açıktır; içerik hiçbir yapay zekâ katmanına gönderilmez.")}
      </p>
      {error && <div className="login-error">{error}</div>}

      {/* Çalışanın kendi eksikleri — "benden ne isteniyor" ekranı. */}
      {mine && mine.missing.length > 0 && (
        <div className="hr-warn">
          ⚠ {t("Özlük dosyanda {n} zorunlu belge eksik:", { n: mine.missing.length })}{" "}
          {/* Liste aynı sayfada aşağıdaki tabloda da geçiyordu; burada
              katlanır. Sayı zaten cümlede — isimler istendiğinde açılır. */}
          <details className="inline-details">
            <summary>{t("hangileri?")}</summary>
            <span>{mine.missing.map((m) => m.label).join(", ")}</span>
          </details>
        </div>
      )}

      {/* Dört bölüm aynı anda ekrandaydı. Yönetici panelindeki kenar çubuğu
          kalıbına geçiyor; İK bölümleri yalnızca yetkisi olanda listelenir
          (koşullar aynen korundu). */}
      <div className="side-panel">
      <div className="subtabs">
        {AREAS.map((a) => (
          <button
            key={a.key}
            className={`tab ${area === a.key ? "active" : ""}`}
            onClick={() => setArea(a.key)}
          >
            {a.label}
          </button>
        ))}
      </div>
      <div className="side-body">

      {area === "upload" && (
      <section className="section">
        <h3>{t("Belge yükle")}</h3>
        <UploadForm
          user={user}
          types={types}
          canManage={canManage}
          employees={employees}
          onUploaded={load}
        />
      </section>

      )}

      {/* İK: dönem özeti — bordro kapatılmadan önce ne bekliyor. */}
      {canManage && area === "period" && (
        <section className="section">
          <div className="hr-toolbar">
            <h3>{t("Dönem özeti")}</h3>
            <span style={{ flex: 1 }} />
            <input type="month" value={period} onChange={(e) => setPeriod(e.target.value)} />
          </div>
          {!summary || summary.total === 0 ? (
            <p className="desc">{t("Bu döneme ait belge yok.")}</p>
          ) : (
            <>
              {summary.blocking_payroll > 0 && (
                <div className="hr-warn">
                  ⚠ {t("Bordroyu etkileyen {n} belge hâlâ incelenmedi.", { n: summary.blocking_payroll })}
                </div>
              )}
              <table className="quality">
                <thead>
                  <tr>
                    <th>{t("Belge türü")}</th>
                    <th className="num">{t("Toplam")}</th>
                    <th className="num">{t("Kabul")}</th>
                    <th className="num">{t("İncelemede")}</th>
                    <th className="num">{t("Red")}</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.by_type.map((r) => (
                    <tr key={r.doc_type} className={r.pending > 0 && r.affects_payroll ? "row-warn" : ""}>
                      <td>
                        {r.label}
                        {r.affects_payroll && <span className="doc-badge payroll">{t("Bordro")}</span>}
                      </td>
                      <td className="num">{r.total}</td>
                      <td className="num">{r.approved}</td>
                      <td className="num">{r.pending || "—"}</td>
                      <td className="num">{r.rejected || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
      )}

      {/* İK: kimde ne eksik. */}
      {canManage && area === "gaps" && checklist && (
        <section className="section">
          <h3>{t("Özlük dosyası eksikleri")}</h3>
          <p className="desc">
            {t("Zorunlu {n} belgeden kaçı kabul edilmiş. Kabul edilmeyen belge yeniden eksik sayılır.",
              { n: checklist.required_total })}
          </p>
          <table className="quality">
            <thead>
              <tr>
                <th>{t("Kişi")}</th>
                <th className="num">{t("Tam")}</th>
                <th>{t("Eksik belgeler")}</th>
              </tr>
            </thead>
            <tbody>
              {checklist.rows.map((r) => (
                <tr key={r.user_id} className={r.missing.length > 0 ? "row-warn" : ""}>
                  <td>{r.person}</td>
                  <td className="num">{r.approved_count}/{r.required_total}</td>
                  {/* Kadronun çoğu hiçbir belge vermemiş olduğunda bu sütun
                      aynı 12 ismi her satırda tekrar ediyordu (9 satır × 12 =
                      ekranda 108 etiket). "Hepsi eksik" hâli artık tek cümle;
                      kısmi eksikte liste hâlâ görünür — asıl işe yarayan bilgi
                      odur. */}
                  <td className="doc-missing">
                    {r.missing.length === 0
                      ? t("Eksik yok ✓")
                      : r.missing.length === r.required_total
                      ? t("Hiçbir belge verilmemiş")
                      : r.missing.map((m) => m.label).join(", ")}
                    {r.pending.length > 0 && (
                      <span className="hr-muted"> · {t("incelemede")}: {r.pending.map((p) => p.label).join(", ")}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {area === "list" && (
      <section className="section">
        <div className="hr-toolbar">
          <h3>{canManage ? t("Tüm belgeler") : t("Belgelerim")}</h3>
          <span style={{ flex: 1 }} />
          {canManage && (
            <select value={filterUser} onChange={(e) => setFilterUser(e.target.value)}>
              <option value="">{t("Herkes")}</option>
              {employees.filter((u) => u.is_active).map((u) => (
                <option key={u.id} value={u.id}>{u.display_name}</option>
              ))}
            </select>
          )}
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
            <option value="">{t("Tüm durumlar")}</option>
            <option value="pending">{t("İncelemede")}</option>
            <option value="approved">{t("Kabul edildi")}</option>
            <option value="rejected">{t("Kabul edilmedi")}</option>
          </select>
        </div>
        {docs.length === 0 ? (
          <p className="empty-note">{t("Henüz belge yok.")}</p>
        ) : (
          <ul className="doc-list">
            {docs.map((d) => <DocumentRow key={d.id} doc={d} onChanged={load} />)}
          </ul>
        )}
      </section>
      )}

      </div>{/* /side-body */}
      </div>{/* /side-panel */}
    </div>
  );
}
