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
    url: str = "sqlite:///./eng_health.db"


class SyncSettings(BaseModel):
    interval_minutes: int = 0


class GitLabSource(BaseModel):
    base_url: str = ""
    token_env: str = "GITLAB_TOKEN"
    projects: list[str] = Field(default_factory=list)


class GitSource(BaseModel):
    provider: str = "git_log"  # git_log | gitlab | fixture
    repos: list[dict[str, Any]] = Field(default_factory=list)
    gitlab: GitLabSource = Field(default_factory=GitLabSource)


class JiraSource(BaseModel):
    base_url: str = ""
    token_env: str = "JIRA_TOKEN"
    projects: list[str] = Field(default_factory=list)


class TrelloSource(BaseModel):
    key_env: str = "TRELLO_KEY"
    token_env: str = "TRELLO_TOKEN"
    boards: list[str] = Field(default_factory=list)


class TaskSource(BaseModel):
    provider: str = "none"  # jira | trello | fixture | none
    jira: JiraSource = Field(default_factory=JiraSource)
    trello: TrelloSource = Field(default_factory=TrelloSource)


class SonarQubeSource(BaseModel):
    base_url: str = ""
    token_env: str = "SONAR_TOKEN"
    project_keys: list[str] = Field(default_factory=list)


class LinterSource(BaseModel):
    command: str = ""


class QualitySource(BaseModel):
    provider: str = "none"  # sonarqube | linter | fixture | none
    sonarqube: SonarQubeSource = Field(default_factory=SonarQubeSource)
    linter: LinterSource = Field(default_factory=LinterSource)


class Sources(BaseModel):
    git: GitSource = Field(default_factory=GitSource)
    tasks: TaskSource = Field(default_factory=TaskSource)
    quality: QualitySource = Field(default_factory=QualitySource)


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
    model: str = "llama3.1"
    api_key_env: str = "LOCAL_LLM_API_KEY"


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
    edilir. exclude_globs: analiz dışı klasörler (üretilen/vendor kod)."""

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
    exclude_globs: list[str] = Field(default_factory=lambda: [
        "generated/*", "vendor/*", "node_modules/*", "dist/*", "build/*",
        "*.min.js", "*.lock", "*.map",
    ])
    # Bir çalıştırmada en fazla kaç diff analiz edilsin (maliyet freni)
    max_files_per_run: int = 40
    # Diff'te bu satır sayısını aşan dosyalar kırpılır (token freni)
    max_diff_lines: int = 400


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
    okuma/yazma aynı dosyada olsun (EHD_CONFIG override'ı ile de tutarlı)."""
    return Path(os.environ.get("EHD_CONFIG", DEFAULT_CONFIG_PATH))


def load_config(path: str | Path | None = None) -> Config:
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
