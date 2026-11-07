"""Build a pinned whisper.cpp revision without modifying system packages."""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
from pathlib import Path

from .kb import _write_json_atomic
from .transaction import Transaction, backup_path, fingerprint

VERSION = "v1.8.3"
COMMIT = "2eeeba56e9edd762b4b38467bab96c2517163158"
REPOSITORY = "https://github.com/ggml-org/whisper.cpp.git"


def selected_backend(backend: str) -> str:
    apple = platform.system() == "Darwin" and platform.machine().lower() in {"arm64", "aarch64"}
    if backend == "auto":
        return "metal" if apple else "cpu"
    if backend not in {"metal", "cpu"}:
        raise ValueError("whisper.cpp installation supports auto, metal, or cpu.")
    if backend == "metal" and not apple:
        raise ValueError("Metal installation requires an Apple Silicon Mac.")
    return backend


def install_path(home: Path, backend: str) -> Path:
    return home / ".local/share/ableton-ctrl/whisper" / f"{VERSION}-{backend}"


def binary_path(home: Path, backend: str) -> Path:
    executable = "whisper-cli.exe" if platform.system() == "Windows" else "whisper-cli"
    return install_path(home, backend) / "source/build/bin" / executable


def install(home: Path, backend: str = "auto", jobs: int = 4) -> Path:
    backend = selected_backend(backend)
    if jobs < 1 or jobs > 64:
        raise ValueError("Build jobs must be between 1 and 64.")
    destination = install_path(home, backend)
    binary = binary_path(home, backend)
    marker = destination / "installation.json"
    if destination.exists():
        fingerprint(destination)
        if marker.is_file() and json.loads(marker.read_text()).get("commit") == COMMIT and binary.is_file():
            subprocess.run([str(binary), "--help"], check=True, capture_output=True)
            return binary
        raise ValueError(f"Unmanaged or incomplete installation: {destination}. Move it aside before retrying.")
    missing = [name for name in ("git", "cmake") if not shutil.which(name)]
    if platform.system() != "Windows" and not any(shutil.which(c) for c in ("c++", "clang++", "g++")):
        missing.append("C++ compiler (Xcode Command Line Tools or build-essential)")
    if missing:
        raise ValueError("Install build prerequisites first: " + ", ".join(missing))
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = destination.parent / (destination.name + ".lock")
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise ValueError(f"Another build may be active: {lock}. Remove this lock only if no build is running.") from exc
    try:
        with Transaction(backup_path(home, "whisper"), [destination]):
            source = destination / "source"
            source.mkdir(parents=True)
            subprocess.run(["git", "clone", "--depth", "1", "--branch", VERSION, REPOSITORY, str(source)], check=True)
            actual = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
            if actual != COMMIT:
                raise RuntimeError("whisper.cpp revision differs from the pinned commit; refusing to compile.")
            build = source / "build"
            subprocess.run(["cmake", "-S", str(source), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release",
                            f"-DGGML_METAL={'ON' if backend == 'metal' else 'OFF'}", "-DGGML_CUDA=OFF",
                            "-DGGML_VULKAN=OFF", "-DGGML_NATIVE=OFF", "-DWHISPER_BUILD_TESTS=OFF"], check=True)
            subprocess.run(["cmake", "--build", str(build), "--config", "Release", "--target", "whisper-cli", "-j", str(jobs)], check=True)
            if not binary.is_file():
                # Multi-config generators (notably Windows) put binaries under Release.
                alternate = build / "bin/Release" / binary.name
                if alternate.is_file():
                    raise RuntimeError("Multi-config build layout is not supported yet. Use a single-config CMake generator.")
                raise RuntimeError("Build did not produce whisper-cli.")
            subprocess.run([str(binary), "--help"], check=True, capture_output=True)
            _write_json_atomic(marker, {"commit": COMMIT, "version": VERSION, "backend": backend})
    finally:
        lock.rmdir()
    return binary
