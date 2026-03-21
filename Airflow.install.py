#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║          Apache Airflow Installer for Ubuntu                 ║
║          Automated Setup Script with Rich Output             ║
╚══════════════════════════════════════════════════════════════╝
"""

import subprocess
import sys
import os
import time
import shutil
import getpass

# ─────────────────────────────────────────────
#  ANSI Color & Style Codes
# ─────────────────────────────────────────────
class C:
    RESET       = "\033[0m"
    BOLD        = "\033[1m"
    DIM         = "\033[2m"

    BLACK       = "\033[30m"
    RED         = "\033[31m"
    GREEN       = "\033[32m"
    YELLOW      = "\033[33m"
    BLUE        = "\033[34m"
    MAGENTA     = "\033[35m"
    CYAN        = "\033[36m"
    WHITE       = "\033[37m"

    BG_BLACK    = "\033[40m"
    BG_RED      = "\033[41m"
    BG_GREEN    = "\033[42m"
    BG_YELLOW   = "\033[43m"
    BG_BLUE     = "\033[44m"
    BG_MAGENTA  = "\033[45m"
    BG_CYAN     = "\033[46m"
    BG_WHITE    = "\033[47m"

    BRIGHT_GREEN    = "\033[92m"
    BRIGHT_YELLOW   = "\033[93m"
    BRIGHT_BLUE     = "\033[94m"
    BRIGHT_MAGENTA  = "\033[95m"
    BRIGHT_CYAN     = "\033[96m"
    BRIGHT_WHITE    = "\033[97m"


# ─────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────
AIRFLOW_VERSION  = "2.9.2"
AIRFLOW_HOME     = os.path.expanduser("~/airflow")
VENV_DIR         = os.path.expanduser("~/airflow-env")
AIRFLOW_PORT     = 8080

ADMIN_USERNAME   = "admin"
ADMIN_FIRSTNAME  = "Admin"
ADMIN_LASTNAME   = "User"
ADMIN_EMAIL      = "admin@example.com"
ADMIN_PASSWORD   = "admin123"   # change after first login


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────
TERM_WIDTH = shutil.get_terminal_size((80, 20)).columns


def banner():
    lines = [
        "  █████╗ ██╗██████╗ ███████╗██╗      ██████╗ ██╗    ██╗",
        " ██╔══██╗██║██╔══██╗██╔════╝██║     ██╔═══██╗██║    ██║",
        " ███████║██║██████╔╝█████╗  ██║     ██║   ██║██║ █╗ ██║",
        " ██╔══██║██║██╔══██╗██╔══╝  ██║     ██║   ██║██║███╗██║",
        " ██║  ██║██║██║  ██║██║     ███████╗╚██████╔╝╚███╔███╔╝",
        " ╚═╝  ╚═╝╚═╝╚═╝  ╚═╝╚═╝     ╚══════╝ ╚═════╝  ╚══╝╚══╝ ",
    ]
    subtitle = f"Apache Airflow {AIRFLOW_VERSION} Installer for Ubuntu"
    border = "═" * (TERM_WIDTH - 2)

    print()
    print(f"{C.BRIGHT_CYAN}{C.BOLD}╔{border}╗{C.RESET}")
    for line in lines:
        pad = (TERM_WIDTH - len(line) - 2)
        print(f"{C.BRIGHT_CYAN}{C.BOLD}║{C.RESET}{C.BRIGHT_BLUE}{C.BOLD}{line}{' ' * pad}{C.RESET}{C.BRIGHT_CYAN}{C.BOLD}║{C.RESET}")
    sub_pad = (TERM_WIDTH - len(subtitle) - 2)
    print(f"{C.BRIGHT_CYAN}{C.BOLD}║{C.RESET}{C.BRIGHT_YELLOW}{C.BOLD}  {subtitle}{' ' * (sub_pad - 2)}{C.RESET}{C.BRIGHT_CYAN}{C.BOLD}║{C.RESET}")
    print(f"{C.BRIGHT_CYAN}{C.BOLD}╚{border}╝{C.RESET}")
    print()


def section(title: str):
    """Print a section header."""
    bar = "─" * (TERM_WIDTH - 4)
    print()
    print(f"{C.BRIGHT_MAGENTA}{C.BOLD}┌─ {title} {bar[:max(0, TERM_WIDTH - len(title) - 6)]}┐{C.RESET}")
    print()


def step(num: int, total: int, msg: str):
    badge = f"[{num}/{total}]"
    print(f"  {C.BG_BLUE}{C.BOLD}{C.WHITE} {badge} {C.RESET}  {C.BRIGHT_WHITE}{C.BOLD}{msg}{C.RESET}")


def info(msg: str):
    print(f"    {C.BRIGHT_CYAN}ℹ  {C.RESET}{C.WHITE}{msg}{C.RESET}")


def success(msg: str):
    print(f"    {C.BRIGHT_GREEN}✔  {C.RESET}{C.GREEN}{msg}{C.RESET}")


def warning(msg: str):
    print(f"    {C.BRIGHT_YELLOW}⚠  {C.RESET}{C.YELLOW}{msg}{C.RESET}")


def error(msg: str):
    print(f"    {C.RED}✖  {C.RESET}{C.RED}{C.BOLD}{msg}{C.RESET}")


def spinner_run(cmd: list, desc: str, env: dict = None, cwd: str = None) -> bool:
    """Run a command with a live spinner."""
    spin_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    idx = 0
    merged_env = {**os.environ, **(env or {})}

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=merged_env,
        cwd=cwd,
        text=True,
    )

    while process.poll() is None:
        spin = spin_chars[idx % len(spin_chars)]
        print(f"\r    {C.BRIGHT_CYAN}{spin}{C.RESET}  {C.DIM}{desc}...{C.RESET}", end="", flush=True)
        time.sleep(0.1)
        idx += 1

    stdout, stderr = process.communicate()
    print("\r" + " " * (TERM_WIDTH - 1) + "\r", end="")   # clear spinner line

    if process.returncode != 0:
        error(f"Command failed: {' '.join(cmd)}")
        if stderr.strip():
            for line in stderr.strip().splitlines()[-5:]:
                print(f"      {C.DIM}{C.RED}{line}{C.RESET}")
        return False

    success(desc)
    return True


def run_shell(cmd: str, desc: str, env: dict = None) -> bool:
    return spinner_run(["bash", "-c", cmd], desc, env=env)


def check_root():
    if os.geteuid() == 0:
        warning("Running as root — consider using a non-root user in production.")
    else:
        info(f"Running as user: {C.BRIGHT_CYAN}{getpass.getuser()}{C.RESET}")


def get_python_version() -> str:
    v = sys.version_info
    return f"{v.major}.{v.minor}"


def print_summary(python_ver: str):
    pad = "─" * (TERM_WIDTH - 2)
    print()
    print(f"{C.BRIGHT_GREEN}{C.BOLD}╔{pad}╗{C.RESET}")
    rows = [
        ("Airflow Version",  AIRFLOW_VERSION),
        ("Python Version",   python_ver),
        ("Airflow Home",     AIRFLOW_HOME),
        ("Virtual Env",      VENV_DIR),
        ("Web UI",           f"http://localhost:{AIRFLOW_PORT}"),
        ("Admin User",       ADMIN_USERNAME),
        ("Admin Password",   ADMIN_PASSWORD + "  ← change this!"),
    ]
    for key, val in rows:
        line = f"  {C.BRIGHT_WHITE}{C.BOLD}{key:<20}{C.RESET}{C.BRIGHT_CYAN}{val}{C.RESET}"
        # strip color codes for padding calc
        visible_len = len(f"  {key:<20}{val}")
        spaces = max(0, TERM_WIDTH - visible_len - 3)
        print(f"{C.BRIGHT_GREEN}{C.BOLD}║{C.RESET}{line}{' ' * spaces}{C.BRIGHT_GREEN}{C.BOLD}║{C.RESET}")
    print(f"{C.BRIGHT_GREEN}{C.BOLD}╚{pad}╝{C.RESET}")


def print_next_steps():
    section("Next Steps — Start Airflow")
    steps = [
        ("Activate venv",     f"source {VENV_DIR}/bin/activate"),
        ("Start web server",  f"airflow webserver --port {AIRFLOW_PORT}"),
        ("Start scheduler",   "airflow scheduler   # (new terminal)"),
        ("Open browser",      f"http://localhost:{AIRFLOW_PORT}"),
    ]
    for i, (label, cmd) in enumerate(steps, 1):
        print(f"  {C.BRIGHT_YELLOW}{C.BOLD}{i}.{C.RESET}  {C.WHITE}{label:<20}{C.RESET}  {C.BRIGHT_CYAN}{cmd}{C.RESET}")
    print()
    warning("For production: switch to PostgreSQL + LocalExecutor or CeleryExecutor.")
    print()


# ─────────────────────────────────────────────
#  Installation Steps
# ─────────────────────────────────────────────
TOTAL_STEPS = 7


def step1_check_requirements():
    section("Step 1 — Checking Requirements")
    step(1, TOTAL_STEPS, "Checking system requirements")

    python_ver = get_python_version()
    major, minor = sys.version_info.major, sys.version_info.minor
    if major < 3 or minor < 8:
        error(f"Python 3.8+ required. Found: {python_ver}")
        sys.exit(1)
    success(f"Python {python_ver} detected")

    if shutil.which("pip3") or shutil.which("pip"):
        success("pip is available")
    else:
        warning("pip not found — will install via apt")

    check_root()
    return python_ver


def step2_system_packages():
    section("Step 2 — Installing System Packages")
    step(2, TOTAL_STEPS, "Updating apt and installing dependencies")

    cmds = [
        ("sudo apt-get update -qq",                                        "Updating package list"),
        ("sudo apt-get install -y python3-pip python3-venv libpq-dev "
         "build-essential gcc g++ -qq",                                    "Installing build dependencies"),
    ]
    for cmd, desc in cmds:
        if not run_shell(cmd, desc):
            error("System package installation failed. Check sudo privileges.")
            sys.exit(1)


def step3_virtual_env():
    section("Step 3 — Creating Virtual Environment")
    step(3, TOTAL_STEPS, f"Setting up venv at {VENV_DIR}")

    if os.path.exists(VENV_DIR):
        warning(f"Virtual env already exists at {VENV_DIR} — reusing it.")
    else:
        if not run_shell(f"python3 -m venv {VENV_DIR}", f"Creating venv at {VENV_DIR}"):
            error("Failed to create virtual environment.")
            sys.exit(1)

    # Set AIRFLOW_HOME
    os.environ["AIRFLOW_HOME"] = AIRFLOW_HOME
    os.makedirs(AIRFLOW_HOME, exist_ok=True)
    success(f"AIRFLOW_HOME set to {AIRFLOW_HOME}")


def step4_install_airflow(python_ver: str):
    section("Step 4 — Installing Apache Airflow")
    step(4, TOTAL_STEPS, f"Installing Airflow {AIRFLOW_VERSION} (this may take a few minutes…)")

    pip  = f"{VENV_DIR}/bin/pip"
    constraint_url = (
        f"https://raw.githubusercontent.com/apache/airflow/"
        f"constraints-{AIRFLOW_VERSION}/constraints-{python_ver}.txt"
    )
    env = {"AIRFLOW_HOME": AIRFLOW_HOME}

    cmds = [
        (f"{pip} install --upgrade pip setuptools wheel -q",
         "Upgrading pip, setuptools, wheel"),
        (f"{pip} install 'apache-airflow=={AIRFLOW_VERSION}' "
         f"--constraint '{constraint_url}' -q",
         f"Installing apache-airflow=={AIRFLOW_VERSION}"),
    ]
    for cmd, desc in cmds:
        if not run_shell(cmd, desc, env=env):
            error("Airflow installation failed.")
            sys.exit(1)


def step5_init_db():
    section("Step 5 — Initialising the Database")
    step(5, TOTAL_STEPS, "Running airflow db init")

    airflow_bin = f"{VENV_DIR}/bin/airflow"
    env = {"AIRFLOW_HOME": AIRFLOW_HOME, "PATH": os.environ["PATH"]}

    if not spinner_run([airflow_bin, "db", "init"], "Initialising Airflow database", env=env):
        error("Database initialisation failed.")
        sys.exit(1)


def step6_create_user():
    section("Step 6 — Creating Admin User")
    step(6, TOTAL_STEPS, f"Creating user '{ADMIN_USERNAME}'")

    airflow_bin = f"{VENV_DIR}/bin/airflow"
    env = {"AIRFLOW_HOME": AIRFLOW_HOME, "PATH": os.environ["PATH"]}

    cmd = [
        airflow_bin, "users", "create",
        "--username",  ADMIN_USERNAME,
        "--firstname", ADMIN_FIRSTNAME,
        "--lastname",  ADMIN_LASTNAME,
        "--role",      "Admin",
        "--email",     ADMIN_EMAIL,
        "--password",  ADMIN_PASSWORD,
    ]
    if not spinner_run(cmd, f"Creating admin user '{ADMIN_USERNAME}'", env=env):
        warning("User creation may have failed (user might already exist).")


def step7_persist_env():
    section("Step 7 — Persisting Environment Variables")
    step(7, TOTAL_STEPS, "Adding AIRFLOW_HOME to ~/.bashrc")

    bashrc = os.path.expanduser("~/.bashrc")
    export_line = f'\nexport AIRFLOW_HOME="{AIRFLOW_HOME}"\n'

    try:
        with open(bashrc, "r") as f:
            content = f.read()
        if "AIRFLOW_HOME" not in content:
            with open(bashrc, "a") as f:
                f.write(export_line)
            success("AIRFLOW_HOME added to ~/.bashrc")
        else:
            info("AIRFLOW_HOME already present in ~/.bashrc")
    except Exception as e:
        warning(f"Could not update ~/.bashrc: {e}")


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────
def main():
    banner()

    info(f"Airflow Version  : {C.BRIGHT_CYAN}{AIRFLOW_VERSION}{C.RESET}")
    info(f"Airflow Home     : {C.BRIGHT_CYAN}{AIRFLOW_HOME}{C.RESET}")
    info(f"Virtual Env      : {C.BRIGHT_CYAN}{VENV_DIR}{C.RESET}")
    info(f"Web Port         : {C.BRIGHT_CYAN}{AIRFLOW_PORT}{C.RESET}")
    print()

    print(f"  {C.BG_YELLOW}{C.BLACK}{C.BOLD}  Press ENTER to start installation, or Ctrl+C to abort…  {C.RESET}")
    try:
        input()
    except KeyboardInterrupt:
        print()
        warning("Installation aborted by user.")
        sys.exit(0)

    start_time = time.time()

    python_ver = step1_check_requirements()
    step2_system_packages()
    step3_virtual_env()
    step4_install_airflow(python_ver)
    step5_init_db()
    step6_create_user()
    step7_persist_env()

    elapsed = time.time() - start_time
    print()
    print(f"  {C.BG_GREEN}{C.BLACK}{C.BOLD}  ✔  Installation completed in {elapsed:.1f}s  {C.RESET}")
    print()

    print_summary(python_ver)
    print_next_steps()


if __name__ == "__main__":
    main()
