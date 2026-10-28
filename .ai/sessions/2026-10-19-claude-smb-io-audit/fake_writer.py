"""A fake acquisition PC for scenarios.py: writes raw and TXY files into a folder, slowly, in its own
process, and notes each write in the I/O trace (``writer_start`` / ``writer_chunk`` / ``writer_end``).

    python fake_writer.py FOLDER TRACE --first 1001 --count 12 --every 4 --slow 1006 --stall 1009 --template FILE

Each shot: d<shot>.txt (raw), then d_txy_forc<shot>.txt in one write. The ``--slow`` shot's TXY file is
written in four parts with 2.5 s pauses, each part ending mid-row, as a converter slowed by the network;
the ``--stall`` shot's in two parts with one ``--stall-pause`` (8 s) between: longer than HeLab's 5 s
settle age, as a converter stalled mid-file.
"""
from __future__ import annotations

import argparse
import json
import os
import time


def note(trace: str, op: str, path: str, **fields: object) -> None:
    line = json.dumps({"t": time.time(), "pid": os.getpid(), "op": op, "path": path, "reason": "fake writer",
                       **fields}) + "\n"
    descriptor = os.open(trace, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(descriptor, line.encode("ascii"))
    finally:
        os.close(descriptor)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    parser.add_argument("trace")
    parser.add_argument("--first", type=int, default=1001)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--every", type=float, default=4.0)
    parser.add_argument("--slow", type=int, default=0)
    parser.add_argument("--stall", type=int, default=0)
    parser.add_argument("--stall-pause", type=float, default=8.0)
    parser.add_argument("--template", required=True)
    args = parser.parse_args()
    with open(args.template, "rb") as stream:
        body = stream.read()
    for shot in range(args.first, args.first + args.count):
        raw = os.path.join(args.folder, f"d{shot}.txt")
        note(args.trace, "writer_start", raw)
        with open(raw, "wb") as stream:
            stream.write(b"raw tdc data\n")
        note(args.trace, "writer_end", raw)
        txy = os.path.join(args.folder, f"d_txy_forc{shot}.txt")
        note(args.trace, "writer_start", txy, bytes=len(body))
        with open(txy, "wb") as stream:
            if shot in (args.slow, args.stall):
                parts, pause = (4, 2.5) if shot == args.slow else (2, args.stall_pause)
                cut = [len(body) * part // parts + 7 for part in range(1, parts)]  # +7: mid-row.
                start = 0
                for end in [*cut, len(body)]:
                    stream.write(body[start:end])
                    stream.flush()
                    os.fsync(stream.fileno())
                    note(args.trace, "writer_chunk", txy, bytes=end)
                    start = end
                    if end < len(body):
                        time.sleep(pause)
            else:
                stream.write(body)
        note(args.trace, "writer_end", txy)
        time.sleep(args.every)


if __name__ == "__main__":
    main()
