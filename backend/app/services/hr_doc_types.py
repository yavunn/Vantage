"""Bordro/özlük evrak TÜRLERİ kataloğu (Türkiye mevzuatına göre).

NEDEN SABİT KATALOG, SERBEST METİN DEĞİL: "belge açıklaması" serbest bırakılsa
aynı şey on ayrı isimle yüklenirdi ("rapor", "istirahat", "doktor raporu",
"sağlık raporu") ve İK hiçbir zaman "bu ay kaç rapor geldi" ya da "kimin özlük
dosyası eksik" sorusunu cevaplayamazdı. Tür bir ANAHTAR olduğu için eksik belge
tespiti, dönem kırılımı ve bordroya etki uyarısı hesaplanabilir hâle gelir.

ALAN ANLAMLARI
- category      : arayüzdeki gruplama (leave | payroll | personnel | exit | other)
- affects_payroll: bu belge o ayın BORDROSUNU değiştirir mi (kesinti, ödenek,
                  eksik gün, vergi indirimi). Arayüz bunu işaretler ki İK bir
                  belgeyi "arşivlik evrak" sanıp bordroyu eksik kapatmasın.
- needs_period  : hangi bordro dönemine (YYYY-MM) ait olduğu ZORUNLU mu.
- needs_dates   : başlangıç/bitiş tarihi ZORUNLU mu (rapor/izin gün hesabı).
- required      : özlük dosyasında BULUNMASI ZORUNLU belge mi (eksik listesi
                  bu bayraktan üretilir). 4857 s. İş Kanunu m.75 kapsamı.
- effect        : insana dönük tek cümlelik "bordroda ne olur" açıklaması.

KAPSAM SINIRI: bu katalog belgenin VARLIĞINI takip eder, bordroyu HESAPLAMAZ.
Ücret hesabı bu sistemin işi değildir (SGK/vergi parametreleri her yıl değişir
ve yanlış hesaplanmış bir bordro, hiç hesaplanmamış olandan kötüdür). Burada
üretilen çıktı "İK bordroyu kapatmadan önce elinde ne var / ne eksik"tir.
"""
from __future__ import annotations

# Kategori sırası = arayüzdeki grup sırası.
CATEGORIES: tuple[str, ...] = ("leave", "payroll", "personnel", "exit", "other")

CATEGORY_LABELS_TR: dict[str, str] = {
    "leave": "İzin / devamsızlık belgeleri",
    "payroll": "Kesinti / kazanç belgeleri",
    "personnel": "Özlük dosyası (işe giriş)",
    "exit": "İşten ayrılış belgeleri",
    "other": "Diğer",
}

CATEGORY_LABELS_EN: dict[str, str] = {
    "leave": "Leave / absence documents",
    "payroll": "Deduction / earning documents",
    "personnel": "Personnel file (onboarding)",
    "exit": "Offboarding documents",
    "other": "Other",
}


def _t(
    key: str,
    label: str,
    category: str,
    effect: str,
    *,
    affects_payroll: bool = False,
    needs_period: bool = False,
    needs_dates: bool = False,
    required: bool = False,
) -> dict:
    return {
        "key": key,
        "label": label,
        "category": category,
        "effect": effect,
        "affects_payroll": affects_payroll,
        "needs_period": needs_period,
        "needs_dates": needs_dates,
        "required": required,
    }


# --- katalog (TR ana dil) -----------------------------------------------------
DOC_TYPES: list[dict] = [
    # === İzin / devamsızlık — hepsi o ayın puantajını ve bordroyu değiştirir ===
    _t("sick_report", "İstirahat raporu (iş göremezlik)", "leave",
       "İlk 2 gün işveren, sonrası SGK geçici iş göremezlik ödeneği; puantajda "
       "raporlu gün olarak işlenir.",
       affects_payroll=True, needs_period=True, needs_dates=True),
    _t("work_accident", "İş kazası / meslek hastalığı belgesi", "leave",
       "SGK'ya 3 iş günü içinde bildirim zorunlu; iş göremezlik ödeneği doğurur.",
       affects_payroll=True, needs_period=True, needs_dates=True),
    _t("birth_report", "Doğum (analık) raporu", "leave",
       "Doğum öncesi 8 + sonrası 8 hafta analık izni; SGK analık ödeneği.",
       affects_payroll=True, needs_period=True, needs_dates=True),
    _t("nursing_leave", "Süt izni talebi", "leave",
       "Bir yaşına kadar günde 1,5 saat ücretli süt izni — çalışma süresinden düşer.",
       affects_payroll=True, needs_period=True, needs_dates=True),
    _t("paternity", "Babalık izni belgesi (doğum belgesi)", "leave",
       "5 gün ücretli mazeret izni — ücretten kesilmez.",
       affects_payroll=True, needs_period=True, needs_dates=True),
    _t("marriage", "Evlilik belgesi", "leave",
       "3 gün ücretli mazeret izni; ayrıca aile durumu bildirimini günceller.",
       affects_payroll=True, needs_period=True, needs_dates=True),
    _t("death_certificate", "Vefat belgesi (yakın kaybı)", "leave",
       "Eş/çocuk/ana-baba-kardeş için 3 gün ücretli mazeret izni.",
       affects_payroll=True, needs_period=True, needs_dates=True),
    _t("caregiver_report", "Refakat raporu", "leave",
       "Yakının tedavisine refakat — SGK raporlu gün olarak işlenir.",
       affects_payroll=True, needs_period=True, needs_dates=True),
    _t("adoption", "Evlat edinme belgesi", "leave",
       "3 yaşını doldurmamış çocuğu evlat edinmede analık/babalık haklarını doğurur.",
       affects_payroll=True, needs_period=True, needs_dates=True),
    _t("disabled_child_care", "Engelli çocuk tedavi izni belgesi", "leave",
       "Yılda 10 güne kadar ücretli izin (engelli/süreğen hastalıklı çocuk tedavisi).",
       affects_payroll=True, needs_period=True, needs_dates=True),
    _t("military", "Askerlik sevk / terhis belgesi", "leave",
       "Sözleşme askıya alınır; SGK'da eksik gün + ücretsiz izin olarak işlenir.",
       affects_payroll=True, needs_period=True, needs_dates=True),
    _t("unpaid_leave", "Ücretsiz izin talebi", "leave",
       "O günler ücretten düşülür ve SGK'ya eksik gün nedeniyle bildirilir.",
       affects_payroll=True, needs_period=True, needs_dates=True),
    _t("excuse_leave", "Mazeret izni dilekçesi", "leave",
       "Gerekçeye göre ücretli/ücretsiz — puantajı etkiler.",
       affects_payroll=True, needs_period=True, needs_dates=True),
    _t("annual_leave_form", "Yıllık izin talep / onay formu", "leave",
       "Yıllık izin defterine işlenir; kullanılan gün bakiyeden düşer.",
       needs_dates=True),

    # === Kesinti / kazanç — ücretin TUTARINI değiştiren belgeler ===
    _t("garnishment", "İcra / maaş haczi müzekkeresi", "payroll",
       "Net ücretin en çok 1/4'ü kesilip icra dairesine yatırılır; kesinti "
       "yapılmaması işverene sorumluluk doğurur.",
       affects_payroll=True, needs_period=True),
    _t("alimony", "Nafaka mahkeme kararı", "payroll",
       "Nafaka alacağı hacizde önceliklidir ve 1/4 sınırına tabi değildir.",
       affects_payroll=True, needs_period=True),
    _t("disability_report", "Engelli sağlık kurulu raporu", "payroll",
       "Derecesine göre gelir vergisi matrahından engellilik indirimi uygulanır.",
       affects_payroll=True),
    _t("private_pension", "BES / bireysel emeklilik poliçesi", "payroll",
       "Net ücretten kesilip emeklilik şirketine aktarılır.",
       affects_payroll=True, needs_period=True),
    _t("private_health_insurance", "Özel sağlık / hayat sigortası poliçesi", "payroll",
       "Yasal sınırlar içinde gelir vergisi matrahından indirilebilir.",
       affects_payroll=True),
    _t("union_membership", "Sendika üyelik / aidat belgesi", "payroll",
       "Üyelik aidatı ücretten kesilip sendikaya aktarılır.",
       affects_payroll=True, needs_period=True),
    _t("overtime_consent", "Fazla çalışma onayı (muvafakatname)", "payroll",
       "Fazla mesai için yazılı onay zorunlu; yıllık 270 saat sınırı izlenir.",
       affects_payroll=True),
    _t("timesheet", "Puantaj / mesai çizelgesi", "payroll",
       "Bordronun temeli: çalışılan gün, fazla mesai, hafta tatili buradan gelir.",
       affects_payroll=True, needs_period=True),
    _t("advance_request", "Avans talep formu", "payroll",
       "Ödenen avans o ayın bordrosunda mahsup edilir.",
       affects_payroll=True, needs_period=True),
    _t("expense_receipt", "Masraf / harcırah belgesi", "payroll",
       "Belgeye dayalı masraf iadesi; sınırlar içinde vergi/SGK istisnası.",
       affects_payroll=True, needs_period=True),
    _t("bank_iban", "Banka hesap (IBAN) bildirimi", "payroll",
       "Ücretin bankadan ödenmesi zorunlu — IBAN olmadan ödeme yapılamaz.",
       required=True),
    _t("family_status", "Aile durumu bildirimi", "payroll",
       "Eş/çocuk durumu; asgari ücret istisnası ve bakmakla yükümlü kaydını etkiler.",
       required=True),
    _t("iskur_record", "İŞKUR kayıt belgesi (teşvik)", "payroll",
       "Teşvik kapsamındaki işe alımda SGK prim indirimi sağlar.",
       affects_payroll=True),
    _t("payslip", "İmzalı ücret bordrosu / pusulası", "payroll",
       "Uyuşmazlıkta en güçlü delil; imzalı nüsha özlük dosyasında saklanmalı.",
       needs_period=True, required=True),

    # === Özlük dosyası — 4857 s. İş Kanunu m.75 kapsamında tutulur ===
    _t("employment_contract", "İş sözleşmesi", "personnel",
       "Ücret, çalışma süresi ve görevin yazılı dayanağı.", required=True),
    _t("sgk_entry", "SGK işe giriş bildirgesi", "personnel",
       "İşe başlamadan önce verilmesi zorunlu; sigortalılık başlangıcıdır.",
       required=True),
    _t("id_copy", "Kimlik fotokopisi", "personnel",
       "Kimlik doğrulama ve SGK/vergi bildirimlerinin dayanağı.", required=True),
    _t("residence", "İkametgah belgesi", "personnel",
       "Adres kaydı; tebligat ve yol yardımı hesabında kullanılır.", required=True),
    _t("criminal_record", "Adli sicil kaydı", "personnel",
       "İşe giriş evrakı; bazı görevlerde mevzuat gereği zorunlu.", required=True),
    _t("diploma", "Öğrenim belgesi / diploma", "personnel",
       "Ünvan ve ücret bandının dayanağı.", required=True),
    _t("photo", "Vesikalık fotoğraf", "personnel",
       "Özlük dosyası ve kimlik kartı için.", required=True),
    _t("health_report", "İşe giriş sağlık raporu", "personnel",
       "İşe uygunluk raporu — İSG mevzuatı gereği zorunlu.", required=True),
    _t("ohs_training", "İSG eğitim katılım belgesi", "personnel",
       "İş sağlığı ve güvenliği eğitiminin belgelenmesi zorunlu.", required=True),
    _t("ppe_delivery", "KKD zimmet / teslim tutanağı", "personnel",
       "Kişisel koruyucu donanım teslimi belgelenir."),
    _t("job_description", "Görev tanımı", "personnel",
       "Görev ve sorumlulukların yazılı tanımı."),
    _t("certificate", "Sertifika / ustalık belgesi", "personnel",
       "Mesleki yeterlilik; bazı işlerde mevzuat gereği aranır."),

    # === İşten ayrılış ===
    _t("resignation", "İstifa dilekçesi", "exit",
       "Fesih türünü belirler: kıdem/ihbar tazminatı hakkını doğrudan etkiler.",
       affects_payroll=True),
    _t("termination_notice", "Fesih bildirimi", "exit",
       "İhbar süresi ve tazminat hesabının dayanağı.", affects_payroll=True),
    _t("severance_calc", "Kıdem / ihbar tazminatı hesap tablosu", "exit",
       "Son bordroya giren tazminat kalemlerinin hesabı.",
       affects_payroll=True, needs_period=True),
    _t("release_deed", "İbraname", "exit",
       "Ödenen alacakların ibrası — çıkış dosyasında saklanır."),
    _t("sgk_exit", "SGK işten ayrılış bildirgesi", "exit",
       "10 gün içinde verilmesi zorunlu; çıkış kodu işsizlik ödeneğini belirler.",
       affects_payroll=True),
    _t("experience_letter", "Çalışma belgesi", "exit",
       "İşçinin talebi hâlinde verilmesi zorunlu."),

    # === Diğer ===
    _t("other", "Diğer", "other",
       "Kataloğa girmeyen belge — açıklama alanına ne olduğunu yazın."),
]

DOC_TYPE_MAP: dict[str, dict] = {d["key"]: d for d in DOC_TYPES}

# Özlük dosyasında bulunması ZORUNLU türler — "eksik evrak" listesi bundan üretilir.
REQUIRED_KEYS: tuple[str, ...] = tuple(d["key"] for d in DOC_TYPES if d["required"])


# --- izin (Leave) senkronu -----------------------------------------------------
# "leave" kategorisindeki her tür bir devamsızlık KANITIDIR (rapor, izin talep
# formu, doğum belgesi...) ve tarihleri zaten belgenin kendisinde var. İK'nın
# aynı başlangıç/bitiş tarihini bir de İzin panosuna elle girmesine gerek yok:
# belge onaylanınca ilgili Leave kaydı OTOMATİK oluşur ya da (önceden elle
# bağlanmışsa) otomatik onaylanır — bkz. api/documents.py decide_document.
#
# Leave.leave_type yalnız 3 değer alır (annual|sick|other, bkz. api/leaves.py);
# eşleme bu yüzden var. sick_report/work_accident/caregiver_report SGK'ya
# raporlu gün olarak bildirildiği için "sick"; annual_leave_form doğrudan
# yıllık izin belgesi olduğu için "annual"; geri kalanı (doğum, evlilik, vefat,
# askerlik, ücretsiz izin...) mevcut şemada ayrı bir tür olmadığından "other".
LEAVE_TYPE_FOR_DOC: dict[str, str] = {
    "sick_report": "sick",
    "work_accident": "sick",
    "caregiver_report": "sick",
    "birth_report": "other",
    "nursing_leave": "other",
    "paternity": "other",
    "marriage": "other",
    "death_certificate": "other",
    "adoption": "other",
    "disabled_child_care": "other",
    "military": "other",
    "unpaid_leave": "other",
    "excuse_leave": "other",
    "annual_leave_form": "annual",
}

# Kataloğa yeni bir "leave" türü eklenip bu eşlemenin güncellenmesi unutulursa
# o belge sessizce izin senkronunun dışında kalırdı — testte kontrol edilir
# (tests/test_hr_doc_types.py), burada da açık bir çelişki bırakmamak için not:
# LEAVE_TYPE_FOR_DOC anahtarları TAM OLARAK category=="leave" olan türler olmalı.


# --- İngilizce etiketler ------------------------------------------------------
# Yalnız etiket + etki cümlesi çevrilir; anahtar/bayraklar dilden bağımsızdır.
LABELS_EN: dict[str, tuple[str, str]] = {
    "sick_report": ("Medical leave report",
                    "First 2 days paid by employer, rest by SSI; recorded as sick days."),
    "work_accident": ("Work accident / occupational disease report",
                      "Must be reported to SSI within 3 business days; triggers incapacity benefit."),
    "birth_report": ("Maternity report", "8 weeks before + 8 after birth; SSI maternity benefit."),
    "nursing_leave": ("Nursing leave request", "1.5 paid hours per day until the child turns one."),
    "paternity": ("Paternity leave document", "5 days of paid excuse leave — no pay deduction."),
    "marriage": ("Marriage certificate", "3 days of paid excuse leave; updates family status."),
    "death_certificate": ("Death certificate (bereavement)",
                          "3 days of paid excuse leave for close family."),
    "caregiver_report": ("Caregiver report", "Recorded as reported absence via SSI."),
    "adoption": ("Adoption document", "Grants maternity/paternity rights for children under 3."),
    "disabled_child_care": ("Disabled child treatment leave",
                            "Up to 10 paid days per year for the child's treatment."),
    "military": ("Military service / discharge document",
                 "Contract suspended; reported to SSI as missing days."),
    "unpaid_leave": ("Unpaid leave request",
                     "Days are deducted from pay and reported to SSI as missing days."),
    "excuse_leave": ("Excuse leave petition", "Paid or unpaid depending on reason; affects timesheet."),
    "annual_leave_form": ("Annual leave request / approval form",
                          "Recorded in the leave ledger; days come off the balance."),
    "garnishment": ("Wage garnishment order",
                    "Up to 1/4 of net pay is withheld and paid to the enforcement office."),
    "alimony": ("Alimony court order",
                "Alimony ranks first in garnishment and is exempt from the 1/4 cap."),
    "disability_report": ("Disability board report",
                          "Income tax base is reduced by the disability allowance."),
    "private_pension": ("Private pension (BES) policy",
                        "Deducted from net pay and transferred to the pension company."),
    "private_health_insurance": ("Private health / life insurance policy",
                                 "Deductible from the income tax base within legal limits."),
    "union_membership": ("Union membership / dues document",
                         "Dues are withheld from pay and transferred to the union."),
    "overtime_consent": ("Overtime consent form",
                         "Written consent required; the 270 hours/year cap is tracked."),
    "timesheet": ("Timesheet",
                  "The basis of payroll: worked days, overtime and weekly rest come from here."),
    "advance_request": ("Advance payment request", "Offset against the same month's payroll."),
    "expense_receipt": ("Expense / per diem receipt",
                        "Documented reimbursement; tax and SSI exempt within limits."),
    "bank_iban": ("Bank account (IBAN) declaration",
                  "Wages must be paid via bank — no payment without an IBAN."),
    "family_status": ("Family status declaration",
                      "Spouse/children status; affects the minimum wage exemption and dependants."),
    "iskur_record": ("İŞKUR registration (incentive)",
                     "Qualifies the hire for an SSI premium incentive."),
    "payslip": ("Signed payslip",
                "The strongest evidence in disputes; keep the signed copy on file."),
    "employment_contract": ("Employment contract",
                            "Written basis for pay, working time and duties."),
    "sgk_entry": ("SSI entry notification",
                  "Mandatory before the first working day; starts insured status."),
    "id_copy": ("ID copy", "Identity verification and basis for SSI/tax filings."),
    "residence": ("Residence certificate", "Address record; used for notices and travel allowance."),
    "criminal_record": ("Criminal record certificate",
                        "Onboarding document; mandatory for some roles."),
    "diploma": ("Diploma / education certificate", "Basis for title and pay band."),
    "photo": ("Passport photo", "For the personnel file and ID card."),
    "health_report": ("Pre-employment health report",
                      "Fitness-for-work report — mandatory under OHS legislation."),
    "ohs_training": ("OHS training certificate",
                     "Occupational health and safety training must be documented."),
    "ppe_delivery": ("PPE delivery record", "Documents handover of personal protective equipment."),
    "job_description": ("Job description", "Written definition of duties and responsibilities."),
    "certificate": ("Certificate / mastership document",
                    "Vocational qualification; required by law for some jobs."),
    "resignation": ("Resignation letter",
                    "Determines the type of termination: directly affects severance/notice pay."),
    "termination_notice": ("Termination notice", "Basis for notice period and severance calculation."),
    "severance_calc": ("Severance / notice pay calculation",
                       "Calculation of termination items entering the final payslip."),
    "release_deed": ("Release deed", "Release of paid receivables — kept in the exit file."),
    "sgk_exit": ("SSI exit notification",
                 "Due within 10 days; the exit code determines unemployment benefit."),
    "experience_letter": ("Employment certificate", "Must be issued on the employee's request."),
    "other": ("Other", "Not in the catalogue — describe it in the note field."),
}


def catalog(lang: str = "tr") -> list[dict]:
    """Katalog, istenen dilde. Bilinmeyen dil TR'ye düşer (i18n kuralı)."""
    if lang != "en":
        return [dict(d) for d in DOC_TYPES]
    out = []
    for d in DOC_TYPES:
        label, effect = LABELS_EN.get(d["key"], (d["label"], d["effect"]))
        out.append({**d, "label": label, "effect": effect})
    return out


def type_label(key: str, lang: str = "tr") -> str:
    """Tek türün etiketi. Katalogdan düşmüş eski bir anahtar gelirse anahtarın
    kendisi döner — geçmiş kayıt ekranda boş görünmesin."""
    meta = DOC_TYPE_MAP.get(key)
    if meta is None:
        return key
    if lang == "en":
        return LABELS_EN.get(key, (meta["label"], ""))[0]
    return meta["label"]
