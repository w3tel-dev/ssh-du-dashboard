
import os, shlex, subprocess, time, json, threading
from pathlib import Path
from flask import Flask, render_template, redirect, url_for, request, flash

HOSTS_FILE = os.getenv("HOSTS_FILE", "/data/hosts.txt")
SSH_KEY = os.getenv("SSH_KEY", "/ssh/id_rsa")
DEPTH = int(os.getenv("DEPTH", "2"))
CONNECT_TIMEOUT = int(os.getenv("CONNECT_TIMEOUT", "8"))
CMD_TIMEOUT = int(os.getenv("CMD_TIMEOUT", "60"))
PORT = int(os.getenv("PORT", "9090"))

DATA_DIR = Path("/data")
RESULTS_FILE = DATA_DIR / "results.json"
os.makedirs(DATA_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret")

# Jinja filter for epoch -> local time string
from datetime import datetime
@app.template_filter("datetime")
def _jinja2_filter_datetime(ts):
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)

def read_targets():
    targets = []
    if not os.path.exists(HOSTS_FILE):
        return targets
    with open(HOSTS_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            first = parts[0]
            label = " ".join(parts[1:]) if len(parts) > 1 else ""
            targets.append({"target": first, "label": label})
    return targets

def ssh_du_script(depth):
    script = f'''
set -euo pipefail
whoami 1>/dev/null 2>&1 || true
HOSTNAME="$(hostname 2>/dev/null || uname -n || echo unknown)"
USERNAME="$(id -un 2>/dev/null || whoami || echo user)"
HOME_DIR="${{HOME:-$(getent passwd "$USERNAME" 2>/dev/null | cut -d: -f6)}}"
[[ -z "$HOME_DIR" ]] && HOME_DIR="$HOME"
[[ -z "$HOME_DIR" ]] && HOME_DIR="$(pwd)"
if [[ "$HOME_DIR" == */home/$USERNAME ]]; then
    HOME_DIR="$(dirname "$(dirname "$HOME_DIR")")"
fi
TOTAL_SIZE=""
if du -sh "$HOME_DIR" 1>/dev/null 2>&1; then
    TOTAL_SIZE="$(du -sh "$HOME_DIR" 2>/dev/null | awk '{{print $1}}')"
fi
if du --version >/dev/null 2>&1; then
    LIST="$(du -h --max-depth={depth} "$HOME_DIR" 2>/dev/null)"
else
    LIST="$(find "$HOME_DIR" -mindepth 0 -maxdepth {depth} -type d -print0 2>/dev/null | xargs -0 -I{{}} du -sh "{{}}" 2>/dev/null)"
fi
if sort -h </dev/null >/dev/null 2>&1; then
    LIST_SORTED="$(printf "%s\n" "$LIST" | sort -h)"
else
    LIST_SORTED="$LIST"
fi
printf "HOST\t%s\n" "$HOSTNAME"
printf "USER\t%s\n" "$USERNAME"
printf "HOME\t%s\n" "$HOME_DIR"
printf "TOTAL\t%s\n" "$TOTAL_SIZE"
printf "LIST_BEGIN\n"
printf "%s\n" "$LIST_SORTED"
printf "LIST_END\n"
'''
    return script

def run_ssh(target):
    remote_cmd = ssh_du_script(DEPTH)
    quoted = shlex.quote(remote_cmd)
    ssh_parts = [
        "ssh",
        "-i", SSH_KEY,
        "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", f"ConnectTimeout={CONNECT_TIMEOUT}",
        target,
        "bash", "-lc", quoted
    ]
    try:
        res = subprocess.run(
            ssh_parts,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=CMD_TIMEOUT
        )
        ok = (res.returncode == 0)
        return ok, res.stdout, res.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Timeout after {CMD_TIMEOUT}s"

def parse_output(stdout):
    meta = {"host": "", "user": "", "home": "", "total": ""}
    lines = stdout.splitlines()
    content = []
    in_list = False
    for ln in lines:
        if ln.startswith("HOST\t"):
            meta["host"] = ln.split("\t", 1)[1]
        elif ln.startswith("USER\t"):
            meta["user"] = ln.split("\t", 1)[1]
        elif ln.startswith("HOME\t"):
            meta["home"] = ln.split("\t", 1)[1]
        elif ln.startswith("TOTAL\t"):
            meta["total"] = ln.split("\t", 1)[1]
        elif ln.strip() == "LIST_BEGIN":
            in_list = True
        elif ln.strip() == "LIST_END":
            in_list = False
        elif in_list:
            content.append(ln)

    entries = []
    home = meta["home"] or ""
    prefix = home.rstrip("/") + "/"
    for row in content:
        parts = row.split()
        if len(parts) < 2:
            continue
        size = parts[0]
        path = parts[-1]
        rel = path
        if prefix != "/" and path.startswith(prefix):
            rel = path[len(prefix):]
        elif path == home:
            rel = "."
        depth = rel.count("/") if rel != "." else 0
        entries.append({"size": size, "path": path, "rel": rel, "depth": depth})
    return meta, entries

def scan_all():
    targets = read_targets()
    results = {"generated_at": int(time.time()), "targets": []}
    for t in targets:
        target = t["target"]
        label = t["label"]
        ok, out, err = run_ssh(target)
        if not ok:
            results["targets"].append({
                "target": target,
                "label": label,
                "error": (err or "").strip() or "SSH error",
            })
            continue
        meta, entries = parse_output(out)
        results["targets"].append({
            "target": target,
            "label": label,
            "meta": meta,
            "entries": entries
        })
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)
    return results

def load_results():
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE, "r") as f:
            return json.load(f)
    return {"generated_at": None, "targets": []}

scanning_lock = threading.Lock()

@app.route("/", methods=["GET"])
def index():
    targets = read_targets()
    results = load_results()
    # Pass the hosts file path for display
    results["hosts_file"] = HOSTS_FILE
    return render_template("index.html",
                           targets=targets,
                           results=results,
                           depth=DEPTH)

@app.route("/scan", methods=["POST"])
def scan():
    if scanning_lock.locked():
        flash("Scan déjà en cours.", "warning")
        return redirect(url_for("index"))
    with scanning_lock:
        try:
            scan_all()
            flash("Scan terminé.", "success")
        except Exception as e:
            flash(f"Échec du scan: {e}", "warning")
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
