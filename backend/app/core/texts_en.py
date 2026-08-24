"""API'nin DÖNDÜRDÜĞÜ arayüz metinlerinin çevirileri (TR → EN).

`errors_en.ERRORS_EN` hata mesajları içindir; burası ise ekranda normal içerik
olarak görünen sunucu üretimi metinler: bireysel görünümdeki genel skor
etiketi ve notu, commit mesajı–kod eşleşmesi özeti, 1:1 hazırlık başlıkları,
kural motorunun süreç önerileri. İkisi ayrı dosyada çünkü kapsamları farklı:
hata metni bir arıza anlatır, buradakiler ürünün normal çıktısıdır — birini
ötekinin sözlüğüne koymak "hata mı, içerik mi" ayrımını kaybettirirdi.

Desen `errors_en.py` ile AYNI (gettext): anahtar Türkçe KAYNAK METNİN
KENDİSİDİR, eksik çeviri Türkçeye düşer, ham anahtar asla dönmez.
`{ad}` yer tutucuları TR ve EN metinde AYNI isimde olmalı.

DİL KARARI: etik çerçeve çeviride de korunur — "zorlanıyor, yardım gerekebilir"
destek dilidir; "bad"/"poor"/"underperforming" gibi bir performans dili
KULLANILMAZ. Öneriler emir değil, denemeye değer seçenek olarak yazılır.
"""
from __future__ import annotations

TEXTS_EN: dict[str, str] = {
    # --- bireysel görünüm: genel skor (services/scoring.py) ---
    "Akışta": "Flowing",
    "İyi durumda": "In good shape",
    "İzlenmeli": "Worth watching",
    "Zorlanıyor — yardım gerekebilir": "Struggling — support may help",
    "Veri yetersiz": "Not enough data",
    "Skor üretmek için yeterli veri yok — eksik veri uydurulmaz.":
        "Not enough data to produce a score — missing data is never invented.",
    "Bu skor bir performans notu değil, kendi akışınızın özetidir; "
    "kişiler arası kıyasta kullanılmaz.":
        "This score is not a performance rating; it summarises your own flow "
        "and is never used to compare people.",

    # --- bireysel görünüm: uç notları (api/routes.py) ---
    "Bu görünüm yalnızca sizin (ve yöneticinizin) erişimine açıktır; "
    "kıyas yalnızca kendi geçmişinizle yapılır.":
        "This view is visible only to you (and your manager); comparison is "
        "made only against your own history.",
    "Bağlar tahmindir; 'kesin' olanlar commit mesajında kart numarası geçtiği "
    "için kuruldu. Bu görünüm yalnızca sizin (ve yöneticinizin) erişimine açıktır.":
        "Links are estimates; the 'certain' ones were made because the commit "
        "message contained the card number. This view is visible only to you "
        "(and your manager).",

    # --- commit mesajı ↔ kod eşleşmesi (services/commit_alignment.py) ---
    "Mesaj-kod eşleşmesi için değişen dosya bilgisi yok "
    "(senkronda changed_files gerekli).":
        "No changed-file information for message–code alignment "
        "(sync needs changed_files).",
    "Commit mesajları yazılan kodla büyük ölçüde örtüşüyor.":
        "Commit messages largely match the code that was written.",
    "Mesajlar genelde koda uyuyor; birkaç commit'te kapsam mesajdan geniş.":
        "Messages generally match the code; in a few commits the change is "
        "broader than the message says.",
    "Mesajlarla değişen kod sık sık ayrışıyor — mesaja hangi modülün ve "
    "neden değiştiğini yazmak sonradan aramayı kolaylaştırır.":
        "Messages and changed code often diverge — naming the module and the "
        "reason in the message makes later searching much easier.",
    "Değişen dosya listesi ya da mesaj yok — eşleşme kontrol edilemedi":
        "No changed-file list or message — alignment could not be checked",
    "`test:` yazılmış ama değişen dosyalar arasında test dosyası yok":
        "`test:` was used but no test file is among the changed files",
    "`docs:` yazılmış ama doküman dışı dosyalar da değişmiş":
        "`docs:` was used but non-documentation files changed too",
    "`ci:` yazılmış ama CI yapılandırma dosyası değişmemiş":
        "`ci:` was used but no CI configuration file changed",
    "`build:` yazılmış ama derleme/bağımlılık dosyası değişmemiş":
        "`build:` was used but no build/dependency file changed",
    "`style:` yazılmış ama stil dosyası değişmemiş (davranış değişmiş olabilir)":
        "`style:` was used but no style file changed (behaviour may have changed)",
    "Kapsam `({scope})` yazılmış ama değişen dosya yollarında karşılığı yok":
        "Scope `({scope})` was written but no changed file path matches it",
    "Konu satırı içerik taşımıyor (ör. 'update') — hangi kodun neden "
    "değiştiği mesajdan anlaşılmıyor":
        "The subject line carries no content (e.g. 'update') — the message "
        "does not say which code changed or why",
    "Mesajdaki sözcükler değişen dosya/modül adlarıyla örtüşmüyor — "
    "hangi modülün değiştiği mesajdan anlaşılmıyor":
        "The words in the message do not overlap with the changed file/module "
        "names — the message does not say which module changed",
    "Tek commit'te {dosya} dosya / ~{satir} satır — mesaj bu kadar "
    "değişikliği tek başına anlatamıyor, bölmek okunurluğu artırır":
        "{dosya} files / ~{satir} lines in a single commit — one message "
        "cannot describe a change this large; splitting it reads better",

    # --- 1:1 hazırlık özeti (api/routes.py) ---
    "Kutlanacaklar": "Worth celebrating",
    "Birlikte bakılacaklar": "To look at together",
    "Hatırlatma": "A reminder",
    "{name}: sağlıklı seyrediyor — takdir et.":
        "{name}: healthy — worth acknowledging.",
    "{name}: zorlanma işareti. Ne engel oluyor, nasıl destek olabilirim diye "
    "birlikte bak.":
        "{name}: a sign of strain. Look together at what is blocking and how "
        "you can support.",
    "{name}: izlenmeli. Erken konuşmak sorunu büyümeden çözer.":
        "{name}: worth watching. Talking early solves it before it grows.",
    "{name}: geçen döneme göre iyileşmiş — ilerlemeyi görünür kıl.":
        "{name}: improved since last period — make the progress visible.",
    "Bu dönemde öne çıkan pozitif ve zorlanma yeterli veriyle ölçülemedi — "
    "genel gidişatı ve moralı konuş.":
        "Neither strengths nor strain could be measured with enough data this "
        "period — talk about the overall direction and how the person feels.",
    "Bu notlar performans puanı değil; süreç sağlığı ve destek içindir.":
        "These notes are not a performance score; they are for process health "
        "and support.",
    "Kıyas yalnızca kişinin kendi geçmişiyledir, başka kişiyle değil.":
        "Comparison is only against the person's own history, never another "
        "person.",

    # --- kural motoru: süreç önerileri (rules/engine.py) ---
    # Şablon metinler: kural motoru bunları parametreleriyle birlikte saklar,
    # çeviri OKUMA anında yapılır (bkz. Recommendation.params).
    "PR'lar ilk review için ortalama {gun} gün bekliyor (eşik: {esik} gün). "
    "Takım review kapasitesinde sıkışıyor olabilir — bir review WIP limiti ya "
    "da reviewer rotasyonu denemek bekleme süresini kısaltabilir.":
        "PRs wait {gun} days on average for a first review (threshold: {esik} "
        "days). The team may be short on review capacity — a review WIP limit "
        "or a reviewer rotation could shorten the wait.",
    "Son {gun} günde aynı dosyalar tekrar tekrar düzeltme aldı: {dosyalar}. "
    "Bu modüller refactor ve test coverage yatırımı için güçlü adaylar — "
    "buraya ayrılacak zaman, gelecekteki fix yükünü azaltır.":
        "Over the last {gun} days the same files were fixed again and again: "
        "{dosyalar}. These modules are strong candidates for refactoring and "
        "test coverage — time spent here reduces future fix load.",
    "Kişi başına ortalama {wip} açık iş görünüyor (eşik: {esik}). Çok iş "
    "başlatılıp az bitiriliyor olabilir — takımca bir WIP limiti belirlemek "
    "akışı hızlandırabilir.":
        "There are {wip} open items per person on average (threshold: {esik}). "
        "A lot may be started and little finished — agreeing a WIP limit as a "
        "team could speed up the flow.",
    "Task'ların %{yuzde}'inde estimate girilmemiş. Bu bir kusur değil, "
    "görünürlük kaybı: planlama sinyalleri eksik kalıyor ve bazı metrikler "
    "hesaplanamıyor. Kısa bir planlama rutini (örn. haftalık estimate turu) "
    "süreci görünür kılabilir.":
        "{yuzde}% of tasks have no estimate. This is not a fault but a loss of "
        "visibility: planning signals stay incomplete and some metrics cannot "
        "be computed. A short planning routine (e.g. a weekly estimate round) "
        "could make the process visible.",
    "Son dönemde {sayi} kez cuma akşamı deploy'unu hafta sonu düzeltmesi "
    "izledi. Cuma öğleden sonrası riskli bir deploy penceresi olabilir — "
    "hafta sonu öncesi kısa bir deploy freeze'i denemeye değer.":
        "Recently a Friday evening deploy was followed by a weekend fix {sayi} "
        "times. Friday afternoon may be a risky deploy window — a short deploy "
        "freeze before the weekend is worth trying.",
}
