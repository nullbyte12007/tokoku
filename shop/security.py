"""CSRF, header keamanan, throttle login, captcha, dan decorator pembatas akses."""

import hashlib
import hmac
import secrets
import time
from functools import wraps
from urllib.parse import urlparse

from flask import abort, current_app, flash, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import db

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# Throttle login: {(ip, email): (jumlah_gagal, waktu_gagal_terakhir)}
_LOGIN_FAILURES = {}
_LOGIN_MAX_FAILURES = 8
_LOGIN_WINDOW_SECONDS = 300
_LOGIN_FAILURES_MAX_KEYS = 10_000

# Hash dummy: dipakai saat email tidak ditemukan supaya waktu respons tetap sama,
# sehingga penyerang tidak bisa menebak email mana yang terdaftar lewat timing.
_DUMMY_PASSWORD_HASH = generate_password_hash("tokoku-dummy-password")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}

# Tanpa 'unsafe-inline': tidak ada JS/CSS inline di template, jadi CSP bisa ketat.
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "object-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' https: http: data:",
        "connect-src 'self'",
    )
)



def generate_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = None
    if user_id is not None:
        g.user = db.query(
            "SELECT id, email, name, role, created_at FROM users WHERE id = ?",
            (user_id,),
            one=True,
        )
        if g.user is None:  # user dihapus tapi sesi masih hidup
            session.clear()


def protect_csrf():
    if request.method in SAFE_METHODS:
        return None
    expected = session.get("_csrf_token")
    sent = request.form.get("_csrf_token") or request.headers.get("X-CSRF-Token", "")
    if not expected or not sent or not hmac.compare_digest(expected, sent):
        abort(400, "CSRF token tidak valid atau kedaluwarsa.")
    return None


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            flash("Silakan masuk dulu untuk melanjutkan.", "info")
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(**kwargs)

    return wrapped_view


def admin_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            flash("Silakan masuk dulu untuk melanjutkan.", "info")
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        if g.user["role"] != "admin":
            abort(403)
        return view(**kwargs)

    return wrapped_view


def safe_redirect_target(target):
    """Terima hanya path internal, cegah open redirect."""
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return None
    if not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return None
    return target


def add_security_headers(response):
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    if current_app.config.get("SESSION_COOKIE_SECURE"):
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


def verify_dummy_password(password):
    """Bakar waktu hashing yang setara supaya respons login tidak bocor via timing."""
    check_password_hash(_DUMMY_PASSWORD_HASH, password)


def _prune_failures(now):
    """Batasi memori: buang entri kedaluwarsa, lalu yang paling lama kalau masih penuh."""
    if len(_LOGIN_FAILURES) < _LOGIN_FAILURES_MAX_KEYS:
        return
    for key, (_, last) in list(_LOGIN_FAILURES.items()):
        if now - last > _LOGIN_WINDOW_SECONDS:
            _LOGIN_FAILURES.pop(key, None)
    while len(_LOGIN_FAILURES) >= _LOGIN_FAILURES_MAX_KEYS and len(_LOGIN_FAILURES) > 1:
        oldest = sorted(_LOGIN_FAILURES, key=lambda k: _LOGIN_FAILURES[k][1])
        for key in oldest[: len(oldest) // 2]:
            _LOGIN_FAILURES.pop(key, None)


def check_login_throttle(ip, email):
    """True kalau percobaan login masih diizinkan."""
    now = time.monotonic()
    _prune_failures(now)
    key = (ip, email.lower())
    count, last = _LOGIN_FAILURES.get(key, (0, 0.0))
    if now - last > _LOGIN_WINDOW_SECONDS:
        _LOGIN_FAILURES.pop(key, None)
        return True
    return count < _LOGIN_MAX_FAILURES


def note_login_failure(ip, email):
    key = (ip, email.lower())
    count, _ = _LOGIN_FAILURES.get(key, (0, 0.0))
    _LOGIN_FAILURES[key] = (count + 1, time.monotonic())


def clear_login_failures(ip, email):
    _LOGIN_FAILURES.pop((ip, email.lower()), None)


# Throttle registrasi: batasi jumlah percobaan per IP supaya tidak bisa
# dipakai spam akun / enumerasi massal.
_REGISTER_HITS = {}
_REGISTER_MAX_PER_WINDOW = 5
_REGISTER_WINDOW_SECONDS = 3600
_REGISTER_MAX_KEYS = 10_000


def check_register_throttle(ip):
    """True kalau IP ini masih boleh mencoba registrasi."""
    now = time.monotonic()
    hits = [t for t in _REGISTER_HITS.get(ip, ()) if now - t < _REGISTER_WINDOW_SECONDS]
    if hits:
        _REGISTER_HITS[ip] = hits
    else:
        _REGISTER_HITS.pop(ip, None)

    if len(_REGISTER_HITS) >= _REGISTER_MAX_KEYS:
        for key, stamps in list(_REGISTER_HITS.items()):
            if not stamps or now - max(stamps) > _REGISTER_WINDOW_SECONDS:
                _REGISTER_HITS.pop(key, None)
        while len(_REGISTER_HITS) >= _REGISTER_MAX_KEYS:
            _REGISTER_HITS.pop(next(iter(_REGISTER_HITS)))

    return len(hits) < _REGISTER_MAX_PER_WINDOW


def note_register_attempt(ip):
    _REGISTER_HITS.setdefault(ip, []).append(time.monotonic())


# ---------- Captcha sederhana (tanpa layanan pihak ketiga) ----------
# Tantangan aritmatika kecil yang disimpan di session:
#   - sekali pakai (langsung dihapus saat diverifikasi)
#   - ada batas waktu minimum (anti submit instan) dan maksimum
#   - ditambah honeypot: field tersembunyi yang HARUS kosong
CAPTCHA_SESSION_KEY = "_captcha"
CAPTCHA_MIN_SECONDS = 2
CAPTCHA_MAX_SECONDS = 1800


def generate_captcha():
    """Bikin soal baru, simpan jawabannya di session, kembalikan teks soalnya."""
    left = secrets.randbelow(8) + 2   # 2..9
    right = secrets.randbelow(8) + 2  # 2..9
    session[CAPTCHA_SESSION_KEY] = {"answer": str(left + right), "issued": time.time()}
    return f"{left} + {right}"


def verify_captcha(answer, honeypot=""):
    """(ok, pesan_error). Tantangan selalu dihabiskan (sekali pakai)."""
    data = session.pop(CAPTCHA_SESSION_KEY, None)

    if (honeypot or "").strip():
        return False, "Formulir tidak valid."
    if not data:
        return False, "Captcha sudah kedaluwarsa. Coba lagi."
    elapsed = time.time() - float(data.get("issued", 0))
    if elapsed < CAPTCHA_MIN_SECONDS:
        return False, "Terkirim terlalu cepat. Coba kirim ulang."
    if elapsed > CAPTCHA_MAX_SECONDS:
        return False, "Captcha sudah kedaluwarsa. Coba lagi."
    if str(answer or "").strip() != data.get("answer"):
        return False, "Jawaban captcha salah. Coba lagi."
    return True, None


# ---------- Token reset password ----------
RESET_TTL_MINUTES = 60


def new_reset_token():
    """Token mentah (dikirim ke user lewat tautan) — tidak disimpan di DB."""
    return secrets.token_urlsafe(32)


def hash_reset_token(token):
    """Yang disimpan di DB hanya hash-nya, jadi bocoran DB tidak langsung bisa dipakai."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _mark_secure_context():
    """Kalau request masuk lewat HTTPS, aktifkan cookie Secure + HSTS otomatis.

    Di staging HTTP (localhost) cookie tetap jalan; begitu dipasang di belakang
    TLS, cookie otomatis dikirim hanya lewat HTTPS tanpa perlu ubah config.
    """
    if request.is_secure:
        current_app.config["SESSION_COOKIE_SECURE"] = True


def init_app(app):
    app.before_request(_mark_secure_context)
    app.before_request(load_logged_in_user)
    app.before_request(protect_csrf)
    app.after_request(add_security_headers)
