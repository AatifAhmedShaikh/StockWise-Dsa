"""Tests for the pre-built C libraries that let StockWise run with no compiler installed."""
import ctypes
import os
import platform
import sys
import unittest

import build_c

PREBUILT = os.path.join(build_c.BACKEND, "prebuilt")
WIN_DLL = os.path.join(PREBUILT, "stockwise-win-amd64.dll")
LINUX_SO = os.path.join(PREBUILT, "libstockwise-linux-x86_64.so")
API = (b"sw_api_version", b"sw_engine_create", b"sw_engine_destroy", b"sw_hash_search_id", b"sw_prefix_search",
       b"sw_price_range", b"sw_knapsack", b"sw_shortest_path", b"sw_fifo_lots", b"sw_restock_ranking")


class PrebuiltTests(unittest.TestCase):
    def test_binaries_match_the_current_c_sources(self):
        """Fails when a C file changed but tools/make_prebuilt.py was not run again."""
        with open(os.path.join(PREBUILT, "SOURCES.sha256")) as fh:
            self.assertEqual(fh.read().strip(), build_c.sources_digest(),
                             "backend/*.c or *.h changed: run  python tools/make_prebuilt.py")

    def test_windows_dll_is_a_64_bit_pe_exporting_the_api(self):
        with open(WIN_DLL, "rb") as fh:
            data = fh.read()
        self.assertEqual(data[:2], b"MZ")
        pe = int.from_bytes(data[0x3C:0x40], "little")
        self.assertEqual(data[pe:pe + 4], b"PE\0\0")
        self.assertEqual(int.from_bytes(data[pe + 4:pe + 6], "little"), 0x8664)  # x86-64
        for name in API:
            self.assertIn(name, data, name)

    def test_linux_library_loads_and_runs(self):
        if not (sys.platform.startswith("linux") and platform.machine().lower() in ("x86_64", "amd64")):
            self.skipTest("Linux x86-64 only")
        lib = ctypes.CDLL(LINUX_SO)
        lib.sw_api_version.restype = ctypes.c_int32
        import c_bridge
        self.assertEqual(lib.sw_api_version(), c_bridge.EXPECTED_API_VERSION)

    def test_a_machine_without_a_compiler_uses_the_prebuilt_library(self):
        if build_c.prebuilt_path() is None:
            self.skipTest("no pre-built library for this platform")
        saved = (build_c.find_compiler, build_c.library_path)
        os.environ.pop("STOCKWISE_LIB", None)
        try:
            build_c.find_compiler = lambda: None
            build_c.library_path = lambda: os.path.join(PREBUILT, "does-not-exist.lib")
            self.assertEqual(build_c.ensure_library(), build_c.prebuilt_path())
        finally:
            build_c.find_compiler, build_c.library_path = saved


if __name__ == "__main__":
    unittest.main()
