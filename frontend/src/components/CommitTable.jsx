// Proje commit listesi (Faz 4) — operasyonel görünüm. Renkler destek
// dilidir: konvansiyon dışı mesaj "hata" değil, hijyen fırsatıdır.
// Kişi bazlı sayaç/sıralama yoktur.
export default function CommitTable({ commits }) {
  if (!commits.length) {
    return <p className="desc">Henüz commit verisi yok. Önce analiz çalıştırın.</p>;
  }
  return (
    <table className="quality">
      <thead>
        <tr>
          <th>SHA</th><th>Mesaj</th><th>Yazar</th><th>Tarih</th>
          <th>Dosya</th><th>+/−</th>
        </tr>
      </thead>
      <tbody>
        {commits.map((c) => (
          <tr key={c.sha}>
            <td>{c.sha}</td>
            <td>
              {c.message ?? <span className="na">mesaj yok</span>}
              {c.conventional === false && (
                <span className="na"> · konvansiyon dışı</span>
              )}
            </td>
            <td>{c.author ?? <span className="na">bilinmiyor</span>}</td>
            <td>
              {c.committed_at
                ? new Date(c.committed_at).toLocaleDateString()
                : <span className="na">veri yok</span>}
            </td>
            <td className="num">
              {c.files_changed ?? <span className="na">—</span>}
            </td>
            <td className="num">
              {c.additions != null || c.deletions != null
                ? `+${c.additions ?? "?"} −${c.deletions ?? "?"}`
                : <span className="na">—</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
