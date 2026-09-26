"""Keranjang belanja (per user, tersimpan di DB)."""

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from . import db, security

bp = Blueprint("cart", __name__, url_prefix="/cart")

MAX_QTY_PER_ITEM = 99


def cart_items(user_id):
    return db.query(
        "SELECT c.id AS cart_id, c.qty, p.id AS product_id, p.name, p.price,"
        "       p.stock, p.category, p.is_active,"
        "       (p.price * c.qty) AS subtotal"
        "  FROM cart_items c JOIN products p ON p.id = c.product_id"
        " WHERE c.user_id = ? ORDER BY c.id",
        (user_id,),
    )


def _clamp_qty(qty, stock):
    return max(1, min(qty, stock, MAX_QTY_PER_ITEM))


@bp.get("/")
@security.login_required
def view():
    items = cart_items(g.user["id"])
    total = sum(row["subtotal"] for row in items)
    problems = [
        row for row in items if not row["is_active"] or row["qty"] > row["stock"]
    ]
    return render_template("cart.html", items=items, total=total, problems=problems)


@bp.post("/add")
@security.login_required
def add():
    product_id = request.form.get("product_id", type=int)
    qty = max(1, request.form.get("qty", 1, type=int) or 1)
    target = security.safe_redirect_target(request.form.get("next")) or url_for("cart.view")

    product = db.query(
        "SELECT id, name, stock FROM products WHERE id = ? AND is_active = 1",
        (product_id,),
        one=True,
    )
    if product is None:
        flash("Produk tidak ditemukan.", "error")
        return redirect(url_for("catalog.index"))
    if product["stock"] < 1:
        flash(f"Stok {product['name']} sedang habis.", "error")
        return redirect(url_for("catalog.product_detail", product_id=product_id))

    with db.transaction() as conn:
        existing = conn.execute(
            "SELECT id, qty FROM cart_items WHERE user_id = ? AND product_id = ?",
            (g.user["id"], product_id),
        ).fetchone()

        if existing is None:
            new_qty = _clamp_qty(qty, product["stock"])
            conn.execute(
                "INSERT INTO cart_items (user_id, product_id, qty) VALUES (?, ?, ?)",
                (g.user["id"], product_id, new_qty),
            )
        else:
            new_qty = _clamp_qty(existing["qty"] + qty, product["stock"])
            conn.execute(
                "UPDATE cart_items SET qty = ? WHERE id = ?", (new_qty, existing["id"])
            )

    flash(f"{product['name']} ditambahkan ke keranjang ({new_qty} pcs).", "success")
    return redirect(target)


@bp.post("/update")
@security.login_required
def update():
    product_id = request.form.get("product_id", type=int)
    qty = request.form.get("qty", type=int)

    row = db.query(
        "SELECT c.id AS cart_id, p.name, p.stock"
        "  FROM cart_items c JOIN products p ON p.id = c.product_id"
        " WHERE c.user_id = ? AND c.product_id = ?",
        (g.user["id"], product_id),
        one=True,
    )
    if row is None:
        flash("Item tidak ada di keranjang.", "error")
        return redirect(url_for("cart.view"))

    if qty is None or qty < 1:
        db.execute("DELETE FROM cart_items WHERE id = ?", (row["cart_id"],))
        flash(f"{row['name']} dihapus dari keranjang.", "info")
        return redirect(url_for("cart.view"))

    new_qty = _clamp_qty(qty, row["stock"])
    if new_qty != qty:
        flash(f"Jumlah {row['name']} disesuaikan dengan stok ({new_qty} pcs).", "info")
    db.execute("UPDATE cart_items SET qty = ? WHERE id = ?", (new_qty, row["cart_id"]))
    return redirect(url_for("cart.view"))


@bp.post("/remove")
@security.login_required
def remove():
    product_id = request.form.get("product_id", type=int)
    db.execute(
        "DELETE FROM cart_items WHERE user_id = ? AND product_id = ?",
        (g.user["id"], product_id),
    )
    flash("Item dihapus dari keranjang.", "info")
    return redirect(url_for("cart.view"))


@bp.post("/clear")
@security.login_required
def clear():
    db.execute("DELETE FROM cart_items WHERE user_id = ?", (g.user["id"],))
    flash("Keranjang dikosongkan.", "info")
    return redirect(url_for("cart.view"))
