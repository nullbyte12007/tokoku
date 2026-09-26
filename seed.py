"""Isi database dengan data demo: 1 admin, 1 pembeli, dan beberapa produk.

Jalankan sekali:  python seed.py
Aman diulang (pakai INSERT OR IGNORE), tapi stok yang sudah ada tidak direset.
"""

import sys

from werkzeug.security import generate_password_hash

from shop import create_app, db

USERS = [
    ("admin@tokoku.test", "Admin Tokoku", "admin12345", "admin"),
    ("budi@tokoku.test", "Budi Santoso", "budi12345", "customer"),
    ("sari@tokoku.test", "Sari Dewi", "sari12345", "customer"),
]

PRODUCTS = [
    ("Kopi Arabika Gayo 250g", "Kopi & Minuman", 85000, 40,
     "Single origin Gayo, medium roast. Notes: cokelat, jeruk manis."),
    ("Kopi Robusta Lampung 250g", "Kopi & Minuman", 62000, 55,
     "Robusta bold dengan body tebal, cocok buat espresso."),
    ("Teh Hijau Premium 100g", "Kopi & Minuman", 45000, 30,
     "Teh hijau daun utuh, aroma segar, tanpa perasa tambahan."),
    ("Keyboard Mekanik 65%", "Elektronik", 725000, 12,
     "Layout 65%, hot-swap, switch linear, kabel USB-C detachable."),
    ("Mouse Wireless Silent", "Elektronik", 189000, 25,
     "Klik senyap, DPI sampai 1600, baterai tahan 12 bulan."),
    ("Headset Over-Ear Studio", "Elektronik", 1250000, 8,
     "Driver 50mm, kabel lurus 3m, earpad velour yang nyaman."),
    ("Powerbank 20000mAh", "Elektronik", 315000, 4,
     "Fast charging 22.5W, dua output, indikator digital."),
    ("Tumbler Stainless 500ml", "Rumah Tangga", 135000, 60,
     "Tahan panas 12 jam, tutup anti bocor, body anti sidik jari."),
    ("Lampu Meja LED Fleksibel", "Rumah Tangga", 165000, 18,
     "Tiga mode warna, arm fleksibel, port USB untuk charging."),
    ("Rak Buku Minimalis 3 Tingkat", "Rumah Tangga", 480000, 6,
     "Kayu solid finishing natural, mudah dirakit, muat banyak buku."),
    ("Tas Ransel Laptop 15 inci", "Fashion", 275000, 22,
     "Kompartemen laptop berlapis busa, bahan anti air, ada port USB."),
    ("Sepatu Sneakers Canvas", "Fashion", 320000, 3,
     "Upper kanvas, sol karet anti slip, insole empuk."),
]


def main():
    app = create_app()
    with app.app_context():
        db.init_db()
        print("Skema database siap.")

        for email, name, password, role in USERS:
            db.execute(
                "INSERT OR IGNORE INTO users (email, name, password_hash, role)"
                " VALUES (?, ?, ?, ?)",
                (email, name, generate_password_hash(password), role),
            )

        for name, category, price, stock, description in PRODUCTS:
            slug = name.lower().replace(" ", "-")
            db.execute(
                "INSERT OR IGNORE INTO products"
                " (slug, name, description, category, price, stock, image_url, is_active)"
                " VALUES (?, ?, ?, ?, ?, ?, '', 1)",
                (slug, name, description, category, price, stock),
            )

        product_count = db.scalar("SELECT COUNT(*) FROM products", default=0)
        user_count = db.scalar("SELECT COUNT(*) FROM users", default=0)

    print(f"Selesai. {user_count} user, {product_count} produk di database.")
    print()
    print("Akun demo:")
    for email, _, password, role in USERS:
        print(f"  {email:22} / {password:11}  ({role})")


if __name__ == "__main__":
    sys.exit(main())
