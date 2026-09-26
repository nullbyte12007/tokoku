"""Panel admin: statistik, CRUD produk, kelola pesanan, kelola user."""

import re
import sqlite3
import unicodedata

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from . import db, security
from .formatting import parse_price
from .order_status import ADMIN_TRANSITIONS, REVENUE_STATUSES, STATUS_LABELS, label

bp = Blueprint("admin", __name__, url_prefix="/admin")


def slugify(text):
    ascii_text = (
        unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    )
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return slug or "produk"


def unique_slug(base, exclude_id=None):
    slug = base
    counter = 2
    while True:
        if exclude_id is None:
            row = db.query("SELECT 1 FROM products WHERE slug = ?", (slug,), one=True)
        else:
            row = db.query(
                "SELECT 1 FROM products WHERE slug = ? AND id != ?",
                (slug, exclude_id),
                one=True,
            )
        if row is None:
            return slug
        slug = f"{base}-{counter}"
        counter += 1


@bp.get("/")
@security.admin_required
def dashboard():
    placeholders = ",".join("?" for _ in REVENUE_STATUSES)
    stats = {
        "products": db.scalar("SELECT COUNT(*) FROM products WHERE is_active = 1", default=0),
        "inactive": db.scalar("SELECT COUNT(*) FROM products WHERE is_active = 0", default=0),
        "users": db.scalar("SELECT COUNT(*) FROM users", default=0),
        "orders": db.scalar("SELECT COUNT(*) FROM orders", default=0),
        "pending": db.scalar("SELECT COUNT(*) FROM orders WHERE status = 'pending'", default=0),
        "revenue": db.scalar(
            f"SELECT COALESCE(SUM(total), 0) FROM orders WHERE status IN ({placeholders})",
            REVENUE_STATUSES,
            default=0,
        ),
    }
    low_stock = db.query(
        "SELECT id, name, stock FROM products WHERE is_active = 1 AND stock <= 5"
        " ORDER BY stock, name LIMIT 8"
    )
    recent_orders = db.query(
        "SELECT o.*, u.name AS customer_name FROM orders o JOIN users u ON u.id = o.user_id"
        " ORDER BY o.id DESC LIMIT 8"
    )
    return render_template(
        "admin/dashboard.html",
        stats=stats,
        low_stock=low_stock,
        recent_orders=recent_orders,
        labels=STATUS_LABELS,
    )


# ---------- Produk ----------


@bp.get("/products")
@security.admin_required
def products():
    q = request.args.get("q", "").strip()
    params = []
    clause = "1 = 1"
    if q:
        clause = "(name LIKE ? ESCAPE '\\' OR category LIKE ? ESCAPE '\\')"
        params = [db.like_pattern(q), db.like_pattern(q)]

    rows = db.query(
        f"SELECT * FROM products WHERE {clause} ORDER BY id DESC", params
    )
    return render_template("admin/products.html", products=rows, q=q)


def _read_product_form():
    raw_price = request.form.get("price", "")
    price = parse_price(raw_price)
    stock_raw = request.form.get("stock", "0").strip()

    values = {
        "name": request.form.get("name", "").strip(),
        "category": request.form.get("category", "").strip() or "Umum",
        "price": raw_price.strip(),
        "stock": stock_raw,
        "description": request.form.get("description", "").strip(),
        "image_url": request.form.get("image_url", "").strip(),
        "is_active": 1 if request.form.get("is_active") else 0,
    }

    errors = []
    if len(values["name"]) < 3:
        errors.append("Nama produk minimal 3 karakter.")
    if price is None or price < 0:
        errors.append("Harga harus berupa angka (contoh: 125000).")
    try:
        stock = int(stock_raw)
    except (TypeError, ValueError):
        stock = None
    if stock is None or stock < 0:
        errors.append("Stok harus berupa angka >= 0.")
    if len(values["image_url"]) > 500:
        errors.append("URL gambar terlalu panjang.")

    parsed = {"price": price, "stock": stock}
    return values, parsed, errors


@bp.route("/products/new", methods=("GET", "POST"))
@security.admin_required
def product_new():
    values = {
        "name": "",
        "category": "",
        "price": "",
        "stock": "0",
        "description": "",
        "image_url": "",
        "is_active": 1,
    }
    if request.method == "POST":
        values, parsed, errors = _read_product_form()
        if errors:
            for error in errors:
                flash(error, "error")
        else:
            db.execute(
                "INSERT INTO products (slug, name, description, category, price, stock,"
                " image_url, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    unique_slug(slugify(values["name"])),
                    values["name"],
                    values["description"],
                    values["category"],
                    parsed["price"],
                    parsed["stock"],
                    values["image_url"],
                    values["is_active"],
                ),
            )
            flash(f"Produk '{values['name']}' ditambahkan.", "success")
            return redirect(url_for("admin.products"))

    return render_template("admin/product_form.html", product=values, mode="new")


@bp.route("/products/<int:product_id>/edit", methods=("GET", "POST"))
@security.admin_required
def product_edit(product_id):
    product = db.query("SELECT * FROM products WHERE id = ?", (product_id,), one=True)
    if product is None:
        abort(404)

    if request.method == "POST":
        values, parsed, errors = _read_product_form()
        if errors:
            for error in errors:
                flash(error, "error")
        else:
            db.execute(
                "UPDATE products SET name = ?, slug = ?, description = ?, category = ?,"
                " price = ?, stock = ?, image_url = ?, is_active = ? WHERE id = ?",
                (
                    values["name"],
                    unique_slug(slugify(values["name"]), exclude_id=product_id),
                    values["description"],
                    values["category"],
                    parsed["price"],
                    parsed["stock"],
                    values["image_url"],
                    values["is_active"],
                    product_id,
                ),
            )
            flash(f"Produk '{values['name']}' diperbarui.", "success")
            return redirect(url_for("admin.products"))

    if request.method == "GET":
        values = dict(product)
        values["is_active"] = int(product["is_active"])

    return render_template("admin/product_form.html", product=values, mode="edit")


@bp.post("/products/<int:product_id>/delete")
@security.admin_required
def product_delete(product_id):
    """Soft delete: produk disembunyikan tapi riwayat pesanan tetap utuh."""
    product = db.query("SELECT * FROM products WHERE id = ?", (product_id,), one=True)
    if product is None:
        abort(404)

    db.execute("UPDATE products SET is_active = 0 WHERE id = ?", (product_id,))
    db.execute("DELETE FROM cart_items WHERE product_id = ?", (product_id,))
    flash(f"Produk '{product['name']}' dinonaktifkan.", "info")
    return redirect(url_for("admin.products"))


# ---------- Pesanan ----------


@bp.get("/orders")
@security.admin_required
def orders():
    status = request.args.get("status", "").strip()
    params = []
    clause = "1 = 1"
    if status in STATUS_LABELS:
        clause = "o.status = ?"
        params = [status]

    rows = db.query(
        f"SELECT o.*, u.name AS customer_name, u.email AS customer_email,"
        "       (SELECT COALESCE(SUM(qty), 0) FROM order_items WHERE order_id = o.id) AS total_qty"
        f"  FROM orders o JOIN users u ON u.id = o.user_id WHERE {clause}"
        " ORDER BY o.id DESC",
        params,
    )
    return render_template(
        "admin/orders.html",
        orders=rows,
        status=status,
        labels=STATUS_LABELS,
        transitions=ADMIN_TRANSITIONS,
    )


@bp.post("/orders/<int:order_id>/status")
@security.admin_required
def order_update_status(order_id):
    order = db.query("SELECT * FROM orders WHERE id = ?", (order_id,), one=True)
    if order is None:
        abort(404)

    new_status = request.form.get("status", "").strip()
    allowed = ADMIN_TRANSITIONS.get(order["status"], ())
    if new_status not in allowed:
        flash("Perubahan status itu tidak diizinkan.", "error")
        return redirect(url_for("admin.orders"))

    with db.transaction() as conn:
        conn.execute(
            "UPDATE orders SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (new_status, order_id),
        )
        if new_status == "cancelled":
            for item in conn.execute(
                "SELECT product_id, qty FROM order_items WHERE order_id = ?", (order_id,)
            ).fetchall():
                if item["product_id"] is not None:
                    conn.execute(
                        "UPDATE products SET stock = stock + ? WHERE id = ?",
                        (item["qty"], item["product_id"]),
                    )

    flash(f"Pesanan #{order_id} → {label(new_status)}.", "success")
    target = security.safe_redirect_target(request.form.get("next")) or url_for("admin.orders")
    return redirect(target)


@bp.get("/orders/<int:order_id>")
@security.admin_required
def order_detail(order_id):
    order = db.query(
        "SELECT o.*, u.name AS customer_name, u.email AS customer_email"
        "  FROM orders o JOIN users u ON u.id = o.user_id WHERE o.id = ?",
        (order_id,),
        one=True,
    )
    if order is None:
        abort(404)
    items = db.query(
        "SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (order_id,)
    )
    return render_template(
        "admin/order_detail.html",
        order=order,
        items=items,
        labels=STATUS_LABELS,
        transitions=ADMIN_TRANSITIONS.get(order["status"], ()),
    )


# ---------- User ----------


@bp.get("/users")
@security.admin_required
def users():
    rows = db.query(
        "SELECT u.id, u.name, u.email, u.role, u.created_at,"
        "       (SELECT COUNT(*) FROM orders WHERE user_id = u.id) AS total_orders,"
        "       (SELECT COALESCE(SUM(total), 0) FROM orders WHERE user_id = u.id AND status != 'cancelled') AS total_spent"
        "  FROM users u ORDER BY u.id"
    )
    return render_template("admin/users.html", users=rows)


@bp.post("/users/<int:user_id>/role")
@security.admin_required
def user_update_role(user_id):
    if user_id == g.user["id"]:
        flash("Lu tidak bisa mengubah peran akun sendiri.", "error")
        return redirect(url_for("admin.users"))

    new_role = request.form.get("role", "").strip()
    if new_role not in ("customer", "admin"):
        flash("Peran tidak dikenal.", "error")
        return redirect(url_for("admin.users"))

    target = db.query("SELECT name, role FROM users WHERE id = ?", (user_id,), one=True)
    if target is None:
        abort(404)

    # Jangan sampai admin terakhir diturunkan -> sistem bisa terkunci
    if target["role"] == "admin" and new_role != "admin":
        remaining = db.scalar(
            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND id != ?", (user_id,), default=0
        )
        if remaining == 0:
            flash("Ini admin terakhir. Buat admin lain dulu sebelum menurunkan yang ini.", "error")
            return redirect(url_for("admin.users"))

    try:
        db.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
    except sqlite3.IntegrityError:
        flash("Peran tidak valid.", "error")
    else:
        flash(f"Peran {target['name']} diubah jadi {new_role}.", "success")
    return redirect(url_for("admin.users"))
