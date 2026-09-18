"""Measure the 'price of hedging': cost premium of scheduling against the
elementwise MEET of several plausible directive interpretations, vs. the
nominal optimum for the single ground-truth interpretation."""
import json, itertools, copy
import numpy as np
from verify_lp import compile_constraints, solve, replay, H, BIG

pack = json.load(open("/home/lucifer/Documents/bup/BUP_CSE_FEST_2026_Participant_Docs/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"))

def meet(Cs):
    """Elementwise conservative meet over compiled constraint tensors."""
    return dict(
        solar=np.min([c["solar"] for c in Cs], axis=0),
        reserve=np.max([c["reserve"] for c in Cs], axis=0),
        chg=np.min([c["chg"] for c in Cs], axis=0),
        dis=np.min([c["dis"] for c in Cs], axis=0),
        gcap=np.min([c["gcap"] for c in Cs], axis=0),
    )

def perturb(dt, adj):
    """Plausible LLM extraction errors a paraphrase could induce."""
    out = []
    if adj is None: return out
    hh = adj.get("hours", [])
    if hh:
        a = copy.deepcopy(adj); a["hours"] = sorted(set(hh + [max(hh) + 1])) if max(hh) < 23 else hh
        out.append((dt, a))                                   # inclusive end-hour error
        if len(hh) > 1:
            b = copy.deepcopy(adj); b["hours"] = hh[:-1]
            out.append((dt, b))                               # dropped last hour
    if dt == "solar_reduction":
        c = copy.deepcopy(adj); c["factor"] = round(max(0.0, 1 - adj["factor"]), 4)
        out.append((dt, c))                                   # remaining-vs-reduction flip
    if dt == "minimum_battery_reserve":
        c = copy.deepcopy(adj); c["minimum_energy_kwh"] = adj["minimum_energy_kwh"] * 1.1
        out.append((dt, c))                                   # +10% reserve
    if dt == "max_grid_window":
        c = copy.deepcopy(adj); c["max_grid_kwh"] = adj["max_grid_kwh"] * 0.9
        out.append((dt, c))                                   # -10% cap
    return out

print(f"{'case':10} {'nominal':>10} {'hedged':>10} {'premium':>9} {'%':>7}  {'k':>2} feasible")
prem_pct = []
for case in pack["cases"]:
    req, exp = case["input"], case["expected_output"]
    gt = [(d["directive_type"], d["structured_adjustment"]) for d in exp["directive_interpretation"]]
    C_gt = compile_constraints(req, gt)
    nominal = solve(req, C_gt).fun

    # Candidate set = ground truth + one perturbed variant per applicable directive
    cands = [gt]
    for i, (dt, adj) in enumerate(gt):
        for p in perturb(dt, adj):
            alt = list(gt); alt[i] = p
            cands.append(alt)
    cands = cands[:4]                                   # cap ensemble at 4 candidates
    Cs = [compile_constraints(req, c) for c in cands]
    Cm = meet(Cs)
    r = solve(req, Cm)
    if r.success:
        hedged = r.fun
        # the hedged plan must also be valid under the TRUE directive
        prem = hedged - nominal; pct = 100 * prem / nominal
        prem_pct.append(pct)
        print(f"{case['id']:10} {nominal:10.2f} {hedged:10.2f} {prem:9.2f} {pct:6.3f}%  {len(cands):2} yes")
    else:
        print(f"{case['id']:10} {nominal:10.2f} {'INFEASIBLE':>10} {'-':>9} {'-':>7}  {len(cands):2} no -> fall back")

print(f"\nmean hedging premium: {np.mean(prem_pct):.3f}%   max: {np.max(prem_pct):.3f}%")
print(f"optimization points lost (10 x premium): {10*np.mean(prem_pct)/100:.4f} of 10")
