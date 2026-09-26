"""Registrasi, login, logout, dan halaman akun."""

import re
import sqlite3

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, security
from .order_status import STATUS_LABELS

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
MIN_PASSWORD = 8

# Pesan yang sama dipakai baik saat akun baru dibuat maupun saat email sudah
# terdaftar -> tidak membocorkan email mana yang sudah ada (anti-enumeration).
REGISTRATION_ACK = (
    "Pendaftaran diterima. Kalau emailnya belum terdaftar, akunmu sudah dibuat — "
    "silakan masuk dengan email dan password itu."
)


def _validate_registration(name, email, password, password2):
    errors = []
    if len(name) < 2:
        errors.append("Nama minimal 2 karakter.")
    if not EMAIL_RE.match(email or ""):
        errors.append("Format email tidak valid.")
    if len(password or "") < MIN_PASSWORD:
        errors.append(f"Password minimal {MIN_PASSWORD} karakter.")
    if password != password2:
        errors.append("Konfirmasi password tidak sama.")
    return errors


@bp.route("/register", methods=("GET", "POST"))
def register():
    if g.user is not None:
        return redirect(url_for("catalog.index"))

    values = {"name": "", "email": ""}
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        values = {"name": name, "email": email}

        ip = request.remote_addr or "unknown"
        if not security.check_register_throttle(ip):
            current_app.logger.warning("Registrasi diblokir (throttle): ip=%s", ip)
            flash("Terlalu banyak pendaftaran dari jaringan ini. Coba lagi nanti.", "error")
            return render_template("register.html", values=values), 429

        security.note_register_attempt(ip)

        ok, captcha_error = security.verify_captcha(
            request.form.get("captcha", ""), request.form.get("website", "")
        )
        if not ok:
            flash(captcha_error, "error")
            return (
                render_template(
                    "register.html",
                    values=values,
                    captcha_question=security.generate_captcha(),
                ),
                400,
            )

        errors = _validate_registration(name, email, password, password2)
        if not errors:
            try:
                db.execute(
                    "INSERT INTO users (email, name, password_hash, role)"
                    " VALUES (?, ?, ?, 'customer')",
                    (email, name, generate_password_hash(password)),
                )
            except sqlite3.IntegrityError:
                # Email sudah terdaftar. Sengaja TIDAK dibedakan dari sukses,
                # supaya halaman ini tidak bisa dipakai menebak email terdaftar.
                current_app.logger.info("Registrasi ditolak (email sudah ada): %r", email)
                flash(REGISTRATION_ACK, "success")
                return redirect(url_for("auth.login"))

        if errors:
            for error in errors:
                flash(error, "error")
        else:
            flash(REGISTRATION_ACK, "success")
            return redirect(url_for("auth.login"))

    return render_template(
        "register.html", values=values, captcha_question=security.generate_captcha()
    )


@bp.route("/login", methods=("GET", "POST"))
def login():
    if g.user is not None:
        return redirect(url_for("catalog.index"))

    next_url = security.safe_redirect_target(request.args.get("next"))
    email = ""

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        ip = request.remote_addr or "unknown"

        if not security.check_login_throttle(ip, email):
            current_app.logger.warning(
                "Login diblokir sementara (throttle): email=%r ip=%s", email, ip
            )
            flash("Terlalu banyak percobaan gagal. Coba lagi beberapa menit lagi.", "error")
            return render_template("login.html", email=email, next_url=next_url), 429

        user = db.query("SELECT * FROM users WHERE email = ?", (email,), one=True)
        if user is None:
            # tetap hashing supaya waktu respons tidak membocorkan email mana yang terdaftar
            security.verify_dummy_password(password)

        if user is None or not check_password_hash(user["password_hash"], password):
            security.note_login_failure(ip, email)
            current_app.logger.warning("Login gagal: email=%r ip=%s", email, ip)
            flash("Email atau password salah.", "error")
        else:
            security.clear_login_failures(ip, email)
            session.clear()  # cegah session fixation
            session["user_id"] = user["id"]
            session.permanent = True
            security.generate_csrf_token()
            flash(f"Selamat datang kembali, {user['name']}!", "success")
            return redirect(next_url or url_for("catalog.index"))

    return render_template("login.html", email=email, next_url=next_url)


@bp.post("/logout")
def logout():
    session.clear()
    flash("Lu udah keluar. Sampai jumpa!", "info")
    return redirect(url_for("catalog.index"))


@bp.get("/account")
@security.login_required
def account():
    user = db.query("SELECT * FROM users WHERE id = ?", (g.user["id"],), one=True)
    summary = db.query(
        "SELECT COUNT(*) AS total_orders,"
        "       COALESCE(SUM(CASE WHEN status != 'cancelled' THEN total ELSE 0 END), 0) AS total_spent"
        "  FROM orders WHERE user_id = ?",
        (g.user["id"],),
        one=True,
    )
    recent_orders = db.query(
        "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 5",
        (g.user["id"],),
    )
    return render_template(
        "account.html",
        user=user,
        summary=summary,
        recent_orders=recent_orders,
        labels=STATUS_LABELS,
    )


@bp.route("/account/password", methods=("GET", "POST"))
@security.login_required
def change_password():
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        new2 = request.form.get("new_password2", "")

        user = db.query("SELECT * FROM users WHERE id = ?", (g.user["id"],), one=True)

        errors = []
        if user is None or not check_password_hash(user["password_hash"], current):
            errors.append("Password saat ini salah.")
        if len(new) < MIN_PASSWORD:
            errors.append(f"Password baru minimal {MIN_PASSWORD} karakter.")
        if new != new2:
            errors.append("Konfirmasi password baru tidak sama.")
        if new and new == current:
            errors.append("Password baru harus berbeda dari yang sekarang.")

        if errors:
            for error in errors:
                flash(error, "error")
        else:
            db.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(new), g.user["id"]),
            )
            current_app.logger.info("Password diubah untuk user id=%s", g.user["id"])
            flash("Password berhasil diubah. Pakai password baru saat masuk berikutnya.", "success")
            return redirect(url_for("auth.account"))

    return render_template("change_password.html", min_password=MIN_PASSWORD)


def _send_reset_email(to_email, to_name, link):
    """Kirim tautan reset lewat SMTP.

    Kalau SMTP belum dikonfigurasi (env TOKOKU_SMTP_*), tautan hanya ditulis ke
    log supaya alur tetap bisa diuji di staging.
    """
    host = current_app.config.get("SMTP_HOST")
    if not host:
        current_app.logger.warning(
            "SMTP belum dikonfigurasi — tautan reset untuk %s: %s", to_email, link
        )
        return False

    import smtplib
    from email.message import EmailMessage

    message = EmailMessage()
    message["Subject"] = "Reset password Tokoku"
    message["From"] = current_app.config.get("SMTP_FROM") or current_app.config.get("SMTP_USER")
    message["To"] = to_email
    message.set_content(
        f"Halo {to_name},\n\n"
        f"Buka tautan berikut untuk mengatur ulang password (berlaku "
        f"{security.RESET_TTL_MINUTES} menit):\n\n{link}\n\n"
        "Kalau kamu tidak meminta ini, abaikan saja email ini — password tidak berubah.\n"
    )

    with smtplib.SMTP(host, current_app.config.get("SMTP_PORT", 587), timeout=10) as smtp:
        if current_app.config.get("SMTP_TLS", True):
            smtp.starttls()
        user = current_app.config.get("SMTP_USER")
        if user:
            smtp.login(user, current_app.config.get("SMTP_PASSWORD", ""))
        smtp.send_message(message)
    return True


@bp.route("/forgot-password", methods=("GET", "POST"))
def forgot_password():
    if g.user is not None:
        return redirect(url_for("catalog.index"))

    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        ok, captcha_error = security.verify_captcha(
            request.form.get("captcha", ""), request.form.get("website", "")
        )
        if not ok:
            flash(captcha_error, "error")
            return (
                render_template(
                    "forgot_password.html",
                    email=email,
                    captcha_question=security.generate_captcha(),
                ),
                400,
            )

        user = db.query("SELECT id, name, email FROM users WHERE email = ?", (email,), one=True)
        if user is not None:
            token = security.new_reset_token()
            db.execute(
                "INSERT INTO password_resets (user_id, token_hash, expires_at)"
                " VALUES (?, ?, datetime('now', ?))",
                (
                    user["id"],
                    security.hash_reset_token(token),
                    f"+{security.RESET_TTL_MINUTES} minutes",
                ),
            )
            link = url_for("auth.reset_password", token=token, _external=True)
            try:
                _send_reset_email(user["email"], user["name"], link)
            except Exception as exc:  # SMTP mati/salah config jangan bikin 500
                current_app.logger.error("Gagal kirim email reset ke %s: %s", user["email"], exc)

        # Pesan selalu sama, baik email terdaftar maupun tidak (anti-enumeration).
        flash(
            "Kalau email itu terdaftar, kami sudah mengirim tautan reset. "
            "Cek inbox (dan folder spam).",
            "success",
        )
        return redirect(url_for("auth.login"))

    return render_template(
        "forgot_password.html", email=email, captcha_question=security.generate_captcha()
    )


@bp.route("/reset-password/<token>", methods=("GET", "POST"))
def reset_password(token):
    row = db.query(
        "SELECT * FROM password_resets"
        " WHERE token_hash = ? AND used_at IS NULL AND expires_at > datetime('now')",
        (security.hash_reset_token(token),),
        one=True,
    )
    if row is None:
        flash("Tautan reset tidak valid atau sudah kedaluwarsa. Minta tautan baru ya.", "error")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        new = request.form.get("new_password", "")
        new2 = request.form.get("new_password2", "")

        errors = []
        if len(new) < MIN_PASSWORD:
            errors.append(f"Password minimal {MIN_PASSWORD} karakter.")
        if new != new2:
            errors.append("Konfirmasi password tidak sama.")

        if errors:
            for error in errors:
                flash(error, "error")
        else:
            with db.transaction() as conn:
                conn.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (generate_password_hash(new), row["user_id"]),
                )
                # sekali pakai: token ini dan token lain milik user tsb dimatikan
                conn.execute(
                    "UPDATE password_resets SET used_at = datetime('now')"
                    " WHERE user_id = ? AND used_at IS NULL",
                    (row["user_id"],),
                )
            current_app.logger.info("Password direset via token, user id=%s", row["user_id"])
            flash("Password berhasil diatur ulang. Silakan masuk dengan password baru.", "success")
            return redirect(url_for("auth.login"))

    return render_template("reset_password.html", token=token)
