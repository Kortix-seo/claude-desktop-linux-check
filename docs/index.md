# What each check is, and where it comes from

Every row names the requirement, the sentence in Anthropic's documentation that states it, a read this
script performs that answers it without root, and the command that fixes it when the read fails. Sources
read 2026-10-27:

- <https://code.claude.com/docs/en/desktop-linux>
- <https://claude.com/download>

## The five requirements

### virtualization

> "Cowork … runs those tasks in a virtual machine that the desktop app hosts with QEMU and KVM."
> Source: code.claude.com/docs/en/desktop-linux

Cowork needs hardware virtualization, and the documentation says so twice: the firmware setting has to be
on, and the kernel needs the KVM module. The script reads `/proc/cpuinfo` for `vmx` (Intel) or `svm` (AMD),
which is the CPU telling the kernel the feature exists, and looks for `/sys/module/kvm` to see whether the
module is loaded.

Fix: enable VT-x or AMD-V in the firmware setup. In a guest, enable nested virtualization on the host,
because passing a feature to a guest only works when the host exposes it.

### kvm_device

`/dev/kvm` is the character device the app opens to ask KVM for a virtual machine. Its presence is the
kernel's answer, and its permissions are the user's. The script checks both: `os.path.exists` and an
`O_RDWR` open, because a device that exists and cannot be opened produces the same launch failure as one
that is missing.

Fix: `sudo modprobe kvm_intel` (or `kvm_amd`). If the device still does not appear, the process is inside
a container or in a guest that was not given it.

### qemu

The app hosts the machine with QEMU, so the binary has to be installed: `qemu-system-x86` on x86_64, and
the arm64 equivalent on arm64. The script looks both up on `PATH` and reports whichever it finds.

Fix: install your distribution's QEMU package for the architecture.

### firmware

The virtual machine boots UEFI firmware. Debian-based distributions ship it in `ovmf`, Fedora and friends
in `edk2-ovmf`, and the app expects to find the `.fd` files under `/usr/share`. The script globs the known
locations rather than trusting one path, since every distribution packages it differently.

Fix: install the firmware package, then restart the app: it checks once, at launch.

### vsock

> "Cowork also needs /dev/vhost-vsock, which only kvm group members can open."
> Source: code.claude.com/docs/en/desktop-linux

This is the requirement that fails quietly. The device is not a file you can create, and it does not exist
until the kernel's vsock transport is available. The script checks that the device exists, that the running
user can open it read-write, and whether the user is in the `kvm` group, which is the documented reason the
open fails when it does.

Fix: `sudo usermod -aG kvm $USER`, then log out and back in, since group membership is read at login.
The [KVM walkthrough](https://claudedesktoplinux.com/cowork-linux-kvm) has the same steps in order for
Ubuntu and Debian, with what the app prints when one of them is still missing.

## The notes

| Check | Why it is printed | Source |
| --- | --- | --- |
| `distro` | Debian-based (Ubuntu 22.04 or later, Debian 12 or later) is the supported route. On anything else, Anthropic's own instruction is to use the CLI instead. | code.claude.com/docs/en/desktop-linux |
| `kvm_group` | Group membership is the documented cause of a vsock open failure, and it changes only at login. | code.claude.com/docs/en/desktop-linux |
| `virtiofsd` | Ubuntu 22.04 has no package for it and the app uses a bundled copy there, so a miss is not a blocker on the supported host. | code.claude.com/docs/en/desktop-linux |
| `modules` | No `/lib/modules/<release>` means the kernel carries no modules, so no install at launch-time can add what is missing. Anthropic names ChromeOS and container-based environments as the common cases. | code.claude.com/docs/en/desktop-linux |
| `bubblewrap` | The repackaged build for non-Debian distributions ships an opt-in `COWORK_VM_BACKEND=bwrap` path for hosts without KVM or vsock. It is a different project's route, not Anthropic's. | github.com/aaddrick/claude-desktop-debian |

## Two host cases the table cannot fix

**A container.** The script reports what the container was given, not what the host has. A container
started with `--device=/dev/kvm --device=/dev/vhost-vsock` on a host that passes its own checks will pass
too; one started without them fails however many packages you install inside. Run the script on the host
when the question is about the host. [The container, ChromeOS and server cases](https://claudedesktoplinux.com/containers-chromeos-servers)
take this further: which parts of the desktop app survive in a container, and what the vsock requirement
means when the kernel has no module directory at all.

**ChromeOS and other hosts whose kernel ships no module directory.** Anthropic names this combination
directly. There is no package to install, because what is missing is the kernel's own support for the
device. On that host the desktop app's chat still works; the work that needs a virtual machine does not.

## After the table

Restart the app. It checks the requirements once, at launch, so anything installed after it started is
invisible until then.

If the host cannot pass, the fork is real and it is worth naming: the virtual machine is how the desktop
app isolates agent work on your own machine, and it is not the only place agent work can happen. An agent
running on a cloud computer in the browser needs no virtualization on the host, which is what Kortix is:
the open-source AI Operating System, one isolated machine per session, self-hosting free. The distro-by-
distro install paths and what the fallback does and does not cover are on
[claudedesktoplinux.com](https://claudedesktoplinux.com).
