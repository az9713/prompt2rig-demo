"""Live vs HQ motion quality, measured on exported prompt2rig takes (Tier 3). Needs only numpy.

    python metrics.py ../prompt2rig-main/takes            # pairs takeN_*_live.glb with takeN_*_hq.glb
    python metrics.py a_live.glb b_hq.glb ...             # or any GLBs
    python metrics.py ../prompt2rig-main/takes --plot     # also writes metrics.png (needs matplotlib)

Per take (lower is better for all):
  jerk      mean angular jerk of body bones, deg/s^3 (third derivative of rotation; jitter shows up here)
  skate     mean horizontal toe speed while the toe is on the floor, body heights/s (foot sliding)
  hips_acc  mean hips acceleration, body heights/s^2 (root wobble)
  bone_cv   mean coefficient of variation of body bone lengths (limb stretch; ~0 for rotation-only rigs)
"""

from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path

import numpy as np

FPS = 30.0
BODY = ["Hips", "Spine", "Spine1", "Spine2", "Neck", "Head",
        "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand", "RightShoulder", "RightArm", "RightForeArm", "RightHand",
        "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase", "RightUpLeg", "RightLeg", "RightFoot", "RightToeBase"]
short = lambda n: re.sub(r"^mixamorig\d*[:_]?", "", n or "", flags=re.I)  # noqa: E731 (same rule as retarget.js)
NP_TYPE = {5126: np.float32, 5123: np.uint16, 5125: np.uint32, 5121: np.uint8}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


# ---- GLB reading -----------------------------------------------------------------------------
def read_glb(path):
    data = Path(path).read_bytes()
    magic, _, _ = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF", f"{path}: not a .glb"
    off, gltf, binc = 12, None, b""
    while off < len(data):
        ln, kind = struct.unpack_from("<I4s", data, off)
        chunk = data[off + 8: off + 8 + ln]
        if kind == b"JSON":
            gltf = json.loads(chunk)
        elif kind == b"BIN\x00":
            binc = chunk
        off += 8 + ln
    return gltf, binc


def accessor(gltf, binc, i):
    a = gltf["accessors"][i]
    bv = gltf["bufferViews"][a["bufferView"]]
    dt, nc = NP_TYPE[a["componentType"]], NCOMP[a["type"]]
    start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride", 0) or nc * np.dtype(dt).itemsize
    raw = np.frombuffer(binc, np.uint8, count=stride * (a["count"] - 1) + nc * np.dtype(dt).itemsize, offset=start)
    rows = np.lib.stride_tricks.as_strided(raw, (a["count"], nc * np.dtype(dt).itemsize), (stride, 1))
    out = np.ascontiguousarray(rows).view(dt).reshape(a["count"], nc).astype(np.float64)
    if a.get("normalized") and dt != np.float32:
        out /= np.iinfo(dt).max
    return out


# ---- quaternions (x, y, z, w like glTF) ---------------------------------------------------------
def qmul(a, b):
    ax, ay, az, aw = np.moveaxis(a, -1, 0)
    bx, by, bz, bw = np.moveaxis(b, -1, 0)
    return np.stack([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz], -1)


def qinv(q):
    return q * np.array([-1, -1, -1, 1.0])


def qlog(q):  # rotation vector (rad) of a unit quaternion
    q = np.where(q[..., 3:4] < 0, -q, q)
    v, w = q[..., :3], np.clip(q[..., 3], -1, 1)
    s = np.linalg.norm(v, axis=-1)
    ang = 2 * np.arctan2(s, w)
    return v * np.where(s > 1e-9, ang / np.maximum(s, 1e-12), 2.0)[..., None]


def qmat(q):
    x, y, z, w = np.moveaxis(q, -1, 0)
    return np.stack([np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], -1),
                     np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], -1),
                     np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], -1)], -2)


def sample(times, values, t, path):
    """Linear (nlerp for rotations) resampling of one glTF channel at times t."""
    idx = np.clip(np.searchsorted(times, t, side="right") - 1, 0, len(times) - 1)
    nxt = np.minimum(idx + 1, len(times) - 1)
    span = np.maximum(times[nxt] - times[idx], 1e-9)
    f = np.clip((t - times[idx]) / span, 0, 1)[:, None]
    a, b = values[idx], values[nxt]
    if path != "rotation":
        return a + (b - a) * f
    b = np.where((a * b).sum(-1, keepdims=True) < 0, -b, b)
    q = a + (b - a) * f
    return q / np.linalg.norm(q, axis=-1, keepdims=True)


# ---- forward kinematics -----------------------------------------------------------------------
def load_motion(path):
    """Returns (names, local quats [T,N,4], world positions [T,N,3]) sampled at FPS."""
    gltf, binc = read_glb(path)
    nodes = gltf["nodes"]
    anim = gltf["animations"][0]
    chans = []
    tmax = 0.0
    for ch in anim["channels"]:
        s = anim["samplers"][ch["sampler"]]
        if s.get("interpolation", "LINEAR") == "CUBICSPLINE":
            raise SystemExit(f"{path}: CUBICSPLINE animation not supported")
        times = accessor(gltf, binc, s["input"])[:, 0]
        vals = accessor(gltf, binc, s["output"])
        chans.append((ch["target"]["node"], ch["target"]["path"], times, vals))
        tmax = max(tmax, times[-1])
    t = np.arange(0, tmax + 1e-6, 1 / FPS)
    T, N = len(t), len(nodes)

    def rest(n, key, default):
        return np.tile(np.array(n.get(key, default), float), (T, 1))
    tr = [rest(n, "translation", [0, 0, 0]) for n in nodes]
    ro = [rest(n, "rotation", [0, 0, 0, 1]) for n in nodes]
    sc = [rest(n, "scale", [1, 1, 1]) for n in nodes]
    for node, p, times, vals in chans:
        if p in ("translation", "rotation", "scale"):
            {"translation": tr, "rotation": ro, "scale": sc}[p][node] = sample(times, vals, t, p)

    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    world = [None] * N

    def wmat(i):  # [T,4,4]
        if world[i] is None:
            m = np.zeros((T, 4, 4))
            if "matrix" in nodes[i]:
                m[:] = np.array(nodes[i]["matrix"]).reshape(4, 4).T
            else:
                m[:, :3, :3] = qmat(ro[i]) * sc[i][:, None, :]
                m[:, :3, 3] = tr[i]
                m[:, 3, 3] = 1
            world[i] = wmat(parent[i]) @ m if i in parent else m
        return world[i]

    names = [short(n.get("name")) for n in nodes]
    pick = [names.index(b) for b in BODY if b in names]
    if len(pick) < 10:
        raise SystemExit(f"{path}: no Mixamo skeleton found (bones: {names[:8]}...)")
    quats = np.stack([ro[i] for i in pick], 1)
    pos = np.stack([wmat(i)[:, :3, 3] for i in pick], 1)
    return [names[i] for i in pick], quats, pos, parent, pick


def metrics(path):
    names, q, pos, parent, pick = load_motion(path)
    T = len(q)
    if T < 8:
        raise SystemExit(f"{path}: clip too short")
    # angular velocity per bone from consecutive local rotations, then jerk = 2nd derivative of it
    w = qlog(qmul(qinv(q[:-1]), q[1:])) * FPS                       # [T-1, B, 3] rad/s
    jerk = np.linalg.norm(np.diff(w, 2, axis=0), axis=-1) * FPS ** 2  # rad/s^3
    up = 1  # glTF is Y-up
    feet = [names.index(b) for b in ("LeftToeBase", "RightToeBase", "LeftFoot", "RightFoot") if b in names][:2]
    head = names.index("Head") if "Head" in names else int(np.argmax(pos[0, :, up]))
    floor = np.percentile(pos[:, feet, up], 2)
    height = max(pos[0, head, up] - floor, 1e-6)
    skate = []
    for f in feet:
        h = pos[:, f, up] - floor
        v = np.linalg.norm(np.diff(pos[:, f][:, [0, 2]], axis=0), axis=-1) * FPS / height
        contact = (h[1:] < 0.03 * height) & (h[:-1] < 0.03 * height)
        if contact.any():
            skate.append(v[contact].mean())
    hips = pos[:, names.index("Hips")] if "Hips" in names else pos[:, 0]
    hips_acc = np.linalg.norm(np.diff(hips, 2, axis=0), axis=-1).mean() * FPS ** 2 / height
    gi = {g: k for k, g in enumerate(pick)}
    cv = []
    for k, g in enumerate(pick):
        p = parent.get(g)
        if p in gi:
            L = np.linalg.norm(pos[:, k] - pos[:, gi[p]], axis=-1)
            if L.mean() > 1e-6:
                cv.append(L.std() / L.mean())
    return {"frames": T, "jerk": float(np.degrees(jerk.mean())), "skate": float(np.mean(skate)) if skate else float("nan"),
            "hips_acc": float(hips_acc), "bone_cv": float(np.mean(cv)) if cv else float("nan"),
            "jerk_t": np.degrees(jerk.mean(1))}


def main(argv):
    plot = "--plot" in argv
    args = [a for a in argv if a != "--plot"]
    if not args:
        print(__doc__)
        return 1
    files = []
    for a in args:
        p = Path(a)
        files += sorted(p.glob("*.glb")) if p.is_dir() else [p]
    if not files:
        print("no .glb files found")
        return 1
    rows = {}
    print(f"{'take':58s} {'frames':>6s} {'jerk':>10s} {'skate':>7s} {'hips_acc':>9s} {'bone_cv':>8s}")
    for f in files:
        m = metrics(f)
        rows[f.stem] = m
        print(f"{f.stem[:58]:58s} {m['frames']:6d} {m['jerk']:10.0f} {m['skate']:7.3f} {m['hips_acc']:9.3f} {m['bone_cv']:8.4f}")
    # live vs HQ ratios for takes exported both ways
    pairs = [(k, k[:-5] + "_hq") for k in rows if k.endswith("_live") and k[:-5] + "_hq" in rows]
    if pairs:
        print("\nHQ / live (below 1 means HQ is better)")
        for lv, hq in pairs:
            r = {k: rows[hq][k] / rows[lv][k] if rows[lv][k] else float("nan") for k in ("jerk", "skate", "hips_acc")}
            print(f"  {lv[:-5][:50]:50s} jerk {r['jerk']:.2f}  skate {r['skate']:.2f}  hips_acc {r['hips_acc']:.2f}")
    with open("metrics.csv", "w", encoding="utf-8") as fh:
        fh.write("take,frames,jerk_deg_s3,skate_heights_s,hips_acc_heights_s2,bone_cv\n")
        for k, m in rows.items():
            fh.write(f"{k},{m['frames']},{m['jerk']:.3f},{m['skate']:.5f},{m['hips_acc']:.5f},{m['bone_cv']:.6f}\n")
    print("wrote metrics.csv")
    if plot:
        try:
            import matplotlib
        except ImportError:
            print("--plot needs matplotlib: python -m pip install matplotlib")
            return 0
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 4))
        for k, m in rows.items():
            ax.plot(np.arange(len(m["jerk_t"])) / FPS, m["jerk_t"], label=k[:40], lw=1)
        ax.set(xlabel="time (s)", ylabel="mean body jerk (deg/s³)", yscale="log", title="angular jerk per frame")
        ax.legend(fontsize=7)
        fig.tight_layout()
        fig.savefig("metrics.png", dpi=130)
        print("wrote metrics.png")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
