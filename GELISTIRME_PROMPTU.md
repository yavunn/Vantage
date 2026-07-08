# Engineering Health Dashboard — Geliştirme Promptu (Claude Code / Fable 5)

> Bu dosya, Claude Code'a (Fable 5 ile) verilecek **tek parça talimattır**.
> Terminalde şununla başlat:
>
> ```bash
> claude
> # sonra:  bu dosyanın tamamını yapıştır  ya da:  "GELISTIRME_PROMPTU.md dosyasını oku ve uygula"
> ```
>
> İstersen doğrudan: `claude "GELISTIRME_PROMPTU.md dosyasını oku; Faz 1'den başla, her fazı ayrı ayrı planla ve onayımı al."`

---

## 0) ROLÜN VE ÇALIŞMA BİÇİMİN

Sen bu **mevcut, çalışan** on-prem "Engineering Health Dashboard" projesini geliştiren kıdemli bir mühendissin. Sıfırdan yazmıyorsun — olgun bir kod tabanına **eklemeler** yapıyorsun.

Kurallar:
1. **Önce oku, sonra yaz.** Dokunacağın her modülü (`backend/app/...`, `frontend/src/...`) değiştirmeden önce oku. Mevcut konvansiyona uy; yeni bir mimari dayatma.
2. **Fazları teker teker yap.** Bir fazı bitirmeden diğerine geçme. Her fazın başında kısa bir plan çıkar, bana onaylat, sonra uygula.
3. **Mevcut testleri asla kırma.** Özellikle `backend/tests/test_api_ethics.py` içindeki `test_leaderboard_ucu_yok` (ve diğer etik testler) her zaman yeşil kalmalı. Her faz sonunda `cd backend; .venv\Scripts\python -m pytest tests` çalıştır.
4. **Her faz sonunda:** testleri geçir → kısa manuel doğrulama → tek bir anlamlı commit (aşağıdaki commit formatı). Push'u ben istemeden yapma.
5. **Emin değilsen sor.** Şema/etik/kimlik gibi geri dönüşü zor kararlarda bana danış.

---

## 1) PAZARLIKSIZ ETİK ÇERÇEVE (bu her şeyin üstünde)

Bu ürün **B tipidir: mühendislik/delivery sağlığı aracı.** Asla **A tipi (bireysel gözetim / performans kovalama)** değildir. Bu çerçeve pazarlık konusu değildir ve eklenen HER özellik buna uymak zorundadır:

1. **Leaderboard yok.** Hiçbir uç, birden çok kişinin metriğini yan yana döndürmez. (`test_leaderboard_ucu_yok` bunu zorlar — bozma.)
2. **Bireysel veri yalnızca kişinin kendisi + yöneticisi içindir.** Kıyas yalnızca kişinin **kendi geçmişiyle** yapılır, asla başkasıyla.
3. **Eksik veri cezalandırılmaz.** "Veri yetersiz" birinci sınıf bir durumdur; process hygiene olarak raporlanır, ceza puanı olarak değil. Değer **asla uydurulmaz**.
4. **Kırmızı = "yardım gerekebilir"** destek dili. "Kötü performans / suçlu" dili yok.
5. **LLM katmanı varsayılan kapalı**, on-prem; hiçbir veri dışarı çıkmaz.
6. **Anonimleştirme modu** açıkken bireysel uçlar kapanır, isimler maskelenir.

> **Kullanıcının yeni fikri (aynen):**
> _"aklıma şu geldi genel bi ik takip sistemi yapabiliriz yani çalışanların izinlerini tatillerini tutabiliriz sonrasında çalışanlar ani bi sebeple izin alması gerekirse sisteme girer yani genel olarak çalışanların performanslarını ölçen ve ik için çalışan takibi yapan bir sistem"_

**Bu fikri şöyle yorumla ve öyle uygula** (çerçeveyi bozmadan):
- **İzin/tatil takibi = metriğe BAĞLAM.** İzindeki günler, düşük aktiviteyi "anomali" saymaz; metrik pencereleri izin günlerini hariç tutar. (Faz 5'in asıl amacı budur — spec'te de böyle.)
- **Self-servis izin talebi** (çalışan ani izin girer, admin onaylar) tamamen meşru ve teşvik edilir.
- **"Performans ölçme"** kısmı **bireysel kovalama/sıralama olarak DEĞİL**, mevcut delivery-health merceğinden uygulanır: kişi yalnızca kendi geçmişini görür, takım agregatı herkese açıktır, karşılaştırmalı sıralama yoktur.
- Yani: İK bir **"delivery health + izin bağlamı"** paneli alır; bir "çalışan fişleme" aracı değil. Bir özellik bu ayrımı bulanıklaştırıyorsa, önce bana sor.

---

## 2) MEVCUT MİMARİ (dokunacağın zemin)

**Stack:** FastAPI · SQLAlchemy 2.0 (typed `Mapped`) · Alembic · taşınabilir PostgreSQL 17.5 (port **5433**) · React 18 + Vite (**JSX, TypeScript DEĞİL**) · Python 3.14 venv.

**Backend (`backend/app/`):**
- `models/__init__.py` — Team, Developer, TeamMembership, Repo, Commit, PullRequest, PRReview, Task, TaskStatusTransition, CodeQualitySnapshot, MetricResult, Recommendation. Alanlar bilerek **nullable** (kirli veri = ana özellik).
- `api/routes.py` — REST API. Kimlik **demo amaçlı `X-Dev-Id` başlığından** okunur (`current_dev`). Not: bu, şirket ortamında SSO/reverse-proxy başlığıyla değiştirilecek **tek noktadır** — Faz 1 kimlik katmanını buraya oturtmalısın, paralel ikinci bir kimlik sistemi kurma.
- `metrics/engine.py` — cycle_time, pr_review_time, review_latency, wip vb.
- `rules/engine.py`, `services/health.py` — sağlık durumu + insan-dostu öneriler.
- `adapters/` — github/gitlab/jira/trello/sonarqube/git_log/linter/fixture (factory pattern).
- `llm/advisor.py` — opsiyonel öneri katmanı (varsayılan kapalı).
- `core/config.py` (`config/config.yaml`'dan okur), `core/db.py`, `cli.py`.

**Frontend (`frontend/src/`):** `App.jsx`, `api.js`, `components/{IndividualView,MetricCard,TrendChart}.jsx`, `styles.css`. Router yok, tek sayfa. **Aynı sade JSX üslubunu koru** — gereksiz yere TypeScript/react-router/state-kütüphanesi ekleme; ekleyeceksen önce gerekçesini söyle.

**Veritabanı / çalıştırma (project-setup):**
```bash
# 1) Taşınabilir Postgres'i başlat (port 5433, user health/health, db eng_health)
.pgsql\pgsql\bin\pg_ctl -D .pgsql\data -o "-p 5433" start
# 2) Backend
cd backend
.venv\Scripts\alembic upgrade head
.venv\Scripts\python scripts\seed_dirty_data.py     # deterministik seed (seed=42)
.venv\Scripts\python -m app.cli sync
.venv\Scripts\python -m app.cli serve               # port 8000, frontend/dist'i de servis eder
# Testler:
.venv\Scripts\python -m pytest tests
```
> Temiz demo gerekiyorsa: DB'de `DROP SCHEMA public CASCADE` → `alembic upgrade head` → seed → sync (üst üste seed eski kayıt bırakır).

**Genel kurallar:**
- Yeni tablo = yeni **Alembic migration** (`alembic revision --autogenerate -m "..."`), elle SQL değil. `TODO` dosyasındaki `V00X__*.sql` isimlendirmesini değil, projenin mevcut Alembic düzenini kullan.
- Şifre/parola **bcrypt** ile hash'lenir, token **asla** plain saklanmaz (Fernet), token URL'de/log'da görünmez.
- Her yeni özellik için pytest testi yaz. Etik guardrail'ler için de test yaz (ör. "başkasının izin talebini göremezsin").

---

## 3) FAZLAR

> Aşağıdaki fazlar `PROJE_FAZLARI_TODO.txt`'ten uyarlanmıştır. **Fark:** o dosya `.tsx`/TypeScript ve ayrı `users` sistemi varsayıyor; gerçek proje **JSX** ve **Developer + `X-Dev-Id` tek-nokta kimlik** kullanıyor. Çelişkide **gerçek projeyi** esas al, TODO'yu niyet/checklist olarak kullan.

### FAZ 1 — Kimlik Doğrulama (mevcut tek-noktaya oturt)
**Amaç:** Demo `X-Dev-Id` başlığının yerine gerçek giriş/çıkış + JWT koy; ama `current_dev` **tek kimlik noktası** kalsın.
- Backend: `User` kavramı (email, password_hash [bcrypt], role: admin|user, timestamps) ve bunun mevcut `Developer` ile ilişkisi (User ↔ Developer bağı; ikisini çoğaltma). `python-jose[cryptography]`, `passlib[bcrypt]`, `python-multipart`.
- `POST /api/auth/login` → JWT access (1s) + refresh (7g). `POST /api/auth/refresh`. Secret env'den (`SECRET_KEY`).
- `current_dev`'i JWT'yi de kabul edecek şekilde genişlet (Bearer token → user → developer). `X-Dev-Id` demo modu config ile kalabilir ama prod yolu JWT olsun.
- Frontend: `LoginPage.jsx`, header'da çıkış, token'ı sakla, isteklerde `Authorization: Bearer` gönder. `api.js`'i buna göre güncelle.
- **Kabul:** Girişsiz korumalı uçlar 401; geçersiz/expired token 401; mevcut etik testler yeşil; yeni `tests/test_auth.py`.

### FAZ 2 — Admin & Kullanıcı Paneli (rol bazlı)
**Amaç:** `role`'e göre iki görünüm; **leaderboard üretmeden.**
- Backend: `check_admin_role` bağımlılığı. `/api/admin/*` yalnız admin (403 aksi halde). `GET /api/admin/users`, `DELETE /api/admin/users/{id}` (**soft delete**), `PUT /api/admin/users/{id}` (rol değiştir).
- Admin dashboard **istatistik kartları** agregat olsun (toplam kullanıcı, bağlı proje, son 7g commit, genel sağlık %) — **kişi kıyas tablosu değil.**
- Frontend: `AdminDashboard.jsx`, `UserDashboard.jsx`, rol bilgisini tutan hafif bir auth context.
- **Kabul:** user, admin uçlarında 403 alır; soft-delete edilen kullanıcı listede görünmez; etik testler yeşil.

### FAZ 3 — Proje Bağlama (şifreli credential)
**Amaç:** Kullanıcı kendi Git/Jira/Trello kaynağını bağlar; token **şifreli** saklanır. (Mevcut `adapters/` altyapısıyla uyumlu.)
- Backend: `UserProject` (user_id FK, project_name, source_type, source_url, timestamps) ve `ProjectCredential` (encrypted_value — **Fernet**, `ENCRYPTION_KEY` env). `cryptography` ekle.
- `POST /api/user/projects` (token'ı şifrele, kaydet), `GET /api/user/projects` (**credential asla dönme**, sadece "bağlı" + last_run), `DELETE /api/user/projects/{id}` (sahiplik kontrolü: yalnız kendi projesi).
- Mümkünse `UserProject`'i mevcut `Repo`/adapter factory'sine bağla; ayrı bir veri adası yapma.
- Frontend: `AddProjectForm.jsx`, `ProjectList.jsx`.
- **Kabul:** token hiçbir response/log'da plain görünmez; başkasının projesini silme → 403/404; `tests/test_projects.py`.

### FAZ 4 — Analiz Motoru + (opsiyonel) MCP/LLM
**Amaç:** Bağlı projeden commit çek, kalite skoru üret — mevcut `metrics`/`rules`/`adapters` motoruyla **entegre**, paralel ikinci motor kurma.
- Backend: bağlı kaynaktan commit fetch (şifreli token'ı decrypt ederek), mevcut normalize modele (`Commit`, `Task`...) yaz, mevcut metrik motorunu çalıştır.
- Commit kalite sinyalleri (mesaj konvansiyonu, dosya/satır genişliği) **takım hijyeni** olarak raporlansın — bireysel ceza/sıralama olarak değil.
- Analizi arka planda çalıştır (**mevcut APScheduler** zaten bağımlılıkta) — Celery ekleme. `POST /api/user/projects/{id}/analyze` + durum sorgu ucu.
- LLM/MCP **opsiyonel ve varsayılan kapalı** (`llm/advisor.py` desenini izle; `ANTHROPIC_API_KEY` yalnız açıkken). On-prem: veri dışarı çıkmaz.
- Frontend: `AnalysisResults.jsx`, `CommitTable.jsx` — renk kodları destek dili ("yardım gerekebilir").
- **Kabul:** eksik alanlı commit'te skor uydurulmaz, `data_completeness` düşer; etik testler yeşil.

### FAZ 5 — İK / İzin Modülü (kullanıcının yeni fikri, çerçeveye uygun)
**Amaç:** Self-servis izin/tatil takibi + izin bağlamının metriklere yansıması. Bu faz kullanıcının "genel İK takip sistemi" fikrinin **çerçeveye uygun** hâlidir.
- Backend: `Leave` (user_id/developer_id FK, start_date, end_date, leave_type: yillik|hastalik|rapor, description, status: pending|approved|rejected, approved_by, approved_at, created_at). Migration ile.
- `POST /api/user/leave-requests` (çalışan ani izin girer), `PUT /api/admin/leave-requests/{id}` (admin/yönetici onay/ret), takvim ucu.
  - **Guardrail:** bir çalışan yalnız **kendi** izin taleplerini görebilir; yönetici yalnız **kendi takımını**. İzin sebebi/`description` gibi hassas alan bireysel görünüm kurallarına tabidir (leaderboard'a sızmaz).
- **Metrik entegrasyonu (asıl değer):** `metrics/engine.py` ve bireysel görünümde, kişinin/takımın metrik penceresi hesaplanırken **onaylı izin günleri hariç tutulur** — "2 hafta izindeki kişide düşük commit = anomali değil". Cycle time hesabı izin günlerini düşer.
- İzin **takvimi** takım görünümünde olabilir (kim ne zaman müsait) — bu operasyonel bir bilgidir, performans kıyası değildir; yine de isim maskeleme/anonim moduna saygı duy.
- Frontend: `LeaveRequestForm.jsx`, `LeaveCalendar.jsx`, `LeaveApprovalList.jsx`.
- **Kabul:** izin günleri metrikten düşülüyor (bunun için test yaz); çalışan başkasının iznini göremiyor (test yaz); anonim mod izin görünümünü de maskeliyor; etik testler yeşil.

---

## 4) HER FAZ İÇİN "DONE" TANIMI
- [ ] Dokunulan mevcut dosyalar önce okundu, üslup korundu.
- [ ] Yeni tablo(lar) için Alembic migration üretildi ve `upgrade head` çalışıyor.
- [ ] Yeni özellik için pytest testi + ilgili **etik guardrail testi** yazıldı.
- [ ] `pytest tests` tamamen yeşil (özellikle `test_leaderboard_ucu_yok` ve etik testler).
- [ ] `serve` ile açılıp ilgili akış manuel doğrulandı (kısa not düş).
- [ ] Secret/token env'den; hiçbir credential response/log/URL'de plain değil.
- [ ] Tek, anlamlı commit atıldı; push için benden onay istendi.

## 5) YAPMA LİSTESİ (kırmızı çizgiler)
- ❌ Birden çok kişinin metriğini yan yana döndüren HERHANGİ bir uç/tablo.
- ❌ Eksik veriyi puan cezasıyla "doldurmak" ya da metrik değeri **uydurmak**.
- ❌ Plain token/şifre saklamak, log'lamak, URL'de taşımak.
- ❌ Mevcut kimlik akışını (`current_dev` tek noktası) baypas eden paralel kimlik.
- ❌ Anonim/bireysel-görünüm kurallarını izin/İK modülünde delmek.
- ❌ Bir fazı yarıda bırakıp diğerine atlamak; testleri kırık bırakmak.
- ❌ Mevcut sade JSX frontend'i gereksiz büyük bağımlılıklarla değiştirmek (önce sor).

## 6) COMMIT & BRANCH
- Branch: `faz-1-kimlik`, `faz-2-panel`, `faz-3-proje-baglama`, `faz-4-analiz`, `faz-5-izin`.
- Commit formatı: `feat(auth): JWT login + refresh`, `fix(dashboard): admin agregat kart`, `test(leave): izin günü metrikten düşülüyor`.

---

**Başlangıç:** Faz 1 için kısa bir plan (dosya listesi + şema kararı: `User`↔`Developer` bağı nasıl) çıkar, bana onaylat, sonra uygula. Etik çerçeveyle çelişebilecek herhangi bir tasarım kararında dur ve sor.
