"""Restart everything in one go: rebuild + restart the server, set up the adb tunnels, relaunch the patched
game on the phone and keep the Frida hooks attached until Ctrl+C (which also stops the server).

  python tools/restart.py [--http-port 8081]

Logs go to scratch/server.log and scratch/frida.log. Keep it running while you play: if Frida detaches,
hook.js's connect() redirect is gone and the game hangs on its next reconnect.
"""
import argparse, os, socket, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADB = os.path.join(ROOT, "tools", "platform-tools", "adb.exe" if os.name == "nt" else "adb")
SERVER = os.path.join(ROOT, "server", "WitcherRevival.Server")
SCRATCH = os.path.join(ROOT, "scratch")
PKG = "com.spokko.witchermonsterslayer"


def adb(*args):
    subprocess.run([ADB, *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop_server():
    # `dotnet run` starts the server as a separate exe, so kill it by name rather than via the Popen handle
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/IM", "WitcherRevival.Server.exe"], capture_output=True)
    else:
        subprocess.run(["pkill", "-f", "WitcherRevival.Server"], capture_output=True)


def wait_for_port(port, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.5)
    sys.exit(f"server never listened on {port} — see scratch/server.log")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--http-port", type=int, default=8081, help="host port for HTTP static data (8080 is Steam's on the dev PC)")
    port = ap.parse_args().http_port
    os.makedirs(SCRATCH, exist_ok=True)

    print("restarting server ...")
    stop_server()
    for name in ("server", "frida"):  # keep the last run's logs (e.g. to debug a freeze after restarting)
        try:
            os.replace(os.path.join(SCRATCH, name + ".log"), os.path.join(SCRATCH, name + ".prev.log"))
        except OSError:
            pass  # missing, or still held open by an earlier run's process
    subprocess.run(["dotnet", "build", "-v", "q", "--nologo"], cwd=SERVER, check=True, stdout=subprocess.DEVNULL)
    env = dict(os.environ, ASPNETCORE_ENVIRONMENT="Production", Http__Port=str(port))
    subprocess.Popen(["dotnet", "run", "--no-build"], cwd=SERVER, env=env,
                     stdout=open(os.path.join(SCRATCH, "server.log"), "w"), stderr=subprocess.STDOUT)
    wait_for_port(4253)

    print("relaunching game ...")
    adb("forward", "tcp:27042", "tcp:27042")
    adb("reverse", "tcp:4253", "tcp:4253")
    adb("reverse", "tcp:8080", f"tcp:{port}")
    adb("shell", "am", "force-stop", PKG)
    adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")

    frida_log = open(os.path.join(SCRATCH, "frida.log"), "w")
    for _ in range(15):  # the Gadget shows up a few seconds after launch; frida_run.py exits 1 until then
        time.sleep(2)
        frida = subprocess.Popen([sys.executable, "-u", os.path.join(ROOT, "tools", "patch", "frida_run.py"), "999999"],
                                 stdout=frida_log, stderr=subprocess.STDOUT)
        try:
            frida.wait(timeout=5)
        except subprocess.TimeoutExpired:
            break  # attached and running
    else:
        stop_server()
        sys.exit("Frida Gadget never appeared — is the phone connected and the patched APK installed?")

    print("running — logs in scratch/server.log and scratch/frida.log; Ctrl+C to stop")
    try:
        frida.wait()
    except KeyboardInterrupt:
        pass
    finally:
        frida.terminate()
        stop_server()


if __name__ == "__main__":
    main()
