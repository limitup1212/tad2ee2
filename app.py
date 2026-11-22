"""تدقيق الكشوف — Streamlit interface (Arabic, right-to-left).

Run:  streamlit run app.py
All processing is local: photos go only to the Ollama server on this machine.
"""
from __future__ import annotations

import hashlib
import time
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from sheetcheck import aggregation as agg
from sheetcheck import documents
from sheetcheck import extraction as ex
from sheetcheck import form as form_mod
from sheetcheck import inbox
from sheetcheck import review as rv
from sheetcheck import sample_data
from sheetcheck.config import DATA_DIR, ROOT, load_config, save_config, verification_settings
from sheetcheck.models import FIELD_LABELS, F_ROUNDING, F_STAMP, F_TAX, F_TOTAL
from sheetcheck.parsing import fmt_money, parse_amount, quarter_months, quarter_of
from sheetcheck.verification import Result, month_label, verify

BATCH_DIR = DATA_DIR / "batches"
INBOX_DIR = DATA_DIR / "inbox"
STEP_INPUT, STEP_REVIEW, STEP_AGG = "١ · الإدخال", "٢ · المراجعة والنتيجة", "٣ · التجميع"
IMAGE_TYPES = ["jpg", "jpeg", "png", "webp", "bmp"]
UPLOAD_TYPES = IMAGE_TYPES + ["pdf"]   # a PDF becomes one image per page

st.set_page_config(page_title="تدقيق الكشوف", page_icon="🧾", layout="wide")

st.markdown(
    """
    <style>
      .stApp, [data-testid="stSidebar"] { direction: rtl; text-align: right; }
      html, body, .stApp, input, textarea, button {
        font-family: "Segoe UI", Tahoma, "Noto Naskh Arabic", Arial, sans-serif;
      }
      [data-testid="stMetricValue"] { direction: ltr; text-align: right; }
      [data-testid="stFileUploaderDropzone"] { direction: ltr; }
      .big-total { font-size: 2.6rem; font-weight: 700; direction: ltr; text-align: right; }
      .muted { color: #6b7280; font-size: 0.9rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

ss = st.session_state
cfg = load_config()


# --- session state ---------------------------------------------------------------

def init_state() -> None:
    ss.setdefault("sheets", [])            # [{"label", "image", "df"}]
    ss.setdefault("summary_image", None)
    ss.setdefault("summary_vals", None)    # {"total","tax","rounding","stamp","unclear"}
    ss.setdefault("result", None)
    ss.setdefault("version", 0)            # bumps to give review widgets fresh keys
    ss.setdefault("cache", {})             # image hash -> extraction
    ss.setdefault("cam_summary", None)
    ss.setdefault("cam_sheets", [])
    ss.setdefault("saved_id", None)
    ss.setdefault("year", date.today().year)
    ss.setdefault("form_date", date.today())
    ss.setdefault("name", "")
    # Streamlit forgets a widget's value when its page is not shown; re-assigning
    # keeps the batch details alive while moving between the steps.
    for key in ("name", "form_date"):
        ss[key] = ss[key]
    # Values queued by a button are applied before the widgets that own them exist.
    for key, value in ss.pop("_pending", {}).items():
        ss[key] = value


def queue(**values) -> None:
    ss.setdefault("_pending", {}).update(values)


def reset_batch() -> None:
    for key in ("sheets", "summary_image", "summary_vals", "result", "cam_summary",
                "cam_sheets", "saved_id"):
        ss.pop(key, None)
    ss["version"] = ss.get("version", 0) + 1
    ss["uploader_version"] = ss.get("uploader_version", 0) + 1
    inbox.clear(INBOX_DIR)
    queue(nav=STEP_INPUT, name="")


def fmt_input(value) -> str:
    return "" if value is None else fmt_money(value)


# --- sidebar ------------------------------------------------------------------------

@st.cache_data(max_entries=40, show_spinner="جارٍ تحويل صفحات PDF إلى صور…")
def pages_of(label: str, data: bytes) -> list[tuple[str, bytes]]:
    return documents.expand(label, data)


def gather_inputs(summary_file, sheet_files) -> tuple[bytes | None, list[tuple[str, bytes]], list[str]]:
    """Summary image, [(label, sheet image)] and problems, from every source, PDFs split into pages.

    A PDF with several pages given as the summary is treated as the whole batch:
    page 1 is the summary page and the following pages are sheets.
    """
    problems: list[str] = []

    def expand(label: str, data: bytes) -> list[tuple[str, bytes]]:
        try:
            return pages_of(label, data)
        except documents.DocumentError as e:
            problems.append(f"{label}: {e}")
            return []

    summary_image, sheets = None, []
    summary_source = ((summary_file.name, summary_file.getvalue()) if summary_file
                      else ("صورة الكاميرا", ss.cam_summary) if ss.cam_summary
                      else ("الخلاصة من الهاتف", inbox.summary(INBOX_DIR)))
    if summary_source[1]:
        pages = expand(*summary_source)
        if pages:
            summary_image = pages[0][1]
            sheets += [(f"{summary_source[0]} · صفحة {i}", img)
                       for i, (_, img) in enumerate(pages[1:], start=2)]
    for f in sheet_files or []:
        sheets += expand(f.name, f.getvalue())
    sheets += [(f"كاميرا {i + 1}", data) for i, data in enumerate(ss.cam_sheets)]
    for i, data in enumerate(inbox.sheets(INBOX_DIR)):
        sheets += expand(f"من الهاتف {i + 1}", data)
    return summary_image, sheets, problems


@st.cache_data(ttl=15, show_spinner=False)
def model_status(model: str):
    return ex.server_status(model)


def sidebar() -> dict:
    """Returns the extraction settings for this run."""
    with st.sidebar:
        st.header("الإعدادات")
        st.success("🔒 كل المعالجة تتم على هذا الجهاز. الصور لا تُرسل إلى الإنترنت.")

        base = cfg["extraction"]["model"]
        options = list(dict.fromkeys([base, "qwen3-vl:4b-instruct", "qwen3-vl:8b-instruct"]))
        model = st.selectbox(
            "النموذج المحلي",
            options,
            accept_new_options=True,
            help="4b أسرع، 8b أدق وأبطأ. يمكن كتابة اسم أي نموذج رؤية منزّل في Ollama.",
        )
        _, ready, message = model_status(model)
        (st.info if ready else st.error)(message)

        modes = {
            "عادية — الصفحة على جزأين تقريباً": None,      # values from config.yaml
            "سريعة — الصفحة كاملة مرة واحدة": 0,
            "دقيقة — شرائط صغيرة (أبطأ بكثير)": 4.5,
        }
        mode = st.selectbox(
            "دقة القراءة",
            list(modes),
            help="كلما صغر الجزء المقروء رأى النموذج الأرقام أكبر وأوضح، لكن كل جزء يأخذ "
                 "وقت قراءة كاملاً. استخدم «دقيقة» للكشوف المزدحمة أو الخط الصغير.",
        )
        double_read = st.toggle(
            "قراءة مزدوجة للتأكد",
            value=False,
            help="يقرأ كل صورة مرتين ويعلّم أي رقم اختلفت فيه القراءتان. أدق لكنه يضاعف الوقت.",
        )
        sheet_hint = st.text_area(
            "وصف شكل الكشف (اختياري)",
            value=cfg["extraction"].get("sheet_hint", ""),
            placeholder="مثال: العمود الأول من اليمين هو التسلسل، ثم الاسم (تجاهله)، ثم المبلغ، ثم التاريخ",
            help="وصف بسيط للأعمدة يساعد النموذج على القراءة الصحيحة.",
        )
        if sheet_hint != cfg["extraction"].get("sheet_hint", "") and st.button("حفظ الوصف"):
            cfg["extraction"]["sheet_hint"] = sheet_hint
            save_config(cfg)
            st.toast("تم حفظ الوصف")

        with st.expander("خلايا النموذج (Excel)"):
            form_settings()

        v = cfg["verification"]
        st.caption(
            f"نسبة الضريبة {float(v['tax_rate']) * 100:g}% · التقريب إلى "
            f"{fmt_money(parse_amount(v['rounding_unit']))} — تُعدَّل من الملف config.yaml"
        )
    settings = {**cfg["extraction"], "model": model, "sheet_hint": sheet_hint,
                "double_read": double_read, "ready": ready}
    if modes[mode] is not None:
        settings["strip_ratio"] = settings["summary_strip_ratio"] = modes[mode]
    return settings


def form_settings() -> None:
    st.caption("لكل قيمة، اكتب عنوان الخلية في ملف النموذج (مثل C7). اتركها فارغة لتجاهلها.")
    cells = cfg["form"]["cells"]
    table = pd.DataFrame(
        [{"key": k, "القيمة": label, "الخلية": cells.get(k, "") or ""}
         for k, label in form_mod.FIELD_NAMES.items()]
    )
    edited = st.data_editor(
        table,
        hide_index=True,
        column_config={"key": None, "القيمة": st.column_config.TextColumn(disabled=True)},
        key="cells_editor",
    )
    sheet_name = st.text_input("اسم الورقة داخل الملف (فارغ = الأولى)",
                               value=cfg["form"].get("sheet") or "")
    if st.button("حفظ خلايا النموذج"):
        cfg["form"]["cells"] = {
            row["key"]: str(row["الخلية"]).strip().upper()
            for row in edited.to_dict("records")
            if str(row["الخلية"] or "").strip()
        }
        cfg["form"]["sheet"] = sheet_name.strip() or None
        save_config(cfg)
        st.toast("تم الحفظ")


# --- step 1: input --------------------------------------------------------------------

def page_input(settings: dict) -> None:
    st.subheader("بيانات الدفعة")
    batches = agg.load_batches(BATCH_DIR)
    name = st.text_input("اسم الشخص", key="name")
    known = agg.last_serial_for(name, batches)
    if known is not None:
        st.caption(f"آخر تسلسل محفوظ لهذا الاسم في التجميع: {known}")

    st.date_input("تاريخ النموذج", key="form_date", format="DD/MM/YYYY")
    st.caption("الربع والسنة يُستخرجان تلقائياً من تواريخ الكشوف، وآخر تسلسل في الدفعة السابقة "
               "يُعتبر أصغر تسلسل في الكشوف ناقص 1.")

    st.subheader("الصور")
    up = ss.get("uploader_version", 0)
    u1, u2 = st.columns(2)
    summary_file = u1.file_uploader("صفحة الخلاصة (صورة أو PDF)", type=UPLOAD_TYPES,
                                    key=f"summary_file_{up}",
                                    help="إذا كانت الدفعة كلها في ملف PDF واحد فارفعه هنا: "
                                         "الصفحة الأولى تُعدّ الخلاصة وباقي الصفحات كشوفاً.")
    sheet_files = u2.file_uploader("الكشوف (صور أو ملفات PDF)", type=UPLOAD_TYPES,
                                   accept_multiple_files=True, key=f"sheet_files_{up}",
                                   help="كل صفحة في ملف PDF تُقرأ ككشف مستقل، بترتيب الصفحات.")
    phone_section()

    if st.toggle("التصوير بكاميرا هذا الجهاز"):
        shot = st.camera_input("التقط صورة")
        kind = st.radio("هذه الصورة هي", ["كشف", "صفحة الخلاصة"], horizontal=True)
        if shot is not None and st.button("➕ إضافة الصورة"):
            if kind == "كشف":
                ss.cam_sheets.append(shot.getvalue())
            else:
                ss.cam_summary = shot.getvalue()
        if ss.cam_summary or ss.cam_sheets:
            st.caption(
                f"صور الكاميرا: خلاصة {'1' if ss.cam_summary else '0'} · كشوف {len(ss.cam_sheets)}"
            )
            if st.button("مسح صور الكاميرا"):
                ss.cam_summary, ss.cam_sheets = None, []
                st.rerun()

    summary_image, sheet_images, problems = gather_inputs(summary_file, sheet_files)
    for problem in problems:
        st.warning(problem)
    if summary_image is not None or sheet_images:
        st.caption(f"جاهز للقراءة: صفحة خلاصة {'1' if summary_image is not None else '0'} · "
                   f"كشوف {len(sheet_images)}")

    st.divider()
    b1, b2, b3 = st.columns(3)
    start = b1.button("🔍 استخراج البيانات من الصور", type="primary", width="stretch")
    manual = b2.button("✍️ إدخال يدوي بدون صور", width="stretch")
    demo = b3.button("🧪 تجربة ببيانات نموذجية", width="stretch")

    if demo:
        load_sample()
    elif manual:
        start_review([{"label": "إدخال يدوي", "image": None, "df": rv.empty_frame()}], None,
                     {F_TOTAL: None, F_TAX: None, F_ROUNDING: None, F_STAMP: None, "unclear": {}})
    elif start:
        if not sheet_images and summary_image is None:
            st.error("ارفع صورة أو ملف PDF واحداً على الأقل.")
        elif not settings["ready"]:
            st.error("النموذج المحلي غير جاهز — راجع الرسالة في الشريط الجانبي.")
        else:
            run_extraction(summary_image, sheet_images, settings)


def phone_url() -> str | None:
    """Address of the phone page, or None when the app only listens on this computer."""
    if st.get_option("server.address") in ("localhost", "127.0.0.1"):
        return None
    ip = inbox.lan_ip()
    return f"http://{ip}:{st.get_option('server.port')}/?phone=1" if ip else None


@st.fragment(run_every=3)
def inbox_status() -> None:
    n_summary, n_sheets = inbox.counts(INBOX_DIR)
    if not (n_summary or n_sheets):
        st.caption("لم تصل صور من الهاتف بعد. تظهر هنا تلقائياً عند إرسالها.")
        return
    st.success(f"📱 وصلت من الهاتف: صفحة خلاصة {n_summary} · كشوف {n_sheets}")
    files = ([inbox.summary(INBOX_DIR)] if n_summary else []) + inbox.sheets(INBOX_DIR)
    thumbs = []
    for data in files[:8]:
        try:
            thumbs += [img for _, img in pages_of("", data)][:8 - len(thumbs)]
        except documents.DocumentError:
            pass
    if thumbs:
        st.image(thumbs[:8], width=110)
    if st.button("مسح صور الهاتف"):
        inbox.clear(INBOX_DIR)
        st.rerun()


def phone_section() -> None:
    with st.expander("📱 التصوير من الهاتف مباشرة", expanded=any(inbox.counts(INBOX_DIR))):
        url = phone_url()
        if url is None:
            st.info("لتفعيل التصوير من الهاتف شغّل التطبيق بالملف **run_phone.bat** "
                    "(بدل run.bat) والهاتف على نفس شبكة Wi‑Fi.")
        else:
            left, right = st.columns([1, 2])
            left.image(inbox.qr_png(url), width=220)
            with right:
                st.markdown(
                    """
1. افتح كاميرا الهاتف ووجّهها إلى الرمز (الهاتف على نفس شبكة Wi‑Fi).
2. صوّر صفحة الخلاصة والكشوف من الصفحة التي تفتح واضغط «إرسال».
3. تظهر الصور هنا تلقائياً، ثم اضغط «استخراج البيانات».
"""
                )
                st.code(url, language=None)
        inbox_status()


def page_phone() -> None:
    """Minimal page for the phone: take photos and send them to the computer."""
    st.title("📱 تصوير الكشوف")
    st.caption("الصور تُرسل إلى الحاسوب على نفس الشبكة فقط، ولا تذهب إلى الإنترنت.")
    v = ss.get("phone_version", 0)
    for message in ss.pop("phone_done", []):
        st.success(message)
    summary_file = st.file_uploader("١ · صفحة الخلاصة (صورة أو PDF)", type=UPLOAD_TYPES,
                                    key=f"p_summary_{v}")
    sheet_files = st.file_uploader("٢ · الكشوف (صورة لكل ورقة بالترتيب، أو ملفات PDF)",
                                   type=UPLOAD_TYPES,
                                   accept_multiple_files=True, key=f"p_sheets_{v}")
    st.caption("اضغط على مربع الرفع ثم اختر «الكاميرا» للتصوير. صوّر الورقة كاملة، مستقيمة، "
               "وبإضاءة جيدة بدون ظل.")
    if st.button("📤 إرسال إلى الحاسوب", type="primary", width="stretch",
                 disabled=not (summary_file or sheet_files)):
        sent, failed = 0, 0
        for kind, files in ((inbox.SUMMARY, [summary_file] if summary_file else []),
                            (inbox.SHEETS, sheet_files or [])):
            for f in files:
                try:
                    inbox.save(INBOX_DIR, kind, f.getvalue())
                    sent += 1
                except ValueError:
                    failed += 1
        messages = [f"✅ تم إرسال {sent} ملف إلى الحاسوب. يمكنك تصوير المزيد."]
        if failed:
            messages.append(f"⚠️ {failed} ملف لم يكن صورة ولا PDF صالحاً وتم تجاهله.")
        ss["phone_done"] = messages
        ss["phone_version"] = v + 1          # empties the upload boxes for the next photos
        st.rerun()
    n_summary, n_sheets = inbox.counts(INBOX_DIR)
    st.caption(f"بانتظار الحاسوب الآن: صفحة خلاصة {n_summary} · كشوف {n_sheets}")


def load_sample() -> None:
    rows = sample_data.sample_rows()
    sheets = []
    for number in sorted({r.sheet for r in rows}):
        sheets.append({
            "label": f"ورقة {number} (بيانات نموذجية)",
            "image": None,
            "df": rv.rows_to_frame([r for r in rows if r.sheet == number]),
        })
    s = sample_data.sample_summary()
    queue(name="بيانات نموذجية")
    start_review(sheets, None, {F_TOTAL: s.total, F_TAX: s.tax, F_ROUNDING: s.rounding,
                                F_STAMP: s.stamp, "unclear": {}})


def start_review(sheets: list[dict], summary_image, summary_vals: dict) -> None:
    ss.sheets, ss.summary_image, ss.summary_vals = sheets, summary_image, summary_vals
    ss.result, ss.saved_id = None, None
    ss.version += 1
    queue(nav=STEP_REVIEW)
    st.rerun()


def cached_extract(kind: str, image: bytes, settings: dict, callbacks):
    key = hashlib.sha256(image).hexdigest() + "|".join(
        [kind, settings["model"], str(settings["double_read"]), settings.get("sheet_hint", ""),
         str(settings.get("strip_ratio")), str(settings.get("summary_strip_ratio"))]
    )
    if key not in ss.cache:
        func = ex.extract_summary if kind == "summary" else ex.extract_sheet
        ss.cache[key] = func(image, settings, settings["double_read"], *callbacks)
    return ss.cache[key]


def run_extraction(summary_image, sheet_images, settings: dict) -> None:
    total_steps = len(sheet_images) + (1 if summary_image else 0)
    bar = st.progress(0.0)
    note = st.empty()
    errors = []
    started = time.time()
    st.caption("القراءة على جهاز بدون كرت شاشة تأخذ بضع دقائق لكل صورة. اترك الصفحة مفتوحة.")

    def progress_for(label: str, index: int):
        part = {"text": ""}

        def show(chars: int = 0) -> None:
            minutes = int(time.time() - started) // 60
            note.info(f"⏳ {label} ({index} من {total_steps}){part['text']} — "
                      f"تمت قراءة {chars} حرفاً · الوقت المنقضي {minutes} د")

        def step(i: int, n: int) -> None:
            part["text"] = f" — الجزء {i} من {n}" if n > 1 else ""
            show()

        return show, step

    done = 0
    summary_vals = {F_TOTAL: None, F_TAX: None, F_ROUNDING: None, F_STAMP: None, "unclear": {}}
    if summary_image:
        note.info("⏳ جارٍ تحميل النموذج وقراءة صفحة الخلاصة…")
        try:
            summary = cached_extract("summary", summary_image, settings,
                                     progress_for("صفحة الخلاصة", 1))
            summary_vals = rv.summary_values(summary)
        except ex.ExtractionError as e:
            errors.append(f"صفحة الخلاصة: {e}")
        done += 1
        bar.progress(done / total_steps)

    sheets = []
    for i, (label, image) in enumerate(sheet_images, start=1):
        note.info(f"⏳ جارٍ قراءة الكشف {i} من {len(sheet_images)}…")
        try:
            sheet = cached_extract("sheet", image, settings, progress_for(f"الكشف {i}", done + 1))
            df = rv.sheet_to_frame(sheet, fallback_number=i, default_year=ss.year)
        except ex.ExtractionError as e:
            errors.append(f"{label}: {e}")
            df = rv.empty_frame()
        sheets.append({"label": label, "image": image, "df": df})
        done += 1
        bar.progress(done / total_steps)

    if not sheets:
        sheets = [{"label": "إدخال يدوي", "image": None, "df": rv.empty_frame()}]
    ss["extraction_errors"] = errors
    inbox.clear(INBOX_DIR)          # the photos now live in this session
    start_review(sheets, summary_image, summary_vals)


# --- step 2: review + result ------------------------------------------------------------

def editor_config(sheet_number) -> dict:
    cc = st.column_config
    return {
        rv.COL_SHEET: cc.NumberColumn(format="%d", width="small", default=sheet_number),
        rv.COL_SERIAL: cc.NumberColumn(format="%d", step=1),
        rv.COL_REPEAT: cc.CheckboxColumn(help="تسلسل مكرر (م)", default=False, width="small"),
        rv.COL_AMOUNT: cc.NumberColumn(format="localized", min_value=0),
        rv.COL_DATE: cc.DateColumn(format="DD/MM/YYYY"),
        rv.COL_UNCLEAR: cc.CheckboxColumn(
            help="أزل العلامة بعد التأكد من الرقم وتصحيحه", default=False, width="small"),
        rv.COL_HINT: cc.TextColumn(width="large"),
    }


def page_review() -> None:
    if not ss.sheets:
        st.info("لا توجد بيانات بعد. ابدأ من خطوة الإدخال.")
        return
    for message in ss.pop("extraction_errors", []):
        st.error(message)

    st.caption(f"الاسم: {ss.get('name') or '—'}")
    st.markdown("راجع الأرقام مقابل الصورة وصحّح ما يلزم، ثم اضغط **إعادة الحساب**.")
    v = ss.version
    vals = ss.summary_vals

    with st.form("review_form"):
        st.subheader("صفحة الخلاصة")
        left, right = st.columns([1, 1])
        if ss.summary_image:
            left.image(ss.summary_image, width="stretch")
        else:
            left.caption("لا توجد صورة لصفحة الخلاصة — أدخل الأرقام يدوياً.")
        with right:
            total_txt = st.text_input("الرقم 1 — المجموع", fmt_input(vals[F_TOTAL]), key=f"s_total_{v}")
            tax_txt = st.text_input("الرقم 2 — الضريبة", fmt_input(vals[F_TAX]), key=f"s_tax_{v}")
            rounding_txt = st.text_input(
                "الرقم 3 — فرق التقريب (اتركه فارغاً إذا لم يُكتب كرقم منفصل)",
                fmt_input(vals[F_ROUNDING]), key=f"s_round_{v}")
            stamp_txt = st.text_input("الطابع", fmt_input(vals[F_STAMP]), key=f"s_stamp_{v}")
            still_unclear = {}
            for key, hint in vals["unclear"].items():
                if st.checkbox(f"غير واضح — {FIELD_LABELS[key]}: {hint}", value=True,
                               key=f"s_unclear_{key}_{v}",
                               help="أزل العلامة بعد التأكد من الرقم"):
                    still_unclear[key] = hint

        edited = []
        for i, sheet in enumerate(ss.sheets):
            st.subheader(sheet["label"])
            df = sheet["df"]
            number = df[rv.COL_SHEET].dropna().iloc[0] if df[rv.COL_SHEET].notna().any() else i + 1
            if sheet["image"]:
                left, right = st.columns([1, 1.3])
                left.image(sheet["image"], width="stretch")
            else:
                right = st.container()
            with right:
                edited.append(st.data_editor(
                    df, key=f"editor_{v}_{i}", num_rows="dynamic", hide_index=True,
                    width="stretch", column_config=editor_config(int(number)),
                    column_order=rv.COLUMNS[::-1],   # first column on the right, as in Arabic

                    height=min(38 * (len(df) + 3), 700),
                ))
                unclear_count = int(df[rv.COL_UNCLEAR].sum())
                if unclear_count:
                    st.caption(f"⚠️ {unclear_count} سطر فيه قراءة غير واضحة — راجعها أولاً.")

        submitted = st.form_submit_button("🔄 إعادة الحساب", type="primary",
                                          width="stretch")

    if submitted:
        bad = [label for label, txt in (("الرقم 1", total_txt), ("الرقم 2", tax_txt),
                                        ("الرقم 3", rounding_txt), ("الطابع", stamp_txt))
               if txt.strip() and parse_amount(txt) is None]
        if bad:
            st.error("أرقام غير صالحة في صفحة الخلاصة: " + "، ".join(bad))
            return
        # Commit the edits and give the widgets fresh keys so nothing is applied twice.
        for sheet, df in zip(ss.sheets, edited):
            sheet["df"] = rv.rows_to_frame(rv.frame_to_rows(df))
        ss.summary_vals = {
            F_TOTAL: parse_amount(total_txt), F_TAX: parse_amount(tax_txt),
            F_ROUNDING: parse_amount(rounding_txt), F_STAMP: parse_amount(stamp_txt),
            "unclear": still_unclear,
        }
        ss.version += 1
        ss.saved_id = None
        ss.result = compute_result()
        st.rerun()

    if ss.result is not None:
        st.divider()
        render_result(ss.result)
        render_form_and_save(ss.result)


def compute_result() -> Result:
    vals = ss.summary_vals
    rows = rv.frame_to_rows(rv.combine([s["df"] for s in ss.sheets]))
    summary = rv.make_summary(vals[F_TOTAL], vals[F_TAX], vals[F_ROUNDING], vals[F_STAMP],
                              vals["unclear"])
    return verify(rows, summary, None, None,
                  verification_settings(cfg))


def render_result(r: Result) -> None:
    st.subheader("النتيجة")
    st.markdown('<div class="muted">المجموع النهائي</div>'
                f'<div class="big-total">{fmt_money(r.computed_total)}</div>',
                unsafe_allow_html=True)
    if r.ok:
        st.success("✅ كل شيء مطابق")
    else:
        st.warning("⚠️ توجد فروقات أو أرقام مشكوك فيها")

    cols = st.columns(len(r.numbers))
    for col, (label, value) in zip(cols, r.numbers):
        col.metric(label, fmt_money(value))

    for w in r.warnings:
        st.warning(w)
    for n in r.notes:
        st.info(n)
    if r.unclear:
        st.markdown("**أرقام غير واضحة**")
        st.markdown("\n".join(f"- {u}" for u in r.unclear))

    with st.expander("تفاصيل الحساب", expanded=not r.ok):
        d1, d2, d3 = st.columns(3)
        d1.metric("الرقم 1 المكتوب", fmt_money(r.written_total))
        d2.metric("الضريبة الدقيقة (5%)", fmt_money(r.exact_tax))
        d3.metric("فرق التقريب المرجعي", fmt_money(r.reference_rounding))
        d4, d5, d6 = st.columns(3)
        serial_range = f"{r.first_serial} – {r.last_serial}" if r.first_serial else "—"
        d4.metric("التسلسل", serial_range,
                  help=(f"آخر تسلسل في الدفعة السابقة يُعتبر {r.previous_last_serial} "
                        "(أصغر تسلسل هنا ناقص 1)") if r.previous_last_serial is not None else None)
        d5.metric("عدد التسلسلات / المتوقع",
                  f"{r.serial_count} / {r.expected_count if r.expected_count is not None else '—'}")
        d6.metric("الأشهر", "، ".join(month_label(m) for m in r.months) or "—",
                  help=(f"الربع المدقق: الربع {r.quarter[1]} لسنة {r.quarter[0]} "
                        "(حسب أغلب التواريخ)") if r.quarter else None)
        if r.tax_owed:
            st.error(f"المبلغ المستحق من الضريبة: {fmt_money(r.tax_owed)}")


def template_bytes(uploaded) -> bytes:
    if uploaded is not None:
        return uploaded.getvalue()
    path = Path(cfg["form"]["template"])
    path = path if path.is_absolute() else ROOT / path
    if not path.exists():
        form_mod.create_default_template(path)
    return path.read_bytes()


def render_form_and_save(r: Result) -> None:
    st.divider()
    left, right = st.columns(2)

    with left:
        st.subheader("تعبئة النموذج")
        uploaded = st.file_uploader("ملف نموذج آخر (اختياري، xlsx)", type=["xlsx"],
                                    key="template_file")
        name = ss.get("name") or ""
        try:
            data = form_mod.fill_form(
                template_bytes(uploaded), cfg["form"]["cells"],
                form_mod.build_values(name, ss.form_date, r), cfg["form"].get("sheet"),
            )
            st.download_button(
                "⬇️ تحميل النموذج المعبأ", data,
                file_name=f"نموذج_{name or 'بدون_اسم'}_{ss.form_date:%Y-%m-%d}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
        except Exception as e:  # bad template or cell map: show it, keep the page alive
            st.error(f"تعذّرت تعبئة النموذج: {e}")

    with right:
        st.subheader("الحفظ في التجميع")
        if r.main_month:
            year, month = r.main_month                 # the month most of the dates fall in
            st.markdown(f"تُحفظ على شهر **{month}/{year}** (الربع {quarter_of(month)}) حسب التواريخ.")
            if len(r.months) > 1:
                st.caption("تنبيه: تواريخ هذه الدفعة تقع في أكثر من شهر؛ ستُحسب كلها على هذا الشهر.")
        else:
            year = date.today().year
            month = st.selectbox("لا توجد تواريخ مقروءة — اختر شهر هذه الدفعة",
                                 list(range(1, 13)), index=date.today().month - 1,
                                 format_func=lambda m: f"{m}/{year}")
        if not r.ok:
            st.caption("توجد ملاحظات على هذه الدفعة — يمكن حفظها كما هي أو تصحيحها أولاً.")
        if ss.saved_id:
            st.success("تم حفظ هذه الدفعة في التجميع.")
            if st.button("➕ بدء دفعة جديدة", width="stretch"):
                reset_batch()
                st.rerun()
        elif st.button("💾 حفظ في التجميع", width="stretch"):
            batch = agg.batch_from_result(ss.get("name") or "بدون اسم", int(year), int(month), r)
            agg.save_batch(batch, BATCH_DIR)
            ss.saved_id = batch["id"]
            st.rerun()


# --- step 3: aggregation -------------------------------------------------------------------

def page_aggregation() -> None:
    st.subheader("التجميع الشهري والربعي")
    batches = agg.load_batches(BATCH_DIR)
    c1, c2 = st.columns(2)
    # Which quarter to show: the one of the batch just checked, else the current one.
    shown = ss.result.quarter if ss.get("result") is not None and ss.result.quarter else (
        date.today().year, quarter_of(date.today().month))
    year = c1.number_input("السنة", min_value=2000, max_value=2100, step=1,
                           value=int(shown[0]), key="agg_year")
    quarter = c2.selectbox("الربع", [1, 2, 3, 4], index=int(shown[1]) - 1, key="agg_quarter",
                           format_func=lambda q: f"الربع {q} (الأشهر {quarter_months(q)[0]}–"
                                                 f"{quarter_months(q)[2]})")

    table = agg.monthly_table(batches, int(year), int(quarter))
    money = {label: st.column_config.NumberColumn(format="localized")
             for label in agg.NUMBER_LABELS.values()}
    st.dataframe(table, hide_index=True, width="stretch", column_config=money)

    st.download_button(
        "⬇️ تصدير الجدول إلى Excel", agg.export_excel(batches, int(year), int(quarter)),
        file_name=f"تجميع_الربع{quarter}_{year}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    months = quarter_months(int(quarter))
    mine = [b for b in batches if b["year"] == int(year) and b["month"] in months]
    st.subheader("الدفعات المحفوظة في هذا الربع")
    if not mine:
        st.caption("لا توجد دفعات محفوظة لهذا الربع.")
        return
    details = agg.batches_table(batches, int(year), int(quarter))
    st.dataframe(details, hide_index=True, width="stretch", column_config=money)

    with st.expander("حذف دفعة"):
        choice = st.selectbox(
            "الدفعة", mine,
            format_func=lambda b: f"{b['name']} — {b['month']}/{b['year']} — "
                                  f"{fmt_money(parse_amount(b['total']))} — {b['saved_at']}",
        )
        sure = st.checkbox("أؤكد الحذف النهائي لهذه الدفعة")
        if st.button("🗑️ حذف", disabled=not sure):
            agg.delete_batch(choice["id"], BATCH_DIR)
            st.rerun()


# --- main -------------------------------------------------------------------------------------

init_state()
if st.query_params.get("phone"):
    page_phone()
    st.stop()
settings = sidebar()
st.title("🧾 تدقيق الكشوف")
step = st.radio("الخطوة", [STEP_INPUT, STEP_REVIEW, STEP_AGG], horizontal=True,
                key="nav", label_visibility="collapsed")
st.divider()
if step == STEP_INPUT:
    page_input(settings)
elif step == STEP_REVIEW:
    page_review()
else:
    page_aggregation()
