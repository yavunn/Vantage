"""API hata mesajı çevirileri (TR → EN).

Frontend'deki `i18n-en.js` ile AYNI desen: anahtar Türkçe KAYNAK METNİN
KENDİSİDİR (`app/api/*.py` ve `app/services/hr_documents.py` içindeki
`HTTPException(detail=...)` / `UploadError(...)` çağrılarının birebir aynısı —
biri değişirse öteki de değişmeli, aksi hâlde çeviri sessizce düşer ve
İngilizce arayüzde bir Türkçe hata cümlesi belirir). `core.i18n.tr_error` bu
sözlüğü okur; eksik anahtar TR metne düşer.

Parametreli mesajlarda `{ad}` yer tutucusu TR ve EN'de AYNI isimde olmalı
(`str.format(**params)` ile doldurulur).

KAPSAM SINIRI: burada YALNIZ bizim yazdığımız sabit metinler var. Alt
katmandan gelen ham kütüphane/adaptör hataları (`detail=str(e)`) buraya
girmez — onlar bizim seçtiğimiz kelimeler değil, dış sistemin verdiği ham
mesajdır; sabit bir sözlükle çevrilemez.
"""
from __future__ import annotations

ERRORS_EN: dict[str, str] = {
    # --- kimlik / oturum ---
    "Giriş gerekli": "Login required",
    "Oturum geçersiz veya süresi doldu": "Session invalid or expired",
    "Hesap bulunamadı veya pasif": "Account not found or inactive",
    "Oturum geçersiz — parola değişti, tekrar giriş yapın":
        "Session invalid — password changed, please log in again",
    "E-posta ya da parola hatalı": "Incorrect email or password",
    "Mevcut parola hatalı": "Current password is incorrect",
    "Çok fazla giriş denemesi. {mins} dk sonra tekrar deneyin.":
        "Too many login attempts. Try again in {mins} minutes.",
    "Çok fazla başarısız deneme. Hesap geçici kilitli — {mins} dk sonra tekrar deneyin.":
        "Too many failed attempts. Account temporarily locked — try again in {mins} minutes.",
    "Kod geçersiz ya da süresi dolmuş. Lütfen yeni bir kod isteyin.":
        "Code is invalid or expired. Please request a new one.",
    "Çok fazla istek. {mins} dk sonra tekrar deneyin.":
        "Too many requests. Try again in {mins} minutes.",
    "E-posta gönderimi yapılandırılmamış. Lütfen yöneticinize başvurun.":
        "Email sending isn't configured. Please contact your admin.",
    "E-posta gönderilemedi. Lütfen yöneticinize başvurun.":
        "The email couldn't be sent. Please contact your admin.",
    "Kurulum zaten tamamlanmış": "Setup is already complete",

    # --- yetki ---
    "Bu işlem için yönetici yetkisi gerekli": "This action requires admin privileges",
    "Bu işlem için yönetici veya İK yetkisi gerekli": "This action requires admin or HR privileges",
    "Bu işlem için baş yönetici yetkisi gerekli": "This action requires owner privileges",
    "Baş yönetici hesabı korunuyor; bu işlem yapılamaz":
        "The owner account is protected; this action isn't allowed",
    "Baş yönetici hesabı silinemez": "The owner account can't be deleted",
    "Baş yönetici hesabının rolü veya aktifliği değiştirilemez":
        "The owner account's role or active status can't be changed",
    "Kendi hesabını silemezsin": "You can't delete your own account",
    "Kendi rolünü ya da aktiflik durumunu buradan değiştiremezsin":
        "You can't change your own role or active status here",
    "Sistemde en az bir aktif yönetici kalmalı": "There must be at least one active admin in the system",
    "İK yalnızca çalışan (user) hesabı oluşturabilir": "HR can only create employee (user) accounts",
    "İK yalnızca çalışan (user) parolasını sıfırlayabilir": "HR can only reset employee (user) passwords",
    "role yalnızca 'user', 'admin' veya 'hr' olabilir": "role can only be 'user', 'admin' or 'hr'",
    "Bu e-posta zaten kayıtlı": "This email is already registered",

    # --- hesap / kullanıcı / takım / üyelik kayıtları ---
    "Hesap bulunamadı": "Account not found",
    "Kullanıcı bulunamadı": "User not found",
    "Hedef kullanıcı yok": "Target user doesn't exist",
    "Hesap bir geliştiriciye bağlı değil": "This account isn't linked to a developer",
    "Takım bulunamadı": "Team not found",
    "Üyelik bulunamadı": "Membership not found",
    "'{name}' adlı takım zaten var.": "A team named '{name}' already exists.",

    # --- izinler ---
    "Başkasına izin ekleme yetkisi yok": "You don't have permission to add leave for someone else",
    "Herkese izin ekleme yetkisi yok": "You don't have permission to add leave for everyone",
    "Bitiş tarihi başlangıçtan önce olamaz": "End date can't be before the start date",
    "İzin bulunamadı": "Leave not found",
    "Bu izni silme yetkiniz yok": "You don't have permission to delete this leave",
    "month biçimi YYYY-MM olmalı": "month must be in YYYY-MM format",
    "Red için gerekçe gerekli": "A reason is required to reject",
    "leave_type: annual | sick | other": "leave_type: annual | sick | other",

    # --- bordro / özlük evrakı ---
    "Bilinmeyen belge türü": "Unknown document type",
    "Başkası adına belge yükleme yetkiniz yok":
        "You don't have permission to upload a document on someone else's behalf",
    "Bu belge için bordro dönemi (YYYY-MM) zorunlu":
        "A payroll period (YYYY-MM) is required for this document",
    "Bu belge için başlangıç ve bitiş tarihi zorunlu":
        "Start and end dates are required for this document",
    "İlgili izin kaydı bulunamadı": "The related leave request wasn't found",
    "Dönem biçimi YYYY-MM olmalı": "Period must be in YYYY-MM format",
    "{field} biçimi YYYY-AA-GG olmalı": "{field} must be in YYYY-MM-DD format",
    "Başlangıç tarihi": "Start date",
    "Bitiş tarihi": "End date",
    "status: pending | approved | rejected": "status: pending | approved | rejected",
    "Başkasının belgelerini görme yetkiniz yok": "You don't have permission to view someone else's documents",
    "Belge bulunamadı": "Document not found",
    "Bu belgeyi görme yetkiniz yok": "You don't have permission to view this document",
    "Belgenin dosyası sunucuda bulunamadı": "The document's file could not be found on the server",
    "decision: approved | rejected": "decision: approved | rejected",
    "Bu belgeyi silme yetkiniz yok": "You don't have permission to delete this document",
    "İncelenmiş belge silinemez; kaldırılması için İK ile görüşün":
        "A reviewed document can't be deleted; contact HR to remove it",
    # hr_documents.py (UploadError — dosya doğrulama)
    "Dosyanın uzantısı okunamadı; uzantılı bir dosya seçin":
        "The file's extension couldn't be read; choose a file with an extension",
    "'{ext}' uzantısı kabul edilmiyor. İzinli türler: {allowed}":
        "'{ext}' isn't an accepted extension. Allowed types: {allowed}",
    "Dosya çok büyük (en fazla {mb} MB)": "File is too large (max {mb} MB)",
    "Boş dosya yüklenemez": "Empty files can't be uploaded",
    "Geçersiz dosya kaydı": "Invalid file record",

    # --- projeler ---
    "Yöneticiler proje eklemez — projeleri yalnız görüntüler.":
        "Admins don't add projects — they only view them.",
    "source_type yalnızca {list} olabilir": "source_type can only be {list}",
    "Proje bulunamadı": "Project not found",
    "Bu projeye erişim yetkiniz yok": "You don't have permission to access this project",
    "Değerlendirilecek commit yok — önce senkronize edin": "No commits to review yet — sync first",

    # --- yönetici ayarları ---
    "provider yalnızca {list} olabilir": "provider can only be {list}",
    "jira_auth 'basic' ya da 'bearer' olmalı.": "jira_auth must be 'basic' or 'bearer'.",
    "jira_api_style 'auto', 'cloud' ya da 'server' olmalı.":
        "jira_api_style must be 'auto', 'cloud' or 'server'.",
    "Senkron işi bulunamadı.": "Sync job not found.",

    # --- takvim işaretleri (app/api/annotations.py) ---
    "kind yalnızca {list} olabilir": "kind can only be {list}",
    "label boş olamaz": "label can't be empty",
    "Anotasyon bulunamadı": "Annotation not found",

    # --- anket ---
    "Anket modülü kapalı": "The survey module is disabled",
    "Anket şifrelemesi kurulmadı (hazır değil)": "Survey encryption is not set up (not ready)",
    "Anketi yöneticiler doldurmaz": "Admins don't fill out the survey",
    "Anket döngüsü kapalı": "The survey cycle is closed",
    "Bu dönem anketini zaten doldurdun": "You've already filled out this cycle's survey",
    "Döngü bulunamadı": "Cycle not found",
    "En az bir soru gerekli": "At least one question is required",
    "En az bir likert (1-5 puan) sorusu gerekli": "At least one Likert (1–5) question is required",
    "Soru etiketi boş olamaz": "Question label can't be empty",
    "Soru etiketi 200 karakteri aşamaz": "Question label can't exceed 200 characters",
    "Geçersiz tip: {typ} (likert | text)": "Invalid type: {typ} (likert | text)",
    "Geçersiz anahtar: '{key}' (yalnız a-z 0-9 _, 1-32)":
        "Invalid key: '{key}' (only a-z 0-9 _, 1-32 chars)",
    "Anahtar tekrarı: '{key}'": "Duplicate key: '{key}'",

    # --- sağlık ucu ---
    "Veritabanına erişilemiyor": "Database unavailable",

    # --- takım/bireysel görünüm, RAG, task analizi (app/api/routes.py) ---
    "Bu görünümü yalnızca kişinin kendisi ve admin görebilir":
        "Only the person themselves and admins can view this",
    "Bireysel görünüm bu kurulumda kapalı (takım-agregat mod)":
        "Individual view is disabled in this setup (team-aggregate mode)",
    "Kişi bulunamadı": "Person not found",
    "Bireysel görünümü yalnızca kişinin kendisi, yöneticisi ya da admin görebilir":
        "Only the person themselves, their manager, or an admin can view individual view",
    "Bu takımın kayıtlarına erişim yetkiniz yok": "You don't have permission to access this team's records",
    "İş bulunamadı": "Task not found",
    "Commit bulunamadı": "Commit not found",
    "days yalnızca {list} olabilir": "days can only be {list}",
    "LLM öneri katmanı kapalı. On-prem kısıtı gereği varsayılan olarak "
    "hiçbir veri dış servise gönderilmez — açtırmak için yöneticinize başvurun.":
        "The LLM advice layer is off. Under the on-prem constraint, no data is sent "
        "to external services by default — ask your administrator to turn it on.",
    "RAG asistanı kapalı. On-prem kısıtı gereği varsayılan olarak kapalıdır "
    "— açtırmak için yöneticinize başvurun.":
        "The RAG assistant is off. It's off by default under the on-prem constraint "
        "— ask your administrator to turn it on.",
    "RAG cevabı üretilemedi": "Couldn't generate a RAG answer",
    "Analiz üretilemedi": "Couldn't generate the analysis",

    # --- RAG cevap üretimi (app/services/rag/query.py) — sabit "reason" kümesi,
    # AI'nin serbest metin çıktısı DEĞİL: kodun kendi ürettiği durum açıklaması.
    "RAG katmanı kapalı.": "The RAG layer is off.",
    "Embedding sağlayıcısı kurulamadı (seçili sağlayıcı: {provider}).":
        "Couldn't set up the embedding provider (selected provider: {provider}).",
    "LLM katmanı kapalı — cevap üretilemez.":
        "The LLM layer is off — no answer can be generated.",
    "Soru vektöre çevrilemedi ({err}) — embedding sağlayıcısı erişilebilir mi?":
        "Couldn't convert the question to a vector ({err}) — is the embedding provider reachable?",
    "Bu soruyla yeterince ilgili kayıt bulunamadı. Senkron çalıştı mı, "
    "ilgili takımda commit/task var mı kontrol edin.":
        "No sufficiently relevant records were found for this question. Check whether "
        "sync has run and whether the team has commits/tasks.",
    "LLM çağrısı başarısız ({err}).": "The LLM call failed ({err}).",

    # --- iş (task) süreç analizi (app/services/task_analysis.py) — aynı kural:
    # sabit durum açıklamaları, AI'nin ürettiği düzyazı analiz metni DEĞİL.
    "Task bulunamadı.": "Task not found.",
    "Bu iş için onaylanmış commit bağı yok. Analiz tahmine "
    "dayanmaz — önce önerilen bağları onaylayın.":
        "There's no confirmed commit link for this task. Analysis doesn't rely on "
        "guesses — confirm the suggested links first.",
    "LLM katmanı kapalı — analiz üretilemez.":
        "The LLM layer is off — no analysis can be generated.",
}
