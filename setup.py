#!/usr/bin/env python3
"""
setup.py — Two Minds installer
Checks dependencies, creates venv, installs packages, pulls Ollama models.
"""

import os, sys, subprocess, shutil, time, json

# ── Colours ───────────────────────────────────────────────────────────────────
G = "\033[92m"  # green
R = "\033[91m"  # red
Y = "\033[93m"  # yellow
B = "\033[94m"  # blue
M = "\033[95m"  # magenta
D = "\033[0m"   # reset
BOLD = "\033[1m"

def ok(msg):    print("  {}✓{} {}".format(G, D, msg))
def err(msg):   print("  {}✗{} {}".format(R, D, msg))
def warn(msg):  print("  {}!{} {}".format(Y, D, msg))
def info(msg):  print("  {}→{} {}".format(B, D, msg))
def head(msg):  print("\n{}{}{}".format(BOLD, msg, D))

def run(cmd, capture=True):
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=capture,
            text=True, timeout=300
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "timeout"
    except Exception as e:
        return False, "", str(e)

# ── Banner ────────────────────────────────────────────────────────────────────

print()
print("  {}{}TWO MINDS — Setup{}".format(BOLD, M, D))
print("  {}{}A psychological conversation simulator{}".format(BOLD, B, D))
print("  " + "─" * 50)

# ── Step 1: Python version ────────────────────────────────────────────────────

head("Step 1 / Python")
major, minor = sys.version_info[:2]
if major < 3 or (major == 3 and minor < 10):
    err("Python 3.10+ required. You have {}.{}.".format(major, minor))
    sys.exit(1)
ok("Python {}.{} detected".format(major, minor))

# ── Step 2: Virtual environment ───────────────────────────────────────────────

head("Step 2 / Virtual environment")
venv_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv")

if os.path.exists(venv_dir):
    warn("venv already exists — skipping creation")
else:
    info("Creating venv...")
    success, _, stderr = run("{} -m venv {}".format(sys.executable, venv_dir))
    if not success:
        err("Failed to create venv: {}".format(stderr))
        sys.exit(1)
    ok("venv created at {}".format(venv_dir))

# Detect pip path
if sys.platform == "win32":
    pip = os.path.join(venv_dir, "Scripts", "pip")
    python = os.path.join(venv_dir, "Scripts", "python")
else:
    pip = os.path.join(venv_dir, "bin", "pip")
    python = os.path.join(venv_dir, "bin", "python")

# ── Step 3: Install dependencies ─────────────────────────────────────────────

head("Step 3 / Python dependencies")
req_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")

if os.path.exists(req_file):
    info("Installing from requirements.txt...")
    success, stdout, stderr = run("{} install -r {}".format(pip, req_file))
else:
    info("Installing flask and requests...")
    success, stdout, stderr = run("{} install flask requests".format(pip))

if not success:
    err("pip install failed: {}".format(stderr[:200]))
    sys.exit(1)
ok("Dependencies installed")

# ── Step 4: Check Ollama ──────────────────────────────────────────────────────

head("Step 4 / Ollama")

if not shutil.which("ollama"):
    err("Ollama not found.")
    print()
    print("  Install Ollama first:")
    print("  {}macOS:{}  brew install ollama".format(Y, D))
    print("  {}Linux:{}  curl -fsSL https://ollama.com/install.sh | sh".format(Y, D))
    print("  {}Web:{}    https://ollama.com".format(Y, D))
    print()
    choice = input("  Have you installed Ollama? (y/n): ").strip().lower()
    if choice != "y":
        warn("Re-run setup.py after installing Ollama.")
        sys.exit(0)

ok("Ollama found")

# Check if Ollama is running
import urllib.request, urllib.error
def ollama_running():
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
        return True
    except:
        return False

if not ollama_running():
    warn("Ollama is not running. Attempting to start...")
    subprocess.Popen(["ollama", "serve"],
                     stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    for i in range(10):
        time.sleep(2)
        if ollama_running():
            ok("Ollama started")
            break
    else:
        err("Could not start Ollama. Start it manually with: ollama serve")
        sys.exit(1)
else:
    ok("Ollama is running")

# ── Step 5: Pull models ───────────────────────────────────────────────────────

head("Step 5 / Models")

# Check what's already installed
try:
    response = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5)
    data = json.loads(response.read())
    installed = [m["name"].split(":")[0] for m in data.get("models", [])]
except:
    installed = []

REQUIRED_MODELS = [
    ("llama3.2",  "2.0 GB", "James and Samantha — character dialogue"),
    ("mistral",   "4.4 GB", "Narrator and therapist — analysis"),
]

OPTIONAL_MODELS = [
    ("openhermes",       "4.1 GB", "Alternative character model"),
    ("heretic-thinking", "4.9 GB", "Dark profiles — abliterated"),
]

def pull_model(name, size, desc):
    if any(name in i for i in installed):
        ok("{} already installed — {}".format(name, desc))
        return True
    print()
    info("Pulling {} ({}) — {}".format(name, size, desc))
    info("This may take several minutes...")
    success, _, _ = run("ollama pull {}".format(name), capture=False)
    if success:
        ok("{} installed".format(name))
        return True
    else:
        err("Failed to pull {}".format(name))
        return False

print("  Required models:")
all_ok = True
for name, size, desc in REQUIRED_MODELS:
    if not pull_model(name, size, desc):
        all_ok = False

if not all_ok:
    err("Some required models failed to install.")
    sys.exit(1)

print()
print("  Optional models (for dark profiles):")
for name, size, desc in OPTIONAL_MODELS:
    choice = input("  Pull {} ({})? (y/n): ".format(name, size)).strip().lower()
    if choice == "y":
        pull_model(name, size, desc)
    else:
        info("Skipping {}".format(name))

# ── Step 6: Verify profiles ───────────────────────────────────────────────────

head("Step 6 / Profiles")

profiles_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")
if not os.path.exists(profiles_dir):
    err("profiles/ directory not found. Make sure you cloned the full repo.")
    sys.exit(1)

expected = ["james.json", "samantha.json"]
for f in expected:
    path = os.path.join(profiles_dir, f)
    if os.path.exists(path):
        ok("profiles/{} found".format(f))
    else:
        err("profiles/{} missing".format(f))

# ── Step 7: Verify templates ──────────────────────────────────────────────────

head("Step 7 / Templates")

templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
if not os.path.exists(templates_dir):
    err("templates/ directory not found.")
    sys.exit(1)

for t in ["dashboard.html", "index.html", "traits.html", "emotions.html"]:
    path = os.path.join(templates_dir, t)
    if os.path.exists(path):
        ok("templates/{} found".format(t))
    else:
        warn("templates/{} missing".format(t))

# ── Done ──────────────────────────────────────────────────────────────────────

print()
print("  " + "─" * 50)
print("  {}{}Setup complete.{}".format(BOLD, G, D))
print("  " + "─" * 50)
print()
print("  To run:")
print()

if sys.platform == "win32":
    print("  {}venv\\Scripts\\activate{}".format(Y, D))
else:
    print("  {}source venv/bin/activate{}".format(Y, D))

print("  {}python3 two_minds_server.py{}".format(Y, D))
print()
print("  Then open: {}http://localhost:5000/dashboard{}".format(B, D))
print()
print("  For dark profiles:")
print("  {}python3 two_evil_minds_server.py{}".format(Y, D))
print()
