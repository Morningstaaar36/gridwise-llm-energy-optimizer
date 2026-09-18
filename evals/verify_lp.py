"""Verify the signed-flow LP against the 10 public GridWise reference cases."""
import json, math
import numpy as np
from scipy.optimize import linprog

BIG = 1e7
H = 24

def compile_constraints(req, directives):
    """directives: list of (type, adjustment). Returns constraint tensor."""
    hrs = sorted(req["hours"], key=lambda x: x["hour"])
    bat = req["battery"]
    solar = np.array([h["solar_kwh"] for h in hrs], float)
    C = dict(
        solar=solar.copy(),
        reserve=np.full(H, float(bat["minimum_energy_kwh"])),
        chg=np.full(H, float(bat["max_charge_kwh_per_hour"])),
        dis=np.full(H, float(bat["max_discharge_kwh_per_hour"])),
        gcap=np.full(H, BIG),
    )
    for dt, adj in directives:
        if dt == "no_op" or adj is None:
            continue
        hh = adj.get("hours", [])
        if dt == "solar_reduction":
            f = float(adj["factor"])
            for h in hh: C["solar"][h] = min(C["solar"][h], solar[h] * f)
        elif dt == "minimum_battery_reserve":
            v = float(adj["minimum_energy_kwh"])
            for h in hh: C["reserve"][h] = max(C["reserve"][h], v)
        elif dt == "no_charge_window":
            for h in hh: C["chg"][h] = 0.0
        elif dt == "no_discharge_window":
            for h in hh: C["dis"][h] = 0.0
        elif dt == "max_grid_window":
            v = float(adj["max_grid_kwh"])
            for h in hh: C["gcap"][h] = min(C["gcap"][h], v)
    return C

def solve(req, C):
    """Variables x = [g(24), s(24), b(24), e(24)]; b>0 charge, b<0 discharge."""
    hrs = sorted(req["hours"], key=lambda x: x["hour"])
    bat = req["battery"]
    demand = np.array([h["demand_kwh"] for h in hrs], float)
    tariff = np.array([h["tariff_bdt_per_kwh"] for h in hrs], float)
    cap  = float(bat["capacity_kwh"]); e0 = float(bat["initial_energy_kwh"])
    n = 4 * H
    G, S, B, E = 0, H, 2 * H, 3 * H
    c = np.zeros(n); c[G:G + H] = tariff
    Aeq = np.zeros((2 * H, n)); beq = np.zeros(2 * H)
    for h in range(H):                                   # energy balance
        Aeq[h, G + h] = 1; Aeq[h, S + h] = 1; Aeq[h, B + h] = -1
        beq[h] = demand[h]
    for h in range(H):                                   # battery state
        r = H + h
        Aeq[r, E + h] = 1; Aeq[r, B + h] = -1
        if h == 0: beq[r] = e0
        else: Aeq[r, E + h - 1] = -1; beq[r] = 0.0
    bounds = []
    bounds += [(0, C["gcap"][h]) for h in range(H)]
    bounds += [(0, C["solar"][h]) for h in range(H)]
    bounds += [(-C["dis"][h], C["chg"][h]) for h in range(H)]
    bounds += [(C["reserve"][h], cap) for h in range(H)]
    bounds[E + H - 1] = (e0, e0)                         # end-of-day neutrality
    res = linprog(c, A_eq=Aeq, b_eq=beq, bounds=bounds, method="highs")
    return res

def replay(req, C, plan, tol=1e-6):
    """Independent arithmetic replay of a returned plan."""
    hrs = sorted(req["hours"], key=lambda x: x["hour"])
    bat = req["battery"]; cap = float(bat["capacity_kwh"]); e = float(bat["initial_energy_kwh"])
    errs = []
    for h in range(H):
        p = plan[h]; d = hrs[h]["demand_kwh"]
        act, mag = p["battery_action"], float(p["battery_kwh"])
        chg = mag if act == "charge" else 0.0
        dis = mag if act == "discharge" else 0.0
        if act == "idle" and abs(mag) > tol: errs.append(f"h{h} idle w/ mag")
        if chg > C["chg"][h] + tol: errs.append(f"h{h} charge-rate")
        if dis > C["dis"][h] + tol: errs.append(f"h{h} discharge-rate")
        if p["solar_used_kwh"] > C["solar"][h] + tol: errs.append(f"h{h} solar>eff")
        if p["grid_kwh"] > C["gcap"][h] + tol: errs.append(f"h{h} grid-cap")
        if abs(p["grid_kwh"] + p["solar_used_kwh"] + dis - d - chg) > 1e-4: errs.append(f"h{h} balance")
        e = e + chg - dis
        if abs(e - p["battery_energy_after_kwh"]) > 1e-4: errs.append(f"h{h} state")
        if e < C["reserve"][h] - tol or e > cap + tol: errs.append(f"h{h} bounds {e}")
    if abs(e - float(bat["initial_energy_kwh"])) > 1e-4: errs.append("neutrality")
    return errs

pack = json.load(open("/home/lucifer/Documents/bup/BUP_CSE_FEST_2026_Participant_Docs/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"))
print(f"{'case':10} {'ref cost':>10} {'LP cost':>10} {'delta':>9}  replay")
tot_ok = 0
for case in pack["cases"]:
    req = case["input"]; exp = case["expected_output"]
    ds = [(d["directive_type"], d["structured_adjustment"]) for d in exp["directive_interpretation"]]
    C = compile_constraints(req, ds)
    r = solve(req, C)
    refcost = exp["total_cost_bdt"]
    errs = replay(req, C, exp["hourly_plan"])
    ok = r.success and abs(r.fun - refcost) < 0.01 and not errs
    tot_ok += ok
    print(f"{case['id']:10} {refcost:10.2f} {r.fun:10.2f} {r.fun-refcost:9.4f}  {'OK' if not errs else errs}")
print(f"\n{tot_ok}/10 cases: LP optimum == published reference cost AND reference plan replays clean")
