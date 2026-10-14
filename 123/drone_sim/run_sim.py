"""Run the flight sim and show the full report directly in the console.

No txt / xlsx result file is written. simulate.py --stdout stores the
fingerprint in drone_sim/sim_last_fp.txt and prints the last/this
comparison itself, so this launcher just runs the simulation.
"""
import os
import sys
import subprocess

# bat cd's into drone_sim; run from project root (123/) so relative paths match
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

args = ["python", "drone_sim/simulate.py", "--minutes", sys.argv[1], "--stdout"]
if len(sys.argv) > 2 and sys.argv[2]:
    args += ["--seed", sys.argv[2]]

print()
r = subprocess.run(args)
if r.returncode != 0:
    print("[ERROR] simulate.py failed")
    sys.exit(1)
