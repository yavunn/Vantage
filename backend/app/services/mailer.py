"""Giden e-posta (SMTP).

Standart kütüphane (`smtplib` + `email.message`) — yeni bağımlılık yok.

TASARIM: gönderim SESSİZ BAŞARISIZ OLMAZ. "Şifremi unuttum" akışında parola
sıfırlandıktan sonra mail gidemezse kullanıcı hesabından tamamen kilitlenir;
bu yüzden `send_email` hata yutmaz, çağıran önce `is_configured()` ile bakar
ve gönderim başarısız olursa sıfırlama da yapılmaz (bkz. auth.forgot_password).

Sır (SMTP parolası) config.yaml'da değil ortamda/.secrets.env'de tutulur.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import Config, get_config


class MailError(RuntimeError):
    """SMTP yapılandırması eksik ya da gönderim başarısız."""


def _password(cfg: Config) -> str:
    return os.environ.get(cfg.smtp.password_env, "")


def sender_address(cfg: Config) -> str:
    """Gönderen adresi: açıkça verilmişse o, yoksa kullanıcı adı."""
    return (cfg.smtp.from_address or cfg.smtp.username or "").strip()


def is_configured(cfg: Config | None = None) -> bool:
    """Mail gönderilebilir mi? Kimlik doğrulaması İSTEĞE BAĞLIDIR: kurum içi
    açık relay'ler (security=none) kullanıcı adı/parola istemez."""
    cfg = cfg or get_config()
    if not cfg.smtp.enabled:
        return False
    return bool(cfg.smtp.host.strip() and sender_address(cfg))


def send_email(to: str, subject: str, body: str, cfg: Config | None = None) -> None:
    """Düz metin e-posta gönderir. Başarısızlıkta MailError fırlatır."""
    cfg = cfg or get_config()
    if not is_configured(cfg):
        raise MailError("SMTP yapılandırılmamış (host + gönderen adresi gerekli)")

    gonderen = sender_address(cfg)
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.smtp.from_name or "", gonderen))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    guvenlik = (cfg.smtp.security or "starttls").lower()
    parola = _password(cfg)
    try:
        if guvenlik == "ssl":
            sunucu = smtplib.SMTP_SSL(
                cfg.smtp.host, cfg.smtp.port,
                timeout=cfg.smtp.timeout_seconds, context=ssl.create_default_context(),
            )
        else:
            sunucu = smtplib.SMTP(cfg.smtp.host, cfg.smtp.port, timeout=cfg.smtp.timeout_seconds)
        with sunucu:
            if guvenlik == "starttls":
                sunucu.starttls(context=ssl.create_default_context())
            if cfg.smtp.username and parola:
                sunucu.login(cfg.smtp.username, parola)
            sunucu.send_message(msg)
    except (OSError, smtplib.SMTPException, ssl.SSLError) as e:
        # Hata metni kullanıcıya değil yöneticiye/loga gider (bkz. çağıranlar):
        # sunucu adı/kimlik ipucu sızdırmamak için üst katman genel mesaj verir.
        raise MailError(f"E-posta gönderilemedi: {e}") from e
