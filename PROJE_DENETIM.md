# Proje Denetimi — Nabız (Mühendislik Sağlığı Panosu)

**Tarih:** 2026-07-29 · **Denetlenen commit:** `28ea078` (main) · **Temizlik branch'i:** `chore/audit-cleanup`

---

## 1. Özet

Bu, tek process olarak çalışan, on-prem bir mühendislik sağlığı panosu: Git ve Trello/Jira
verisini ortak şemaya normalize edip DORA + akış metriklerini **takım seviyesinde** sunuyor,
üzerine İK modülleri (izin, anket, hesap yönetimi) ve kendi AI kod analizi modülü ekliyor.
Kod, iddia ettiği etik çerçeveyi gerçekten uyguluyor: leaderboard uçları yok, bireysel
görünüm sunucu tarafında yetkilendiriliyor, anonimleştirme gerçek bir anahtar. Metrikler
"değer + veri tamlığı + kaynak katmanı" üçlüsü üretiyor ve veri yetersizse değer uydurmuyor —
bu, benzer araçlarda nadir görülen bir olgunluk.

Genel sağlık **iyi**. 128 backend testi geçiyor, ölü kod neredeyse yok, sırlar config'ten
ayrılmış, JWT/bcrypt/hesap kilitleme doğru kurulmuş. Ancak üretime alınmadan önce kapatılması
gereken üç boşluk var: **kimlik doğrulaması olmayan bir uç**, **Alembic migration'larının
şemanın %20'sini kaçırması** ve **CI'ın hiç olmaması**. README ise kaldırılmış bir kimlik
mekanizmasını (`X-Dev-Id`) hâlâ gerçekmiş gibi anlatıyor.

### KRİTİK BULGULAR

| # | Bulgu | Kanıt |
|---|---|---|
| **K1** ✅ **ÇÖZÜLDÜ** (`2d52772`) | **`GET /api/annotations` kimlik doğrulaması istemiyor.** Router seviyesinde de uç seviyesinde de bağımlılık yok. Tatil/incident/sürüm etiketleri (ör. "ödeme servisi çöktü", sürüm adları) tokensiz okunabiliyor. Diğer tüm dashboard uçları `routes.py:46`'daki router bağımlılığıyla korunuyor — bu uç o router'da değil. | `app/api/annotations.py:20,42` · Doğrulandı: çalışan sunucuya tokensiz `curl` → **200** (`/api/teams` aynı istekte **401**) |
| **K2** ✅ **ÇÖZÜLDÜ** (`51b4070`) | **Alembic şemanın 5 tablosunu hiç oluşturmuyor:** `users`, `leaves`, `user_projects`, `audit_logs`, `notifications`. Temiz bir DB'de `alembic upgrade head` çalıştıran biri **giriş yapamaz** (users tablosu yok). Sistem sadece açılıştaki `create_all` sayesinde ayakta. İki ayrı şema yönetimi (`create_all` + `ensure_schema_patches` + alembic) birbirinden habersiz. | Modellerde 25 tablo (`app/models/__init__.py`), migration'larda 21 `create_table` (`migrations/versions/`) |
| **K3** | **README güvenlik mimarisini yanlış anlatıyor.** 3 yerde kimliğin `X-Dev-Id` başlığıyla taşındığı yazıyor; bu başlık `cb4af9e`'de "taklit edilebilir" diye kaldırıldı. Ayrıca "EHD_SECRET yoksa güvensiz geliştirme varsayılanı kullanılır" diyor — kod artık güçlü rastgele anahtar üretiyor. Yeni gelen mühendis yanlış tehdit modeliyle çalışır. | `README.md:180,245,249` vs `app/api/routes.py:43`, `README.md:146` vs `app/core/security.py:24-44` |

> Veri kaybı riski, hardcoded API anahtarı veya sessizce yutulan ödeme/veri-yazma hatası
> **bulunmadı**. `config/config.yaml:7`'de commit'lenmiş bir yerel DB parolası var
> (`health:health`) — yalnızca taşınabilir demo Postgres'e ait, üretim sırrı değil (bkz. öneri 11).

---

## 2. Durum değerlendirmesi

### Proje ne yapıyor?

Şirketin kendi Git ve görev-takip verisini çekip ortak bir şemaya normalize ediyor; bundan
takım seviyesinde süreç sağlığı göstergeleri (cycle time, PR review süresi, review gecikmesi,
deploy sıklığı, hata oranı, WIP, rework, süreç hijyeni) üretiyor. Her metrik yanında "bu değer
ne kadar veriye dayanıyor" bilgisini taşıyor; veri yetersizse değeri gizliyor. Üzerine bir
kural motoruyla "şurada tıkanıyorsunuz, şunu deneyin" tarzı öneriler, bir AI modülüyle kod
kalitesi analizi ve İK tarafı için izin/anket/hesap yönetimi ekliyor. Veri dışarı çıkmıyor.

### Mimari

```
Kaynaklar → Adaptörler → Ingest → Normalize DB şeması → Metrik motoru → Kural motoru → API → React SPA
(git_log,   (ortak       (kirli   (25 tablo,          (değer+tamlık+   (öneriler)   (JWT)  (tek bundle,
 gitlab,     Protocol     alan     SQLAlchemy 2.0)      kaynak katmanı)                      backend'den
 jira,       arayüzü,     tolere                                                             servis edilir)
 trello,     DTO döner,   eder)
 fixture)    DB'ye
             dokunmaz)
```

**Katmanlar ve bağımlılık yönü temiz:** `adapters` → sadece DTO döndürür, DB bilmez;
`services/ingest` tek kirli-veri ele alma noktası; `metrics/engine` + `rules/engine` yalnız
DB ve config okur; `api/*` sunum katmanı. Çekirdek (`ingest`/`metrics`/`rules`) yeni kaynak
eklendiğinde değişmiyor — `adapters/factory.py`'ye bir satır yetiyor. Tek giriş noktası
`services/pipeline.py`; hem CLI hem APScheduler oradan geçiyor.

**Uygulama giriş noktaları:** `app/main.py` (FastAPI + statik SPA + zamanlayıcı),
`app/cli.py` (`init-db`, `sync`, `serve`, `set-password`, `analyze-code`, `survey-genkey`).

**Yetki katmanları:** `current_user` (32 uç) → `require_admin` (31) → `require_admin_or_hr` (10)
→ `require_owner` (3). `routes.py` router'ı komple JWT arkasında; `admin/auth/leaves/projects/survey`
uçlarının her biri tek tek bağımlılık taşıyor (tarandı, eksik yok). Tek istisna: K1.

### Teknoloji stack'i

| Katman | Teknoloji | Sürüm | Durum |
|---|---|---|---|
| Runtime | Python | 3.14.0 | Güncel |
| API | FastAPI / uvicorn | 0.139 / 0.50 | Güncel |
| ORM / DB | SQLAlchemy 2.0.51 / psycopg 3.3 / PostgreSQL | — | Güncel |
| Migration | Alembic 1.18 | — | Kurulu ama **eksik** (K2) |
| Doğrulama | pydantic 2.13 | — | Güncel |
| Kimlik | python-jose 3.5 + bcrypt 5.0 | — | Çalışır; `python-jose`, `ecdsa` 0.19.2'yi sürüklüyor (CVE-2024-23342, yamalanmayacak). **Proje HS256 kullandığı için bu yol hiç çalışmıyor** — risk teorik (bkz. öneri 10) |
| AI | anthropic 0.117 | — | Güncel |
| Frontend | React 18.3 + Vite 6 + Recharts 2.13 | — | React 19 ve Vite 7 çıktı; 18/6 hâlâ destekli, EOL değil |
| Build | — | — | `npm audit`: üretim bağımlılıklarında **0 açık**; dev'de postcss **1 high** (öneri 4) |

**EOL/terk edilmiş bağımlılık yok.**

### Olgunluk seviyesi: **Gelişmiş MVP — üretime hazır değil**

Ürün mantığı ve veri modeli üretim kalitesinde; işletim tarafı değil. Gerekçe:

- ✅ 128 test, gerçek pipeline üzerinden sentetik kirli veriyle; etik kısıtlar teste bağlanmış
- ✅ Sır yönetimi, hesap kilitleme, oturum geçersizleştirme, denetim kaydı mevcut
- ❌ **CI yok** (`.github/` dizini yok) — testler yalnız elle çalışıyor
- ❌ **Migration yolu kırık** (K2) — "temiz kurulum" prosedürü fiilen `create_all`'a bağımlı
- ❌ **Deploy artefaktı yok**: Dockerfile, servis tanımı, `.env.example`, sağlık kontrolü ucu yok
- ❌ **Frontend testi sıfır**; 8.160 satır JSX hiç otomatik doğrulanmıyor
- ❌ Sunucu `127.0.0.1:8000`'e sabitlenmiş (`cli.py:61`) — host/port ayarlanamıyor

### Sağlık göstergeleri

| Gösterge | Ölçüm |
|---|---|
| Backend kod | 12.375 satır Python (testler dahil), 75 dosya |
| Frontend kod | 8.160 satır (JSX+CSS+JS), 35 dosya |
| Test | 15 dosya, **128 test, hepsi geçiyor** (~2 dk) · **kapsam yüzdesi ölçülmedi** (pytest-cov kurulu değil) |
| Ölü kod | Ruff F401/F811/F841 taraması: temizlik sonrası **0 gerçek bulgu** |
| En şişkin dosyalar | `styles.css` 1.690 · `admin.py` 806 · `code_analysis.py` 706 · `App.jsx` 685 · `routes.py` 639 · `engine.py` 631 |
| En uzun fonksiyon | `survey.py:201 aggregate_results()` — 89 satır (kabul edilebilir; 100+ satırlık canavar yok) |
| Kod tekrarı | Sınırlı ve yerel: `pad/ymd/monthKey` üçlüsü `LeavesPanel.jsx:22-24` ve `HrDashboard.jsx:9-11`'de birebir aynı; `TYPE_LABEL` iki dosyada; `fmtDate` iki farklı imzayla iki dosyada |
| Debug artığı | `console.log` **0**, `debugger` **0**, TODO/FIXME/HACK **0** (`cli.py`'deki `print`'ler meşru CLI çıktısı) |
| Git hijyeni | Çalışma ağacı temiz, 123 izlenen dosya, log/build/secret/`__pycache__` izlenmiyor |

**Yarım kalmış branch'ler:** `faz-1-kimlik` … `faz-5-izin` (5 adet) ve `feat/owner-ai-provider`
uzakta duruyor; hepsinin içeriği `main`'e girmiş görünüyor (fazlar sırayla merge edilmiş).
Silinmeleri güvenli görünüyor ama **doğrulamadım** — öneri 16.

---

## 3. Silinenler listesi (branch: `chore/audit-cleanup`, 3 commit)

Her aday önce tüm projede `grep -r` ile arandı; dinamik çağrı (FastAPI `Depends`, string ile
import, config'ten yükleme) ihtimali tek tek kontrol edildi. **Silme sonrası: 128 test geçiyor,
frontend build başarılı, config yükleniyor.**

| Dosya | Silinen | Gerekçe / doğrulama |
|---|---|---|
| `backend/app/api/auth.py:133-138` | `require_hr()` fonksiyonu | Hiçbir uçta `Depends()` ile kullanılmıyor. Sayım: `require_admin` 31, `require_admin_or_hr` 10, `require_owner` 3, **`require_hr` 0**. Salt-İK ucu yok; paylaşımlı uçlar `require_admin_or_hr` kullanıyor. |
| `backend/requirements.txt:10` | `python-dateutil>=2.9` | Backend'in tamamında (app, tests, scripts, migrations) tek bir `dateutil` import'u yok. |
| `backend/app/core/config.py:85-98` | `QualitySource` modeli + `Sources.quality` alanı | Dış kalite taraması `e84c6b5`'te kaldırılmıştı; model "eski config uyumu" için duruyordu. **Ampirik doğrulama:** `Sources` pydantic varsayılanı `extra="ignore"` — eski `sources.quality` bloğu içeren config zaten hatasız yükleniyor (test edildi). Geriye dönük uyum kaybı yok. |
| `backend/tests/conftest.py:8,30` | `import os` + test config'indeki `quality: {provider: fixture}` satırı | `os.` kullanımı yok; `quality` artık okunmuyor. |
| `backend/tests/test_llm_provider.py:131` | `import app.core.config as cfgmod` | `cfgmod` dosyada hiç geçmiyor (aynı satırdaki `DEFAULT_CONFIG_PATH` import'u korundu — o kullanılıyor). |
| `backend/tests/test_rules.py:4` | `timezone` import'u | Kullanılmıyor. |
| `backend/tests/test_leaves_flow.py:137` | `b = ` ataması | Ruff F841. **Fonksiyon çağrısı korundu** — kullanıcı kaydını yan etki olarak yaratıyor, silinseydi test senaryosu bozulurdu. |
| `backend/app/adapters/base.py:4` | Docstring'de `sonarqube` örneği | Var olmayan bir adaptöre atıf; `gitlab` ile değiştirildi. |
| `frontend/src/styles.css:1221-1247, 1518-1547` | `.btn-primary` / `.btn-ghost` / `.btn-danger` takma adları | Hiçbir JSX kullanmıyor. **Davranış birebir korundu:** yalnız seçici listelerinden kullanılmayan ad çıkarıldı, `.login-btn` ve `.mini` kuralları aynen duruyor. `.btn-ghost:disabled` bilinçli olarak `.mini:disabled`'a **dönüştürülmedi** — bu görsel bir değişiklik olurdu (`.mini:disabled` zaten satır 976'da tanımlı). Build sonrası CSS'te `btn-primary` 0, `login-btn` 13 kez geçiyor. |

**Silinmedi — bilinçli olarak listelendi:**

- `app/adapters/{gitlab,jira,fixture}.py` — şu an config'te seçili değil ama `factory.py`
  üzerinden çalışan özellik kodu, ölü değil.
- `migrations/versions/18731b1ad718:94` — `code_quality_snapshots` tablosu (kaldırılan
  SonarQube entegrasyonundan kalan orphan tablo). Migration geçmişi geriye dönük değiştirilmez;
  temizliği yeni bir migration ister → öneri 15.
- `README.md`'deki eskimiş bölümler — dokümantasyon; kural gereği silmedim → öneri 3.
- `backend/fixtures/`, `.pgsql/`, `.secrets.env` — üretilen veri / yerel DB / sır; hepsi
  gitignore'lu, dokunulmadı.

---

## 4. Öneriler

| No | Öneri | Kategori | Neden gerekli | Etki | Efor | Risk |
|---|---|---|---|---|---|---|
| ~~**1**~~ ✅ | ~~`app/api/annotations.py` — kimlik doğrulaması ekle.~~ **Yapıldı** (`2d52772`): koruma uç yerine **router seviyesine** kondu (`routes.py:46` ile aynı desen) — sonradan eklenen her anotasyon ucu da otomatik korunur. Yazma uçlarındaki `require_admin_or_hr` korundu. Regresyon testleri eklendi (tokensiz → 401, kimlikli → 200, düz kullanıcı yazma → 403). Canlı doğrulama: 200 → 401. | Güvenlik | Tokensiz `curl` ile şirket içi olay/sürüm etiketleri okunabiliyordu | Yüksek | S | Düşük |
| ~~**2**~~ ✅ | ~~Eksik 5 tablo için migration + şema eşitliği testi.~~ **Yapıldı** (`51b4070`): yeni revizyon `e1f2a3b4c5d6`, zincirde `initial_schema`'nın hemen ardına kondu (head'e değil — users'a dokunan 3 migration ondan sonra geliyor). Mevcut DB'ler etkilenmez (head değişmedi, `alembic current` → `d0e1f2a3b4c5`). Yol boyunca çıkan iki engel de düzeltildi: `a1b2c3d4e5f6` korumasız ALTER'dı → idempotent yapıldı; `f6a7b8c9d0e1` satır içi FK yüzünden SQLite'ta hiç koşamıyordu → `batch_alter_table`. 3 yeni test: temiz DB'de upgrade head çalışıyor, alembic şeması tüm model tablo/kolonlarını kapsıyor, tek head. | Güvenlik / Veri | Temiz DB'de sadece alembic ile kurulum yapan **giriş bile yapamıyordu** | Yüksek | M | Orta |
| **3** | `README.md:180,245,249` — `X-Dev-Id` anlatımını sil, kimliğin yalnız JWT'den geldiğini yaz. `:146` — "güvensiz geliştirme varsayılanı" ifadesini düzelt (kod güçlü rastgele anahtar üretiyor). `:192,244` — `sonarqube/linter` sağlayıcısını ve `/api/teams/{id}/quality` ucunu kaldır. `:235` — "28 pytest" → 128. | Dokümantasyon | Yeni gelen mühendis yanlış (ve daha zayıf) bir tehdit modeliyle çalışır; var olmayan uçlara entegrasyon yazar | Yüksek | S | Düşük |
| **4** | `cd frontend && npm audit fix` — postcss'i 8.5.18+'a çek. | Güvenlik | `npm audit`: 1 high (GHSA-r28c-9q8g-f849, source-map path traversal). Yalnız build zamanı etkili, üretim bundle'ında 0 açık — ama düzeltmesi tek komut | Orta | S | Düşük |
| **5** | `.github/workflows/ci.yml` ekle: `pytest tests` + `ruff check app tests` + `npm ci && npm run build`. | DX / Test | 128 testin değeri yalnız birinin elle çalıştırmasına bağlı; bozuk commit sessizce main'e giriyor | Yüksek | S | Düşük |
| **6** | `app/api/leaves.py:47`, `projects.py:87,125`, `survey.py:105,107` — `raise HTTPException(...) from err` kullan. | Hata yönetimi | Şu an orijinal istisna zinciri kopuyor; sunucu log'unda kök neden görünmüyor (ör. GitHub API hatası "422" olarak yutuluyor) | Orta | S | Düşük |
| **7** | Frontend'de sessiz `.catch(() => {})` noktalarını kullanıcıya görünür hale getir: `App.jsx:209` (takım listesi yenilenemedi), `NotificationBell.jsx:15,37,54`, `LeavesPanel.jsx:73` (çalışan listesi boş kalıyor → "Kişi" seçici sessizce boşalıyor), `CodeAnalysisPanel.jsx:85`. Mevcut `toast()` altyapısı zaten var. | Hata yönetimi | Kullanıcı boş listeyi "veri yok" sanıyor, oysa istek başarısız; destek çağrısı üretir | Orta | M | Düşük |
| **8** | Frontend için Vitest + React Testing Library kur; ilk hedef `LeavesPanel` (takvim ızgarası + izin/işaret çakışması) ve `api.js:parseError/humanizeDetail` (401 → oturum düşürme akışı). | Test | 8.160 satır JSX'te hiç otomatik doğrulama yok; en kritik iş mantığı (takvim, yetki görünürlüğü) elle test ediliyor | Yüksek | L | Düşük |
| **9** | Parola minimumunu 6'dan 10-12'ye çıkar: `app/api/auth.py:60,66,75,99` (`Field(min_length=6)`). Mevcut hesapları etkilemez, yalnız yeni/değişen parolaları. | Güvenlik | 6 karakter bugünün standardının altında; hesap kilitleme (5 deneme) bunu kısmen telafi ediyor ama çevrimdışı hash saldırısına karşı değil | Orta | S | Düşük |
| **10** | `python-jose` → `PyJWT` geçişi (`app/core/security.py`, 3 fonksiyon). | Güvenlik | `python-jose`, `ecdsa` 0.19.2'yi sürüklüyor (CVE-2024-23342, "düzeltilmeyecek" damgalı). Proje **HS256** kullandığı için bu kod yolu hiç çalışmıyor — risk bugün teorik, ama gereksiz saldırı yüzeyi ve bağımlılık | Düşük | M | Orta |
| **11** | `config/config.yaml:7`'deki `postgresql+psycopg://health:health@...` satırını `${DATABASE_URL}` ile değiştir; gerçek değeri `.secrets.env`/ortam değişkenine taşı. `.env.example` ekle. | Güvenlik / DX | Commit'lenmiş bir kimlik bilgisi (bugün yalnız yerel demo DB'sine ait); repo başka bir ortama kopyalandığında alışkanlık olarak taşınır | Düşük | S | Düşük |
| **12** | `app/cli.py:61` — `serve()`'e host/port parametresi ver (ortam değişkeni ya da argüman). | DX | `127.0.0.1:8000` sabit; başka bir makineden erişim ya da ikinci bir örnek çalıştırma imkânsız | Orta | S | Düşük |
| **13** | Tekrarlayan tarih yardımcılarını tek dosyaya al: `pad/ymd/monthKey` (`LeavesPanel.jsx:22-24` = `HrDashboard.jsx:9-11`, birebir aynı), `TYPE_LABEL` (iki dosya), `fmtDate` (`Settings.jsx:25`, `TrendChart.jsx:17` — farklı imzalar, aynı isim). | Kod kalitesi | Ay/gün hesabında bir düzeltme iki dosyada ayrı ayrı yapılmak zorunda; TZ hatası tek yerde düzeltilirse diğerinde kalır | Orta | S | Düşük |
| **14** | `App.jsx` (685 satır) ve `styles.css` (1.690 satır) bölünmesi: App'ten yönlendirme/sekme mantığını, CSS'ten bileşen bloklarını ayır. | Kod kalitesi | En sık değişen iki dosya (18 ve 16 commit) — çakışma ve yanlışlıkla bozma olasılığı en yüksek noktalar | Orta | L | Orta |
| **15** | Yeni bir migration'la orphan `code_quality_snapshots` tablosunu düşür (`migrations/versions/18731b1ad718:94` yaratıyor, hiçbir model kullanmıyor — `models/__init__.py:221-223` durumu zaten not etmiş). | Kod kalitesi | Şemada kimsenin yazmadığı/okumadığı bir tablo; yeni gelen "bu ne?" diye zaman kaybeder | Düşük | S | Düşük |
| **16** | Merge edilmiş faz branch'lerini sil: `faz-1-kimlik` … `faz-5-izin`, `feat/owner-ai-provider` (yerel + `origin`). **Önce** `git branch --merged main` ile içeriklerinin main'de olduğunu doğrula. | DX | 6 ölü branch dal listesini kirletiyor; hangisinin canlı olduğu belirsiz | Düşük | S | Orta |
| **17** | `tests/test_llm_provider.py:133` — `open(cfg_path).read()` yerine `Path(...).read_text()` ya da `with`. | Kod kalitesi | Ruff SIM115; testte dosya tanıtıcısı sızıyor (Windows'ta sonraki temizliği kilitleyebilir) | Düşük | S | Düşük |
| **18** | `scripts/seed_dirty_data.py:153` — döngüde kullanılmayan `team` değişkeni (Ruff B007); ya kullanılmalı ya `_` olmalı. | Kod kalitesi | Muhtemel kopyala-yapıştır kalıntısı; niyetin ne olduğu belirsiz | Düşük | S | Düşük |
| **19** | Girişe IP bazlı hız sınırı ekle (`app/api/auth.py:223`). Hesap kilidi (5 deneme) var ama saldırgan farklı hesapları sırayla deneyebiliyor. | Güvenlik | Kullanıcı numaralandırma + dağıtık deneme yavaşlatılmıyor | Düşük | M | Orta |
| **20** | `/api/health` gibi kimliksiz bir sağlık kontrolü ucu ekle (DB bağlantısı + son senkron zamanı). | DX / İşletim | Bu denetimde sunucunun ayağa kalktığını doğrulamak için 404 dönen bir uca istek atmak zorunda kaldım; izleme/otomasyon bağlanacak bir nokta bulamaz | Düşük | S | Düşük |

---

## 5. İncelenmeyen / emin olamadığım alanlar

Aşağıdakiler hakkında **yorum yapmadım**, çünkü satır satır okumadım:

- **Satır satır okunmayan backend modülleri:** `services/code_analysis.py` (706), `metrics/engine.py`
  (631 — yalnız başlık ve sabitler), `services/survey.py`, `report.py`, `notifications.py`,
  `code_health.py`, `scoring.py`, `commit_alignment.py`, `commit_review.py`, `github.py`,
  `rules/engine.py` ve adaptörlerin gövdeleri. Bunlarda **metrik doğruluğu, LLM prompt/token
  yönetimi ve hesaplama hatası** olup olmadığını bilmiyorum.
- **Frontend bileşenlerinin çoğu:** `CodeAnalysisPanel`, `HrDashboard`, `IntegrationPanel`,
  `SurveyAdminPanel/Form`, `ProjectsPanel`, `MetricCard`, `TrendChart`, `CommandPalette` vb.
  yalnız import/CSS/hata-yakalama açısından tarandı; **iş mantığı doğrulanmadı**.
- **Test kapsamı yüzdesi ölçülmedi** — `pytest-cov` kurulu değil. "128 test geçiyor" bir
  kapsam garantisi değildir; hangi dalların test edilmediğini bilmiyorum.
- **Metriklerin istatistiksel doğruluğu** (DORA tanımlarına uygunluk, eşiklerin makullüğü)
  değerlendirilmedi — bu, veri ve alan bilgisi gerektiren ayrı bir iş.
- **Performans ölçülmedi.** N+1 sorgu, indeks eksikliği, büyük repo'da `git log` maliyeti
  konusunda hiçbir ölçüm yapmadım. `metrics/engine.py`'de `selectinload` kullanımı gördüm,
  o kadar.
- **Migration'ların içerikleri** (kolon tipleri, downgrade yolları) okunmadı; yalnız hangi
  tabloları yarattıkları listelendi. K2 bu listeye dayanıyor — **eksik tabloların başka bir
  yolla eklenmediğini** `create_all` dışında doğrulamadım.
- **`.pgsql/` taşınabilir PostgreSQL kurulumu** ve `frontend/node_modules` incelenmedi
  (vendor / üretilen içerik).
- **Güvenlik denetimi sınırlı:** `npm audit` çalıştırıldı, Python tarafında `pip-audit`
  **çalıştırılmadı**. Penetrasyon testi, yetki matrisinin uçtan uca doğrulanması (her rolün
  her uca isteği) yapılmadı — yalnız bağımlılık bildirimleri statik olarak tarandı.
- **`faz-*` branch'lerinin içeriği** `main` ile karşılaştırılmadı (öneri 16 bu yüzden
  "önce doğrula" diyor).
