import subprocess, sys
r = subprocess.run([sys.executable, "_test_search.py"], capture_output=True, text=True, timeout=120)
with open("_test_result.txt", "w", encoding="utf-8") as f:
    f.write(r.stdout or "")
    if r.stderr:
        f.write("\n--- STDERR (last 500) ---\n")
        f.write(r.stderr[-500:])
print("Written to _test_result.txt")
