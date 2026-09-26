"""Label status pesanan dan aturan perpindahannya."""

STATUS_LABELS = {
    "pending": "Menunggu Pembayaran",
    "paid": "Sudah Dibayar",
    "shipped": "Dikirim",
    "completed": "Selesai",
    "cancelled": "Dibatalkan",
}

# Status berikutnya yang boleh dipilih admin.
ADMIN_TRANSITIONS = {
    "pending": ("paid", "cancelled"),
    "paid": ("shipped", "cancelled"),
    "shipped": ("completed",),
    "completed": (),
    "cancelled": (),
}

# Status yang masih boleh dibatalkan sendiri oleh pembeli.
CUSTOMER_CANCELLABLE = ("pending", "paid")

REVENUE_STATUSES = ("paid", "shipped", "completed")


def label(status):
    return STATUS_LABELS.get(status, status)
