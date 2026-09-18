"""Verify the meet theorem numerically + lattice-descent fallback on infeasible meets."""
import json, copy, itertools
import numpy as np
from verify_lp import compile_constraints, solve, replay, H
from hedging_premium import meet, perturb

pack = json.load(open("/home/lucifer/Documents/bup/BUP_CSE_FEST_2026_Participant_Docs/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"))

def plan_from(res):
    g, s, b, e = (res.x[i*H:(i+1)*H] for i in range(4))
    out = []
    for h in range(H):
        if b[h] > 1e-8:   act, mag = "charge", b[h]
        elif b[h] < -1e-8: act, mag = "discharge", -b[h]
        else:             act, mag = "idle", 0.0
        out.append(dict(hour=h, grid_kwh=g[h], solar_used_kwh=s[h], battery_action=act,
                        battery_kwh=mag, battery_energy_after_kwh=e[h]))
    return out

print(f"{'case':10} {'|S|':>3} {'used':>4} {'nominal':>10} {'shipped':>10} {'prem%':>7}  valid-under-GT")
for case in pack["cases"]:
    req, exp = case["input"], case["expected_output"]
    gt = [(d["directive_type"], d["structured_adjustment"]) for d in exp["directive_interpretation"]]
    C_gt = compile_constraints(req, gt); nominal = solve(req, C_gt).fun

    cands = [gt]
    for i, (dt, adj) in enumerate(gt):
        for p in perturb(dt, adj):
            alt = list(gt); alt[i] = p; cands.append(alt)
    cands = cands[:4]
    Cs = [compile_constraints(req, c) for c in cands]

    # LATTICE DESCENT: largest prefix of the posterior-ordered candidate list whose meet is feasible
    used, res = 1, solve(req, Cs[0])
    for k in range(len(Cs), 1, -1):
        r = solve(req, meet(Cs[:k]))
        if r.success and r.status == 0:
            used, res = k, r; break

    plan = plan_from(res)
    errs = replay(req, C_gt, plan)          # replay against the TRUE directive
    prem = 100 * (res.fun - nominal) / nominal
    print(f"{case['id']:10} {len(Cs):3} {used:4} {nominal:10.2f} {res.fun:10.2f} {prem:6.3f}%  "
          f"{'PASS' if not errs else errs}")
