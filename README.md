# Tokoku — E-commerce Multiuser

Aplikasi toko online sederhana dengan **Flask + SQLite**, dibangun tanpa ORM
(SQL langsung dengan *prepared statement*). Mencakup katalog, keranjang, checkout,
riwayat pesanan, panel admin, dan manajemen akun.

Proyek ini dipakai sebagai **latihan penerapan kontrol keamanan aplikasi web** —
perbaikan keamanannya didokumentasikan di bawah.

---

## Fitur

**Pembeli**
- Katalog produk: pencarian, filter kategori, paginasi
- Detail produk + rekomendasi produk sekategori
- Keranjang: tambah, ubah jumlah, hapus, kosongkan
- Checkout dengan data pengiriman + validasi stok saat transaksi
- Riwayat & detail pesanan, pembatalan pesanan (dengan pengembalian stok)
- Akun: profil, ringkasan belanja, ubah password
- Lupa password: tautan reset berbasis token (sekali pakai, kedaluwarsa)

**Admin**
- Ringkasan: jumlah produk, pengguna, pesanan, dan pendapatan
- CRUD produk (soft delete agar riwayat pesanan tetap utuh)
- Kelola pesanan: perubahan status mengikuti aturan transisi yang valid
- Kelola pengguna: ubah peran dengan pengamanan admin terakhir

---

## Keamanan

| Kontrol | Implementasi |
|---|---|
| **SQL Injection** | Seluruh query memakai *prepared statement* (`?`). Input pencarian juga di-escape untuk `LIKE` |
| **CSRF** | Token per sesi, diverifikasi global di `before_request`, dibandingkan dengan `hmac.compare_digest` (fail-closed) |
| **Session fixation** | `session.clear()` sebelum menetapkan identitas saat login |
| **Cookie** | `HttpOnly`, `SameSite=Lax`, dan `Secure` **otomatis aktif** bila request datang via HTTPS |
| **Header keamanan** | CSP ketat tanpa `unsafe-inline`, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP, HSTS saat HTTPS |
| **Brute force login** | Pembatasan percobaan per `(IP, email)` + *dummy hash* agar waktu respons tidak membocorkan email terdaftar |
| **User enumeration** | Pesan registrasi disamakan untuk email baru maupun email yang sudah terdaftar |
| **Rate limit registrasi** | Maksimum 5 percobaan per IP per jam |
| **Captcha** | Tantangan aritmatika sekali pakai + honeypot (field tersembunyi) + batas waktu minimum |
| **Reset password** | Token disimpan sebagai `sha256`, sekali pakai, kedaluwarsa 60 menit; reset sukses menonaktifkan seluruh token pengguna tersebut |
| **Akses tidak sah (IDOR)** | Pesanan & keranjang selalu difilter berdasarkan pemiliknya; rute admin memakai decorator `admin_required` |
| **Open redirect** | Target pengalihan divalidasi (hanya path internal) |
| **Race condition stok** | `BEGIN IMMEDIATE` + `UPDATE ... WHERE stock >= ?` dengan pemeriksaan `rowcount` |
| **Berkas sensitif** | Database & secret key berizin `600`; `instance/`, `*.sqlite3`, dan `.env` di-`.gitignore` |
| **Kebocoran versi** | Dijalankan dengan **waitress** (ident header dinonaktifkan), bukan server pengembangan Flask |

Semua perubahan diuji dengan *test client* Flask: kasus sukses, kasus gagal, dan
kasus tepi (captcha kosong/salah, honeypot terisi, submit instan, token dipakai ulang).

---

## Struktur

```
run.py              entrypoint (waitress untuk non-debug)
seed.py             data demo (produk + akun)
run.sh              setup venv, install, seed, jalankan
shop/
  __init__.py       factory aplikasi + konfigurasi
  db.py             koneksi SQLite per-request, transaksi, helper query
  schema.sql        skema database
  security.py       CSRF, header, throttle, captcha, token reset
  auth.py           daftar, masuk, keluar, akun, ubah & lupa password
  catalog.py        katalog, pencarian, detail produk
  cart.py           keranjang
  orders.py         checkout, riwayat, pembatalan
  admin.py          panel admin
  templates/        template Jinja2
  static/           CSS & JS
tests/              smoke test
```

---

## Menjalankan

```bash
./run.sh
```

Skrip akan membuat virtualenv, memasang dependensi, mengisi data demo, lalu
menjalankan server di `http://127.0.0.1:5000`.

Manual:

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python seed.py
./.venv/bin/python run.py
```

Konfigurasi opsional lewat environment variable:

| Variabel | Fungsi |
|---|---|
| `TOKOKU_HOST` / `TOKOKU_PORT` | Alamat & port (default `127.0.0.1:5000`) |
| `TOKOKU_DEBUG=1` | Mode debug (server pengembangan Flask) |
| `TOKOKU_SECRET_KEY` | Secret key (kalau kosong, dibuat otomatis di `instance/`) |
| `TOKOKU_SMTP_*` | SMTP untuk mengirim tautan reset password. Tanpa ini, tautan ditulis ke log |
| `TOKOKU_COOKIE_SECURE=1` | Paksa cookie `Secure` (otomatis aktif bila diakses via HTTPS) |

> **Akun demo** dibuat oleh `seed.py` (mis. `admin@tokoku.test` / `admin12345`).
> Hapus atau ganti sebelum dipakai di lingkungan nyata.

---

## Catatan desain

- **Tanpa ORM** — query SQL eksplisit agar alur data mudah dilacak dan diaudit.
- **Soft delete produk** — produk "dihapus" hanya dinonaktifkan, supaya riwayat
  pesanan lama tetap menampilkan data yang benar.
- **Snapshot harga** — `order_items` menyimpan nama & harga saat transaksi,
  sehingga perubahan harga produk tidak mengubah pesanan yang sudah terjadi.
- **Gagal dengan aman** — validasi CSRF dan pembatasan akses menghasilkan
  penolakan (bukan diam-diam lolos) saat kondisi tidak terpenuhi.
