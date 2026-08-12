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
  scripts/task_link_eval.py    # görev↔commit ilk sıra isabeti (prim sabitleri ölçülür)
  tests/        # metrikler (tam+eksik veri), kurallar, etik uçlar, auth/İK/izin,
                # anket anonimliği, kod-analiz prompt, projeler, kimlik eşleme
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

Giriş ekranındaki **"Şifremi unuttum"** üç adımlı çalışır:

1. Kullanıcı e-postasını girer → 6 haneli kod **maille** gönderilir (10 dk).
2. Kodu girer → doğrulanırsa tek kullanımlık bir jeton verilir (15 dk).
3. Yeni parolasını belirler → parola güncellenir, **diğer tüm oturumları
   düşer** ve "parolanız değiştirildi" bilgilendirmesi gider.

Güvenlik:
- Kod ve jeton veritabanında **hash'li** tutulur (düz metin asla saklanmaz);
  karşılaştırma sabit zamanlıdır.
- 5 hatalı denemede kod tamamen iptal edilir; yeni kod istemek gerekir.
- Yeni kod istendiğinde eski kodlar geçersizleşir.
- Uç, e-postanın kayıtlı olup olmadığını **sızdırmaz**; hata mesajları hangi
  adımın patladığını belli etmez.
- Hız sınırı (IP + e-posta başına, 15 dk): kod isteme 5, kod doğrulama 15.
  İkisi ayrı kovadadır — aksi hâlde kod isteği deneme hakkını yer ve "5 hatalı
  deneme" kuralına hiç ulaşılamazdı.

**Kurulum:** `RESEND_API_KEY` gerekir (bkz. `.env.example`). Tanımlı değilse
akış 503 döner — kodu iletemeden parola sıfırlamak kullanıcıyı kilitlerdi.
O durumda sıfırlamayı yönetici yapar: Yönetici paneli → Hesaplar →
**Parola sıfırla** (bu yol her hâlükârda çalışır).

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

Görev↔commit eşleştirmesinin isabeti ayrı ölçülür (bu betik **mevcut**
veritabanını salt okur, yazmaz — ölçüm kümesi insanın onayladığı bağlardır):

```powershell
.venv\Scripts\python scripts\task_link_eval.py
# Kimlikler henüz eşlenmemişse kişi sinyali hiç oluşmaz ve ölçüm "etkisiz" der.
# "Eşleme yapılsaydı ne olurdu" sorusu için kayıtları geçici olarak birleştirin:
.venv\Scripts\python scripts\task_link_eval.py --link 31=1
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
  oturumu kapatma, **kaynak kimlikleri** (aşağıda).

### Hesapları git ve Trello kimliğine bağlama

Bir insan üç ayrı yerde üç ayrı kimlikle görünür: giriş hesabı (e-posta), git
(commit e-postası), Trello (opak üye id'si). **Bu bağ kurulmadan sistem onları
ayrı insan sayar** — commit'ler bir kayda, kartlar diğerine düşer, takım kadrosu
şişer ve WIP kişi başına bölündüğü için metrik olduğundan İYİ görünür.

İki yol var; ikisi de aynı veriyi yazar (`developers.external_ids`):

- **Yönetici paneli → Entegrasyon → Trello üyeleri.** Board'un kadrosu doğrudan
  Trello'dan listelenir (bağlı/bağsız, hangi hesapta). Bağsız üye bir hesapla
  eşlenir; aynı üye id'sini taşıyan **kopya kişi kaydı hedefe birleştirilir**
  (kartları taşınır, kopya silinir). Sistem yalnız **aday** önerir — tam ad ya da
  kullanıcı adı bir hesabın adı/e-postasıyla birebir tutuyorsa (Türkçe karakterler
  katlanarak) satır "muhtemelen X" diye işaretlenir. **Otomatik bağlama yoktur**:
  yanlış eşleme, bir insanın işini sessizce başkasına atfeder.
- **Ayarlar → Kaynak kimliklerim (kullanıcının kendisi).** Kişi kendi git
  e-postalarını ve Trello üyeliğini seçer. Bu yol olmadan bağ pratikte hiç
  kurulmuyordu: kendi commit e-postasını bilen tek kişi zaten sahibidir.

Her iki yolda da **başkasında olan bir kimlik alınamaz** (409, kimde olduğunu
söyler); giriş hesabı olan bir kayıt "kopya" sayılıp birleştirilemez — o başka
bir insandır. Kullanıcının kendi yaptığı değişiklik denetim kaydına yazılır.

- **Çoklu git e-postası:** aynı insan kişisel adresiyle ve GitHub'ın
  `…@users.noreply.github.com` adresiyle commit atar. `external_ids["git"]` artık
  hem tek metin hem **liste** kabul eder, ikisi de aynı kişiye çözülür. Kayıt
  birleştirmede e-postalar **birleşir** — eskiden kopyanınki atılıyor ve bir
  sonraki senkron aynı kopyayı yeniden açıyordu (sessiz döngü).
- **Çoklu atanan:** Trello kartı birden çok üyeye atanabilir; adaptör yalnız
  `idMembers[0]`'ı okuyordu ve ikinci kişi hiçbir yerde görünmüyordu. Artık tüm
  atananlar `task_assignees` tablosuna yazılır (`tasks.assignee_id` birincil
  atanan olarak korunur — WIP ve kişi bazlı metrikler ona dayanıyor).
- **Kurulum kontrol listesi** (Yönetici → Onboarding) artık "hesapların kaçı
  Trello üyeliğine bağlı" adımını da gösterir.

### Görevlerim ve commit'lerim (kişi bazlı)

Bireysel görünümde kişinin kartları ve o kartlara bağlanmış commit'ler listelenir
(`GET /api/developers/{id}/task-links`). Bağın kaynağı görünür: *kesin* (commit
mesajında kart numarası) ya da *öneri*. Yetki bireysel özetle **aynı kapıdan**
geçer (yalnız kişinin kendisi, yöneticisi, admin; anonimleştirme modunda kapalı).

Bu bir üretkenlik ölçümü **değildir**: uç tek kişi döner, hiçbir sayaç/skor
toplamı/sıralama üretmez ve bunu bir test zorlar (`test_api_ethics.py`).

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
| `llm.local.timeout_seconds` | istek zaman aşımı (varsayılan 300). Doğrusu **donanıma bağlıdır**: 14B model CPU'da ölçüldüğünde soğuk başlatma ~23 sn, tek bir iş analizi 26-58 sn sürüyor; eski sabit 120 sn ilk isteği `ReadTimeout`'a düşürüyordu. Büyütmek modeli hızlandırmaz — beklemek istemiyorsanız daha küçük model ya da `llm.enabled: false` |
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

> 👤 **Kişi sinyali hesaplanır, sıralamaya girmez — çünkü ölçüldü.** Kartın
> atananı ile commit'in yazarı aynı insansa bu bilgi bağın yanında (`same_person`,
> arayüzde "aynı kişi") gösterilir. Ama sıralama primi **0.0**'dır:
>
> ```
> scripts\task_link_eval.py --link 31=1     # 6 onaylı bağ, 63 aday commit
>   yalın benzerlik   ilk sıra 5/6 · ort. sıra 1.50
>   +zaman (0.03)     ilk sıra 5/6 · ort. sıra 1.50
>   +kişi  (0.05)     ilk sıra 5/6 · ort. sıra 1.50   ← hiçbir değişiklik
> ```
>
> Sebep yapısal: bu depodaki **tüm commit'ler tek yazara ait**, dolayısıyla prim
> adayların hepsine gidiyor ve hiçbir şeyi yeniden sıralayamıyor (betik bunu
> ayrıca uyarı olarak basar). Ölçülmemiş bir fayda için sıralamayı oynatmak,
> sistemin kaçındığı şeyin ta kendisi olurdu: uydurulmuş kesinlik. Birden çok
> yazarlı bir depoda sinyal ayırt edici hâle gelir; o zaman
> `--person-bonus 0.05` ile **yeniden ölçüp** `task_link.PERSON_BONUS`'u öyle
> değiştirin — kopyalamayın.
>
> Ölçüm kümesi = insanın **onayladığı** bağlar (`status='confirmed'`);
> konvansiyonla kurulanlar hariç tutulur (onlar sıralamaya hiç girmez).

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
dayanıklılık gerçek pipeline üzerinde kanıtlanır. Test paketi (426 pytest + 73 vitest) her
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
| `GET /api/developers/{id}/task-links` | kişinin kartları + bağlı commit'ler (aynı yetki kuralı; sayaç/sıralama üretmez) |
| `GET · PATCH /api/me/identities` | kişinin kendi git e-postaları ve görev kaynağı üyeliği; başkasının kimliği alınamaz (409) |
| `GET /api/admin/trello/members` | board kadrosu + hangi giriş hesabına bağlı (yönetici) |
| `GET /api/teams/{id}/ai-advice` | LLM önerisi — `llm.enabled: true` değilse 503 |
| `GET /api/config/ui` | frontend'in göstereceği metrik seti |

Tablodaki uçların tamamı `Authorization: Bearer <token>` ister; tokensiz istek
401 döner. Şirket ortamında SSO'ya geçilecekse değiştirilecek tek nokta
`app/api/auth.py: current_user` bağımlılığıdır — uçların hiçbiri değişmez.
