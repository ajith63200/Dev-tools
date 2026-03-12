#!/usr/bin/env python3
"""
Kubernetes Auto Installer — Enhanced Python Edition
Supports: Ubuntu 20.04 / 22.04 / 24.04
K8s: v1.29  |  CNI: Calico  |  Runtime: containerd
"""

import argparse
import itertools
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# ─── Constants ───────────────────────────────────────────────────────────────
K8S_VERSION   = "1.29"
POD_CIDR      = "192.168.0.0/16"
CALICO_URL    = "https://docs.projectcalico.org/manifests/calico.yaml"
LOG_DIR       = Path("/var/log")
LOG_FILE      = LOG_DIR / f"k8s-installer-{datetime.now():%Y%m%d_%H%M%S}.log"
JOIN_CMD_FILE = Path("/root/kubeadm-join.sh")

MIN_RAM_MB    = 1500
MIN_CPUS_MASTER = 2

# ─── ANSI Colours ────────────────────────────────────────────────────────────
class C:
    RED    = "\033[0;31m"
    GREEN  = "\033[0;32m"
    YELLOW = "\033[1;33m"
    CYAN   = "\033[0;36m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"
    
    @staticmethod
    def supports_color() -> bool:
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"{code}{text}{C.RESET}" if C.supports_color() else text

# ─── Logging setup ───────────────────────────────────────────────────────────
def setup_logging() -> logging.Logger:
    global LOG_FILE  # must be declared before any use of LOG_FILE in this scope
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        LOG_FILE.touch(mode=0o666, exist_ok=True)
    except PermissionError:
        # Fall back to /tmp if /var/log isn't writable without sudo yet
        LOG_FILE = Path(f"/tmp/k8s-installer-{datetime.now():%Y%m%d_%H%M%S}.log")

    logger = logging.getLogger("k8s")
    logger.setLevel(logging.DEBUG)

    # File handler — plain text, full debug
    fh = logging.FileHandler(LOG_FILE)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    logger.addHandler(fh)
    return logger

log = setup_logging()


# ─── Pretty printers ─────────────────────────────────────────────────────────
def section(title: str) -> None:
    bar = "─" * (len(title) + 6)
    print(f"\n{_c(C.BOLD + C.CYAN, bar)}")
    print(_c(C.BOLD + C.CYAN, f"  {title}"))
    print(_c(C.BOLD + C.CYAN, bar))
    log.info("=== %s ===", title)

def ok(msg: str)   -> None: print(_c(C.GREEN,  f"  [✔] {msg}")); log.info(msg)
def info(msg: str) -> None: print(_c(C.CYAN,   f"  [➜] {msg}")); log.info(msg)
def warn(msg: str) -> None: print(_c(C.YELLOW, f"  [⚠] {msg}")); log.warning(msg)
def fail(msg: str) -> None: print(_c(C.RED,    f"  [✖] {msg}"), file=sys.stderr); log.error(msg)


# ─── Spinner ─────────────────────────────────────────────────────────────────
class Spinner:
    """Thread-safe terminal spinner for long-running operations."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, message: str):
        self.message = message
        self._stop   = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def __enter__(self):
        if C.supports_color():
            self._thread.start()
        else:
            print(f"  … {self.message}")
        return self

    def __exit__(self, exc_type, *_):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join()
        if exc_type is None:
            print(f"\r{_c(C.GREEN, '  [✔]')} {self.message:<60}")
        else:
            print(f"\r{_c(C.RED,   '  [✖]')} {self.message:<60}")

    def _spin(self):
        for frame in itertools.cycle(self.FRAMES):
            if self._stop.is_set():
                break
            print(f"\r{_c(C.CYAN, f'  {frame}')} {self.message}", end="", flush=True)
            time.sleep(0.1)


# ─── Result dataclass ─────────────────────────────────────────────────────────
@dataclass
class CmdResult:
    cmd:        str
    returncode: int
    stdout:     str = ""
    stderr:     str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


# ─── Command runner ──────────────────────────────────────────────────────────
def run(
    cmd: str,
    *,
    check: bool = True,
    capture: bool = False,
    env: Optional[dict] = None,
    retries: int = 0,
    retry_delay: float = 5.0,
    spinner_msg: Optional[str] = None,
) -> CmdResult:
    """
    Execute a shell command with optional spinner, retry, and capture.

    Args:
        cmd:         Shell command string.
        check:       Raise SystemExit on non-zero return code.
        capture:     Return stdout/stderr instead of streaming to terminal.
        env:         Extra environment variables merged with os.environ.
        retries:     Number of retry attempts on failure.
        retry_delay: Seconds to wait between retries.
        spinner_msg: If set, display a spinner instead of raw output.
    """
    merged_env = {**os.environ, **(env or {})}
    log.debug("RUN: %s", cmd)

    def _execute() -> CmdResult:
        result = subprocess.run(
            cmd,
            shell=True,
            text=True,
            capture_output=capture,
            env=merged_env,
        )
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if stdout: log.debug("STDOUT: %s", stdout)
        if stderr: log.debug("STDERR: %s", stderr)
        return CmdResult(cmd, result.returncode, stdout, stderr)

    attempt = 0
    ctx = Spinner(spinner_msg) if spinner_msg else _NullContext()

    with ctx:
        while True:
            result = _execute()
            if result.ok:
                return result
            attempt += 1
            if attempt <= retries:
                warn(f"Retry {attempt}/{retries} for: {cmd}")
                log.warning("Retry %d/%d: %s", attempt, retries, cmd)
                time.sleep(retry_delay)
            else:
                break

    if check:
        fail(f"Command failed (exit {result.returncode}): {cmd}")
        if result.stderr:
            fail(f"stderr: {result.stderr[:400]}")
        fail(f"Full output in: {LOG_FILE}")
        sys.exit(result.returncode)

    return result


class _NullContext:
    """No-op context manager (used when no spinner is requested)."""
    def __enter__(self): return self
    def __exit__(self, *_): pass


# ─── Pre-flight checks ───────────────────────────────────────────────────────
@dataclass
class PreflightResult:
    passed:   bool = True
    warnings: List[str] = field(default_factory=list)
    errors:   List[str] = field(default_factory=list)

    def add_warn(self, msg: str)  -> None: self.warnings.append(msg); warn(msg)
    def add_error(self, msg: str) -> None: self.errors.append(msg);   fail(msg); self.passed = False


def preflight_checks(node_type: str) -> None:
    section("Pre-flight Checks")
    r = PreflightResult()

    # ── Root / sudo ──
    try:
        subprocess.run(["sudo", "-n", "true"], check=True, capture_output=True)
        ok("sudo: passwordless access confirmed")
    except subprocess.CalledProcessError:
        if os.geteuid() != 0:
            r.add_error("Run as root or configure passwordless sudo.")

    # ── OS ──
    os_release = Path("/etc/os-release")
    if os_release.exists():
        content = os_release.read_text()
        if "ubuntu" in content.lower():
            codename = re.search(r'VERSION_CODENAME="?(\w+)"?', content)
            ok(f"OS: Ubuntu ({codename.group(1) if codename else 'unknown'})")
        else:
            r.add_warn("Non-Ubuntu OS detected — script targets Ubuntu LTS.")
    else:
        r.add_warn("Cannot determine OS.")

    # ── RAM ──
    meminfo = Path("/proc/meminfo").read_text()
    ram_kb  = int(re.search(r"MemTotal:\s+(\d+)", meminfo).group(1))
    ram_mb  = ram_kb // 1024
    if ram_mb < MIN_RAM_MB:
        r.add_warn(f"RAM is {ram_mb} MB (min recommended: {MIN_RAM_MB} MB).")
    else:
        ok(f"RAM: {ram_mb} MB")

    # ── CPUs ──
    cpus = os.cpu_count() or 1
    if node_type == "master" and cpus < MIN_CPUS_MASTER:
        r.add_warn(f"Master needs ≥ {MIN_CPUS_MASTER} CPUs. Found: {cpus}")
    else:
        ok(f"CPUs: {cpus}")

    # ── Required binaries ──
    for binary in ("curl", "gpg", "systemctl"):
        if shutil.which(binary):
            ok(f"Binary found: {binary}")
        else:
            r.add_error(f"Required binary not found: {binary}")

    # ── Internet connectivity ──
    probe = run(
        f"curl -fsSL --max-time 10 -o /dev/null -w '%{{http_code}}' https://pkgs.k8s.io",
        check=False, capture=True, spinner_msg="Checking internet connectivity …"
    )
    if probe.ok and probe.stdout.strip() in ("200", "301", "302"):
        ok("Network: pkgs.k8s.io reachable")
    else:
        r.add_error("Cannot reach pkgs.k8s.io — check your network.")

    # ── Existing K8s install ──
    for pkg in ("kubectl", "kubeadm", "kubelet"):
        existing = run(f"dpkg -l {pkg} 2>/dev/null", check=False, capture=True)
        if existing.ok and "ii" in existing.stdout:
            r.add_warn(f"{pkg} already installed — will reinstall.")

    if not r.passed:
        fail("Pre-flight checks failed. Resolve the errors above and retry.")
        sys.exit(1)

    if r.warnings:
        info(f"{len(r.warnings)} warning(s) noted — continuing anyway.")


# ─── System update ───────────────────────────────────────────────────────────
def update_system() -> None:
    section("System Update")
    run("sudo apt-get update -y",
        spinner_msg="Updating package index …", retries=2)
    run("sudo apt-get upgrade -y",
        spinner_msg="Upgrading installed packages …", retries=1)
    run("sudo apt-get install -y apt-transport-https ca-certificates curl gnupg socat conntrack",
        spinner_msg="Installing prerequisites …", retries=2)
    ok("System is up to date.")


# ─── Swap ────────────────────────────────────────────────────────────────────
def disable_swap() -> None:
    section("Disabling Swap")
    run("sudo swapoff -a", spinner_msg="Disabling active swap …")
    run("sudo sed -i.bak '/\\bswap\\b/s/^/#/' /etc/fstab",
        spinner_msg="Commenting swap in /etc/fstab …")
    ok("Swap disabled.")


# ─── Kernel modules ──────────────────────────────────────────────────────────
def configure_kernel() -> None:
    section("Kernel Modules & sysctl")

    modules_conf = "/etc/modules-load.d/k8s.conf"
    run(f"echo -e 'overlay\\nbr_netfilter' | sudo tee {modules_conf}",
        spinner_msg="Persisting kernel modules …", capture=True)
    run("sudo modprobe overlay")
    run("sudo modprobe br_netfilter")
    ok("Kernel modules loaded: overlay, br_netfilter")

    sysctl_conf = "/etc/sysctl.d/99-k8s.conf"
    params = "\n".join([
        "net.bridge.bridge-nf-call-ip6tables = 1",
        "net.bridge.bridge-nf-call-iptables  = 1",
        "net.ipv4.ip_forward                 = 1",
    ])
    run(f"printf '{params}\\n' | sudo tee {sysctl_conf}",
        spinner_msg="Writing sysctl config …", capture=True)
    run("sudo sysctl --system", spinner_msg="Applying sysctl …", capture=True)
    ok("sysctl parameters applied.")


# ─── Containerd ──────────────────────────────────────────────────────────────
def install_containerd() -> None:
    section("Container Runtime (containerd)")

    run("sudo apt-get install -y containerd",
        spinner_msg="Installing containerd …", retries=2)
    run("sudo mkdir -p /etc/containerd",
        spinner_msg="Creating containerd config dir …", capture=True)

    # Generate default config
    run("containerd config default | sudo tee /etc/containerd/config.toml",
        spinner_msg="Generating containerd config …", capture=True)

    # CRITICAL: enable SystemdCgroup — without this kubeadm init silently breaks
    run("sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml",
        spinner_msg="Enabling SystemdCgroup …")
    ok("SystemdCgroup = true (required for kubeadm compatibility)")

    run("sudo systemctl restart containerd",
        spinner_msg="Restarting containerd …")
    run("sudo systemctl enable containerd",
        spinner_msg="Enabling containerd on boot …", capture=True)

    # Verify containerd is running
    status = run("sudo systemctl is-active containerd", check=False, capture=True)
    if status.stdout.strip() == "active":
        ok("containerd is running.")
    else:
        fail("containerd failed to start. Check: journalctl -u containerd")
        sys.exit(1)


# ─── Kubernetes packages ─────────────────────────────────────────────────────
def install_k8s_packages() -> None:
    section(f"Kubernetes Packages (v{K8S_VERSION})")

    run("sudo mkdir -p /etc/apt/keyrings",
        spinner_msg="Creating keyrings dir …", capture=True)

    keyring = "/etc/apt/keyrings/kubernetes-apt-keyring.gpg"
    run(
        f"curl -fsSL https://pkgs.k8s.io/core:/stable:/v{K8S_VERSION}/deb/Release.key"
        f" | sudo gpg --dearmor --yes -o {keyring}",
        spinner_msg="Importing K8s GPG key …", retries=2,
    )

    repo = f"deb [signed-by={keyring}] https://pkgs.k8s.io/core:/stable:/v{K8S_VERSION}/deb/ /"
    run(f"echo '{repo}' | sudo tee /etc/apt/sources.list.d/kubernetes.list",
        spinner_msg="Adding K8s apt repo …", capture=True)

    run("sudo apt-get update", spinner_msg="Refreshing package index …", retries=2)
    run("sudo apt-get install -y kubelet kubeadm kubectl",
        spinner_msg="Installing kubelet kubeadm kubectl …", retries=2)
    run("sudo apt-mark hold kubelet kubeadm kubectl",
        spinner_msg="Holding package versions …", capture=True)

    version = run("kubectl version --client --short 2>/dev/null || kubectl version --client",
                  check=False, capture=True)
    ok(f"kubectl: {version.stdout.splitlines()[0] if version.stdout else 'installed'}")

    run("sudo systemctl enable --now kubelet",
        spinner_msg="Enabling kubelet …", capture=True)


# ─── Master node ─────────────────────────────────────────────────────────────
def setup_master(advertise_addr: Optional[str] = None) -> None:
    section("Initialising Control Plane")

    if not advertise_addr:
        # Auto-detect primary IP
        result = run("hostname -I | awk '{print $1}'", check=False, capture=True)
        detected = result.stdout.strip()
        prompt = f"API server advertise address [{detected or 'auto'}]: "
        user_input = input(f"\n  {prompt}").strip()
        advertise_addr = user_input or detected or ""

    flags = f"--pod-network-cidr={POD_CIDR}"
    if advertise_addr:
        flags += f" --apiserver-advertise-address={advertise_addr}"

    info("Running kubeadm init (this can take 2–3 minutes) …")
    run(f"sudo kubeadm init {flags}", spinner_msg="kubeadm init …")
    ok("Control plane initialised.")

    # Configure kubectl
    section("Configuring kubectl")
    kube_dir = Path.home() / ".kube"
    kube_dir.mkdir(parents=True, exist_ok=True)
    run(f"sudo cp -f /etc/kubernetes/admin.conf {kube_dir}/config",
        spinner_msg="Copying admin.conf …")
    uid, gid = os.getuid(), os.getgid()
    run(f"sudo chown {uid}:{gid} {kube_dir}/config",
        spinner_msg="Setting kubeconfig ownership …")
    ok(f"kubectl configured for user '{os.environ.get('USER', 'current')}'")

    # Install Calico CNI
    section("Installing Calico CNI")
    run(f"kubectl apply -f {CALICO_URL}",
        spinner_msg="Applying Calico manifest …", retries=2)
    ok("Calico CNI applied.")

    # Wait for node Ready
    section("Waiting for Node Ready")
    _wait_for_node_ready(timeout=180)

    # Print + save join command
    section("Worker Join Command")
    join_result = run("kubeadm token create --print-join-command", capture=True)
    join_cmd    = join_result.stdout.strip()

    print(f"\n  {_c(C.BOLD + C.GREEN, 'Run this on each worker:')}")
    print(f"  {_c(C.YELLOW, join_cmd)}\n")

    try:
        JOIN_CMD_FILE.write_text(f"#!/bin/bash\nsudo {join_cmd}\n")
        JOIN_CMD_FILE.chmod(0o755)
        ok(f"Join command saved to {JOIN_CMD_FILE}")
    except PermissionError:
        warn(f"Could not save join command to {JOIN_CMD_FILE} (not root)")

    # Post-install hints
    section("Quick Reference")
    cmds = [
        ("kubectl get nodes",        "Verify node status"),
        ("kubectl get pods -A",      "Check all pods"),
        ("kubectl cluster-info",     "Show cluster endpoints"),
        (f"cat {JOIN_CMD_FILE}",     "Re-read join command"),
    ]
    for cmd, desc in cmds:
        print(f"    {_c(C.CYAN, cmd):<55}  {desc}")


def _wait_for_node_ready(timeout: int = 180) -> None:
    info(f"Polling node status (up to {timeout}s) …")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = run("kubectl get nodes --no-headers 2>/dev/null", check=False, capture=True)
        if result.ok and " Ready" in result.stdout:
            ok("Node is Ready.")
            run("kubectl get nodes", capture=False)
            return
        time.sleep(6)
    warn("Node not Ready within timeout — run 'kubectl get nodes' to check manually.")


# ─── Worker node ─────────────────────────────────────────────────────────────
def setup_worker() -> None:
    section("Joining Cluster as Worker")

    print(f"\n  {_c(C.BOLD, 'Paste the kubeadm join command from the master node:')}")
    print(f"  {_c(C.CYAN, 'Format: kubeadm join <IP>:6443 --token ... --discovery-token-ca-cert-hash ...')}\n")

    join_cmd = ""
    while not join_cmd:
        join_cmd = input("  Join command: ").strip()
        if not join_cmd:
            warn("Join command cannot be empty.")
        elif not re.search(r"kubeadm\s+join\s+\S+:\d+", join_cmd):
            fail("That doesn't look like a valid kubeadm join command.")
            join_cmd = ""

    info("Executing join command …")
    run(f"sudo {join_cmd}", spinner_msg="Joining cluster …")
    ok("Worker successfully joined the cluster.")
    info("Verify on the master with: kubectl get nodes")


# ─── Dry-run mode ─────────────────────────────────────────────────────────────
def dry_run_summary(node_type: str) -> None:
    section("Dry Run — Steps That Would Execute")
    steps = [
        "Pre-flight checks (OS, RAM, CPU, network, existing packages)",
        "System update & prerequisite installation",
        "Disable swap + update /etc/fstab",
        "Load kernel modules (overlay, br_netfilter) + sysctl",
        "Install & configure containerd (SystemdCgroup=true)",
        f"Add K8s apt repo (v{K8S_VERSION}), install kubelet/kubeadm/kubectl",
    ]
    if node_type == "master":
        steps += [
            f"kubeadm init --pod-network-cidr={POD_CIDR}",
            "Configure ~/.kube/config",
            "Deploy Calico CNI",
            f"Save join command to {JOIN_CMD_FILE}",
        ]
    else:
        steps.append("Prompt for join command and execute kubeadm join")

    for i, step in enumerate(steps, 1):
        print(f"  {_c(C.CYAN, str(i).rjust(2))}. {step}")
    print()
    info("Re-run without --dry-run to execute.")


# ─── CLI ─────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="k8s_installer.py",
        description="Kubernetes Auto Installer — Ubuntu LTS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  sudo python3 k8s_installer.py                      # interactive
  sudo python3 k8s_installer.py --node-type master   # skip prompt
  sudo python3 k8s_installer.py --node-type worker   # skip prompt
  python3 k8s_installer.py --dry-run --node-type master
        """,
    )
    parser.add_argument("--node-type", choices=["master", "worker"],
                        help="Node role (skips interactive prompt)")
    parser.add_argument("--advertise-addr", default=None,
                        help="API server advertise address (master only)")
    parser.add_argument("--pod-cidr", default=POD_CIDR,
                        help=f"Pod network CIDR (default: {POD_CIDR})")
    parser.add_argument("--k8s-version", default=K8S_VERSION,
                        help=f"Kubernetes version to install (default: {K8S_VERSION})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print steps without executing anything")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="Skip pre-flight system checks")
    parser.add_argument("--version", action="version",
                        version=f"k8s_installer 2.0 (K8s {K8S_VERSION})")
    return parser.parse_args()


# ─── Banner ──────────────────────────────────────────────────────────────────
def print_banner() -> None:
    lines = [
        "╔══════════════════════════════════════════════╗",
        "║    Kubernetes Auto Installer  v2.0  (Py)     ║",
        f"║       K8s {K8S_VERSION}  |  containerd  |  Calico       ║",
        "╚══════════════════════════════════════════════╝",
    ]
    for line in lines:
        print(_c(C.BOLD + C.CYAN, "  " + line))
    print(f"\n  Log → {_c(C.YELLOW, str(LOG_FILE))}\n")


# ─── Summary ─────────────────────────────────────────────────────────────────
def print_summary(node_type: str, elapsed: float) -> None:
    section("Installation Summary")
    rows = [
        ("Node type",   node_type),
        ("K8s version", f"v{K8S_VERSION}"),
        ("Runtime",     "containerd (SystemdCgroup=true)"),
        ("CNI",         "Calico" if node_type == "master" else "inherited from master"),
        ("Log file",    str(LOG_FILE)),
        ("Elapsed",     f"{elapsed:.0f}s"),
    ]
    if node_type == "master":
        rows.append(("Join cmd", str(JOIN_CMD_FILE)))
    for label, value in rows:
        print(f"  {_c(C.BOLD, label+':'):<30} {value}")
    print()
    ok(f"All done! Kubernetes {node_type} node is ready. 🎉")


# ─── Main ────────────────────────────────────────────────────────────────────
def main() -> None:
    args = parse_args()

    # Apply CLI overrides to globals
    global K8S_VERSION, POD_CIDR
    K8S_VERSION = args.k8s_version
    POD_CIDR    = args.pod_cidr

    print_banner()

    # ── Node type ──
    if args.node_type:
        node_type = args.node_type
        ok(f"Node type (from args): {node_type}")
    else:
        section("Node Configuration")
        print(f"  {_c(C.BOLD, 'Select node role:')}")
        print(f"    {_c(C.CYAN, '1)')} master  — Control plane")
        print(f"    {_c(C.CYAN, '2)')} worker  — Data plane\n")
        while True:
            choice = input("  Choice [1/2 or master/worker]: ").strip().lower()
            if choice in ("1", "master"):
                node_type = "master"; break
            elif choice in ("2", "worker"):
                node_type = "worker"; break
            warn("Invalid — enter 1, 2, master, or worker.")

        new_host = input("\n  Hostname for this node (blank to keep current): ").strip()
        if new_host:
            run(f"sudo hostnamectl set-hostname {new_host}",
                spinner_msg=f"Setting hostname to {new_host} …")
            ok(f"Hostname: {new_host}")

    # ── Dry run ──
    if args.dry_run:
        dry_run_summary(node_type)
        return

    # ── Execute ──
    start = time.monotonic()
    try:
        if not args.skip_preflight:
            preflight_checks(node_type)

        update_system()
        disable_swap()
        configure_kernel()
        install_containerd()
        install_k8s_packages()

        if node_type == "master":
            setup_master(advertise_addr=args.advertise_addr)
        else:
            setup_worker()

        print_summary(node_type, time.monotonic() - start)

    except KeyboardInterrupt:
        print()
        warn("Interrupted by user. Partial installation may need cleanup.")
        log.warning("Interrupted by user.")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as exc:
        fail(f"Unexpected error: {exc}")
        log.exception("Unexpected error")
        sys.exit(1)


if __name__ == "__main__":
    main()
