import frida, sys, time, os
HERE = os.path.dirname(os.path.abspath(__file__))
dev = frida.get_device_manager().add_remote_device("127.0.0.1:27042")
g = next((p for p in dev.enumerate_processes() if p.name == "Gadget"), None)
if not g:
    print("Gadget not found; is the app launched (paused) and port forwarded?"); sys.exit(1)
pid = g.pid
print("attaching to Gadget pid", pid)
sess = dev.attach(pid)
def on_msg(m, data):
    t = m.get("type")
    if t == "send":  print("[js] ", m["payload"])
    elif t == "log": print("[log]", m.get("payload"))
    elif t == "error": print("[ERR]", m.get("stack") or m)
    sys.stdout.flush()
script_name = sys.argv[2] if len(sys.argv) > 2 else "hook.js"
sc = sess.create_script(open(os.path.join(HERE, script_name), encoding="utf-8").read())
sc.on("message", on_msg)
sc.load()
print("script loaded; resuming app")
try: dev.resume(pid)
except Exception as e: print("resume err:", e)
sys.stdout.flush()
time.sleep(int(sys.argv[1]) if len(sys.argv) > 1 else 75)
print("driver done")

