"""StockWise - Inventory Optimization System. Start here:

    python stockwise.py

Needs nothing installed beyond Python 3.8+: the interface is a local web page served by
Python's built-in web server, the data is kept in SQLite (built into Python), and every
data structure and algorithm runs in the C library, which ships pre-built for Windows
and Linux in backend/prebuilt/ (and is compiled from backend/*.c if a C compiler exists).

Options: --port N  --no-browser  --db FILE  --verbose
"""
import argparse
import sys
import threading
import webbrowser


def main():
    parser = argparse.ArgumentParser(description="StockWise inventory optimization system")
    parser.add_argument("--port", type=int, default=8765, help="first port to try (default 8765)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    parser.add_argument("--db", help="SQLite file to use (default: stockwise.db here)")
    parser.add_argument("--verbose", action="store_true", help="log every request")
    args = parser.parse_args()

    if sys.version_info < (3, 8):
        sys.exit("StockWise needs Python 3.8 or newer; this is %d.%d." % sys.version_info[:2])
    from c_bridge import StockWiseError, load_library
    try:
        load_library()  # fail early, with a readable message, if the C library cannot load
    except StockWiseError as exc:
        sys.exit("StockWise cannot start.\n\n%s" % exc)

    from webui.server import make_server
    server = make_server(args.db, args.port, args.verbose)
    url = "http://127.0.0.1:%d/" % server.server_address[1]
    print("StockWise is running at %s\nPress Ctrl+C to stop." % url)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
