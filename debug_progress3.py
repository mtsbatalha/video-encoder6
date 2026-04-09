"""Test: can we read the progress file WHILE ffmpeg is writing to it on Windows?"""
import subprocess, sys, os, tempfile, time

inp = input("Path to video: ").strip()
if not os.path.isfile(inp):
    print("Not found")
    sys.exit(1)

cf = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
pf_fd, pf = tempfile.mkstemp(suffix=".progress")
os.close(pf_fd)
out = inp.replace(".mkv", "_test.mkv").replace(".mp4", "_test.mp4")

cmd = [
    "ffmpeg", "-hwaccel", "cuda", "-thread_queue_size", "512",
    "-i", inp,
    "-map", "0:v:0", "-map", "0:a:0",
    "-c:v", "hevc_nvenc", "-preset", "p4", "-rc", "vbr", "-b:v", "4M",
    "-c:a", "aac", "-t", "10",
    "-progress", pf,
    "-y", out,
]

print(f"Progress file: {pf}")
print(f"Starting ffmpeg in background...")

# Use Popen (not asyncio) - same as sync poll
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=cf)

start = time.time()
count = 0
last_size = 0
for _ in range(50):
    time.sleep(0.2)
    try:
        size = os.path.getsize(pf)
        with open(pf, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        lines = content.strip().split("\n")
        last_lines = lines[-5:] if len(lines) > 5 else lines

        # Extract relevant data
        out_t = "?"
        spd = "?"
        prg = "?"
        for ln in last_lines:
            if ln.startswith("out_time_ms="):
                out_t = ln.split("=",1)[1]
            elif ln.startswith("out_time=") and not ln.startswith("out_time_ms"):
                out_t = ln.split("=",1)[1]
            elif ln.startswith("speed="):
                spd = ln.split("=",1)[1]
            elif ln.startswith("progress="):
                prg = ln.split("=",1)[1]

        elapsed = time.time() - start
        count += 1
        print(f"  [{elapsed:.1f}s] size={size} (+{size-last_size}) time={out_t} speed={spd} progress={prg}")
        last_size = size
    except Exception as e:
        print(f"  [{time.time()-start:.1f}s] ERROR: {e}")

proc.wait()
print(f"\nDone. Updates seen: {count}")
print(f"Return code: {proc.returncode}")

for f in [out, pf]:
    try:
        os.unlink(f)
    except OSError:
        pass
