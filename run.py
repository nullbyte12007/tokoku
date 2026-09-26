"""Entrypoint: python run.py  (atau: flask --app run run --debug)"""

import os

from shop import create_app

app = create_app()


def _serve_production(host, port):
    """Server WSGI produksi (waitress). Tidak membocorkan versi Python/Werkzeug."""
    try:
        from waitress import serve
    except ImportError:
        app.logger.warning("waitress tidak terpasang — fallback ke server dev Flask")
        app.run(host=host, port=port, debug=False)
        return

    # ident=None -> header "Server" tidak dikirim sama sekali
    serve(app, host=host, port=port, ident=None, threads=8)


if __name__ == "__main__":
    host = os.environ.get("TOKOKU_HOST", "127.0.0.1")
    port = int(os.environ.get("TOKOKU_PORT", "5000"))

    if os.environ.get("TOKOKU_DEBUG") == "1":
        app.run(host=host, port=port, debug=True)
    else:
        _serve_production(host, port)
