"""Katalog publik: daftar produk, pencarian, filter kategori, detail produk."""

from flask import Blueprint, abort, current_app, render_template, request

from . import db

bp = Blueprint("catalog", __name__)


@bp.get("/")
def index():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    page = request.args.get("page", 1, type=int)
    page = max(page or 1, 1)
    per_page = current_app.config["PRODUCTS_PER_PAGE"]

    # `where` hanya berisi literal tetap; nilai user selalu lewat placeholder (?).
    where = ["is_active = 1"]
    params = []
    if q:
        where.append("(name LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')")
        params.extend([db.like_pattern(q), db.like_pattern(q)])
    if category:
        where.append("category = ?")
        params.append(category)
    clause = " AND ".join(where)

    total = db.scalar(
        f"SELECT COUNT(*) FROM products WHERE {clause}", params, default=0
    )
    pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, pages)

    products = db.query(
        f"SELECT * FROM products WHERE {clause}"
        " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        [*params, per_page, (page - 1) * per_page],
    )
    categories = db.query(
        "SELECT category, COUNT(*) AS jumlah FROM products"
        " WHERE is_active = 1 GROUP BY category ORDER BY category"
    )

    return render_template(
        "index.html",
        products=products,
        categories=categories,
        q=q,
        category=category,
        page=page,
        pages=pages,
        total=total,
    )


@bp.get("/product/<int:product_id>")
def product_detail(product_id):
    product = db.query(
        "SELECT * FROM products WHERE id = ? AND is_active = 1",
        (product_id,),
        one=True,
    )
    if product is None:
        abort(404)

    related = db.query(
        "SELECT * FROM products WHERE is_active = 1 AND category = ? AND id != ?"
        " ORDER BY id DESC LIMIT 3",
        (product["category"], product_id),
    )
    return render_template("product.html", product=product, related=related)
