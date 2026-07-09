# Engineering Health Dashboard

Şirketin **kendi verisiyle çalışan, on-prem** (dışarıya veri göndermeyen) mühendislik
sağlığı panosu. Git, Jira/Trello ve SonarQube/linter verisini ortak bir şemaya
normalize eder; DORA + akış metriklerini **takım seviyesinde sağlık göstergesi**
olarak sunar ve bir kural motoruyla insan-dostu süreç önerileri üretir.

**Kategori:** Engineering Intelligence / Developer Productivity (LinearB, Swarmia,
Jellyfish muadili — ancak iç sürüm: veri asla dışarı çıkmaz).

---

## Bu araç ne DEĞİLDİR — etik çerçeve kararları

Bu proje bilinçli olarak bir **gözetim aracı değil, süreç sağlığı aracıdır**.
"Kim ne kadar çalışıyor"u değil, "süreç nerede tıkanıyor, takım nerede
zorlanıyor"u gösterir. Bu, pazarlık edilmez bir tasarım kısıtı olarak koda işlendi:

1. **Leaderboard yok — API seviyesinde.** Hiçbir uç, birden çok kişinin metriğini
   yan yana döndürmez. `/api/directory` yalnızca isim/rol verir; metrik içermez.
   Bunu bir test de zorlar (`test_leaderboard_ucu_yok`).
2. **Bireysel görünüm yetkilidir.** Yalnızca kişinin kendisi ve yöneticisi
   erişebilir (sunucu tarafında zorlanır). Kıyas **yalnızca kişinin kendi
   geçmişiyle** yapılır: "geçen aya göre şu kadar hızlandın" EVET,
   "Ali, Ayşe'den yavaş" HAYIR.
3. **Anonimleştirme modu.** İK "isim istemiyoruz" derse `anonymize_individuals: true`
   ile sistem takım-agregat modda çalışır: isimler maskelenir ("Geliştirici #7"),
   bireysel uçlar tamamen kapanır. Kimlik baştan bir katman arkasındadır.
4. **Ceza dili yok.** Kırmızı = "takım zorlanıyor, yardım gerekebilir";
   yeşil = "akıyor". Metrikler performans puanı değil sağlık göstergesidir.
5. **Fix commit'i asla kişi sinyali değildir.** Bug fix eden çoğu zaman en değerli
   kişidir. Fix yoğunluğu yalnızca takım seviyesinde, dosya-hotspot ve deploy
   kalitesi (CFR) bağlamında kullanılır.
6. **Goodhart bilinci.** Bireysel çıktı sayacı (commit sayısı, satır sayısı,
   token) hiçbir yerde metrik değildir.

## Kirli veri bir hata değil, ana özelliktir (İlke A)

Gerçek dünyada estimate girilmez, status güncellenmez, commit'lerin kimliği
bozuktur. Çoğu ölçüm aracı burada ölür; bu sistem tam tersini yapar:

- **Eksik alan metriği kapatır, sistemi çökertmez.** Her metrik
  `(değer, veri tamlığı, kaynak katmanı)` üçlüsü üretir. Değer asla uydurulmaz;
  yetersizse dashboard dürüstçe **"veri yetersiz"** gösterir.
- **Eksikliğin kendisi bir metriktir:** *process hygiene* göstergesi estimate/status/
  review doluluk oranlarını raporlar — cezalandırmadan.
- **Katmanlı veri modeli:**
  - **Katman 0 (Git):** kimse elle girmez → en güvenilir. PR cycle time, review
    latency, rework buradan gelir.
  - **Katman 1 (status geçişleri):** insanlar tarih girmese de status değiştirir;
    sistem geçişleri otomatik damgalar → cycle time.
  - **Katman 2 (estimate/due date/story point):** varsa kullanılır, yoksa metrik
    **gizlenir** — asla varsayılan uydurulmaz.
- **Fallback zinciri config'ten:** ör. `cycle_time.source: jira_status`,
  `fallback: pr_merge` — task verisi yoksa Katman 0'a düşer ve bunu
  `source_layer` alanında beyan eder.

## Mimari

```
Kaynak Adaptörleri → Normalizasyon (ortak şema) → Metrik Motoru (config okur)
                                                → Kural Motoru (öneri üretir)
                                                → API → Dashboard
                                                   ↑
                                       (opsiyonel LLM öneri katmanı — varsayılan KAPALI)
```

- **Backend:** Python + FastAPI + SQLAlchemy, PostgreSQL (Alembic migration).
- **Adaptör deseni (zorunlu):** her kaynak tek ortak arayüz uygular —
  `GitProvider` (git log / GitLab), `TaskProvider` (Jira / Trello),
  `QualityProvider` (SonarQube / linter fallback). Yeni kaynak eklemek çekirdeği
  değiştirmez; kirli/eksik alanlar tek yerde (ingest) ele alınır.
- **Zamanlayıcı:** APScheduler (config: `sync.interval_minutes`).
- **Frontend:** React + Vite + Recharts; build çıktısını FastAPI servis eder
  (tek process, on-prem kurulumu kolay).
- **Metrik standardı:** kendi metriğimizi uydurmuyoruz — DORA + akış metrikleri:
  cycle time, PR review time, review latency, deployment frequency,
  change failure rate, WIP, rework + process hygiene.

### Dizin yapısı

```
backend/
  app/
    adapters/   # git_log, gitlab, jira, trello, sonarqube, linter, fixture + ortak arayüzler
    api/        # REST uçları (etik kurallar burada zorlanır)
    core/       # YAML config yükleyici, DB
    llm/        # opsiyonel öneri katmanı (pluggable, varsayılan kapalı)
    metrics/    # metrik motoru (değer + tamlık + katman)
    models/     # normalize şema (teams, commits, PR'lar, tasks, transitions, ...)
    rules/      # kural motoru (eşikler config'ten, destek dilli öneriler)
    services/   # ingest, pipeline, sağlık durumu eşlemesi
  migrations/   # Alembic
  scripts/seed_dirty_data.py   # sentetik KİRLİ veri üreteci
  tests/        # 28 test: metrikler (tam+eksik veri), kurallar, etik uçlar
frontend/       # React dashboard
config/config.yaml
```

## Kurulum

Gereksinimler: Python 3.12+, Node 18+, PostgreSQL (ya da geliştirme için SQLite).

```powershell
# 1) Backend
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2) Veritabanı — config/config.yaml'daki database.url'i ortamınıza göre ayarlayın
#    (DATABASE_URL ortam değişkeni config'i ezer). Sonra:
.venv\Scripts\alembic upgrade head

# 3) Demo verisi (sentetik kirli veri) + ilk senkron
.venv\Scripts\python scripts\seed_dirty_data.py
.venv\Scripts\python -m app.cli sync

# 4) Frontend build
cd ..\frontend
npm install
npm run build

# 5) Çalıştır
cd ..\backend
.venv\Scripts\python -m app.cli serve    # http://127.0.0.1:8000
```

> Bu repo, demo için `.pgsql/` altında taşınabilir bir PostgreSQL ile geliştirildi
> (kurulum gerektirmez): `.pgsql\pgsql\bin\pg_ctl -D .pgsql\data -o "-p 5433" start`

Testler: `cd backend; .venv\Scripts\python -m pytest tests`

## Nabız — hesap yönetimi ve ek modüller

Ürün arayüzü **Nabız** adıyla gerçek giriş sistemi ve İK/çalışan modülleri içerir.

### Giriş ve hesaplar
- **Gerçek giriş:** e-posta + parola (bcrypt hash) → JWT (`python-jose`, HS256).
  İmza anahtarı `EHD_SECRET` ortam değişkeninden okunur (üretimde MUTLAKA verin;
  yoksa güvensiz geliştirme varsayılanı kullanılır). Oturum 12 saat geçerli.
- **İlk kurulum sihirbazı:** sistemde hiç aktif yönetici yoksa açılışta ilk admin
  hesabı oluşturulur (CLI gerektirmez). Alternatif: `python -m app.cli set-password <email> <parola>`.
- **İlk-giriş zorunlu parola:** admin geçici parola verir/sıfırlar; kullanıcı ilk
  girişte kendi parolasını belirlemeden panoya geçemez.
- **Yönetici paneli:** çalışan ekle/sil, rol (çalışan/admin), aktif/pasif,
  parola sıfırla, takım atama, toplu pasifleştir, arama/sıralama/sayfalama.
  Son aktif yönetici düşürülemez/silinemez (kilitlenme koruması).
- **Ayarlar sayfası:** profil, kendi parolasını değiştirme, tema (açık/koyu/oto),
  oturumu kapatma.

### Projelerim (GitHub) + commit değerlendirme
- Kullanıcı kendi GitHub reposunu ekler; commitler `project_commits` tablosuna
  (takım metriklerinden **izole**) çekilir — httpx ile GitHub REST API.
- **Commit pratiği değerlendirmesi:** mesaj netliği, başlık uzunluğu, gövde
  kullanımı, konvansiyon, düzen boyutlarında 0–100 skor + yapıcı geri bildirim.
  LLM açıksa (config `llm.enabled`) AI, değilse **kural tabanlı** çalışır (çökmez).
  Skor kişiye değil **commit pratiğine** aittir. Kullanıcı kendininkini görür;
  admin tüm kullanıcılarınkine erişebilir.

### İzin panosu (İK)
- Aylık takvim; çalışan kendi + takım arkadaşlarının izinli günlerini, admin
  herkesi görür. Tür: yıllık / rapor / diğer. Admin için ay bazında kişi başına
  toplam izin günü özeti. İzin verisi **metrik/performans hesabına karışmaz**.

### Ortam değişkenleri
| Değişken | Amaç | Zorunlu |
|----------|------|---------|
| `EHD_SECRET` | JWT imza anahtarı | Üretimde evet |
| `DATABASE_URL` | config'teki DB url'ini ezer | Hayır |
| `GITHUB_TOKEN` | GitHub oran sınırını artırır / özel repo | Hayır (public repo tokensiz) |
| `ANTHROPIC_API_KEY` | commit AI değerlendirme (provider=claude) | Yalnızca AI açıksa |

> Kimlik iki katmanlıdır: auth uçları JWT (Bearer), dashboard uçları `X-Dev-Id`
> başlığı kullanır (frontend giriş sonrası oturum sahibinin developer_id'siyle doldurur).

## Config referansı (`config/config.yaml`)

Her şey config'ten yönetilir; **hiçbir metrik zorunlu (elle girilen) veriye bağlı
değildir** (İlke B):

| Bölüm | Ne yapar |
|---|---|
| `app.anonymize_individuals` | `true` → takım-agregat mod: isimler maskeli, bireysel uçlar kapalı |
| `app.individual_view_enabled` | bireysel görünümü tümden aç/kapat |
| `sources.git/tasks/quality.provider` | adaptör seçimi: `git_log`/`gitlab`, `jira`/`trello`, `sonarqube`/`linter`; `fixture` = sentetik demo verisi |
| `metrics.<ad>.enabled` | metriği aç/kapat — kapalıysa hesaplanmaz, kartı bile görünmez |
| `metrics.cycle_time.source/fallback` | veri katmanı zinciri (`jira_status` → `pr_merge`) |
| `health_thresholds` | yeşil/kırmızı eşikleri + `data_completeness_min` (altında "veri yetersiz") |
| `rules.<ad>` | kural motoru eşikleri; her kural tek tek kapatılabilir |
| `llm` | opsiyonel öneri katmanı — **varsayılan kapalı**; `local` (Ollama/vLLM, veri dışarı çıkmaz) ya da bilinçli tercihle `claude` |

Örnek (spec'teki sözleşme):

```yaml
metrics:
  cycle_time:
    enabled: true
    source: jira_status     # git | jira_status | jira_dates
    fallback: pr_merge      # elle veri yoksa buna düş
  estimate_accuracy:
    enabled: false          # takım estimate girmiyorsa kapat
```

## Kural motoru — ölçmekten öteye (İlke D)

| Tespit | Sistemin önerisi |
|---|---|
| PR'lar ort. 4+ gün review'de bekliyor | review WIP limiti / reviewer rotasyonu |
| Aynı dosyalar sürekli fix alıyor | modül refactor / test coverage adayı |
| Kişi başı 5+ açık iş | WIP limiti — çok iş başlatılıyor, az bitiyor |
| Task'ların %70+'ında estimate yok | süreç hijyeni düşük — planlama rutini öner |
| Cuma akşamı deploy + hafta sonu hotfix | riskli deploy penceresi — freeze düşün |

Tüm eşikler config'ten; mesajlar destek dilinde ("kusur değil, görünürlük kaybı").

## Sentetik kirli veri (test stratejisi)

`scripts/seed_dirty_data.py` gerçekçi dağınıklık üretir: estimate'siz task'lar,
hiç review almayan PR'lar, status güncellemeyen takım, kimliksiz commit'ler,
tarihi bozuk kayıtlar, hotspot dosyalar, cuma-akşamı-deploy + hafta-sonu-fix
örüntüsü. Üç takım üç profili temsil eder:

- **Billing** — sağlıklı süreç (kontrol grubu, çoğu gösterge yeşil)
- **Network Ops** — süreç körlüğü (estimate/status girilmiyor → hygiene düşük)
- **CRM** — review darboğazı + hotspot + yüksek WIP + riskli deploy penceresi

Veri fixture JSON'larına yazılır ve **normal ingest hattından** geçirilir —
dayanıklılık gerçek pipeline üzerinde kanıtlanır. 28 pytest, her metriği hem tam
hem eksik veriyle ve her kuralın tetiklenme senaryosunu test eder.

## API özeti

| Uç | Açıklama |
|---|---|
| `GET /api/teams` · `/api/teams/{id}/summary` | takım sağlık kartları + öneriler (varsayılan görünüm) |
| `GET /api/teams/{id}/series/{metric}` | haftalık trend |
| `GET /api/teams/{id}/quality` | SonarQube/linter anlık görüntüsü |
| `GET /api/developers/{id}/summary` | bireysel görünüm — yalnız kendisi + yöneticisi (`X-Dev-Id`) |
| `GET /api/teams/{id}/ai-advice` | LLM önerisi — `llm.enabled: true` değilse 503 |
| `GET /api/config/ui` | frontend'in göstereceği metrik seti |

Kimlik demo amaçlı `X-Dev-Id` başlığıdır; şirket ortamında bu tek nokta
SSO/reverse-proxy başlığıyla değiştirilir (`app/api/routes.py: current_dev`).
