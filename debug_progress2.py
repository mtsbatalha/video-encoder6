"""Test: does FFmpeg -progress write to a temp file periodically?"""
import subprocess, sys, os, time, tempfile

inp = input("Path to video: ").strip()
if not os.path.isfile(inp):
    print("Not found")
    sys.exit(1)

cf = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# Create temp progress file
progress_fd, progress_file = tempfile.mkstemp(suffix=".progress")
os.close(progress_fd)

out = inp.replace(".mkv", "_test.mkv").replace(".mp4", "_test.mp4")
cmd = [
    "ffmpeg", "-hwaccel", "cuda", "-thread_queue_size", "512",
    "-i", inp,
    "-map", "0:v:0", "-map", "0:a:0",
    "-c:v", "hevc_nvenc", "-preset", "p4", "-rc", "vbr", "-b:v", "4M",
    "-c:a", "aac", "-t", "10",
    "-progress", progress_file,
    "-y", out,
]

print(f"Progress file: {progress_file}")
print("Starting ffmpeg...")
print()

proc = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    creationflags=cf,
)

start = time.time()
count = 0
for _ in range(50):  # Poll for up to 10 seconds
    time.sleep(0.2)
    try:
        with open(progress_file, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if content:
            lines = content.strip().split("\n")
            # Show key data
            out_time = ""
            speed = ""
            prog = ""
            for line in lines[-10:]:  # Last 10 lines
                if "out_time" in line:
                    out_time = line
                if "speed" in line:
                    speed = line
                if "progress" in line:
                    prog = line
            elapsed = time.time() - start
            count += 1
            print(f"  [{elapsed:.1f}s] {out_time} | {speed} | {prog}")
    except Exception as e:
        print(f"  Error: {e}")

proc.wait()
print(f"\nDone. Return code: {proc.returncode}")
print(f"Total progress updates seen: {count}")

if os.path.exists(out):
    os.remove(out)
try:
    os.unlink(progress_file)
except OSError:
    pass
