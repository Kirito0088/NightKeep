"""Run the Nightkeep console locally on loopback.

Bound to 127.0.0.1 only. It must not listen on the LAN.
See docs/adr/0002-flask-console.md.
"""

from nightkeep.console.app import create_app

if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=5000, debug=False)
