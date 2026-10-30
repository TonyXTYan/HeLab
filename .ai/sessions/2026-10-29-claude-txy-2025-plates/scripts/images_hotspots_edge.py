"""edge_ellipse from images_hotspots.py, importable without running it."""
import numpy as np


def edge_ellipse(X, Y, cx0=0.0, cy0=0.0):
    """Per 15-degree sector: radius where density drops to half its plateau (10-28 mm)."""
    r = np.hypot(X - cx0, Y - cy0)
    th = np.arctan2(Y - cy0, X - cx0)
    pts = []
    for k in range(24):
        a0 = -np.pi + k * np.pi / 12
        s = (th >= a0) & (th < a0 + np.pi / 12)
        if s.sum() < 2000:
            continue
        rr = r[s]
        e = np.arange(0, 60.5, 0.5) * 1e-3
        h, _ = np.histogram(rr, e)
        dens = h / (np.pi * (e[1:] ** 2 - e[:-1] ** 2))
        dens = np.convolve(dens, np.ones(3) / 3, mode="same")
        mid = (e[1:] + e[:-1]) / 2
        plateau = np.median(dens[(mid > 10e-3) & (mid < 28e-3)])
        beyond = np.flatnonzero((mid > 28e-3) & (dens < 0.5 * plateau))
        if len(beyond) == 0:
            continue
        j = beyond[0]
        # linear interpolation between j-1 and j
        f = (dens[j - 1] - 0.5 * plateau) / max(dens[j - 1] - dens[j], 1e-12)
        redge = mid[j - 1] + f * (mid[j] - mid[j - 1])
        ang = a0 + np.pi / 24
        pts.append((cx0 + redge * np.cos(ang), cy0 + redge * np.sin(ang), redge, ang))
    pts = np.array(pts)
    if len(pts) < 8:
        return None, pts
    x, y = pts[:, 0], pts[:, 1]
    # general conic fit A x^2 + B xy + C y^2 + D x + E y = 1
    M = np.c_[x ** 2, x * y, y ** 2, x, y]
    A, B, C, D, E = np.linalg.lstsq(M, np.ones(len(x)), rcond=None)[0]
    den = B ** 2 - 4 * A * C
    xc = (2 * C * D - B * E) / den
    yc = (2 * A * E - B * D) / den
    F = -1 - (A * xc ** 2 + B * xc * yc + C * yc ** 2 + D * xc + E * yc)
    # axes from eigen of [[A, B/2],[B/2, C]] scaled by -F
    w, v = np.linalg.eigh(np.array([[A, B / 2], [B / 2, C]]))
    axes = np.sqrt(-F / w)
    tilt = float(np.degrees(np.arctan2(v[1, 0], v[0, 0])))
    resid = np.hypot(x - xc, y - yc)
    return {"centre_mm": [round(float(xc) * 1e3, 2), round(float(yc) * 1e3, 2)],
            "semi_axes_mm": [round(float(axes[0]) * 1e3, 2), round(float(axes[1]) * 1e3, 2)],
            "axis_ratio": round(float(max(axes) / min(axes)), 4), "tilt_deg_of_first_axis": round(tilt, 1),
            "mean_radius_mm": round(float(resid.mean()) * 1e3, 2), "radius_sd_mm": round(float(resid.std()) * 1e3, 2),
            "sectors": int(len(x))}, pts
