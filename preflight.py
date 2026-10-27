#!/usr/bin/env python3
"""Pre-flight check for Claude Desktop's Linux build and Cowork on this host.

Anthropic's Linux build is a beta that ships for Debian-based systems only, and
Cowork on Linux runs its tasks in a virtual machine the desktop app hosts with
QEMU and KVM. When one requirement is missing the app reports it once, at
launch, so a failed launch tells you little about what to install.

This script reads the host and prints, requirement by requirement, what is
there and what is not. It changes nothing: every check is a read of /dev, /proc,
/sys or a PATH lookup. Run it as the user who launches the app, because group
membership and /dev permissions are per-user.

    python3 preflight.py            # human readable
    python3 preflight.py --json     # machine readable, same data
    python3 preflight.py --help

Exit code: 0 when all five of Anthropic's documented requirements pass,
1 when any fails, 2 on an unexpected error.

Requirements are taken from Anthropic's own Linux documentation, read
2026-10-27:
  https://code.claude.com/docs/en/desktop-linux
  https://claude.com/download
Distro support and the fallbacks are noted with their sources in docs/index.md.
"""

from __future__ import annotations

import argparse
import grp
import json
import os
import platform
import re
import shutil
import subprocess
import sys

# The five requirements Anthropic documents for Cowork on Linux.
CORE = ("virtualization", "kvm_device", "qemu", "firmware", "vsock")

FIX = {
    "virtualization": "Enable Intel VT-x or AMD-V in the firmware setup (it is often called "
                      "SVM, AMD-V, or Virtualization Technology). In a VM, enable nested "
                      "virtualization on the host.",
    "kvm_device": "Load the KVM module (sudo modprobe kvm_intel or kvm_amd). If /dev/kvm still "
                  "does not appear you are inside a container or a guest that was not given it.",
    "kvm_group": "sudo usermod -aG kvm $USER, then log out and back in.",
    "qemu": "Install QEMU for your architecture (Debian and Ubuntu: qemu-system-x86).",
    "firmware": "Install UEFI firmware for QEMU (Debian and Ubuntu: ovmf; Fedora: edk2-ovmf).",
    "virtiofsd": "Install virtiofsd. Ubuntu 22.04 has no package for it and the app carries its "
                 "own copy there.",
    "vsock": "The app needs /dev/vhost-vsock, which only kvm group members can open. If the "
             "device is missing, load the module (sudo modprobe vmw_vsock_virtio_transport) and "
             "check that your kernel ships vsock: no /lib/modules/<release> directory means it "
             "does not.",
    "modules": "The running kernel has no module directory, so the app cannot add the missing "
               "pieces at launch. This is common on ChromeOS and in container-based Linux.",
}


def sh(cmd: list[str]) -> tuple[int, str]:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return out.returncode, (out.stdout + out.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - host dependent
        return 127, str(exc)


def read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def os_release() -> dict[str, str]:
    data: dict[str, str] = {}
    for line in read("/etc/os-release").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            data[key] = value.strip().strip('"')
    return data


def in_kvm_group() -> tuple[bool | None, str]:
    """True/False when the group is resolvable, None when it does not exist."""
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    try:
        entry = grp.getgrnam("kvm")
    except KeyError:
        return None, "no kvm group on this host"
    if user:
        try:
            import pwd  # noqa: PLC0415 - platform specific, only needed here

            pw = pwd.getpwuid(os.getuid())
            if pw.pw_name in entry.gr_mem:
                return True, f"{pw.pw_name} is in group kvm"
            primary = grp.getgrgid(pw.pw_gid).gr_name
            if primary == "kvm":
                return True, f"{pw.pw_name}'s primary group is kvm"
            return False, f"{pw.pw_name} is not in group kvm"
        except (KeyError, ImportError):
            pass
    if entry.gr_gid == os.getgid():
        return True, "primary group is kvm"
    return False, "current gid is not the kvm group"


def openable(path: str) -> tuple[bool, str]:
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError as exc:
        return False, f"{path}: {exc.strerror}"
    else:
        os.close(fd)
        return True, f"{path} opens read-write"


def cpu_virt() -> tuple[bool, str]:
    text = read("/proc/cpuinfo")
    flags = set(re.findall(r"\b(vmx|svm)\b", text))
    if not text:
        return False, "/proc/cpuinfo is not readable"
    if flags:
        return True, "CPU reports " + ", ".join(sorted(flags)) + " (hardware virtualization exposed)"
    if platform.machine().lower() in {"aarch64", "arm64"}:
        return False, "no vmx or svm flag (expected on arm64; check el2 exposure on the host)"
    return False, "no vmx or svm flag in /proc/cpuinfo"


def find_any(paths: list[str], globs: list[str]) -> str:
    import glob  # noqa: PLC0415 - only used here

    for path in paths:
        if os.path.exists(path):
            return path
    for pattern in globs:
        for hit in sorted(glob.glob(pattern)):
            return hit
    return ""


def check_virtualization() -> dict:
    ok, detail = cpu_virt()
    loaded = os.path.isdir("/sys/module/kvm")
    if loaded:
        detail += "; kvm module loaded"
    return {"id": "virtualization", "core": True, "ok": ok, "detail": detail}


def check_kvm_device() -> dict:
    if not os.path.exists("/dev/kvm"):
        return {"id": "kvm_device", "core": True, "ok": False, "detail": "/dev/kvm is missing"}
    good, why = openable("/dev/kvm")
    detail = "/dev/kvm present, " + ("opens read-write" if good else "not openable: " + why)
    return {"id": "kvm_device", "core": True, "ok": good, "detail": detail}


def check_kvm_group() -> dict:
    ok, detail = in_kvm_group()
    return {"id": "kvm_group", "core": False, "ok": bool(ok), "detail": detail}


def check_qemu() -> dict:
    names = ["qemu-system-x86_64", "qemu-system-aarch64"]
    found = [name for name in names if shutil.which(name)]
    detail = f"found {', '.join(found)}" if found else "no qemu-system-* on PATH"
    return {"id": "qemu", "core": True, "ok": bool(found), "detail": detail}


def check_firmware() -> dict:
    hit = find_any(
        [],
        [
            "/usr/share/OVMF/OVMF_CODE*.fd",
            "/usr/share/ovmf/OVMF.fd",
            "/usr/share/edk2*/**/*.fd",
            "/usr/share/qemu/edk2-*.fd",
            "/usr/share/edk2/ovmf/*.fd",
        ],
    )
    detail = hit or "no OVMF or edk2 firmware found under /usr/share"
    return {"id": "firmware", "core": True, "ok": bool(hit), "detail": detail}


def check_virtiofsd() -> dict:
    path = shutil.which("virtiofsd")
    if path:
        return {"id": "virtiofsd", "core": False, "ok": True, "detail": f"found {path}"}
    return {
        "id": "virtiofsd",
        "core": False,
        "ok": False,
        "detail": "no virtiofsd on PATH (on Ubuntu 22.04 the app uses a bundled copy, so this "
                  "alone is not a blocker there)",
    }


def check_vsock() -> dict:
    path = "/dev/vhost-vsock"
    if not os.path.exists(path):
        return {"id": "vsock", "core": True, "ok": False, "detail": f"{path} is missing"}
    good, why = openable(path)
    return {"id": "vsock", "core": True, "ok": good, "detail": why}


def check_modules() -> dict:
    release = platform.release()
    path = f"/lib/modules/{release}"
    ok = os.path.isdir(path)
    detail = f"{path} present" if ok else f"no {path}: the kernel ships no module directory"
    return {"id": "modules", "core": False, "ok": ok, "detail": detail}


def check_distro() -> dict:
    info = os_release()
    name = info.get("PRETTY_NAME") or info.get("ID") or "unknown"
    ident = info.get("ID", "")
    version = info.get("VERSION_ID", "")
    debian_based = ident in {"ubuntu", "debian", "linuxmint", "pop", "raspbian"} or "debian" in info.get(
        "ID_LIKE", ""
    )
    detail = f"{name} ({platform.machine()})"
    if not debian_based:
        detail += "; not Debian-based, so Anthropic's apt package is not the route here"
    return {"id": "distro", "core": False, "ok": debian_based, "detail": detail}


def check_bwrap() -> dict:
    path = shutil.which("bwrap")
    return {
        "id": "bubblewrap",
        "core": False,
        "ok": bool(path),
        "detail": (f"found {path}" if path else "no bwrap on PATH")
        + " (only relevant to the opt-in COWORK_VM_BACKEND=bwrap path in the repackaged build)",
    }


def run_checks() -> list[dict]:
    order = [
        check_distro,
        check_virtualization,
        check_kvm_device,
        check_kvm_group,
        check_qemu,
        check_firmware,
        check_virtiofsd,
        check_vsock,
        check_modules,
        check_bwrap,
    ]
    return [fn() for fn in order]


def render(results: list[dict]) -> str:
    width = max(len(r["id"]) for r in results) + 2
    lines = ["", "Claude Desktop for Linux, pre-flight", "=" * 40, ""]
    for item in results:
        mark = "PASS" if item["ok"] else ("FAIL" if item["core"] else "note")
        tag = "" if item["core"] else "  (not one of the five)"
        lines.append(f"{item['id']:<{width}}{mark:<6}{item['detail']}{tag}")
        if not item["ok"] and item["id"] in FIX:
            wrapped = FIX[item["id"]]
            lines.append(f"{'':<{width}}{'':<6}fix: {wrapped}")
    core = [r for r in results if r["core"]]
    missing = [r["id"] for r in core if not r["ok"]]
    lines.append("")
    if missing:
        lines.append(f"{len(core) - len(missing)} of {len(core)} requirements met. Missing: {', '.join(missing)}.")
        lines.append(
            "Cowork will not start its virtual machine on this host until those pass. The desktop app's"
        )
        lines.append(
            "chat still runs natively; only the work that needs a VM is blocked."
        )
    else:
        lines.append(f"All {len(core)} requirements met. Restart the app after installing anything:")
        lines.append("it checks once, at launch.")
    lines.append("")
    lines.append("If the host cannot pass them, the other route is an agent that runs on a cloud")
    lines.append("computer in the browser, with nothing to virtualise locally: https://kortix.com")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check this host against the requirements of Claude Desktop for Linux and Cowork on Linux.",
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = parser.parse_args(argv)

    try:
        results = run_checks()
    except Exception as exc:  # pragma: no cover - defensive
        print(f"preflight failed: {exc}", file=sys.stderr)
        return 2

    core = [r for r in results if r["core"]]
    ok = all(r["ok"] for r in core)

    if args.json:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "requirements": core,
                    "notes": [r for r in results if not r["core"]],
                    "host": {
                        "machine": platform.machine(),
                        "kernel": platform.release(),
                        "distro": os_release().get("PRETTY_NAME", ""),
                    },
                },
                indent=2,
            )
        )
    else:
        print(render(results))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
