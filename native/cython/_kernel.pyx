# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True, initializedcheck=False
"""The ``cython`` backend's compiled kernel: ``helab/convert/backends/reference.py`` loop for loop, in C.

Built by ``native/cython/build.py`` into ``helab/convert/backends/cython/_kernel``; called only by
``helab/convert/backends/cython/__init__.py``, which holds the profile logic and the within-shot
split. Every function releases the GIL for its work. The arithmetic is the reference's, operation
for operation, in doubles; the build turns off floating-point contraction (FMA) and fast-math, so
the results are the same bits. Line numbers ``L…`` are MATLAB's 2019 file, as in the reference.

No NumPy C API: arrays come in as typed memoryviews and go out as NumPy arrays made by the caller
or with ``np.empty``.
"""
from libc.math cimport fabs, isnan, NAN
from libc.stdlib cimport free, malloc
from libc.string cimport memcpy

import numpy as np

cdef extern from "_kernel_build.h":
    const char *KERNEL_SOURCE_SHA256

# The SHA-256 of this file when it was built (build.py writes the header), so the wrapper can tell
# a binary older than its source.
SOURCE_SHA256 = KERNEL_SOURCE_SHA256.decode("ascii")


cdef inline bint _before(double a, double b) noexcept nogil:
    """``a`` sorts strictly before ``b``: ascending, NaN last, NaNs equal (MATLAB's sort)."""
    if isnan(a):
        return False
    if isnan(b):
        return True
    return a < b


cdef int _stable_argsort(const double *key, Py_ssize_t n, Py_ssize_t *order) noexcept nogil:
    """``order`` = MATLAB's ``[~, I] = sort(key)`` (stable, NaN last), 0-based. A merge sort over
    runs of 32 sorted by insertion; an already sorted key costs one pass. Returns -1 when out of
    memory."""
    cdef Py_ssize_t i, j, k, lo, mid, hi, width, run = 32
    cdef Py_ssize_t *tmp
    cdef Py_ssize_t *swap
    cdef Py_ssize_t item
    for i in range(n):
        order[i] = i
    for i in range(1, n):
        if _before(key[i], key[i - 1]):
            break
    else:
        return 0
    lo = 0
    while lo < n:
        hi = lo + run if lo + run < n else n
        for i in range(lo + 1, hi):
            item = order[i]
            j = i
            while j > lo and _before(key[item], key[order[j - 1]]):
                order[j] = order[j - 1]
                j -= 1
            order[j] = item
        lo = hi
    if n <= run:
        return 0
    tmp = <Py_ssize_t *> malloc(n * sizeof(Py_ssize_t))
    if tmp == NULL:
        return -1
    cdef Py_ssize_t *src = order
    cdef Py_ssize_t *dst = tmp
    width = run
    while width < n:
        lo = 0
        while lo < n:
            mid = lo + width if lo + width < n else n
            hi = lo + 2 * width if lo + 2 * width < n else n
            i = lo
            j = mid
            k = lo
            while i < mid and j < hi:
                # Take from the right only when strictly before: equal keys keep their order.
                if _before(key[src[j]], key[src[i]]):
                    dst[k] = src[j]
                    j += 1
                else:
                    dst[k] = src[i]
                    i += 1
                k += 1
            while i < mid:
                dst[k] = src[i]
                i += 1
                k += 1
            while j < hi:
                dst[k] = src[j]
                j += 1
                k += 1
            lo = hi
        swap = src
        src = dst
        dst = swap
        width *= 2
    if src != order:
        memcpy(order, src, n * sizeof(Py_ssize_t))
    free(tmp)
    return 0


def prepare(const double[::1] channels, const double[::1] times, bint subtract_time_zero,
            const double[::1] dead_channels, const double[::1] dead_tolerances):
    """Sort the rows by time (L58–60), subtract the first raw row's time (L62–66) and apply the
    dead-time cuts (L2023:429–458; ``dead_tolerances`` in bins, one per entry of
    ``dead_channels``, each corner judged on the channels before any cut). Returns the sorted
    channels (cut rows NaN) and times, as new arrays."""
    cdef Py_ssize_t n = times.shape[0], ndead = dead_channels.shape[0], k, d
    ch_array = np.empty(n, dtype=np.float64)
    t_array = np.empty(n, dtype=np.float64)
    cdef double[::1] ch = ch_array
    cdef double[::1] t = t_array
    cdef Py_ssize_t *order = <Py_ssize_t *> malloc((n if n > 0 else 1) * sizeof(Py_ssize_t))
    cdef double *snapshot = NULL
    cdef double t_zero, first, value, channel, tolerance
    cdef int failed = 0
    if order == NULL:
        raise MemoryError()
    with nogil:
        failed = _stable_argsort(&times[0] if n > 0 else NULL, n, order)
        if failed == 0:
            for k in range(n):
                ch[k] = channels[order[k]]
                t[k] = times[order[k]]
            if subtract_time_zero and n > 0:
                t_zero = times[0]
                for k in range(n):
                    t[k] = t[k] - t_zero
            if ndead > 0:
                snapshot = <double *> malloc((n if n > 0 else 1) * sizeof(double))
                if snapshot == NULL:
                    failed = -1
                else:
                    for k in range(n):
                        snapshot[k] = ch[k]
                    for d in range(ndead):
                        channel = dead_channels[d]
                        tolerance = dead_tolerances[d]
                        # uniquetol_keep: the first of each group within tolerance (≤) of the
                        # group's first value, not chained; a NaN is its own group.
                        first = NAN
                        for k in range(n):
                            if snapshot[k] != channel:
                                continue
                            value = t[k]
                            if isnan(value) or isnan(first) or not fabs(value - first) <= tolerance:
                                first = value
                            else:
                                ch[k] = NAN
                    free(snapshot)
    free(order)
    if failed:
        raise MemoryError()
    return ch_array, t_array


def match(double[::1] ch, const double[::1] t, Py_ssize_t lo, Py_ssize_t hi, Py_ssize_t start,
          const Py_ssize_t[::1] search, double window, double x_limit, double y_limit, double xy_limit,
          double c_x1, double c_x2, double c_y1, double c_y2, double time_sum_t_x, double time_sum_t_y,
          bint centred, double[:, ::1] out):
    """The 4-corner match (L449–576) for x1 rows ``start`` ≤ i < ``hi``, candidates limited to
    ``lo`` ≤ j < ``hi``; used rows get channel NaN in ``ch`` (L557–560). Each hit fills a row of
    ``out``: the row MATLAB fills, T, x1′, x2′, y1′, y2′ (before scaling). Returns the hit count
    and, for the phantom row, whether an x pair without a y came after the last hit with its x1′
    and x2′ columns: ``(hits, pending, x1′, x2′)``. ``out`` needs (hi − lo) // 4 + 1 rows: every
    hit uses four unused rows (distinct corners)."""
    cdef Py_ssize_t depth = search.shape[0], capacity = out.shape[0]
    cdef Py_ssize_t i, j, j2, j3, s, s2, s3, x2_index = 0, hits = 0
    cdef int how_many_x, how_many_y
    cdef bint pending = False, overflow = False
    cdef double x1_val, x2_val, y1_val, y2_val, x1 = 0.0, x2 = 0.0, tx = 0.0, ty
    cdef double col1 = 0.0, col2 = 0.0, pend1 = 0.0, pend2 = 0.0
    cdef double *chp = &ch[0] if ch.shape[0] > 0 else NULL
    cdef const double *tp = &t[0] if t.shape[0] > 0 else NULL
    cdef const Py_ssize_t *sp = &search[0] if depth > 0 else NULL
    if lo < 0 or hi > t.shape[0] or hi > ch.shape[0] or out.shape[1] != 5:
        raise ValueError("match: bounds or output shape")
    with nogil:
        for i in range(start if start > lo else lo, hi):                 # L449
            if chp[i] != c_x1:                                           # L450
                continue
            x1_val = tp[i]                                               # L451
            how_many_x = 0
            for s in range(depth):                                       # L456–457
                j = i + sp[s]
                if j < lo or j >= hi:                                    # L459–464
                    continue
                if fabs(tp[j] - x1_val) > window:                        # L465
                    continue
                if chp[j] == c_x2:                                       # L474
                    x2_val = tp[j]
                    if fabs(x1_val - x2_val) < x_limit:                  # L477
                        how_many_x += 1
                        if how_many_x > 1:                               # L479
                            break
                        x1 = x1_val
                        x2 = x2_val
                        tx = 0.5 * (x1 + x2 - time_sum_t_x)              # L485
                        if centred:                                      # L486–487
                            col1 = x1 - tx
                            col2 = x2 - tx
                        else:
                            col1 = x1
                            col2 = x2
                        x2_index = j                                     # L490
            if how_many_x == 0:                                          # L498
                continue
            how_many_y = 0
            for s2 in range(depth):                                      # L505–506
                j2 = i + sp[s2]
                if j2 < lo or j2 >= hi:                                  # L509–514
                    continue
                if fabs(tp[j2] - x1_val) > window:                       # L515
                    continue
                if chp[j2] != c_y1:                                      # L524
                    continue
                y1_val = tp[j2]
                for s3 in range(depth):                                  # L529–530
                    j3 = i + sp[s3]
                    if j3 < lo or j3 >= hi:                              # L532–537
                        continue
                    if fabs(tp[j3] - x1_val) > window:                   # L538
                        continue
                    if chp[j3] != c_y2:                                  # L542
                        continue
                    y2_val = tp[j3]
                    if fabs(y1_val - y2_val) < y_limit and fabs(x1 + x2 - y1_val - y2_val) < xy_limit:  # L544
                        how_many_y += 1
                        if how_many_y > 1:                               # L546
                            break
                        if hits >= capacity:
                            overflow = True
                            break
                        ty = 0.5 * (y1_val + y2_val - time_sum_t_y)      # L551
                        out[hits, 0] = (tx + ty) / 2                     # L552, L555
                        out[hits, 1] = col1
                        out[hits, 2] = col2
                        if centred:                                      # L553–554
                            out[hits, 3] = y1_val - ty
                            out[hits, 4] = y2_val - ty
                        else:
                            out[hits, 3] = y1_val
                            out[hits, 4] = y2_val
                        hits += 1
                        chp[i] = NAN                                     # L557–560
                        chp[x2_index] = NAN
                        chp[j2] = NAN
                        chp[j3] = NAN
                if overflow:
                    break
            if overflow:
                break
            if how_many_y == 0:                                          # L574–576
                pending = True
                pend1 = col1
                pend2 = col2
            else:
                pending = False
    if overflow:
        raise RuntimeError("match: more hits than rows / 4 (repeated corner channels?)")
    return hits, pending, pend1, pend2


def assemble(list pieces, bint phantom, double phantom_x1, double phantom_x2, double bin_time, double v_x,
             double v_y):
    """The hits from the matched rows (L580–592) and the final sort by T (L1528–1530). ``pieces``
    are ``(out, hits)`` in row order; ``phantom`` adds MATLAB's grown zero row with these x
    columns last. Rows with a NaN T are dropped, then T = t·bin_time, X = (x1′ − x2′)·v⊥x·bin_time,
    Y likewise, sorted by T stably with NaN last. Returns an (n, 3) float64 array."""
    cdef Py_ssize_t total = 0, count, p, r, k, kept = 0
    cdef double[:, ::1] rows
    for item in pieces:
        total += <Py_ssize_t> item[1]
    if phantom:
        total += 1
    staged_array = np.empty((total, 5), dtype=np.float64)
    cdef double[:, ::1] staged = staged_array
    k = 0
    for item in pieces:
        rows = item[0]
        count = item[1]
        for r in range(count):
            for p in range(5):
                staged[k, p] = rows[r, p]
            k += 1
    if phantom:
        staged[k, 0] = 0.0
        staged[k, 1] = phantom_x1
        staged[k, 2] = phantom_x2
        staged[k, 3] = 0.0
        staged[k, 4] = 0.0
    scaled_array = np.empty((total, 3), dtype=np.float64)
    cdef double[:, ::1] scaled = scaled_array
    cdef double *key = <double *> malloc((total if total > 0 else 1) * sizeof(double))
    cdef Py_ssize_t *order = <Py_ssize_t *> malloc((total if total > 0 else 1) * sizeof(Py_ssize_t))
    cdef int failed = 0
    if key == NULL or order == NULL:
        free(key)
        free(order)
        raise MemoryError()
    with nogil:
        for r in range(total):
            if isnan(staged[r, 0]):                                      # L580–581
                continue
            scaled[kept, 0] = staged[r, 0] * bin_time                    # L590–592
            scaled[kept, 1] = (staged[r, 1] - staged[r, 2]) * v_x * bin_time
            scaled[kept, 2] = (staged[r, 3] - staged[r, 4]) * v_y * bin_time
            key[kept] = scaled[kept, 0]
            kept += 1
        failed = _stable_argsort(key, kept, order)
    hits_array = np.empty((kept, 3), dtype=np.float64)
    cdef double[:, ::1] hits = hits_array
    if failed == 0:
        with nogil:
            for r in range(kept):
                for p in range(3):
                    hits[r, p] = scaled[order[r], p]
    free(key)
    free(order)
    if failed:
        raise MemoryError()
    return hits_array
