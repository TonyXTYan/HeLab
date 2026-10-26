"""A thread logs through Qt while the main thread installs and removes a Python handler as
pytest-qt does per test (_start: a fresh bound method; _stop: None). Counts what the thread's
messages hit: errors printed via sys.excepthook."""
import sys, threading, time
from PyQt6.QtCore import QMessageLogger, qInstallMessageHandler

errors = []
sys.excepthook = lambda kind, value, tb: errors.append(f"{kind.__name__}: {value}")

class Capture:
    def handle(self, mode, context, message):
        pass

stop = False
def log():
    logger = QMessageLogger()
    while not stop:
        logger.warning("from a thread")

sys.setswitchinterval(0.0001)
def teardown():
    junk = [object() for _ in range(2000)]  # Python work: the GIL switches meanwhile
thread = threading.Thread(target=log, daemon=True)
thread.start()
end = time.monotonic() + float(sys.argv[1] if len(sys.argv) > 1 else 5)
swaps = 0
while time.monotonic() < end:
    capture = Capture()
    previous = qInstallMessageHandler(capture.handle)  # _start
    time.sleep(0.0005)
    qInstallMessageHandler(previous)  # _stop
    del capture
    teardown()
    swaps += 1
stop = True
thread.join()
print(f"{swaps} swaps, {len(errors)} errors")
for text in sorted(set(errors))[:10]:
    print("  ", text, errors.count(text))
