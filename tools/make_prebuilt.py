"""Developer tool: cross-compile the pre-built libraries in backend/prebuilt/ with Zig.

    python -m pip install ziglang
    python tools/make_prebuilt.py

Users never run this. They get the binaries with the repository, so a machine with
no C compiler can still run StockWise. Run it again whenever a C file changes: the
tests fail if the recorded source fingerprint no longer matches backend/*.c.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import build_c  # noqa: E402

OUT = os.path.join(build_c.BACKEND, "prebuilt")
TARGETS = [  # (zig target, output file)
    ("x86_64-windows-gnu", "stockwise-win-amd64.dll"),
    ("x86_64-linux-gnu.2.17", "libstockwise-linux-x86_64.so"),  # runs on glibc 2.17 and newer
]

os.makedirs(OUT, exist_ok=True)
for target, name in TARGETS:
    command = [sys.executable, "-m", "ziglang", "cc", "-target", target, "-shared", "-O2",
               "-std=c11", "-Wall", "-Wextra", "-s", "-o", os.path.join(OUT, name), *build_c.sources()]
    print(" ".join(command[3:6]), "->", name)
    subprocess.run(command, check=True, cwd=build_c.BACKEND)
for junk in os.listdir(OUT):  # Zig also writes import libraries and debug symbols
    if junk.endswith((".lib", ".pdb", ".o")):
        os.remove(os.path.join(OUT, junk))
with open(os.path.join(OUT, "SOURCES.sha256"), "w") as fh:
    fh.write(build_c.sources_digest() + "\n")
print("fingerprint", build_c.sources_digest())
