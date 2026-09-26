"""Checkout dan riwayat pesanan milik user yang login."""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from . import db, security
from .order_status import CUSTOMER_CANCELLABLE, STATUS_LABELS, label

bp = Blueprint("orders", __name__)


class CheckoutError(Exception):
    """Validasi gagal di tengah transaksi; transaksi akan di-rollback."""

    def __init__(self, messages):
        super().__init__("; ".join(messages))
        self.messages = messages


def _load_cart_rows(conn, user_id):
    return conn.execute(
        "SELECT c.product_id, c.qty, p.name, p.price, p.stock, p.is_active"
        "  FROM cart_items c JOIN products p ON p.id = c.product_id"
        " WHERE c.user_id = ? ORDER BY c.id",
        (user_id,),
    ).fetchall()


def _restore_stock(conn, order_id):
    for item in conn.execute(
        "SELECT product_id, qty FROM order_items WHERE order_id = ?", (order_id,)
    ).fetchall():
        if item["product_id"] is not None:
            conn.execute(
                "UPDATE products SET stock = stock + ? WHERE id = ?",
                (item["qty"], item["product_id"]),
            )


def _validate_shipping(name, phone, address):
    errors = []
    if len(name) < 2:
        errors.append("Nama penerima minimal 2 karakter.")
    if len(phone) < 8:
        errors.append("Nomor telepon minimal 8 karakter.")
    if len(address) < 10:
        errors.append("Alamat minimal 10 karakter.")
    return errors


def _order_or_404(order_id, user_id=None):
    sql = "SELECT * FROM orders WHERE id = ?"
    params = [order_id]
    if user_id is not None:
        sql += " AND user_id = ?"
        params.append(user_id)
    order = db.query(sql, params, one=True)
    if order is None:
        abort(404)
    return order


@bp.route("/checkout", methods=("GET", "POST"))
@security.login_required
def checkout():
    items = db.query(
        "SELECT c.qty, p.id AS product_id, p.name, p.price, p.stock, p.is_active,"
        "       (p.price * c.qty) AS subtotal"
        "  FROM cart_items c JOIN products p ON p.id = c.product_id"
        " WHERE c.user_id = ? ORDER BY c.id",
        (g.user["id"],),
    )
    if not items:
        flash("Keranjang masih kosong.", "info")
        return redirect(url_for("cart.view"))

    values = {
        "shipping_name": g.user["name"],
        "shipping_phone": "",
        "shipping_address": "",
        "note": "",
    }

    if request.method == "POST":
        values = {
            "shipping_name": request.form.get("shipping_name", "").strip(),
            "shipping_phone": request.form.get("shipping_phone", "").strip(),
            "shipping_address": request.form.get("shipping_address", "").strip(),
            "note": request.form.get("note", "").strip()[:500],
        }
        errors = _validate_shipping(
            values["shipping_name"], values["shipping_phone"], values["shipping_address"]
        )
        if errors:
            for error in errors:
                flash(error, "error")
        else:
            order_id = None
            try:
                with db.transaction() as conn:
                    rows = _load_cart_rows(conn, g.user["id"])
                    problems = []
                    if not rows:
                        problems.append("Keranjang kosong.")
                    for row in rows:
                        if not row["is_active"]:
                            problems.append(f"{row['name']} sudah tidak dijual.")
                        elif row["qty"] > row["stock"]:
                            problems.append(
                                f"Stok {row['name']} tinggal {row['stock']} pcs."
                            )
                    if problems:
                        raise CheckoutError(problems)

                    total = sum(row["price"] * row["qty"] for row in rows)
                    order_id = conn.execute(
                        "INSERT INTO orders (user_id, status, total, shipping_name,"
                        " shipping_phone, shipping_address, note)"
                        " VALUES (?, 'pending', ?, ?, ?, ?, ?)",
                        (
                            g.user["id"],
                            total,
                            values["shipping_name"],
                            values["shipping_phone"],
                            values["shipping_address"],
                            values["note"],
                        ),
                    ).lastrowid

                    for row in rows:
                        conn.execute(
                            "INSERT INTO order_items (order_id, product_id, name, unit_price, qty)"
                            " VALUES (?, ?, ?, ?, ?)",
                            (
                                order_id,
                                row["product_id"],
                                row["name"],
                                row["price"],
                                row["qty"],
                            ),
                        )
                        # UPDATE bersyarat: kalau stok berubah di detik yang sama,
                        # rowcount 0 dan transaksi dibatalkan.
                        cur = conn.execute(
                            "UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
                            (row["qty"], row["product_id"], row["qty"]),
                        )
                        if cur.rowcount != 1:
                            raise CheckoutError(
                                [f"Stok {row['name']} baru saja berubah. Coba lagi."]
                            )

                    conn.execute("DELETE FROM cart_items WHERE user_id = ?", (g.user["id"],))
            except CheckoutError as exc:
                for message in exc.messages:
                    flash(message, "error")
                return redirect(url_for("cart.view"))

            flash("Pesanan berhasil dibuat. Lanjutkan pembayaran ya.", "success")
            return redirect(url_for("orders.detail", order_id=order_id))

    total = sum(row["subtotal"] for row in items)
    return render_template("checkout.html", items=items, total=total, values=values)


@bp.get("/orders")
@security.login_required
def index():
    orders = db.query(
        "SELECT o.*, (SELECT COALESCE(SUM(qty), 0) FROM order_items WHERE order_id = o.id)"
        "       AS total_qty"
        "  FROM orders o WHERE o.user_id = ? ORDER BY o.id DESC",
        (g.user["id"],),
    )
    return render_template("orders.html", orders=orders, labels=STATUS_LABELS)


@bp.get("/orders/<int:order_id>")
@security.login_required
def detail(order_id):
    order = _order_or_404(order_id, user_id=g.user["id"])
    items = db.query(
        "SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (order_id,)
    )
    return render_template(
        "order_detail.html",
        order=order,
        items=items,
        labels=STATUS_LABELS,
        status_label=label(order["status"]),
        cancellable=order["status"] in CUSTOMER_CANCELLABLE,
    )


@bp.post("/orders/<int:order_id>/cancel")
@security.login_required
def cancel(order_id):
    order = _order_or_404(order_id, user_id=g.user["id"])
    if order["status"] not in CUSTOMER_CANCELLABLE:
        flash("Pesanan ini sudah tidak bisa dibatalkan.", "error")
        return redirect(url_for("orders.detail", order_id=order_id))

    with db.transaction() as conn:
        conn.execute(
            "UPDATE orders SET status = 'cancelled', updated_at = datetime('now') WHERE id = ?",
            (order_id,),
        )
        _restore_stock(conn, order_id)

    flash("Pesanan dibatalkan dan stok dikembalikan.", "info")
    return redirect(url_for("orders.detail", order_id=order_id))
