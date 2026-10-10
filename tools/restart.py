"""Restart everything in one go: rebuild and restart the 1.1.116 server (server/, built into local/) and its
OSM map helpers, set up the adb tunnels, push hook.js to the phone and relaunch the game.
Rerun it to restart everything; Ctrl+C stops the server side.

  python tools/restart.py [--index local/maps/israel-features.sqlite]
  python tools/restart.py --hook-only   # only copy hook.js to the phone (a client from build_client.py loads it from there)

While it runs you can also start the game from its icon: the client loads hook.js by itself.
The operator panel (players, map, news, tasks, weather) is at http://127.0.0.1:18090/ while it runs.
One-time setup is in tools/client116/ (extract_packs.py, build_client.py) plus a map index:
  local/venv/Scripts/python -B server/connection/map-road-fixture-01/osm_extract_index.py
      --input local/maps/<region>.osm.pbf --output local/maps/<region>-features.sqlite

Logs go to scratch/{server,tiles,placement,game}.log (the previous run's as *.prev.log); game.log holds the
hook's output and Unity errors. Build output, profiles and caches go to local/.
"""
import argparse, http.client, http.server, os, secrets, shutil, socket, subprocess, sys, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADB = os.path.join(ROOT, "tools", "platform-tools", "adb.exe" if os.name == "nt" else "adb")
SCRATCH = os.path.join(ROOT, "scratch")
PKG = "com.spokko.witchermonsterslayer"
CLIENT = os.path.join(ROOT, "tools", "client116")
HOOK_DIR = f"/sdcard/Android/data/{PKG}/files"  # the client's Gadget loads hook.js from here (build_client.py)
SERVER = os.path.join(ROOT, "server")
MAPS = os.path.join(SERVER, "connection", "map-road-fixture-01")
LOCAL = os.path.join(ROOT, "local")
STATE = os.path.join(LOCAL, "server116")
BUILD = os.path.join(LOCAL, "build", "server116")
PY = os.path.join(LOCAL, "venv", "Scripts", "python.exe") if os.name == "nt" else os.path.join(LOCAL, "venv", "bin", "python")
HTTP, GAME, TILES, PLACEMENT = 18080, 4253, 18082, 18093
PANEL, ADMIN = 18090, 18092  # browser-facing panel proxy, server's operator listener
WORLD = os.path.join(STATE, "world")


def adb(*args, check=True):
    subprocess.run([ADB, *args], check=check, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop_previous():
    """Kill what an earlier run left behind (server, map helpers, logcat reader)."""
    marks = ["server116", "osm_live_sidecar.py", "playable_locations.py", "Frida:V"]
    if os.name == "nt":
        match = " -or ".join(f"$_.CommandLine -like '*{m}*'" for m in marks)
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"Get-CimInstance Win32_Process | Where-Object {{ ({match}) -and $_.ProcessId -ne $PID }}"
                        " | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"], capture_output=True)
    else:
        for m in marks:
            subprocess.run(["pkill", "-f", m], capture_output=True)


def start(name, cmd, **kw):
    path = os.path.join(SCRATCH, name + ".log")
    try:  # keep the last run's log (e.g. to debug a freeze after restarting)
        os.replace(path, os.path.join(SCRATCH, name + ".prev.log"))
    except OSError:
        pass  # missing, or still held open by an earlier run's process
    return subprocess.Popen(cmd, stdout=open(path, "w"), stderr=subprocess.STDOUT, **kw)


def bundle_hook():
    """hook.js imports gps.js and Frida's Java bridge; Gadget loads a single file, so bundle them into one."""
    if not os.path.isdir(os.path.join(CLIENT, "node_modules")):
        subprocess.run([shutil.which("npm"), "install", "--no-package-lock", "--no-audit", "--no-fund"], cwd=CLIENT, check=True)
    import frida
    path = os.path.join(LOCAL, "client", "hook.bundle.js")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(frida.Compiler().build("hook.js", project_root=CLIENT, source_maps="omitted", compression="terser"))
    return path


def serve_panel(key):
    """Loopback stand-in for the panel's authenticating proxy: adds the operator key to every request."""
    class Proxy(http.server.BaseHTTPRequestHandler):
        def forward(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "connection", "x-monster-admin-key")}
            conn = http.client.HTTPConnection("127.0.0.1", ADMIN, timeout=60)
            conn.request(self.command, self.path, body or None, {**headers, "X-Monster-Admin-Key": key})
            reply = conn.getresponse()
            data = reply.read()
            self.send_response(reply.status)
            for k, v in reply.getheaders():
                if k.lower() not in ("connection", "transfer-encoding", "content-length"):
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = forward

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", PANEL), Proxy)
    threading.Thread(target=server.serve_forever, daemon=True).start()


def wait_for_port(port, log, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.5)
    sys.exit(f"nothing listened on {port}: see scratch/{log}.log")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=os.path.join(LOCAL, "maps", "israel-features.sqlite"))
    ap.add_argument("--hook-only", action="store_true", help="only copy hook.js to the phone, then exit")
    args = ap.parse_args()
    index = args.index
    if args.hook_only:  # the companion app runs the server; a client from build_client.py only needs its hook
        hook = bundle_hook()
        adb("wait-for-device")
        adb("shell", "mkdir", "-p", HOOK_DIR)
        adb("push", hook, HOOK_DIR + "/hook.js")
        return
    os.makedirs(SCRATCH, exist_ok=True)
    stop_previous()
    for data in ("news", "tasks"):  # working copies, so panel edits never touch the tracked defaults
        if not os.path.isdir(os.path.join(STATE, data)):
            shutil.copytree(os.path.join(SERVER, "WitcherRevival.Server", data), os.path.join(STATE, data))
    shutil.copy(os.path.join(SERVER, "WitcherRevival.Server", "news", "release.json"), os.path.join(STATE, "news"))  # What's new
    shutil.copy(os.path.join(SERVER, "WitcherRevival.Server", "tasks", "trinkets.json"), os.path.join(STATE, "tasks"))  # only gains rows
    os.makedirs(WORLD, exist_ok=True)
    if not os.path.exists(os.path.join(WORLD, "world.json")):  # the server's defaults, editable in the panel
        with open(os.path.join(WORLD, "world.json"), "w") as f:
            f.write('{\n  "schemaVersion": 1,\n  "monsterSlotsPerCell": 18\n}\n')
    key_file = os.path.join(STATE, "admin", "proxy.key")
    if not os.path.exists(key_file):
        os.makedirs(os.path.dirname(key_file), exist_ok=True)
        with open(key_file, "w") as f:
            f.write(secrets.token_urlsafe(36))
    with open(key_file) as f:
        admin_key = f.read().strip()

    print("building server ...")  # artifacts path keeps bin/obj out of the source tree
    subprocess.run(["dotnet", "build", os.path.join(SERVER, "WitcherRevival.Server", "WitcherRevival.Server.csproj"),
                    "-c", "Release", "--artifacts-path", BUILD, "-p:NuGetAudit=false",
                    "-p:UseSharedCompilation=false", "-v", "q", "--nologo"], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL)
    dll = os.path.join(BUILD, "bin", "WitcherRevival.Server", "release", "WitcherRevival.Server.dll")
    print("bundling hook.js ...")
    hook = bundle_hook()

    procs = [
        start("tiles", [PY, "-B", os.path.join(MAPS, "osm_live_sidecar.py"), "--bind", "127.0.0.1", "--port", str(TILES),
                        "--index", index, "--cache-dir", os.path.join(LOCAL, "maps", "tile-cache"), "--offline"]),
        start("placement", [PY, "-B", os.path.join(MAPS, "playable_locations.py"), "--index", index,
                            "--port", str(PLACEMENT), "--policy", os.path.join(WORLD, "placement-policy.json"),
                            "--tuning", os.path.join(WORLD, "tuning.json")]),
        start("server", ["dotnet", dll, "--Http:Port", str(HTTP), "--GameServer:Port", str(GAME),
                         "--LocalProfile:DataDirectory", os.path.join(STATE, "profiles"),
                         "--LocalProfile:NewProfileMode", "reconstructed",
                         "--News:Directory", os.path.join(STATE, "news"), "--Tasks:Directory", os.path.join(STATE, "tasks"),
                         "--World:Directory", WORLD, "--Playable:Url", f"http://127.0.0.1:{PLACEMENT}",
                         "--Weather:Url", "https://api.open-meteo.com/v1/forecast",
                         "--Admin:Port", str(ADMIN), "--Admin:Origin", f"http://127.0.0.1:{PANEL}",
                         "--Admin:KeyFile", key_file, "--Admin:DataDirectory", os.path.join(STATE, "admin", "data"),
                         "--Admin:DebugTools", "true"],
              cwd=STATE, env=dict(os.environ, ASPNETCORE_ENVIRONMENT="Production")),
    ]
    try:
        for port, log in ((GAME, "server"), (HTTP, "server"), (ADMIN, "server"), (TILES, "tiles"), (PLACEMENT, "placement")):
            wait_for_port(port, log)
        serve_panel(admin_key)

        print("relaunching game ...")
        adb("wait-for-device")  # rides out a USB reconnect instead of failing the whole restart
        for port in (GAME, HTTP, TILES):
            adb("reverse", f"tcp:{port}", f"tcp:{port}")
        adb("shell", "mkdir", "-p", HOOK_DIR)
        adb("push", hook, HOOK_DIR + "/hook.js")
        adb("logcat", "-c", check=False)
        procs.append(start("game", [ADB, "logcat", "-v", "time", "-s", "Frida:V", "Unity:E"]))
        adb("shell", "am", "force-stop", PKG)
        adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")

        print(f"running: operator panel at http://127.0.0.1:{PANEL}/, logs in scratch/; Ctrl+C to stop")
        procs[2].wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
