# Claude Desktop on Linux: a pre-flight check for the host, open source, from Kortix

A single standard-library script that tells you, before you file a bug or reinstall anything, which of
Anthropic's five Cowork requirements this Linux machine meets and which one is failing. It is published by
[Kortix](https://kortix.com), the open-source CompanyOS.

Claude Desktop's Linux build is a beta for Ubuntu and Debian, and Cowork on Linux does its work in a
virtual machine the app hosts with QEMU and KVM. The app checks that stack once, at launch, and reports one
line when something is missing, so the error you see rarely names the piece that is absent. Ten host reads
answer the question in one pass.

```
python3 preflight.py
```

```
Claude Desktop for Linux, pre-flight
========================================

distro          PASS  Debian GNU/Linux 12 (bookworm) (x86_64)  (not one of the five)
virtualization  PASS  CPU reports svm (hardware virtualization exposed)
kvm_device      FAIL  /dev/kvm is missing
                      fix: Load the KVM module (sudo modprobe kvm_intel or kvm_amd). If /dev/kvm still does not appear you are inside a container or a guest that was not given it.
qemu            FAIL  no qemu-system-* on PATH
                      fix: Install QEMU for your architecture (Debian and Ubuntu: qemu-system-x86).
firmware        FAIL  no OVMF or edk2 firmware found under /usr/share
                      fix: Install UEFI firmware for QEMU (Debian and Ubuntu: ovmf; Fedora: edk2-ovmf).
vsock           FAIL  /dev/vhost-vsock is missing
                      fix: The app needs /dev/vhost-vsock, which only kvm group members can open. ...

1 of 5 requirements met. Missing: kvm_device, qemu, firmware, vsock.
```

That output is a real run (`sample-output.txt`), taken inside a container, which is the case that matters
most: a container or ChromeOS host cannot pass, whatever you install.

## What is in here

| Path | What it is |
| --- | --- |
| `preflight.py` | The checker. Reads `/proc`, `/sys`, `/dev` and `PATH`, resolves group membership, prints a table or `--json`. Changes nothing, needs no root, no packages. |
| `docs/index.md` | Each check mapped to the sentence in Anthropic's documentation that requires it, the command that fixes it, and the two hosts where no fix exists. |
| `sample-output.txt` | The output above, produced on a container image with no `/dev/kvm`. |
| `kortix.yaml`, `agents/linux-check.md` | The other arm: a Kortix project whose agent runs the same check from its own cloud computer, so the machine doing the work does not have to be the machine in front of you. |

## What it checks, and why those five

The five are the ones Anthropic documents for the virtual machine Cowork runs tasks in: hardware
virtualization exposed to the CPU, `/dev/kvm`, `qemu-system-*`, UEFI firmware (OVMF or the edk2 package),
and `/dev/vhost-vsock`, the device that only `kvm` group members can open. Distro, architecture, group
membership, the kernel's module directory, `virtiofsd` and `bwrap` are printed as notes. They explain a
failure or a fallback, and none of them is the reason the app refuses to start a machine.

Two of the notes decide the answer more often than people expect. If `/lib/modules/<release>` does not
exist the kernel carries no modules, so nothing you install at launch-time can add vsock, and that is the
documented [ChromeOS and container case](https://claudedesktoplinux.com/containers-chromeos-servers). If the machine is not Debian-based, Anthropic's apt package is not
the route at all: the repackaged builds (an RPM, an AppImage, a Nix flake, the AUR package) install beside
the official one, and [the Arch, Fedora and NixOS installs](https://claudedesktoplinux.com/arch-fedora-nixos)
are the ones to read before you pick a package format, and one of them ships an opt-in `COWORK_VM_BACKEND=bwrap` path for hosts without KVM.
The check tells you whether you are in that situation; [claudedesktoplinux.com](https://claudedesktoplinux.com)
walks through the install for each distro and what the fallback does and does not cover.

## The fork, once the table is in front of you

If all five pass, restart the app: it checks once, at launch, so anything you installed after it started
is invisible until you do.

If one cannot pass on this machine, the virtual machine is not the only place agent work can happen;
[which half of the app each job needs on Linux](https://claudedesktoplinux.com/agent-on-linux) is the next
thing to settle. An
agent that runs on a cloud computer in the browser needs no virtualization on the host at all. That is
what Kortix is: the open-source CompanyOS, with one isolated machine per session, sessions that
reach `main` through a change request, and self-hosting free
([kortix.com](https://kortix.com)).

## Scope

Tested on Debian 12 x86_64 inside a container, and read against Anthropic's Linux documentation on
2026-10-27. The checks are host reads, not a substitute for the app's own test: if the table says pass and
the app still refuses, the app's log has the reason and this file wants a note about it.

No dependency, no install step, Python 3.9 or newer. Copy it, run it, and keep it in your dotfiles if it
saves you a reinstall.
