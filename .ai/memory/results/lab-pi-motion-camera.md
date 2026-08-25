---
date: 2026-08-25
status: settled
name: lab-pi-motion-camera
description: "Lab Raspberry Pi running motion for the webcam stream (see Maestri 'SSH Pi TailScale' for address) — USB/IP camera caps resolution at 640x480, tuning knobs, and a disk-full incident"
metadata:
  node_type: memory
  type: result
---
Working notes for the lab's Raspberry Pi that serves a live webcam view via the
`motion` daemon on port 8081. Address intentionally omitted from this file —
in Maestri, connect via the "SSH Pi TailScale" agent (passwordless `sudo`
once connected), and the same host is where the live view portal points.

Hardware: **Raspberry Pi 2 Model B Rev 1.1**, armv7l (32-bit), quad-core
~900MHz, 921MB RAM — weak, has no headroom to spare. `motion` version 4.5.1-2.
Config at `/etc/motion/motion.conf`; service is `motion.service` (systemd);
restart with `sudo systemctl restart motion` (~5s to reach steady-state CPU
after restart — `ps -C motion -o %cpu=` is a cumulative average since process
start, so sample 30-40s after a restart, not immediately).

## The camera is remote over USB/IP — this is the resolution ceiling

The webcam (`v4l2-ctl` shows it as "Integrated Camera", `/dev/video0`) is
**not physically attached to the Pi** — it's shared over the network via
**USB/IP** (`dmesg` shows `usbip-host 1-1.2`). This caps usable resolution at
**640x480**, independent of CPU headroom:

- At **1280x720** or **1920x1080**, `v4l2-ctl --get-fmt-video` reports the
  format negotiated fine and `systemctl status motion` shows the service
  "active" — but the capture thread silently hangs. The stream serves a
  frozen/stale frame (or "CONNECTION TO CAMERA LOST"), and
  `curl http://localhost:8081/` (run **on the Pi**) returns **0 bytes** even
  after 5+ seconds, while `motion` sits pinned near 100%+ CPU. `dmesg` shows
  `usb_clear_halt` / `unlinked by a call to usb_unlink_urb()` errors on the
  usbip device around the same time — classic signs the USB/IP link can't
  sustain the isochronous MJPG bandwidth at higher resolution.
- This reproduced identically at both 720p and 1080p. Don't retry either
  without first improving the USB/IP link itself (whatever host is exporting
  the camera, and the network path to it) — CPU/framerate tuning alone can't
  fix a transport-layer failure.
- A stuck stream can look client-side-cached even after the server recovers
  (reverting resolution and restarting `motion` didn't visibly unstick the
  portal view until the page was reloaded) — always force-reload the viewer
  before concluding the fix didn't work.

## Orientation

Native feed is mirrored (left-right) **and**, after correcting that, appeared
upside-down. Fixed with both directives together in `motion.conf`:

```
flip_axis h
rotate 180
```

`flip_axis` valid values are `none`, `v`, `h` (see
`/usr/share/doc/motion/motion_config.html`, anchor `flip_axis`). Needing both
`h` and `rotate 180` together (rather than just `flip_axis v`) was empirical,
found by testing — worth re-checking if the physical camera mount or the
USB/IP source ever changes.

## Stream tuning at 640x480 (the settled config)

- `stream_quality` (1-100, default 50) is the JPEG compression quality for
  the live MJPEG stream — the direct "pixelation" knob, independent of
  capture resolution.
- `stream_maxrate` (default **1** fps!) throttles how many of the captured
  frames actually get sent over the stream — separate from `framerate`
  (the capture rate). The default of 1 is easy to miss and looks like
  "pixelation" even though it's really a frame-rate problem.
- Quality/CPU tradeoff measured on this Pi 2 at 640x480, `stream_maxrate 3`:
  `stream_quality 100` → ~102-103% CPU (of one core); `stream_quality 95` →
  ~80-81% CPU, visually indistinguishable from 100. ~20% CPU savings for
  negligible quality loss — prefer 95 over 100.
- Settled values (2026-08-25): `framerate 15`, `stream_quality 95`,
  `stream_maxrate 3`.

## Disk-full incident (resolved 2026-08-25)

`movie_output on` (recording clips on motion-detection events, mkv,
`/var/lib/motion/`) had been accumulating since **2026-07-15** with **no
retention/cleanup** anywhere (checked both `pi` and `root` crontabs — empty;
`/etc/logrotate.d/motion` only rotates the text log, not recordings). This
filled the 6.8GB SD card to **100% (0 bytes available)** — 845 files, 2.2GB.
Symptom noticed: several 0-byte `.mkv` files appearing on every `motion`
restart, consistent with disk-full write failures.

Resolved: deleted all `.mkv` files in `/var/lib/motion` (freed to 66%
used / 2.2GB available) and set **`movie_output off`** (alongside the
already-off `picture_output`) — `motion` now writes nothing to disk, stream
only. If recording is ever wanted again, set up a retention cron
(`find /var/lib/motion -name '*.mkv' -mtime +N -delete`) before re-enabling
`movie_output` — nothing like that exists on this Pi today.

## Backups

Timestamped `motion.conf.bak.<timestamp>` copies from this session's edits
are left in `/etc/motion/` — the earliest predates the `flip_axis`/`rotate`
change, in case any of today's changes need reverting.
