import random, sys
sys.path.insert(0, ".ai/sessions/2026-10-29-claude-txy-reference/crosscheck/tools")
import oracle
from helab.convert.profile import builtin_profile
from helab.convert.pipeline import convert_raw
from helab.convert.reconstruct import NoRowsError
P = {"2019": builtin_profile("matlab-2019"), "2023": builtin_profile("matlab-2023-lab-edit")}
EDGE = [0, 1, -1, 199, 200, 201, 399, 400, 401, 3199, 3200, 3201, 3399, 3400, 3401, 19999, 20000, 20001]
def gen(rng):
    rows = []
    kind = rng.random()
    nhits = rng.choice([0, 1, 2, 3, 5, 10, 40])
    t = rng.randrange(-5000, 5000)
    rows.append((5, 0))
    for _ in range(rng.randrange(0, 4)):
        rows.append((5, rng.randrange(-10**6, 10**6)))
    for _ in range(nhits):
        t += rng.choice([rng.randrange(0, 4000), rng.randrange(0, 40000), rng.choice(EDGE)])
        sx = 3200 + rng.choice([0, 0, rng.randrange(-500, 500), rng.choice(EDGE) - 1600])
        sy = sx + rng.choice([0, rng.randrange(-450, 450), rng.choice([-401, -400, -399, 399, 400, 401])])
        dx = rng.choice([rng.randrange(-3300, 3300), rng.choice(EDGE) * rng.choice([1, -1])])
        dy = rng.choice([rng.randrange(-3500, 3500), rng.choice(EDGE) * rng.choice([1, -1])])
        p = [(0, t + (sx + dx) // 2), (1, t + (sx - dx) // 2), (2, t + (sy + dy) // 2), (3, t + (sy - dy) // 2)]
        p = [q for q in p if rng.random() > 0.1]  # drop corners sometimes
        rows += p
        for _ in range(rng.choice([0, 0, 1, 2])):  # extra corner / mcp / duplicate pulses
            rows.append((rng.choice([0, 1, 2, 3, 4, 4, 6]), t + rng.randrange(-3500, 7000)))
        if rng.random() < 0.05:
            rows.append(rng.choice(p) if p else (0, t))
    head = rows[:1] if rng.random() < 0.9 else []
    body = rows[len(head):]
    if rng.random() < 0.5: body.sort(key=lambda r: r[1])
    else: rng.shuffle(body)
    rows = head + body
    B = 13656646605557
    lines = [f"{c},{x + B}".encode() for c, x in rows]
    if rng.random() < 0.1 and lines:  # a NaN-time line
        lines.insert(rng.randrange(len(lines) + 1), rng.choice([b"0", b"1,", b"2", b"3,"]))
    data = b"\r\n".join(lines) + (b"\r\n" if rng.random() < 0.9 else b"")
    return data
rng = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
N = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
bad = 0; stats = {"hits": 0, "phantom_like": 0}
for k in range(N):
    data = gen(rng)
    for v in ("2019", "2023"):
        try:
            o = oracle.reconstruct(oracle.read_raw(data), v); ob = oracle.dlmwrite_bytes(o)
            if v == "2019" and not o: ob = None
            stats["hits"] += len(o); stats["phantom_like"] += sum(1 for r in o if r[0] == 0 and r[2] == 0)
        except oracle.MatlabError:
            ob = "error"
        try:
            pb = convert_raw(data, P[v])
        except NoRowsError:
            pb = "error"
        if ob != pb:
            bad += 1
            if bad <= 3:
                open(f".ai/temp/crosscheck/fuzzfail_{v}_{k}.txt", "wb").write(data); print("MISMATCH", v, k)
print(N, "files x 2 variants;", bad, "mismatches;", stats)
