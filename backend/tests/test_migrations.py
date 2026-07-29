"""Migration'lar şemanın TEK doğru kaynağı mı?

Bu proje şemayı iki yoldan kurabiliyor: açılışta `create_all` (+ kolon yamaları)
ve `alembic upgrade head`. İkisi sessizce ayrışırsa "temiz kurulum" yolu kırılır
ve bu ancak üretimde fark edilir — nitekim bir dönem users/leaves/user_projects/
audit_logs/notifications tabloları hiçbir migration'da yoktu; alembic ile kurulan
bir veritabanında kimse giriş bile yapamazdı.

Bu testler o ayrışmayı yakalar.
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa


def _alembic_cfg():
    from pathlib import Path

    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "migrations"))
    # sqlalchemy.url'i BİLEREK vermiyoruz: migrations/env.py onu her hâlükârda
    # get_config().database_url ile ezer. URL'i EHD_CONFIG üzerinden yönlendirmek
    # hem tek çalışan yol hem de gerçek env.py davranışını test eder.
    return cfg


@pytest.fixture()
def fresh_db_url(tmp_path, monkeypatch):
    """Hiç dokunulmamış, boş bir SQLite DB — ve config onu göstersin.

    KRİTİK: EHD_CONFIG kurulmazsa env.py gerçek (üretim/demo) Postgres'e
    bağlanır ve migration'ları ORAYA uygular."""
    from tests.conftest import TEST_CONFIG

    db_url = f"sqlite:///{(tmp_path / 'migr.db').as_posix()}"
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        TEST_CONFIG.format(db_path=(tmp_path / "migr.db").as_posix()), encoding="utf-8"
    )
    monkeypatch.setenv("EHD_CONFIG", str(cfg_file))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from app.core.config import get_config, reset_config_cache
    from app.core.db import reset_engine

    reset_config_cache()
    reset_engine()
    assert get_config().database_url == db_url, "config test DB'sini göstermiyor"
    yield db_url
    reset_engine()
    reset_config_cache()


def test_temiz_veritabaninda_alembic_upgrade_head_calisir(fresh_db_url):
    """Sıfırdan `alembic upgrade head` çökmeden tamamlanmalı.

    Eskiden ikinci revizyonda (a1b2c3d4e5f6) "no such table: users" ile
    çöküyordu."""
    from alembic import command

    command.upgrade(_alembic_cfg(), "head")

    engine = sa.create_engine(fresh_db_url)
    tables = set(sa.inspect(engine).get_table_names())
    engine.dispose()
    # Giriş ve İK akışının dayandığı tablolar gerçekten oluşmuş olmalı.
    for t in ("users", "leaves", "user_projects", "audit_logs", "notifications"):
        assert t in tables, f"{t} tablosu alembic ile oluşmadı"


def test_alembic_semasi_modellerle_ortusuyor(fresh_db_url):
    """alembic'in ürettiği şema, modellerin (create_all) beklediğini KAPSAMALI.

    Migration'ların fazladan tablo taşıması sorun değil (ör. artık kullanılmayan
    code_quality_snapshots); eksik tablo/kolon taşıması sorundur."""
    from alembic import command

    import app.models  # noqa: F401 — tablolar metadata'ya kaydolsun
    from app.core.db import Base

    command.upgrade(_alembic_cfg(), "head")

    engine = sa.create_engine(fresh_db_url)
    insp = sa.inspect(engine)
    alembic_tables = set(insp.get_table_names())

    eksik_tablolar = set(Base.metadata.tables) - alembic_tables
    assert not eksik_tablolar, f"migration'larda eksik tablolar: {sorted(eksik_tablolar)}"

    eksik_kolonlar: dict[str, list[str]] = {}
    for name, table in Base.metadata.tables.items():
        db_cols = {c["name"] for c in insp.get_columns(name)}
        missing = {c.name for c in table.columns} - db_cols
        if missing:
            eksik_kolonlar[name] = sorted(missing)
    engine.dispose()
    assert not eksik_kolonlar, f"migration'larda eksik kolonlar: {eksik_kolonlar}"


def test_alembic_tek_head_tasiyor():
    """Çatallanmış revizyon grafiği `upgrade head`'i belirsizleştirir."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "migrations"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, f"birden fazla head var: {heads}"
