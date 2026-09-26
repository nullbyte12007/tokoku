"""Smoke test end-to-end pakai Flask test client (stdlib unittest, tanpa DB asli).

Jalankan:  ./.venv/bin/python -m unittest discover -s tests -v
"""

import os
import re
import tempfile
import unittest

from werkzeug.security import generate_password_hash

from shop import create_app, db
from shop import security as sec


class TokokuTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test.sqlite3")
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE": self.db_path,
                "PRODUCTS_PER_PAGE": 5,
            }
        )
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.init_db()
        sec._LOGIN_FAILURES.clear()
        self._seed()
        self.client = self.app.test_client()

    def tearDown(self):
        db.close_db()
        self.ctx.pop()
        self.tmpdir.cleanup()

    # ---------- helper ----------

    def _seed(self):
        db.execute(
            "INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, 'customer')",
            ("budi@test.id", "Budi", generate_password_hash("rahasia123")),
        )
        db.execute(
            "INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, 'admin')",
            ("admin@test.id", "Admin", generate_password_hash("admin12345")),
        )
        for i, (name, price, stock) in enumerate(
            [("Kopi Gayo", 85000, 10), ("Keyboard", 725000, 3), ("Mouse", 189000, 0)], start=1
        ):
            db.execute(
                "INSERT INTO products (slug, name, description, category, price, stock, is_active)"
                " VALUES (?, ?, ?, ?, ?, ?, 1)",
                (f"produk-{i}", name, f"Deskripsi {name}", "Umum", price, stock),
            )

    def token(self):
        with self.client.session_transaction() as sess:
            return sess.get("_csrf_token")

    def post(self, url, data=None, **kwargs):
        payload = dict(data or {})
        payload["_csrf_token"] = self.token()
        return self.client.post(url, data=payload, **kwargs)

    def login(self, email="budi@test.id", password="rahasia123"):
        self.client.get("/login")  # render dulu supaya token CSRF dibuat
        resp = self.post("/login", {"email": email, "password": password})
        self.assertEqual(resp.status_code, 302, resp.data[:300])
        return resp

    def product_id_by_name(self, name):
        return db.scalar("SELECT id FROM products WHERE name = ?", (name,))

    def stock_of(self, name):
        return db.scalar("SELECT stock FROM products WHERE name = ?", (name,))

    # ---------- katalog ----------

    def test_katalog_tampil_produk_aktif_saja(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn("Kopi Gayo", body)
        self.assertNotIn("Produk Rahasia", body)

    def test_pencarian_dan_wildcard_di_escape(self):
        self.assertEqual(self.client.get("/?q=Kopi").status_code, 200)
        body = self.client.get("/?q=Kopi").get_data(as_text=True)
        self.assertIn("Kopi Gayo", body)
        # '%' harus diperlakukan sebagai teks biasa, bukan wildcard
        resp = self.client.get("/?q=%")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("Keyboard", resp.get_data(as_text=True))

    def test_filter_kategori_dan_pagination(self):
        self.assertEqual(self.client.get("/?category=Umum").status_code, 200)
        self.assertEqual(self.client.get("/?page=2").status_code, 200)

    def test_produk_tidak_ada_404(self):
        self.assertEqual(self.client.get("/product/99999").status_code, 404)

    # ---------- auth ----------

    def test_registrasi_lalu_login(self):
        self.client.get("/register")
        resp = self.post(
            "/register",
            {
                "name": "Sari",
                "email": "sari@test.id",
                "password": "rahasia123",
                "password2": "rahasia123",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIsNotNone(db.query("SELECT 1 FROM users WHERE email = ?", ("sari@test.id",), one=True))

        self.login("sari@test.id", "rahasia123")
        self.assertEqual(self.client.get("/account").status_code, 200)

    def test_registrasi_email_duplikat_ditolak(self):
        self.client.get("/register")
        self.post(
            "/register",
            {
                "name": "Budi Lagi",
                "email": "budi@test.id",
                "password": "rahasia123",
                "password2": "rahasia123",
            },
        )
        self.assertEqual(
            db.scalar("SELECT COUNT(*) FROM users WHERE email = ?", ("budi@test.id",), default=0), 1
        )

    def test_password_pendek_ditolak(self):
        self.client.get("/register")
        self.post(
            "/register",
            {"name": "X", "email": "x@test.id", "password": "123", "password2": "123"},
        )
        self.assertIsNone(db.query("SELECT 1 FROM users WHERE email = ?", ("x@test.id",), one=True))

    def test_password_disimpan_sebagai_hash(self):
        row = db.query("SELECT password_hash FROM users WHERE email = ?", ("budi@test.id",), one=True)
        self.assertNotIn("rahasia123", row["password_hash"])

    def test_keranjang_perlu_login(self):
        resp = self.client.get("/cart/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    def test_admin_perlu_peran_admin(self):
        self.login()  # customer
        self.assertEqual(self.client.get("/admin/").status_code, 403)

        self.post("/logout")
        self.login("admin@test.id", "admin12345")
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    # ---------- CSRF ----------

    def test_post_tanpa_csrf_ditolak(self):
        resp = self.client.post("/login", data={"email": "budi@test.id", "password": "rahasia123"})
        self.assertEqual(resp.status_code, 400)

    def test_csrf_salah_ditolak(self):
        self.client.get("/login")
        resp = self.client.post(
            "/login",
            data={"email": "budi@test.id", "password": "rahasia123", "_csrf_token": "palsu"},
        )
        self.assertEqual(resp.status_code, 400)

    # ---------- keranjang & checkout ----------

    def test_alur_beli_lengkap(self):
        self.login()
        kopi_id = self.product_id_by_name("Kopi Gayo")

        resp = self.post("/cart/add", {"product_id": kopi_id, "qty": 2})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(db.scalar("SELECT qty FROM cart_items WHERE product_id = ?", (kopi_id,)), 2)

        # tambah lagi -> qty digabung
        self.post("/cart/add", {"product_id": kopi_id, "qty": 1})
        self.assertEqual(db.scalar("SELECT qty FROM cart_items WHERE product_id = ?", (kopi_id,)), 3)

        self.assertEqual(self.client.get("/cart/").status_code, 200)
        self.assertEqual(self.client.get("/checkout").status_code, 200)

        resp = self.post(
            "/checkout",
            {
                "shipping_name": "Budi",
                "shipping_phone": "081234567890",
                "shipping_address": "Jl. Merdeka No. 10, Bandung",
                "note": "kirim siang",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/orders/", resp.headers["Location"])

        order = db.query("SELECT * FROM orders ORDER BY id DESC LIMIT 1", one=True)
        self.assertEqual(order["status"], "pending")
        self.assertEqual(order["total"], 85000 * 3)
        self.assertEqual(order["shipping_name"], "Budi")

        # stok ikut berkurang, keranjang dikosongkan
        self.assertEqual(self.stock_of("Kopi Gayo"), 7)
        self.assertEqual(db.scalar("SELECT COUNT(*) FROM cart_items", default=0), 0)

        # snapshot harga tersimpan di order_items
        item = db.query("SELECT * FROM order_items WHERE order_id = ?", (order["id"],), one=True)
        self.assertEqual(item["unit_price"], 85000)
        self.assertEqual(item["name"], "Kopi Gayo")

        self.assertEqual(self.client.get(f"/orders/{order['id']}").status_code, 200)

    def test_qty_melebihi_stok_dibatasi(self):
        self.login()
        keyboard_id = self.product_id_by_name("Keyboard")  # stok 3
        self.post("/cart/add", {"product_id": keyboard_id, "qty": 99})
        self.assertEqual(db.scalar("SELECT qty FROM cart_items WHERE product_id = ?", (keyboard_id,)), 3)

    def test_produk_stok_habis_tidak_bisa_ditambah(self):
        self.login()
        mouse_id = self.product_id_by_name("Mouse")  # stok 0
        self.post("/cart/add", {"product_id": mouse_id, "qty": 1})
        self.assertEqual(db.scalar("SELECT COUNT(*) FROM cart_items", default=0), 0)

    def test_checkout_ditolak_kalau_stok_berubah(self):
        self.login()
        keyboard_id = self.product_id_by_name("Keyboard")
        self.post("/cart/add", {"product_id": keyboard_id, "qty": 3})

        # admin lain "menghabiskan" stok setelah barang masuk keranjang
        db.execute("UPDATE products SET stock = 0 WHERE id = ?", (keyboard_id,))

        resp = self.post(
            "/checkout",
            {
                "shipping_name": "Budi",
                "shipping_phone": "081234567890",
                "shipping_address": "Jl. Merdeka No. 10, Bandung",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(db.scalar("SELECT COUNT(*) FROM orders", default=0), 0)
        # stok tidak boleh jadi minus
        self.assertEqual(self.stock_of("Keyboard"), 0)

    def test_checkout_alamat_pendek_ditolak(self):
        self.login()
        self.post("/cart/add", {"product_id": self.product_id_by_name("Kopi Gayo"), "qty": 1})
        self.post(
            "/checkout",
            {"shipping_name": "Budi", "shipping_phone": "081234567890", "shipping_address": "pendek"},
        )
        self.assertEqual(db.scalar("SELECT COUNT(*) FROM orders", default=0), 0)

    def test_batal_pesanan_mengembalikan_stok(self):
        self.login()
        kopi_id = self.product_id_by_name("Kopi Gayo")
        self.post("/cart/add", {"product_id": kopi_id, "qty": 4})
        self.post(
            "/checkout",
            {
                "shipping_name": "Budi",
                "shipping_phone": "081234567890",
                "shipping_address": "Jl. Merdeka No. 10, Bandung",
            },
        )
        self.assertEqual(self.stock_of("Kopi Gayo"), 6)
        order_id = db.scalar("SELECT id FROM orders ORDER BY id DESC LIMIT 1")

        self.post(f"/orders/{order_id}/cancel")
        self.assertEqual(db.scalar("SELECT status FROM orders WHERE id = ?", (order_id,)), "cancelled")
        self.assertEqual(self.stock_of("Kopi Gayo"), 10)

        # tidak bisa dibatalkan dua kali
        self.post(f"/orders/{order_id}/cancel")
        self.assertEqual(self.stock_of("Kopi Gayo"), 10)

    # ---------- isolasi antar user ----------

    def test_pesanan_user_lain_tidak_bisa_dilihat(self):
        self.login()
        self.post("/cart/add", {"product_id": self.product_id_by_name("Kopi Gayo"), "qty": 1})
        self.post(
            "/checkout",
            {
                "shipping_name": "Budi",
                "shipping_phone": "081234567890",
                "shipping_address": "Jl. Merdeka No. 10, Bandung",
            },
        )
        order_id = db.scalar("SELECT id FROM orders ORDER BY id DESC LIMIT 1")
        self.post("/logout")

        self.login("admin@test.id", "admin12345")
        self.assertEqual(self.client.get(f"/orders/{order_id}").status_code, 404)

    def test_keranjang_terpisah_per_user(self):
        self.login()
        self.post("/cart/add", {"product_id": self.product_id_by_name("Kopi Gayo"), "qty": 2})
        self.post("/logout")

        self.login("admin@test.id", "admin12345")
        admin_id = db.scalar("SELECT id FROM users WHERE email = ?", ("admin@test.id",))

        # admin tidak melihat keranjang Budi, dan keranjangnya sendiri kosong
        self.assertEqual(
            db.scalar(
                "SELECT COUNT(*) FROM cart_items WHERE user_id = ?", (admin_id,), default=0
            ),
            0,
        )
        self.assertEqual(
            db.scalar(
                "SELECT COUNT(*) FROM cart_items WHERE user_id != ?", (admin_id,), default=0
            ),
            1,
        )
        self.assertEqual(self.client.get("/cart/").status_code, 200)

    # ---------- admin ----------

    def test_admin_crud_produk(self):
        self.login("admin@test.id", "admin12345")

        self.client.get("/admin/products/new")
        resp = self.post(
            "/admin/products/new",
            {
                "name": "Teh Melati",
                "category": "Minuman",
                "price": "45.000",
                "stock": "20",
                "description": "Teh wangi melati.",
                "is_active": "1",
            },
        )
        self.assertEqual(resp.status_code, 302)
        row = db.query("SELECT * FROM products WHERE name = ?", ("Teh Melati",), one=True)
        self.assertEqual(row["price"], 45000)  # titik diabaikan
        self.assertEqual(row["slug"], "teh-melati")

        resp = self.post(
            f"/admin/products/{row['id']}/edit",
            {
                "name": "Teh Melati Premium",
                "category": "Minuman",
                "price": "52000",
                "stock": "15",
                "is_active": "1",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            db.scalar("SELECT price FROM products WHERE id = ?", (row["id"],)), 52000
        )

        self.post(f"/admin/products/{row['id']}/delete")
        self.assertEqual(
            db.scalar("SELECT is_active FROM products WHERE id = ?", (row["id"],)), 0
        )
        # tidak muncul lagi di katalog (link detail produknya hilang)
        catalog_html = self.client.get("/").get_data(as_text=True)
        self.assertNotIn(f'href="/product/{row["id"]}"', catalog_html)

    def test_admin_produk_validasi_gagal(self):
        self.login("admin@test.id", "admin12345")
        self.client.get("/admin/products/new")
        self.post("/admin/products/new", {"name": "ab", "price": "abc", "stock": "-1"})
        self.assertIsNone(db.query("SELECT 1 FROM products WHERE name = 'ab'", one=True))

    def test_admin_ubah_status_pesanan_dan_transisi_ditolak(self):
        self.login()
        self.post("/cart/add", {"product_id": self.product_id_by_name("Kopi Gayo"), "qty": 1})
        self.post(
            "/checkout",
            {
                "shipping_name": "Budi",
                "shipping_phone": "081234567890",
                "shipping_address": "Jl. Merdeka No. 10, Bandung",
            },
        )
        order_id = db.scalar("SELECT id FROM orders ORDER BY id DESC LIMIT 1")
        self.post("/logout")
        self.login("admin@test.id", "admin12345")

        # pending -> shipped tidak diizinkan
        self.post(f"/admin/orders/{order_id}/status", {"status": "shipped"})
        self.assertEqual(db.scalar("SELECT status FROM orders WHERE id = ?", (order_id,)), "pending")

        for status in ("paid", "shipped", "completed"):
            self.post(f"/admin/orders/{order_id}/status", {"status": status})
        self.assertEqual(
            db.scalar("SELECT status FROM orders WHERE id = ?", (order_id,)), "completed"
        )

        # status final tidak bisa diubah lagi
        self.post(f"/admin/orders/{order_id}/status", {"status": "cancelled"})
        self.assertEqual(
            db.scalar("SELECT status FROM orders WHERE id = ?", (order_id,)), "completed"
        )

    def test_admin_tidak_bisa_ubah_peran_sendiri(self):
        self.login("admin@test.id", "admin12345")
        admin_id = db.scalar("SELECT id FROM users WHERE email = ?", ("admin@test.id",))
        self.post(f"/admin/users/{admin_id}/role", {"role": "customer"})
        self.assertEqual(db.scalar("SELECT role FROM users WHERE id = ?", (admin_id,)), "admin")

    def test_admin_ubah_peran_user_lain(self):
        self.login("admin@test.id", "admin12345")
        budi_id = db.scalar("SELECT id FROM users WHERE email = ?", ("budi@test.id",))
        self.post(f"/admin/users/{budi_id}/role", {"role": "admin"})
        self.assertEqual(db.scalar("SELECT role FROM users WHERE id = ?", (budi_id,)), "admin")

    def test_admin_halaman_utama_ok(self):
        self.login("admin@test.id", "admin12345")
        for path in ("/admin/", "/admin/products", "/admin/orders", "/admin/users"):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    # ---------- SQL injection ----------

    def test_injection_di_pencarian_aman(self):
        resp = self.client.get("/?q=' OR 1=1 --")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("CREATE TABLE", db.query("SELECT sql FROM sqlite_master WHERE name='users'", one=True)["sql"])

    def test_injection_di_login_aman(self):
        self.client.get("/login")
        self.post("/login", {"email": "budi@test.id' --", "password": "apa saja"})
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)


    # ---------- hardening ----------

    def test_security_headers_ada_di_semua_respons(self):
        for path in ("/", "/login", "/static/style.css"):
            resp = self.client.get(path)
            try:
                headers = dict(resp.headers)
            finally:
                resp.close()
            self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff", path)
            self.assertEqual(headers.get("X-Frame-Options"), "DENY", path)
            self.assertEqual(headers.get("Referrer-Policy"), "same-origin", path)
            self.assertIn("default-src 'self'", headers.get("Content-Security-Policy", ""), path)

    def test_csp_tanpa_unsafe_inline(self):
        csp = self.client.get("/").headers["Content-Security-Policy"]
        self.assertNotIn("unsafe-inline", csp)
        self.assertNotIn("unsafe-eval", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("object-src 'none'", csp)

    def test_hsts_hanya_saat_cookie_secure(self):
        self.assertNotIn("Strict-Transport-Security", self.client.get("/").headers)
        self.app.config["SESSION_COOKIE_SECURE"] = True
        try:
            headers = self.client.get("/").headers
        finally:
            self.app.config["SESSION_COOKIE_SECURE"] = False
        self.assertIn("max-age=31536000", headers.get("Strict-Transport-Security", ""))

    def test_cookie_sesi_httponly_dan_samesite(self):
        cookie = self.client.get("/login").headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)

    def test_tidak_ada_handler_inline_untuk_csp(self):
        self.login("admin@test.id", "admin12345")
        html = self.client.get("/admin/products").get_data(as_text=True)
        self.assertIn("data-confirm=", html)
        self.assertNotIn("onsubmit=", html)
        self.assertIn("/static/app.js", html)

    def test_logout_hanya_bisa_post(self):
        self.assertEqual(self.client.get("/logout").status_code, 405)

    def test_izin_file_database_600(self):
        self.client.get("/")
        self.assertEqual(os.stat(self.db_path).st_mode & 0o777, 0o600)

    def test_throttle_memblokir_setelah_8_percobaan(self):
        self.client.get("/login")
        for _ in range(8):
            resp = self.post("/login", {"email": "budi@test.id", "password": "salah"})
            self.assertEqual(resp.status_code, 200)

        # percobaan ke-9 diblokir walau passwordnya benar
        resp = self.post("/login", {"email": "budi@test.id", "password": "rahasia123"})
        self.assertEqual(resp.status_code, 429)
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)

    def test_throttle_dict_tidak_tumbuh_tanpa_batas(self):
        original_max = sec._LOGIN_FAILURES_MAX_KEYS
        sec._LOGIN_FAILURES.clear()
        sec._LOGIN_FAILURES_MAX_KEYS = 50
        try:
            for i in range(300):
                sec.note_login_failure(f"10.0.0.{i}", f"user{i}@test.id")
            sec.check_login_throttle("10.0.0.0", "x@test.id")
            self.assertLessEqual(len(sec._LOGIN_FAILURES), 50)
        finally:
            sec._LOGIN_FAILURES_MAX_KEYS = original_max
            sec._LOGIN_FAILURES.clear()

    def test_email_tidak_terdaftar_tidak_bocor_lewat_pesan(self):
        self.client.get("/login")
        resp = self.post("/login", {"email": "tidak-ada@test.id", "password": "apa saja"})
        body = resp.get_data(as_text=True)
        self.assertIn("Email atau password salah", body)
        self.assertNotIn("tidak terdaftar", body.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
