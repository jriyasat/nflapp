import subprocess, os, sys

# Run fetch_sgo_history.py inside container with start date 2024-01-01
# Output CSV to /app/data/sgo_historical_2024.csv
cmd = ['docker', 'exec', 'nfl-edge-v2-admin', 'python3', '/app/fetch_sgo_history.py', '2024-01-01', '/app/data/sgo_historical_2024.csv']
print('Running:', ' '.join(cmd))
result = subprocess.run(cmd, capture_output=True, text=True)
print('STDOUT:', result.stdout)
print('STDERR:', result.stderr)
print('Exit code:', result.returncode)