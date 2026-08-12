"""YAML konfigürasyon yükleyicisi.

İlke B'nin uygulanma noktası: her metrik config'ten açılıp kapanır,
source/fallback burada tanımlanır. Config dosyası eksik alan içerse bile
sistem çökmez — pydantic varsayılanları devreye girer (graceful degradation).
"""
from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# Proje kökü: backend/app/core/config.py -> 3 seviye yukarı
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


class AppSettings(BaseModel):
    individual_view_enabled: bool = True
    anonymize_individuals: bool = False
    window_days: int = 30
    bucket_days: int = 7


class DatabaseSettings(BaseModel):
    url: str = "sqlite:///./vantage.db"


class SyncSettings(BaseModel):
    interval_minutes: int = 0


class GitLabSource(BaseModel):
    base_url: str = ""
    token_env: str = "GITLAB_TOKEN"
    projects: list[str] = Field(default_factory=list)
    # Dosya listesi commit LİSTESİ ucunda gelmez; en yeni N commit için ayrı
    # istek atılır (GitHub adaptörüyle aynı anlam). Sınırın ötesi None kalır ve
    # tamlık oranı düşer — uydurma yok.
    detail_limit: int = 150
    # Onay verisi yoksa yorumlara düşülür; aranan İLK review olduğu için tüm
    # tartışmayı çekmek gereksiz ağır.
    max_notes_pages: int = 3
    # Ek bot hesapları (kullanıcı adı). Yaygın olanlar zaten koda gömülü.
    bot_users: list[str] = Field(default_factory=list)


class GitHubSource(BaseModel):
    """GitHub API ayarları. Repo listesi ortak `repos` alanından okunur;
    her girdi `slug: owner/repo` (ya da tam URL) taşımalıdır."""

    token_env: str = "GITHUB_TOKEN"
    # Dosya listesi (rework metriği + hotspot kuralı) yalnız commit DETAY
    # isteğiyle gelir; oran sınırını yakmamak için üst sınır.
    detail_limit: int = 150
    max_prs: int = 200


class GitSource(BaseModel):
    provider: str = "git_log"  # git_log | github | gitlab | fixture
    repos: list[dict[str, Any]] = Field(default_factory=list)
    # git_log: yalnız HEAD mi okunsun, `--all` ile tüm dallar mı? Varsayılan dar
    # tutuldu: ölçüm genelde ana dalın akışıdır, `--all` kişisel deneme dallarını
    # da metriğe sokar. Merge edilmemiş dallar da sayılsın isteniyorsa açılır.
    scan_all_branches: bool = False
    gitlab: GitLabSource = Field(default_factory=GitLabSource)
    github: GitHubSource = Field(default_factory=GitHubSource)


class JiraSource(BaseModel):
    base_url: str = ""
    token_env: str = "JIRA_TOKEN"
    projects: list[str] = Field(default_factory=list)
    # Jira CLOUD e-posta + API token ile BASIC auth ister; Bearer yalnızca
    # Server/Data Center kişisel erişim token'ında geçerlidir. Adaptör eskiden
    # yalnız Bearer gönderiyordu → Cloud'da her istek 401 alıyor ve hata sessizce
    # yutulduğu için kullanıcı sadece "0 task" görüyordu.
    auth: str = "basic"        # basic | bearer
    email: str = ""            # basic auth kullanıcı adı (Jira Cloud hesabı)
    email_env: str = "JIRA_EMAIL"   # e-posta config yerine ortamdan da gelebilir
    # auto: base_url'e göre (atlassian.net → Cloud). Cloud'da /rest/api/2/search
    # kaldırıldı; yerine token tabanlı sayfalamalı /rest/api/3/search/jql geldi.
    api_style: str = "auto"    # auto | cloud | server
    # Story point alanı kurulumdan kuruluma DEĞİŞİR. Sabit kodlanmışken yanlış
    # kurulumda sessizce None üretiyordu. Boş bırakılırsa hiç okunmaz.
    story_points_field: str = "customfield_10016"


class TrelloSource(BaseModel):
    key_env: str = "TRELLO_KEY"
    token_env: str = "TRELLO_TOKEN"
    boards: list[str] = Field(default_factory=list)


class StatusMapping(BaseModel):
    """Kaynaktaki statü/kolon adlarının akış kategorilerine eşlenmesi.

    Trello listesi, Jira workflow adımı — hepsi SERBEST METİNDİR ve ekipten
    ekibe değişir ("Araştırma Konuları", "DEVELOPMENT", "QA Bekliyor"…).
    Gömülü kelime listesi bunu asla kapsayamaz; kapsamadığında WIP ve cycle
    time SESSİZCE yanlış çıkar. Bu yüzden eşleme config'ten yönetilir.

    Beyan edilen ad varsayılan kategorisinden çıkarılır (açık beyan kazanır),
    böylece ör. 'open' backlog yerine in_progress yapılabilir."""

    backlog: list[str] = Field(default_factory=list)
    in_progress: list[str] = Field(default_factory=list)
    done: list[str] = Field(default_factory=list)


class TaskSource(BaseModel):
    provider: str = "none"  # jira | trello | fixture | none
    jira: JiraSource = Field(default_factory=JiraSource)
    trello: TrelloSource = Field(default_factory=TrelloSource)
    status_mapping: StatusMapping = Field(default_factory=StatusMapping)


class Sources(BaseModel):
    """Dış kod-kalitesi taraması (SonarQube/linter) KALDIRILDI — kod taraması
    artık kendi AI Kod Analizi modülümüzle yapılır (bkz. app/services/code_analysis.py).
    Eski config.yaml'lardaki `sources.quality` bloğu pydantic'in varsayılan
    extra="ignore" davranışıyla sessizce yok sayılır; yükleme kırılmaz."""

    git: GitSource = Field(default_factory=GitSource)
    tasks: TaskSource = Field(default_factory=TaskSource)


class MetricConfig(BaseModel):
    """Tek bir metriğin config'i. Bilinmeyen ekstra alanlara izin verilir
    (deploy_signal, window_days gibi metriğe özel ayarlar)."""

    model_config = {"extra": "allow"}

    enabled: bool = True
    source: str | None = None
    fallback: str | None = None

    def extra_int(self, key: str, default: int) -> int:
        val = (self.model_extra or {}).get(key, default)
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    def extra_str(self, key: str, default: str) -> str:
        val = (self.model_extra or {}).get(key, default)
        return str(val) if val is not None else default


class Threshold(BaseModel):
    green: float
    red: float


class HealthThresholds(BaseModel):
    model_config = {"extra": "allow"}

    cycle_time_days: Threshold = Threshold(green=3, red=7)
    pr_review_time_days: Threshold = Threshold(green=2, red=5)
    review_latency_days: Threshold = Threshold(green=1, red=4)
    deployment_frequency: Threshold = Threshold(green=3, red=1)
    change_failure_rate: Threshold = Threshold(green=0.15, red=0.30)
    mttr_hours: Threshold = Threshold(green=24, red=72)  # toparlanma süresi (saat); düşük iyi
    wip_per_dev: Threshold = Threshold(green=3, red=5)
    rework_rate: Threshold = Threshold(green=0.15, red=0.35)
    process_hygiene: Threshold = Threshold(green=0.8, red=0.5)
    data_completeness_min: float = 0.5


class RuleConfig(BaseModel):
    model_config = {"extra": "allow"}

    enabled: bool = True

    def extra_num(self, key: str, default: float) -> float:
        val = (self.model_extra or {}).get(key, default)
        try:
            return float(val)
        except (TypeError, ValueError):
            return default


class LLMLocal(BaseModel):
    # Self-hosted / OpenAI-uyumlu uç (Ollama, LM Studio, vLLM, OpenAI, OpenRouter…).
    # base_url'i değiştirerek istenen sağlayıcıya yönlendirilir. api_key_env
    # opsiyonel: anahtar isteyen uçlar için Authorization başlığı gönderilir
    # (Ollama gibi anahtarsız uçlar için boş bırakılır).
    base_url: str = "http://localhost:11434"
    # Genel amaçlı sohbet modeli olmalı. Kod modelleri (…-coder) bu işte
    # bağlamı özetlemek yerine kod üretmeye eğilimli ve Türkçe'de zayıf.
    # 14B tabanı: 7B Türkçe üretimde sayı okuyamıyor ve kelime uyduruyor
    # (ölçüldü; bkz. config/config.yaml'daki not).
    model: str = "qwen2.5:14b"
    api_key_env: str = "LOCAL_LLM_API_KEY"
    # ollama: /api/chat + options.num_ctx  |  openai: /v1/chat/completions
    #
    # NEDEN İKİ STİL: Ollama'nın OpenAI-uyumlu ucu (/v1/chat/completions)
    # `options` kabul ETMEZ, dolayısıyla bağlam uzunluğu ayarlanamaz ve Ollama
    # varsayılan 4096 token'a düşer. Ölçüldü: 400 satırlık (config sınırı) bir
    # analiz prompt'u ~7.700 token iken Ollama prompt_tokens=2050 saydı — diff'in
    # dörtte üçü modele HİÇ ulaşmadı, model yine de puan üretti. Yerel uçta
    # varsayılan bu yüzden 'ollama'. vLLM/OpenRouter/OpenAI için 'openai' seçilir.
    api_style: str = "ollama"  # ollama | openai
    # Modelin bağlam penceresi (token). Prompt bu bütçeye göre kırpılır ve
    # ollama stilinde num_ctx olarak uca bildirilir.
    context_tokens: int = 16384
    # Yanıta ayrılan pay: bütçenin tamamı prompt'a verilirse cevap yeri kalmaz.
    reserve_output_tokens: int = 1024
    # İstek zaman aşımı (saniye). 120 sn SABİTTİ ve yetmiyordu: 14B model CPU'da
    # ölçüldüğünde soğuk başlatma (~9 GB'ın diskten yüklenmesi) tek başına ~23 sn,
    # gerçek bir iş analizi çağrısı ise 30-38 sn sürüyor — ikisi üst üste gelince
    # ilk istek zaman aşımına düşüyor ve kullanıcı "LLM çağrısı başarısız
    # (ReadTimeout)" görüyordu. Değer config'ten yönetilir çünkü doğrusu donanıma
    # bağlıdır: GPU'da 30 sn fazlasıyla yeter, yavaş bir CPU'da 300 sn bile az
    # gelebilir. Zaman aşımını büyütmek modeli hızlandırmaz — çok beklemek
    # istemiyorsanız doğru hamle daha küçük bir model ya da llm.enabled: false.
    timeout_seconds: float = 300.0


class LLMClaude(BaseModel):
    model: str = "claude-sonnet-5"
    api_key_env: str = "ANTHROPIC_API_KEY"


class LLMSettings(BaseModel):
    # On-prem kısıtı: varsayılan KAPALI, dışarı veri göndermez (İlke/Faz 5)
    enabled: bool = False
    provider: str = "none"  # none | local | claude
    local: LLMLocal = Field(default_factory=LLMLocal)
    claude: LLMClaude = Field(default_factory=LLMClaude)


class CodeAnalysisSettings(BaseModel):
    """AI kod analizi ayarları. Kişiyi puanlamaz — repo/modül düzeyinde toplar.
    Rubrik ağırlıkları composite skoru belirler; toplamları 0 değilse normalize
    edilir."""

    enabled: bool = False
    # 7 boyut ağırlığı (composite skor için). Eşit varsayılan.
    weights: dict[str, float] = Field(default_factory=lambda: {
        "readability": 1.0,
        "complexity": 1.0,
        "maintainability": 1.0,
        "test_adequacy": 1.0,
        "security": 1.0,
        "code_smells": 1.0,
        "conventions": 1.0,
    })
    # İsteğe bağlı EK hariç tutma desenleri; temel liste
    # code_analysis.BUILTIN_EXCLUDES'ta sabittir (arayüzde/API'de yok).
    exclude_globs: list[str] = Field(default_factory=list)
    # Bir çalıştırmada en fazla kaç diff analiz edilsin (maliyet freni)
    max_files_per_run: int = 40
    # Diff'te bu satır sayısını aşan dosyalar kırpılır (token freni)
    max_diff_lines: int = 400


class RagEmbeddingSettings(BaseModel):
    """Embedding sağlayıcısı — SOHBET sağlayıcısından AYRIDIR.

    Bu ayrım şart: Anthropic'in embedding ucu yoktur. `llm.provider: claude`
    seçili olsa bile vektörler yerelden (Ollama vb.) gelir. İkisini tek ayara
    bağlamak, Claude seçildiğinde RAG'ı sessizce çalışmaz hâle getirirdi.
    """

    provider: str = "local"  # local | hash
    base_url: str = "http://localhost:11434"
    # Çok dilli olmalı: chunk'lar Türkçe. İngilizce ağırlıklı modeller bu
    # veride ilgili/ilgisiz ayrımını yapamıyor (bkz. scripts/rag_eval.py).
    model: str = "bge-m3"


class RagChunkSettings(BaseModel):
    words: int = 400
    overlap: int = 60


class RagRetrievalSettings(BaseModel):
    top_k: int = 3
    # Bu skorun altındaki isabet atılır. Hepsi atılırsa cevap üretilmez —
    # zayıf eşleşmeyle konuşmak, bilmemekten kötüdür (halüsinasyon kaynağı).
    # Değer EMBEDDING MODELİNE ve KORPUSA bağlıdır (bge-m3 ile ölçüldü:
    # ilgili min 0.5456, alakasız maks 0.4885 → eşik ortada). Model ya da
    # korpus belirgin değişirse scripts/rag_eval.py ile yeniden belirlenir;
    # korpus değişikliği de boşluğu kaydırıyor (ölçüldü, bkz. config.yaml).
    min_score: float = 0.517


class RagSettings(BaseModel):
    """RAG asistanı. Varsayılan KAPALI — açmak bilinçli bir karardır."""

    enabled: bool = False
    embedding: RagEmbeddingSettings = Field(default_factory=RagEmbeddingSettings)
    chunk: RagChunkSettings = Field(default_factory=RagChunkSettings)
    retrieval: RagRetrievalSettings = Field(default_factory=RagRetrievalSettings)
    index: str = "auto"  # auto | pgvector | memory


class SurveyQuestion(BaseModel):
    key: str
    label: str
    type: str = "likert"  # likert (1-5) | text
    required: bool = True


class SurveySettings(BaseModel):
    """Anonim çalışan memnuniyet anketi. Cevaplar KİMLİĞE bağlanmaz, save'den
    önce şifrelenir (SURVEY_ENC_KEY). Admin yalnız k-eşiği aşınca AGREGE görür.
    interval_days: döngü uzunluğu (2 hafta). min_responses: gizlilik eşiği."""

    enabled: bool = False
    interval_days: int = 14
    min_responses: int = 4
    # Bu rollerdeki kullanıcılar anketi DOLDURMAZ (anketi yönetirler). Katılım
    # oranı paydasına da sayılmazlar. owner zaten admin → dahil.
    exclude_roles: list[str] = Field(default_factory=lambda: ["admin"])
    # Sabit döngü hizası — bu Pazartesi'den itibaren interval_days pencereleri.
    epoch: date = date(2026, 1, 5)
    questions: list[SurveyQuestion] = Field(default_factory=lambda: [
        SurveyQuestion(key="workload", label="Son iki haftada iş yükün sürdürülebilir miydi?"),
        SurveyQuestion(key="team", label="Takımınla çalışmaktan memnun musun?"),
        SurveyQuestion(key="management", label="Yöneticinden yeterli destek görüyor musun?"),
        SurveyQuestion(key="growth", label="Kendini geliştirme/öğrenme fırsatı buluyor musun?"),
        SurveyQuestion(key="overall", label="Genel memnuniyetin?"),
    ])


class ProjectsSettings(BaseModel):
    """Kullanıcıların "Projelerim"e ekleyebildiği kaynaklar.

    local_roots: yerel klasör kaynağı için İZİNLİ KÖKLER. Bu bir kolaylık ayarı
    değil GÜVENLİK SINIRI: kullanıcı sunucudaki rastgele bir dizini (ör.
    C:\\Users\\baskasi ya da /etc) proje diye ekleyip commit mesajlarını
    okuyamasın. Boş liste = yerel kaynak KAPALI (varsayılan). Yani özelliği
    açmak bilinçli bir yönetici kararıdır — kurulumda kendiliğinden açılmaz.
    """

    local_roots: list[str] = Field(default_factory=list)
    max_local_commits: int = 100


class HrDocumentSettings(BaseModel):
    """Bordro/özlük evrakı yükleme ayarları.

    Bu klasördeki dosyalar ÖZEL NİTELİKLİ kişisel veri taşır: istirahat raporu,
    engelli sağlık kurulu raporu, icra müzekkeresi, nafaka kararı. Bu yüzden
    tasarım kararları pazarlıksız:

    - Dosyalar `frontend/dist` altına (StaticFiles ile servis edilen web köküne)
      ASLA yazılmaz. Oraya yazmak, tahmin edilebilir bir URL'i olan herkese
      birinin sağlık raporunu açardı. Varsayılan konum PROJECT_ROOT/data/hr-docs
      ve içerik yalnız kimlikli `/api/documents/{id}/download` ucundan akar.
    - Dosya adı SUNUCU üretir (uuid4 + doğrulanmış uzantı); kullanıcının verdiği
      ad yalnız gösterim için saklanır — yol geçişi (../) imkânsız olsun.
    - LLM katmanına hiçbir koşulda gönderilmez (bkz. services/rag, code_analysis).

    retention_years: İş Kanunu'ndaki zamanaşımı süreleriyle uyumlu saklama
    penceresi. Sistem KENDİLİĞİNDEN SİLMEZ — yalnızca arayüzde "saklama süresi
    doldu" bilgisi üretmek için tutulur; imha kararı insanındır.
    """

    # Boş = PROJECT_ROOT/data/hr-docs. Mutlak yol verilebilir (ör. şifreli disk).
    storage_dir: str = ""
    max_file_mb: int = 15
    # Uzantı ALLOWLIST'i (küçük harf, noktasız). svg/html/htm/xhtml BİLEREK yok:
    # tarayıcıda script çalıştırabilen biçimlerdir ve yüklenen dosya aynı origin'den
    # servis edildiği için depolanmış XSS'e dönüşürdü.
    allowed_extensions: list[str] = Field(default_factory=lambda: [
        "pdf", "jpg", "jpeg", "png", "webp", "heic", "heif",
        "doc", "docx", "xls", "xlsx", "odt", "ods", "txt", "zip", "rar",
    ])
    retention_years: int = 10


class Config(BaseModel):
    app: AppSettings = Field(default_factory=AppSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    sync: SyncSettings = Field(default_factory=SyncSettings)
    sources: Sources = Field(default_factory=Sources)
    metrics: dict[str, MetricConfig] = Field(default_factory=dict)
    health_thresholds: HealthThresholds = Field(default_factory=HealthThresholds)
    rules: dict[str, RuleConfig] = Field(default_factory=dict)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    code_analysis: CodeAnalysisSettings = Field(default_factory=CodeAnalysisSettings)
    survey: SurveySettings = Field(default_factory=SurveySettings)
    projects: ProjectsSettings = Field(default_factory=ProjectsSettings)
    rag: RagSettings = Field(default_factory=RagSettings)
    hr_documents: HrDocumentSettings = Field(default_factory=HrDocumentSettings)

    def metric(self, key: str) -> MetricConfig:
        """Metrik config'i döner; config'te hiç yoksa 'kapalı' kabul edilir —
        tanımsız metrik asla varsayılan değer uydurup çalışmaz."""
        return self.metrics.get(key, MetricConfig(enabled=False))

    def rule(self, key: str) -> RuleConfig:
        return self.rules.get(key, RuleConfig(enabled=False))

    @property
    def database_url(self) -> str:
        # Ortam değişkeni config dosyasını ezer (deploy kolaylığı, sır yönetimi)
        return os.environ.get("DATABASE_URL", self.database.url)


def active_config_path() -> Path:
    """Yürürlükteki config dosyası yolu. Yazma uçları da BURAYA yazmalı ki
    okuma/yazma aynı dosyada olsun (VANTAGE_CONFIG override'ı ile de tutarlı)."""
    return Path(os.environ.get("VANTAGE_CONFIG", DEFAULT_CONFIG_PATH))


def load_config(path: str | Path | None = None) -> Config:
    # Kalıcı sırları (DATABASE_URL, token'lar) ortama yükle — config OKUNMADAN
    # önce. Yoksa bu modülü doğrudan kullanan her yol (ad-hoc script, REPL,
    # yeni bir CLI komutu) config'teki geliştirme varsayılanına düşer ve
    # sessizce yanlış veritabanına bağlanır. load_secrets() idempotenttir ve
    # setdefault kullanır: gerçek ortam değişkeni her zaman kazanır.
    from app.core.secrets import load_secrets
    load_secrets()

    cfg_path = Path(path) if path else active_config_path()
    if not cfg_path.exists():
        # Config yoksa bile sistem ayağa kalkar; her şey varsayılanla çalışır
        return Config()
    with open(cfg_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Config.model_validate(raw)


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config()


def reset_config_cache() -> None:
    """Testlerde farklı config yüklemek için."""
    get_config.cache_clear()
