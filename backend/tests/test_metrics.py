"""Metrik motoru testleri.

Her metrik iki koşulda test edilir (spec Bölüm 6):
1. Tam veri → doğru değer üretir.
2. Eksik/kirli veri → metrik GİZLENİR (value None), sistem çökmez,
   completeness dürüstçe raporlanır.
"""
from __future__ import annotations

from tests.conftest import NOW, days_ago, make_team


def _team_data(session, team, window_days=30, cfg=None):
    from datetime import timedelta

    from app.metrics.engine import load_team_data

    return load_team_data(session, team, NOW - timedelta(days=window_days), NOW, cfg)


def _cfg():
    from app.core.config import get_config

    return get_config()


def add_pr(session, repo, author, opened_d, review_d=None, merged_d=None, ext=None):
    from app.models import PullRequest

    pr = PullRequest(
        repo_id=repo.id,
        external_id=ext or f"pr-{opened_d}-{id(object())}",
        author_id=author.id if author else None,
        opened_at=days_ago(opened_d) if opened_d is not None else None,
        first_review_at=days_ago(review_d) if review_d is not None else None,
        merged_at=days_ago(merged_d) if merged_d is not None else None,
    )
    session.add(pr)
    session.commit()
    return pr


class TestPRReviewTime:
    def test_tam_veri(self, session):
        from app.metrics.engine import pr_review_time

        team, repo, devs, _ = make_team(session)
        add_pr(session, repo, devs[0], opened_d=10, merged_d=6)  # 4 gün
        add_pr(session, repo, devs[1], opened_d=8, merged_d=6)   # 2 gün
        out = pr_review_time(_team_data(session, team), _cfg())
        assert out.value == 3.0
        assert out.completeness == 1.0
        assert out.source_layer == "git"

    def test_veri_yoksa_gizlenir(self, session):
        from app.metrics.engine import pr_review_time

        team, repo, devs, _ = make_team(session)
        out = pr_review_time(_team_data(session, team), _cfg())
        assert out.value is None  # asla 0 uydurulmaz

    def test_kirli_tarih_dusuk_completeness(self, session):
        from app.metrics.engine import pr_review_time

        team, repo, devs, _ = make_team(session)
        add_pr(session, repo, devs[0], opened_d=10, merged_d=6)
        add_pr(session, repo, devs[0], opened_d=None, merged_d=5)  # açılış tarihi yok
        out = pr_review_time(_team_data(session, team), _cfg())
        assert out.value == 4.0          # hesap sadece sağlam kayıtla
        assert out.completeness == 0.5   # eksiklik raporlanır, cezalandırılmaz


class TestCycleTimeFallback:
    def test_task_yoksa_pr_merge_fallback(self, session):
        """İlke B: birincil katman (jira_status) boşsa Katman 0'a düşer."""
        from app.metrics.engine import cycle_time

        team, repo, devs, _ = make_team(session)
        add_pr(session, repo, devs[0], opened_d=9, merged_d=4)  # 5 gün
        out = cycle_time(_team_data(session, team), _cfg())
        assert out.source_layer == "pr_merge"
        assert out.value == 5.0

    def test_status_gecisi_varsa_katman1(self, session):
        from app.metrics.engine import cycle_time
        from app.models import Task, TaskStatusTransition

        team, repo, devs, _ = make_team(session)
        task = Task(source="fixture", external_id="T-1", team_id=team.id,
                    assignee_id=devs[0].id, status="Done", created_at=days_ago(10))
        session.add(task)
        session.flush()
        session.add_all([
            TaskStatusTransition(task_id=task.id, from_status="To Do",
                                 to_status="In Progress", changed_at=days_ago(8)),
            TaskStatusTransition(task_id=task.id, from_status="In Progress",
                                 to_status="Done", changed_at=days_ago(2)),
        ])
        session.commit()
        out = cycle_time(_team_data(session, team), _cfg())
        assert out.source_layer == "jira_status"
        assert abs(out.value - 6.0) < 0.01  # In Progress → Done = 6 gün


class TestWIP:
    def test_task_statusu_yoksa_pr_fallback(self, session):
        from app.metrics.engine import wip

        team, repo, devs, _ = make_team(session)
        add_pr(session, repo, devs[0], opened_d=5)  # açık PR
        out = wip(_team_data(session, team), _cfg())
        assert out.source_layer == "pr_open"
        assert out.value == 0.5  # 1 açık PR / 2 üye (yönetici sayılmaz)

    def test_hic_veri_yoksa_gizli(self, session):
        from app.metrics.engine import wip

        team, repo, devs, _ = make_team(session)
        out = wip(_team_data(session, team), _cfg())
        assert out.value is None

    def test_uyesiz_takimda_kisi_basi_metrik_uydurulmaz(self, session):
        """Payda 1'e yuvarlanırsa '10 iş / hayali 1 kişi' gibi yanlış bir
        kırmızı çıkar. Üye yoksa değer üretilmez (İlke A)."""
        from app.metrics.engine import wip
        from app.models import Task

        team, repo, devs, _ = make_team(session, devs=(), manager="mgr")
        for i in range(3):
            session.add(Task(source="trello", external_id=f"T-{i}", team_id=team.id,
                             status="DEVELOPMENT"))
        session.commit()
        out = wip(_team_data(session, team), _cfg())
        assert out.value is None
        assert out.completeness == 0.0

    def test_eslenmemis_kolon_wipe_sayilmaz(self, session):
        """Trello/Jira kolon adları serbest metindir; eşlenmemiş kolon BİLİNMEYEN'dir.

        Eski davranış "done ve backlog dışındaki her şey akıştadır" diyordu; bu,
        eşlenmemiş her yeni kolonu sessizce WIP'e yazıyor ve takımı yok yere
        kırmızıya çekiyordu. Artık yalnız in_progress kategorisi akış sayılır,
        eşlenmemiş kolon değere girmez ama tamlık oranını düşürür."""
        from app.metrics.engine import wip
        from app.models import Task

        team, repo, devs, _ = make_team(session)  # 2 üye
        for i, status in enumerate(["DEVELOPMENT", "TEST", "Araştırma Konuları",
                                    "Araştırma Konuları", "DONE"]):
            session.add(Task(source="trello", external_id=f"T-{i}", team_id=team.id,
                             status=status))
        session.commit()

        # Eşleme yokken: yalnız "DONE" varsayılan kümede var; DEVELOPMENT/TEST/
        # Araştırma Konuları hiçbir kategoriye düşmüyor → akış 0 ve tamlık 1/5.
        # Tamlık eşiğin (0.5) altında olduğu için pano bunu "veri yetersiz" gösterir:
        # yanlış bir WIP sayısı basmaktansa eşlemenin eksik olduğunu söylüyoruz.
        out = wip(_team_data(session, team), _cfg())
        assert out.value == 0.0
        assert out.completeness == 0.2

        # Eşleme verilince: yalnız DEVELOPMENT + TEST akışta → 2/2 = 1.0,
        # 5 task'ın 5'i de bir kategoriye düştüğü için tamlık 1.0.
        cfg = _cfg()
        cfg.sources.tasks.status_mapping.in_progress = ["DEVELOPMENT", "TEST"]
        cfg.sources.tasks.status_mapping.backlog = ["Araştırma Konuları"]
        cfg.sources.tasks.status_mapping.done = ["DONE"]
        data = _team_data(session, team, cfg=cfg)
        out = wip(data, cfg)
        assert out.value == 1.0
        assert out.completeness == 1.0

    def test_kismi_esleme_tamligi_dusurur(self, session):
        """Kolonların bir kısmı eşlenmemişse metrik "emin" görünmemeli:
        değer üretilir ama tamlık düşer, eşiğin altına inince pano
        'veri yetersiz' der."""
        from app.metrics.engine import wip
        from app.models import Task

        team, repo, devs, _ = make_team(session)
        for i, status in enumerate(["DEVELOPMENT", "Beklemede", "Blocked", "DONE"]):
            session.add(Task(source="trello", external_id=f"T-{i}", team_id=team.id,
                             status=status))
        session.commit()
        cfg = _cfg()
        cfg.sources.tasks.status_mapping.in_progress = ["DEVELOPMENT"]
        cfg.sources.tasks.status_mapping.done = ["DONE"]
        out = wip(_team_data(session, team, cfg=cfg), cfg)
        assert out.value == 0.5              # 1 akıştaki iş / 2 üye
        assert out.completeness == 0.5       # 4 task'ın 2'si eşlendi

    def test_turkce_buyuk_harfli_statuler_eslesir(self, session):
        """Türkçe'de "I".lower() → "i" ama doğru küçük harf "ı"dır.
        Gerçek board kolonları büyük harfle yazılır ("YAPILIYOR", "TAMAMLANDI");
        bu düzeltme öncesi hiçbir kategoriye düşmüyorlardı."""
        from app.metrics.engine import _is_done, is_in_flow, resolve_statuses

        st = resolve_statuses(_cfg())
        for yazim in ("YAPILIYOR", "Yapılıyor", "yapılıyor", "yapiliyor", " YAPILIYOR "):
            assert is_in_flow(yazim, st) is True, yazim
        for yazim in ("TAMAMLANDI", "Tamamlandı", "tamamlandı", "tamamlandi"):
            assert _is_done(yazim, st) is True, yazim

    def test_turkce_fold_config_beyaninda_da_gecerli(self, app_env):
        """Config'te büyük harfle yazılmış Türkçe kolon adı da eşleşmeli."""
        from app.core.config import get_config
        from app.metrics.engine import is_in_flow, resolve_statuses

        cfg = get_config()
        cfg.sources.tasks.status_mapping.in_progress = ["GELİŞTİRİLİYOR"]
        st = resolve_statuses(cfg)
        assert is_in_flow("geliştiriliyor", st) is True
        assert is_in_flow("GELİŞTİRİLİYOR", st) is True

    def test_beyan_edilen_ad_varsayilan_kategoriyi_ezer(self, app_env):
        """'open' varsayılanda backlog'dur; in_progress beyan edilirse
        iki kategoride birden kalmaz — açık beyan kazanır.
        (app_env: taze config; mutasyon gerçek config'e sızmasın.)"""
        from app.core.config import get_config
        from app.metrics.engine import resolve_statuses

        cfg = get_config()
        cfg.sources.tasks.status_mapping.in_progress = ["open"]
        st = resolve_statuses(cfg)
        assert "open" in st["in_progress"]
        assert "open" not in st["backlog"]


class TestChangeFailureRate:
    """İŞ-04: pencere kenarındaki deploy'lar oranı sistematik düşürüyordu."""

    def test_hotfix_pencere_disinda_gelse_de_sayilir(self, session):
        """Haftalık kovada deploy kovanın sonunda, hotfix ertesi hafta gelir.
        Eskiden hotfix hiç görülmüyordu ve deploy 'hatasız' sayılıyordu."""
        from datetime import timedelta

        from app.metrics.engine import change_failure_rate, load_team_data
        from app.models import Commit

        team, repo, devs, _ = make_team(session)
        session.add(Commit(repo_id=repo.id, sha="m1", author_id=devs[0].id,
                           committed_at=days_ago(9), message="Merge branch 'feature'"))
        session.add(Commit(repo_id=repo.id, sha="h1", author_id=devs[0].id,
                           committed_at=days_ago(7), message="hotfix: acil düzeltme"))
        session.commit()
        # Kova 12..8 gün önce: merge içeride, hotfix DIŞARIDA (7 gün önce).
        data = load_team_data(session, team, NOW - timedelta(days=12), NOW - timedelta(days=8))
        assert data.later_commits, "ileriye bakış commit'leri yüklenmedi"
        out = change_failure_rate(data, _cfg())
        assert out.value == 1.0

    def test_hotfix_penceresi_dolmamis_deploy_paydaya_girmez(self, session):
        """Bugün yapılan deploy'un 3 günlük hotfix penceresi henüz dolmadı;
        'hatasız' saymak oranı yapay olarak iyileştirirdi."""
        from app.metrics.engine import change_failure_rate
        from app.models import Commit

        team, repo, devs, _ = make_team(session)
        session.add(Commit(repo_id=repo.id, sha="eski-merge", author_id=devs[0].id,
                           committed_at=days_ago(20), message="Merge branch 'a'"))
        session.add(Commit(repo_id=repo.id, sha="yeni-merge", author_id=devs[0].id,
                           committed_at=days_ago(0.5), message="Merge branch 'b'"))
        session.commit()
        out = change_failure_rate(_team_data(session, team), _cfg())
        assert out.sample == 1              # yalnız eski deploy gözlenebilir
        assert out.completeness == 0.5      # 2 deploy'un 1'i gözlenebildi
        assert out.value == 0.0

    def test_hicbiri_gozlenebilir_degilse_veri_yetersiz(self, session):
        from app.metrics.engine import change_failure_rate
        from app.models import Commit

        team, repo, devs, _ = make_team(session)
        session.add(Commit(repo_id=repo.id, sha="yeni-merge", author_id=devs[0].id,
                           committed_at=days_ago(0.5), message="Merge branch 'b'"))
        session.commit()
        out = change_failure_rate(_team_data(session, team), _cfg())
        assert out.value is None
        assert out.completeness == 0.0


class TestReworkPencereBagimsizligi:
    """İŞ-02: manşet (30 gün) ile trend noktaları (7 gün) aynı tanımı kullanmalı.

    Eski davranışta kısa kovada dosyanın ilk dokunuşunun geçmişi kesiliyordu:
    aynı veride 30 günlük değer haftalık kovalardan sistematik olarak yüksek
    çıkıyor, trend grafiği manşetle kıyaslanamıyordu."""

    def test_kova_geriye_bakisi_pencere_oncesini_de_gorur(self, session):
        from datetime import timedelta

        from app.metrics.engine import load_team_data, rework_rate
        from app.models import Commit

        team, repo, devs, _ = make_team(session)
        # Aynı dosyaya 12 ve 5 gün önce dokunulmuş: 21 günlük rework penceresinde
        # bu bir "tekrar dokunma"dır.
        for gun, sha in ((12, "eski"), (5, "yeni")):
            session.add(Commit(repo_id=repo.id, sha=sha, author_id=devs[0].id,
                               committed_at=days_ago(gun), message="iş",
                               changed_files=["app/servis.py"]))
        session.commit()

        # Son 7 günlük kova: içinde YALNIZ "yeni" commit var. Geriye bakış
        # pencere öncesini görmezse oran 0 çıkar (eski hata).
        kova = load_team_data(session, team, NOW - timedelta(days=7), NOW)
        assert kova.prior_commits, "pencere öncesi commit'ler yüklenmedi"
        assert rework_rate(kova, _cfg()).value == 1.0

        # 30 günlük pencere aynı veriyi aynı tanımla görüyor.
        genis = load_team_data(session, team, NOW - timedelta(days=30), NOW)
        assert rework_rate(genis, _cfg()).value == 0.5  # 2 dokunuş, 1'i tekrar

    def test_rework_penceresi_disindaki_dokunus_sayilmaz(self, session):
        """Geriye bakış sınırsız değil: 21 günden eski dokunuş rework değildir."""
        from datetime import timedelta

        from app.metrics.engine import load_team_data, rework_rate
        from app.models import Commit

        team, repo, devs, _ = make_team(session)
        for gun, sha in ((40, "cok-eski"), (2, "yeni")):
            session.add(Commit(repo_id=repo.id, sha=sha, author_id=devs[0].id,
                               committed_at=days_ago(gun), message="iş",
                               changed_files=["app/servis.py"]))
        session.commit()
        kova = load_team_data(session, team, NOW - timedelta(days=7), NOW)
        assert rework_rate(kova, _cfg()).value == 0.0


class TestDeploymentFrequency:
    """İŞ-01: "sinyal yok" ile "0 teslim" ayrımı.

    Eski davranış: PR verisi ve merge commit'i olmayan takımda (git_log kaynağı,
    squash-merge akışı) metrik value=0.0 + completeness=1.0 yazıyordu. Eşik
    gereği bu KIRMIZI oluyor ve yöneticiye "Teslim Sıklığı kırmızıya döndü"
    alarmı gidiyordu — hiçbiri gerçek değil, sadece sinyal yokluğu."""

    def test_sinyal_yoksa_veri_yetersiz(self, session):
        from app.metrics.engine import deployment_frequency
        from app.models import Commit

        team, repo, devs, _ = make_team(session)
        # Commit VAR ama PR yok ve hiçbiri merge commit'i değil.
        for i in range(5):
            session.add(Commit(repo_id=repo.id, sha=f"s{i}", author_id=devs[0].id,
                               committed_at=days_ago(i + 1), message=f"feat: iş {i}"))
        session.commit()
        out = deployment_frequency(_team_data(session, team), _cfg())
        assert out.value is None
        assert out.completeness == 0.0
        assert out.source_layer is None

    def test_merge_commiti_olan_repoda_bos_pencere_gercek_sifirdir(self, session):
        """Repo merge commit'i kullanıyor ama bu pencerede yok → gerçekten 0 teslim."""
        from app.metrics.engine import deployment_frequency
        from app.models import Commit

        team, repo, devs, _ = make_team(session)
        # Pencere DIŞINDA bir merge commit'i: sinyal var demektir.
        session.add(Commit(repo_id=repo.id, sha="eski", author_id=devs[0].id,
                           committed_at=days_ago(200), message="Merge branch 'x'"))
        session.add(Commit(repo_id=repo.id, sha="yeni", author_id=devs[0].id,
                           committed_at=days_ago(2), message="feat: iş"))
        session.commit()
        out = deployment_frequency(_team_data(session, team), _cfg())
        assert out.value == 0.0
        assert out.completeness == 1.0
        assert out.source_layer == "merge_commit"

    def test_pr_verisi_varsa_merge_edilen_pr_sayilir(self, session):
        from app.metrics.engine import deployment_frequency

        team, repo, devs, _ = make_team(session)
        add_pr(session, repo, devs[0], opened_d=10, merged_d=8, ext="pr-1")
        add_pr(session, repo, devs[0], opened_d=6, merged_d=4, ext="pr-2")
        out = deployment_frequency(_team_data(session, team), _cfg())
        assert out.source_layer == "pr_merge"
        assert out.sample == 2
        assert out.value is not None and out.value > 0

    def test_acik_pr_varsa_pencerede_merge_yoksa_sifir(self, session):
        """PR verisi var (sinyal var) ama merge yok → gerçek 0, veri yetersiz değil."""
        from app.metrics.engine import deployment_frequency

        team, repo, devs, _ = make_team(session)
        add_pr(session, repo, devs[0], opened_d=5, ext="pr-acik")
        out = deployment_frequency(_team_data(session, team), _cfg())
        assert out.value == 0.0
        assert out.completeness == 1.0
        assert out.source_layer == "pr_merge"


class TestRework:
    def test_ayni_dosyaya_tekrar_dokunma(self, session):
        from app.metrics.engine import rework_rate
        from app.models import Commit

        team, repo, devs, _ = make_team(session)
        session.add_all([
            Commit(repo_id=repo.id, sha="a1", author_id=devs[0].id,
                   committed_at=days_ago(10), changed_files=["x.py"]),
            Commit(repo_id=repo.id, sha="a2", author_id=devs[1].id,
                   committed_at=days_ago(5), changed_files=["x.py", "y.py"]),
        ])
        session.commit()
        out = rework_rate(_team_data(session, team), _cfg())
        # 3 dokunuş, 1'i rework (x.py 5 gün sonra tekrar)
        assert abs(out.value - 1 / 3) < 0.01
        assert out.sample == 3


class TestProcessHygiene:
    def test_eksik_veri_metrige_donusur(self, session):
        """İlke A: 'bu takım hiç estimate girmiyor' bilgisi bir metriktir."""
        from app.metrics.engine import process_hygiene
        from app.models import Task

        team, repo, devs, _ = make_team(session)
        for i in range(4):
            session.add(Task(source="fixture", external_id=f"T-{i}", team_id=team.id,
                             status="To Do", estimate_hours=8.0 if i == 0 else None))
        session.commit()
        out = process_hygiene(_team_data(session, team), _cfg())
        assert out.value is not None
        # bileşen1: estimate doluluk 0.25; bileşen2: transition doluluk 0.0
        assert abs(out.value - (0.25 + 0.0) / 2) < 0.01

    def test_kaynakta_olmayan_alan_cezalandirilmaz(self, session):
        """Trello'da estimate alanı YOK. Boşluğunu hijyen eksikliği saymak
        takımı yapısal tavana çakar (İlke B: alan yoksa metrik gizlenir)."""
        from app.metrics.engine import process_hygiene
        from app.models import Task, TaskStatusTransition

        team, repo, devs, _ = make_team(session)
        for i in range(4):
            t = Task(source="trello", external_id=f"T-{i}", team_id=team.id,
                     status="DEVELOPMENT", estimate_hours=None)
            session.add(t)
            session.flush()
            session.add(TaskStatusTransition(task_id=t.id, from_status=None,
                                             to_status="DEVELOPMENT",
                                             changed_at=days_ago(3)))
        session.commit()
        out = process_hygiene(_team_data(session, team), _cfg())
        # Estimate bileşeni HİÇ sayılmaz; kalan tek bileşen (status doluluk) = 1.0
        assert out.value == 1.0
        # sample artık BİLEŞEN değil KAYIT sayısı (4 task) — kullanıcıya
        # "1 kayıt" gibi yanlış okunan bir sayı gösteriliyordu.
        assert out.sample == 4

    def test_estimate_destekleyen_kaynakta_bosluk_hala_olculur(self, session):
        """Jira/fixture'da alan VAR — doldurulmaması gerçek bir hijyen sinyalidir,
        bu düzeltme onu susturmamalı."""
        from app.metrics.engine import process_hygiene
        from app.models import Task

        team, repo, devs, _ = make_team(session)
        for i in range(4):
            session.add(Task(source="jira", external_id=f"J-{i}", team_id=team.id,
                             status="To Do", estimate_hours=None))
        session.commit()
        out = process_hygiene(_team_data(session, team), _cfg())
        assert out.sample == 4  # 4 task = 4 kayıt (bileşen sayısı değil)
        assert out.value == 0.0

    def test_tek_kayitlik_takim_yesil_gorunmez(self, session):
        """İŞ-03: 0 üye, 0 repo, 1 task olan takım eskiden %100 / 'Akıyor'
        gösteriyordu (completeness sabit 1.0). Veri yokluğu mükemmel süreç gibi
        okunuyordu; artık tamlık kanıt sayısına bağlı ve pano 'veri yetersiz' der."""
        from app.metrics.engine import process_hygiene
        from app.models import Task, TaskStatusTransition
        from app.services.health import health_status

        team, repo, devs, _ = make_team(session, devs=(), manager="mgr")
        t = Task(source="trello", external_id="TEK", team_id=team.id, status="DEVELOPMENT")
        session.add(t)
        session.flush()
        session.add(TaskStatusTransition(task_id=t.id, from_status=None,
                                         to_status="DEVELOPMENT", changed_at=days_ago(1)))
        session.commit()
        out = process_hygiene(_team_data(session, team), _cfg())
        assert out.value == 1.0            # tek kaydın oranı hâlâ 1.0
        assert out.completeness == 0.2     # ama kanıt tek kayıt
        assert health_status("process_hygiene", out.value, out.completeness,
                             _cfg()) == "insufficient_data"


class TestConfigKapatma:
    def test_kapali_metrik_hesaplanmaz(self, session, app_env):
        from sqlalchemy import select

        from app.core.config import get_config
        from app.metrics.engine import compute_all
        from app.models import MetricResult

        team, repo, devs, _ = make_team(session)
        add_pr(session, repo, devs[0], opened_d=10, merged_d=6)
        compute_all(session, get_config())
        keys = {r.metric_key for r in session.scalars(select(MetricResult))}
        assert "estimate_accuracy" not in keys  # config'te enabled: false
        assert "pr_review_time" in keys


class TestSQLPencereFiltresi:
    """İŞ-22: pencere filtresi SQL'e taşındı — sonuçlar DEĞİŞMEMELİ.

    Bu bir performans işidir, davranış değişikliği değil. Ayrıca SQLite'ta
    ölçülmüş bir tuzak var: timezone=True kolonlarda saat dilimi SAKLANMIYOR
    (12:00+03:00 → "12:00"), yani SQL karşılaştırması tek başına yanlış sonuç
    verebilir. Bu yüzden SQL yalnız taramayı daraltır, kesin kararı as_utc verir.
    """

    def test_farkli_saat_dilimli_kayitlar_dogru_siniflanir(self, session):
        from datetime import timedelta, timezone

        from app.metrics.engine import load_team_data
        from app.models import Commit

        team, repo, devs, _ = make_team(session)
        ist = timezone(timedelta(hours=3))
        # İkisi de aynı ANI gösteriyor; biri +03:00, biri UTC yazılmış.
        an = NOW - timedelta(days=3)
        session.add(Commit(repo_id=repo.id, sha="utc", author_id=devs[0].id,
                           committed_at=an.astimezone(timezone.utc), message="a",
                           changed_files=["x.py"]))
        session.add(Commit(repo_id=repo.id, sha="ist", author_id=devs[0].id,
                           committed_at=an.astimezone(ist), message="b",
                           changed_files=["y.py"]))
        # Pencerenin AÇIKÇA dışında (60 gün önce) — SQL payına rağmen girmemeli.
        session.add(Commit(repo_id=repo.id, sha="cok-eski", author_id=devs[0].id,
                           committed_at=NOW - timedelta(days=60), message="c",
                           changed_files=["z.py"]))
        session.commit()

        data = load_team_data(session, team, NOW - timedelta(days=7), NOW)

        assert {c.sha for c in data.commits} == {"utc", "ist"}

    def test_tarihi_eksik_commit_pencereye_girmeye_devam_eder(self, session):
        """Mevcut davranış: tarihsiz kayıt tamlık paydasına giriyor.
        SQL filtresi bunu SESSİZCE değiştirmemeli."""
        from datetime import timedelta

        from app.metrics.engine import load_team_data
        from app.models import Commit

        team, repo, devs, _ = make_team(session)
        session.add(Commit(repo_id=repo.id, sha="tarihsiz", author_id=devs[0].id,
                           committed_at=None, message="?"))
        session.commit()

        data = load_team_data(session, team, NOW - timedelta(days=7), NOW)
        assert [c.sha for c in data.commits] == ["tarihsiz"]
