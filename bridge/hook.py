from pathlib import Path
from time import sleep


file = Path(__file__).with_name("prompt.md")
last_edited = file.stat().st_mtime

while True:
    if last_edited == file.stat().st_mtime:
        sleep(1)
    else:
        txt = file.read_text(encoding="utf-8")
        print('Done')
        exit()
