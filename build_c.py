"""build_c.py - build the C engine into a shared library, on Windows, Linux or macOS.

    python build_c.py          build the library
    python build_c.py --test   build it, then build and run the C tests

c_bridge.py calls ensure_library() too, so the app builds the library itself the
first time (and again after the C sources change). No make is needed.
"""
import glob
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
WINDOWS = sys.platform.startswith("win")

# Where MSYS2 / MinGW-w64 usually installs GCC when it was not added to PATH.
WINDOWS_GCC_DIRS = [r"C:\msys64\ucrt64\bin", r"C:\msys64\mingw64\bin", r"C:\mingw64\bin",
                    r"C:\msys64\clang64\bin", r"C:\Program Files\mingw-w64\bin",
                    os.path.expanduser(r"~\scoop\apps\gcc\current\bin")]

INSTALL_HELP = {
    True: ("No C compiler found. Install GCC with MSYS2 (https://www.msys2.org), then in the "
           "'MSYS2 UCRT64' terminal run:\n"
           "    pacman -S --needed mingw-w64-ucrt-x86_64-gcc\n"
           "Close and reopen this terminal and run again. (If GCC is installed in a custom "
           "folder, add its bin folder to PATH or set the CC environment variable.)"),
    False: ("No C compiler found. Install one: Ubuntu/Debian 'sudo apt install build-essential', "
            "macOS 'xcode-select --install'."),
}


class BuildError(Exception):
    """The C library could not be built; the message says what to do."""


def library_path():
    """Where the shared library lives (STOCKWISE_LIB overrides it)."""
    if os.environ.get("STOCKWISE_LIB"):
        return os.environ["STOCKWISE_LIB"]
    name = ("stockwise.dll" if WINDOWS else
            "libstockwise.dylib" if sys.platform == "darwin" else "libstockwise.so")
    return os.path.join(BACKEND, name)


def sources():
    """Every library source file; a new .c file is picked up automatically."""
    return sorted(glob.glob(os.path.join(BACKEND, "*.c")))


def _inputs():
    return sources() + glob.glob(os.path.join(BACKEND, "*.h"))


def sources_digest():
    """SHA-256 over every C source and header; identifies which code a binary was built from."""
    import hashlib
    h = hashlib.sha256()
    for f in sorted(_inputs()):
        with open(f, "rb") as fh:  # normalise line endings so Windows checkouts hash the same
            h.update(os.path.basename(f).encode() + fh.read().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def prebuilt_path():
    """Pre-built library for this OS/CPU shipped in backend/prebuilt/, or None."""
    import platform
    machine = platform.machine().lower()
    if WINDOWS and machine in ("amd64", "x86_64") and struct_bits() == 64:
        name = "stockwise-win-amd64.dll"
    elif sys.platform.startswith("linux") and machine in ("x86_64", "amd64"):
        name = "libstockwise-linux-x86_64.so"
    else:
        return None
    path = os.path.join(BACKEND, "prebuilt", name)
    return path if os.path.exists(path) else None


def struct_bits():
    import struct
    return struct.calcsize("P") * 8


def needs_build(lib=None):
    """True if the library is missing or older than any C source or header."""
    lib = lib or library_path()
    if not os.path.exists(lib):
        return True
    built = os.path.getmtime(lib)
    return any(os.path.getmtime(f) > built for f in _inputs())


def find_compiler():
    """Path of a C compiler, or None. Order: $CC, gcc, cc, clang, then MSYS2 folders."""
    names = [os.environ.get("CC"), "gcc", "cc", "clang"]
    for name in filter(None, names):
        found = shutil.which(name)
        if found:
            return found
    if WINDOWS:
        for folder in WINDOWS_GCC_DIRS:
            for exe in ("gcc.exe", "clang.exe"):
                candidate = os.path.join(folder, exe)
                if os.path.exists(candidate):
                    return candidate
    return None


def _flags(shared):
    flags = ["-std=c11", "-O2", "-Wall", "-Wextra", "-Wpedantic"]
    if shared:
        flags.append("-shared")
    if WINDOWS:
        flags.append("-static-libgcc")  # the DLL must not depend on MinGW's own DLLs
    else:
        flags += ["-fPIC"]
    return flags


def _run(command, compiler):
    env = dict(os.environ)
    # A compiler found outside PATH needs its own folder on PATH to run its helpers.
    env["PATH"] = os.path.dirname(compiler) + os.pathsep + env.get("PATH", "")
    return subprocess.run(command, capture_output=True, text=True, env=env, cwd=BACKEND)


def build_library():
    """Compile backend/*.c into the shared library and return its path."""
    compiler = find_compiler()
    if compiler is None:
        raise BuildError(INSTALL_HELP[WINDOWS])
    lib = library_path()
    command = [compiler, *_flags(True), "-o", lib, *sources()] + ([] if WINDOWS else ["-lm"])
    result = _run(command, compiler)
    if result.returncode != 0:
        raise BuildError(f"Compiling the C library failed ({compiler}):\n{result.stderr or result.stdout}")
    return lib


def ensure_library():
    """Return a usable library path with nothing to install.

    1. a library built from the current sources, if one exists;
    2. else build one if a C compiler is available;
    3. else use the pre-built library shipped in backend/prebuilt/."""
    lib = library_path()
    if os.environ.get("STOCKWISE_LIB") or not needs_build(lib):
        return lib
    if find_compiler() is not None:
        try:
            return build_library()
        except BuildError:
            pass  # fall through to the pre-built library
    prebuilt = prebuilt_path()
    if prebuilt:
        return prebuilt
    if os.path.exists(lib):  # an older build is still better than nothing
        return lib
    raise BuildError(INSTALL_HELP[WINDOWS] + "\nNo pre-built library exists for this system either.")


def run_c_tests():
    """Build backend/tests/test_engine.c with the sources and run it. Returns True if all pass."""
    compiler = find_compiler()
    if compiler is None:
        raise BuildError(INSTALL_HELP[WINDOWS])
    exe = os.path.join(BACKEND, "test_engine.exe" if WINDOWS else "test_engine")
    command = [compiler, *_flags(False), "-I.", "-o", exe,
               os.path.join("tests", "test_engine.c"), *sources()] + ([] if WINDOWS else ["-lm"])
    result = _run(command, compiler)
    if result.returncode != 0:
        raise BuildError(f"Compiling the C tests failed:\n{result.stderr or result.stdout}")
    run = subprocess.run([exe], capture_output=True, text=True, cwd=BACKEND)
    print(run.stdout.strip())
    return run.returncode == 0


if __name__ == "__main__":
    try:
        print("Built", build_library())
        if "--test" in sys.argv[1:] and not run_c_tests():
            sys.exit(1)
    except BuildError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
