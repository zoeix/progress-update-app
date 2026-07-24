from pathlib import Path
import sys
from time import sleep


def parse_timeout(value: str) -> float:
    timeout = float(value)
    if timeout <= 0:
        raise ValueError("Timeout must be greater than 0")
    return timeout


t = 0
zzz = 1
timeout = parse_timeout(sys.argv[1]) if len(sys.argv) > 1 else 300
file = Path(__file__).with_name("prompt.md")
last_edited = file.stat().st_mtime

while True:
    if t >= timeout:
        print('timeout')
        exit()
    elif last_edited == file.stat().st_mtime:
        sleep(zzz)
        t += zzz
    else:
        txt = file.read_text(encoding="utf-8")
        print('Done')
        exit()
