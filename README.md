# Vantage

Şirketin **kendi verisiyle çalışan, on-prem** (dışarıya veri göndermeyen) mühendislik
sağlığı panosu. Git ve Jira/Trello verisini ortak bir şemaya normalize eder;
DORA + akış metriklerini **takım seviyesinde sağlık göstergesi** olarak sunar,
bir kural motoruyla insan-dostu süreç önerileri üretir. Kod içeriği taraması
dış araca (SonarQube vb.) bağlı değildir — kendi **AI Kod Analizi** modülüyle
yapılır (Claude ya da yerel/OpenAI-uyumlu LLM).

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
  `GitProvider` (git log / GitLab), `TaskProvider` (Jira / Trello). Yeni kaynak
  eklemek çekirdeği değiştirmez; kirli/eksik alanlar tek yerde (ingest) ele alınır.
  Kod içeriği taraması ayrı bir **AI Kod Analizi** modülüdür (dış araç değil).
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
    adapters/   # git_log, gitlab, jira, trello, fixture + ortak arayüzler
    api/        # REST uçları (etik kurallar burada zorlanır)
    core/       # YAML config yükleyici, DB
    llm/        # opsiyonel öneri katmanı (pluggable, varsayılan kapalı)
    metrics/    # metrik motoru (değer + tamlık + katman)
    models/     # normalize şema (teams, commits, PR'lar, tasks, transitions, ...)
    rules/      # kural motoru (eşikler config'ten, destek dilli öneriler)
    services/   # ingest, pipeline, sağlık durumu eşlemesi
  migrations/   # Alembic
  scripts/seed_dirty_data.py   # sentetik KİRLİ veri üreteci
  tests/        # metrikler (tam+eksik veri), kurallar, etik uçlar, auth/İK/izin,
                # anket anonimliği, kod-analiz prompt, projeler (246 test)
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
#    Not: Uygulama açılışta (serve/sync) Base.metadata.create_all + ensure_schema_patches
#    de çalıştırır — eksik tablo/kolonu backfill eder. Yani portatif/migration'sız
#    demo kurulumunda alembic zorunlu değildir; migration + create_all birlikte
#    şemayı garanti eder.

# 3) Demo verisi (sentetik kirli veri) + ilk senkron
.venv\Scripts\python scripts\seed_dirty_data.py
.venv\Scripts\python -m app.cli sync
#    Senkron ARTIMLIDIR: son başarılı çekimden sonrasını alır (git tarafında;
#    görev kaynakları tam çekilir — tam görüntü olmadan "kaynakta silinmiş"
#    tespiti yanlış kayıtları kayıp sayardı). Tam çekim gerekirse:
#    .venv\Scripts\python -m app.cli sync full

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

### Şifremi unuttum

Giriş ekranındaki **"Şifremi unuttum"**, e-postayla sıfırlama LİNKİ göndermez
— bu kurulum bilerek bir SMTP sunucusu gerektirmez:

1. Kullanıcı giriş ekranından e-postasını girer.
2. Sunucu hesabı bulur, **yeni bir geçici parolayı hemen üretip uygular**
   (`must_change_password` işaretlenir, eski oturumlar düşer).
3. Yeni parola ekranda gösterilir; kullanıcı **kopyalayabilir** ya da
   **"E-postama gönder"** ile kendi e-posta istemcisinde önceden doldurulmuş
   bir taslak açar (`mailto:` — sunucu e-posta göndermez, taslağı göndermek
   kullanıcıya kalır).
4. Kullanıcı ilk girişte kendi parolasını belirler.

Güvenlik notu (bilinçli tasarım ödünü): bu uç hesap numaralandırmayı
**önlemez** ve ikinci bir kimlik doğrulama adımı (e-postaya gönderilen
link/kod) içermez — yalnızca e-posta adresini bilen biri o hesabın parolasını
sıfırlayıp yeni değeri görebilir. Kapalı, tek kuruluşluk, on-prem bir araç için
kabul edilmiş bir risktir; internete açık bir kurulumda **kullanılmamalıdır**.
IP bazlı hız sınırı (15 dk / 5 istek) yalnızca toplu e-posta taramasını
yavaşlatır, bu ödünü ortadan kaldırmaz. Yönetici panelindeki hesap oluşturma
ve parola sıfırlama akışları bundan bağımsız, değişmeden çalışır.

### Yerel modeller (LLM + RAG kullanacaksanız)

`config/config.yaml` deposu `llm.provider: local` ve `rag.enabled: true` ile gelir;
ikisi de [Ollama](https://ollama.com) üzerinden **iki modele** ihtiyaç duyar:

```powershell
ollama pull bge-m3         # embedding (RAG) — ~1.2 GB, çok dilli
ollama pull qwen2.5:14b    # sohbet/öneri   — ~9 GB, genel amaçlı
```

**Neden 14B, neden 7B değil:** `qwen2.5:7b` ile iş analizi ölçüldüğünde model
prompt'taki sayıyı okuyamıyordu ("+1232/-7 satır"ı "12 commit" diye yazdı) ve
Türkçe'de var olmayan kelimeler üretiyordu. Prompt iki kez sıkılaştırıldı,
davranış değişmedi — bu 7B'nin Türkçe tavanı. 14B daha yavaştır (CPU'da analiz
başına belirgin bekleme); bunu göze alamıyorsanız doğru hamle daha küçük modele
inmek değil, `llm.enabled: false` ile üretimi kapatıp eşleştirme + insan onayı
katmanıyla çalışmaktır — uydurulmuş bir analiz, analizsizlikten kötüdür.

Modeller yoksa senkron çökmez ama indeksleme atlanır ve şu uyarıyı verir:
"Embedding sağlayıcısına ulaşılamadı … chunk gömülmeden kaldı". `/api/teams/{id}/ask`
ucu da cevap üretemez. Veri dışarı çıkmaz — her iki model de yereldir.

Testler: `cd backend; .venv\Scripts\python -m pytest tests`

Ölçüm betikleri (üretim veritabanına yazmaz, geçici DB kurup siler):

```powershell
.venv\Scripts\python scripts\load_test.py 50000 5000   # metrik motoru ölçeği
.venv\Scripts\python scripts
ag_scale_test.py         # asistan indeksi ölçeği
.venv\Scripts\python scripts
ag_eval.py --model bge-m3  # retrieval kalitesi + eşik
```

## Hesap yönetimi ve ek modüller

Ürün arayüzü gerçek giriş sistemi ve İK/çalışan modülleri içerir.

### Giriş ve hesaplar
- **Gerçek giriş:** e-posta + parola (bcrypt hash) → JWT (`PyJWT`, HS256).
  İmza anahtarı `VANTAGE_SECRET` ortam değişkeninden okunur. Tahmin edilebilir SABİT
  varsayılan YOKTUR: env verilmemişse açılışta güçlü rastgele bir anahtar üretilip
  gitignore'lu `backend/.secrets.env`'e yazılır (`ensure_jwt_secret`). Yine de
  üretimde `VANTAGE_SECRET`'i siz verin — anahtarın yaşam döngüsü sizde olsun.
  Oturum 12 saat geçerli; parola değişince eski token'lar düşer (`token_version`).
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
| `VANTAGE_SECRET` | JWT imza anahtarı | Üretimde evet |
| `DATABASE_URL` | config'teki DB url'ini ezer | Hayır |
| `GITHUB_TOKEN` | GitHub oran sınırını artırır / özel repo | Hayır (public repo tokensiz) |
| `ANTHROPIC_API_KEY` | commit AI değerlendirme (provider=claude) | Yalnızca AI açıksa |

> **Kimlik tek katmanlıdır: JWT (Bearer).** Dashboard uçları dahil her uç geçerli
> token ister; tokensiz istek 401 döner (`app/api/routes.py` router bağımlılığı).
> Eskiden dashboard tarafında kullanılan, istemcinin istediği değeri yazabildiği
> için taklit edilebilen `X-Dev-Id` başlığı **kaldırıldı** — kişi kimliği artık
> yalnızca token'ın sahibinden çıkarılır.

## Config referansı (`config/config.yaml`)

Her şey config'ten yönetilir; **hiçbir metrik zorunlu (elle girilen) veriye bağlı
değildir** (İlke B):

| Bölüm | Ne yapar |
|---|---|
| `app.anonymize_individuals` | `true` → takım-agregat mod: isimler maskeli, bireysel uçlar kapalı |
| `app.individual_view_enabled` | bireysel görünümü tümden aç/kapat |
| `sources.git.provider` · `sources.tasks.provider` | adaptör seçimi: `git_log`/`gitlab`, `jira`/`trello`; `fixture` = sentetik demo verisi, `none` = kaynak yok |
| `sources.tasks.status_mapping` | kaynaktaki serbest metinli kolon/statü adlarını `backlog`/`in_progress`/`done`'a eşler (ör. "Araştırma Konuları" → backlog). **Yalnız bu dosyadan yönetilir** — panelde düzenleme ekranı yoktur, akış zaten kartın Trello'daki listesiyle belirlenir. Eşlenmeyen kolon **WIP'e sayılmaz** (bilinmeyen, "akışta" değildir) ama veri tamlığını düşürür ve senkron bunu uyarı olarak bildirir |
| `app` · dil | Arayüz TR/EN — seçim kullanıcıya ait, tarayıcı diline BAKILMAZ (İngilizce OS kullanan Türk çalışana arayüz sormadan İngilizce gösterilmemeli). Seçim `Accept-Language` ile sunucuya da gider: metrik adları ve durum etiketleri API'den geldiği için yalnız arayüzü çevirmek panoyu yarı Türkçe bırakırdı |
| `sources.tasks.jira.auth` / `.email` / `.api_style` | Jira **Cloud** e-posta + API token ile `basic` auth ister ve yeni arama ucunu kullanır; `bearer` yalnız Server/Data Center içindir. `api_style: auto` adresten karar verir. Panelden de girilebilir |
| `sources.tasks.jira.story_points_field` | story point alan kimliği kurulumdan kuruluma değişir; bulunamazsa senkron uyarı verir. Boş bırakılırsa alan hiç okunmaz |
| `sources.git.scan_all_branches` | `git_log`: yalnız HEAD (varsayılan) ya da `--all` ile tüm dallar |
| `llm.local.api_style` / `.context_tokens` | `ollama` → `/api/chat` + `num_ctx` (bağlam gerçekten ayarlanır); `openai` → `/v1/chat/completions` (vLLM/OpenRouter). Bütçeyi aşan prompt gönderilmeden kırpılır ve kırpıldığı beyan edilir |
| `metrics.<ad>.enabled` | metriği aç/kapat — kapalıysa hesaplanmaz, kartı bile görünmez |
| `metrics.cycle_time.source/fallback` | veri katmanı zinciri (`jira_status` → `pr_merge`) |
| `health_thresholds` | yeşil/kırmızı eşikleri + `data_completeness_min` (altında "veri yetersiz") |
| `rules.<ad>` | kural motoru eşikleri; her kural tek tek kapatılabilir |
| `llm` | opsiyonel öneri + kod analizi katmanı — **kod varsayılanı kapalı** (`LLMSettings.enabled = False`); `local` (Ollama/vLLM, veri dışarı çıkmaz) ya da bilinçli tercihle `claude` |
| `rag` | takım kayıtları üzerinde soru-cevap asistanı — **kod varsayılanı kapalı**. `embedding` (vektör modeli, sohbet modelinden AYRI), `chunk` (parça boyutu), `retrieval.top_k`/`min_score` (kaç kayıt + eşik) |

> ⚠️ Depodaki `config/config.yaml` bu varsayılanları **ezer**: `llm.enabled: true`
> ve `rag.enabled: true`. Sağlayıcı `local` olduğu için veri dışarı çıkmaz, ama
> ikisi de yerel modellerin kurulu olmasını bekler (bkz. "Yerel modeller").
> `provider: claude` seçerseniz kod analizi ve öneri metinleri Anthropic API'sine
> gider; RAG'ın **vektörleri** yine yerelde kalır (Anthropic'in embedding ucu yoktur).

> 🔗 **İş ↔ commit bağı için commit konvansiyonu.** Kaynaklarda bu bağ yoktur:
> Trello kart id'si opak bir hash'tir, commit mesajında geçmez. Sistem bağı
> başlık benzerliğinden **tahmin** eder ve ölçülen ilk sıra isabeti ~%50'dir.
> Tahminden kurtulmak için commit mesajına kartın numarasını yazın:
>
> ```
> feat(rapor): aylik ozet ekrani
>
> Refs [#42]
> ```
>
> Numara Trello kartının üstünde görünen `idShort`'tur; arayüzde her işin
> başlığının yanında da yazar. Jira'da anahtar (`VAN-123`) parantezsiz de
> tanınır. Böyle bir referans taşıyan commit'in bağı **tahmin edilmez, kesin
> kurulur** ve onay beklemez; o iş için anlamsal öneri de üretilmez.
>
> Çıplak `#42` bilerek **kabul edilmez** — git'te o neredeyse her zaman bir
> GitHub issue/PR numarasıdır ve kabul etmek "fix #5" yazan bir commit'i 5
> numaralı karta kesin bağ diye işaretlerdi. Aynı numara birden çok işe aitse
> (Trello'da `idShort` board başına benzersizdir) bağ kurulmaz, senkron bunu
> uyarı olarak bildirir. Geçmiş commit'ler bu yolla kurtarılamaz — konvansiyon
> yalnız bundan sonrasını çözer, eskiler için onay ekranı kullanılır.

> 📏 `rag.retrieval.min_score` embedding modeline **ve** korpus büyüklüğüne bağlı
> ampirik bir sayıdır — kopyalanmaz, ölçülür. Model değiştirdiğinizde ya da veri
> belirgin büyüdüğünde yeniden belirleyin:
> `python scripts\rag_eval.py --model <model> --json sonuc.json`
> Script ilgili kayıtların en düşük skorunu ve alakasız sorulardan gelen en yüksek
> skoru basar; eşik bu ikisinin arasına konur. İkisi çakışıyorsa sorun eşikte
> değil embedding modelindedir.

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
dayanıklılık gerçek pipeline üzerinde kanıtlanır. Test paketi (246 pytest + 40 vitest) her
metriği hem tam hem eksik veriyle, her kuralın tetiklenme senaryosunu, etik
kısıtları (leaderboard ucu yok, bireysel görünüm yetkisi), auth/İK izinlerini
ve migration zincirini kapsar.

## API özeti

| Uç | Açıklama |
|---|---|
| `GET /api/teams` · `/api/teams/{id}/summary` | takım sağlık kartları + öneriler (varsayılan görünüm) |
| `GET /api/teams/{id}/series/{metric}` | haftalık trend |
| `GET /api/teams/{id}/code-health` | AI kod analizi özeti (dış araç yok — kendi modülümüz) |
| `GET /api/developers/{id}/summary` | bireysel görünüm — yalnız kişinin kendisi, yöneticisi ya da admin; aksi hâlde 403 |
| `GET /api/teams/{id}/ai-advice` | LLM önerisi — `llm.enabled: true` değilse 503 |
| `GET /api/config/ui` | frontend'in göstereceği metrik seti |

Tablodaki uçların tamamı `Authorization: Bearer <token>` ister; tokensiz istek
401 döner. Şirket ortamında SSO'ya geçilecekse değiştirilecek tek nokta
`app/api/auth.py: current_user` bağımlılığıdır — uçların hiçbiri değişmez.
