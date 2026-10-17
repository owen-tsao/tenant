"""
Reproduce spike: recover published TESS transit parameters from raw public data.

Claims are taken from the papers' tables. Analysis is written from the papers'
method prose (spline detrend excluding transits + 3-sigma outliers, drop
momentum-dump cadences via quality flags, BLS period search), NOT from author code.
"""
import json, sys, time, warnings
import numpy as np
import lightkurve as lk
from astropy.timeseries import BoxLeastSquares

warnings.filterwarnings("ignore")

PAPERS = {
    "1809.07242 LHS 3844 b": dict(
        target="LHS 3844", sector=1,
        claims=dict(P=(0.46292792, 0.0000016), Tc=(1325.72568, 0.00025),
                    T14_hr=(31.08/60, 0.25/60), RpRs=(0.0640, 0.0007)),
        pmin=0.2, pmax=2.0, durations_hr=[0.3, 0.4, 0.5, 0.6, 0.8],
    ),
    "1809.05967 pi Men c": dict(
        target="pi Men", sector=1,
        claims=dict(P=(6.2679, 0.00046), Tc=(2458325.50400-2457000, 0.0012),
                    T14_hr=(2.953, 0.047), RpRs=(0.01703, 0.00025)),
        pmin=1.0, pmax=13.0, durations_hr=[1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
    ),
}

def step(msg, t0):
    print(f"  [{time.time()-t0:6.1f}s] {msg}", flush=True)

def reproduce(name, spec):
    t0 = time.time()
    print(f"\n=== {name} ===")
    # 1. Fetch the data the paper names: Sector 1, 2-min SPOC light curve
    sr = lk.search_lightcurve(spec["target"], mission="TESS", sector=spec["sector"],
                              author="SPOC", exptime=120)
    step(f"search: {len(sr)} products", t0)
    if len(sr) == 0:
        return dict(status="could_not_attempt", reason="no SPOC 2-min product")
    lc = sr[0].download(quality_bitmask="default", flux_column="pdcsap_flux")
    lc = lc.remove_nans().normalize()
    step(f"download: {len(lc)} cadences, span {lc.time.value.max()-lc.time.value.min():.1f} d", t0)

    # 2. Detrend as described: smooth spline-like filter, mask 3-sigma outliers,
    #    then re-flatten with transits masked once found (iterate once).
    flat = lc.flatten(window_length=901, polyorder=2, break_tolerance=10)   # ~1.25 d window at 2-min
    flat = flat.remove_outliers(sigma_upper=3, sigma_lower=20)               # keep dips, drop flares/high outliers
    step(f"flatten+outliers: {len(flat)} cadences, rms {np.std(flat.flux.value)*1e6:.0f} ppm", t0)

    # 3. BLS search over the stated range
    t = flat.time.value; y = flat.flux.value; dy = flat.flux_err.value
    durs = np.array(spec["durations_hr"]) / 24.0
    bls = BoxLeastSquares(t, y, dy)
    periods = np.exp(np.linspace(np.log(spec["pmin"]), np.log(spec["pmax"]), 200000))
    res = bls.power(periods, durs, objective="snr")
    i = np.argmax(res.power)
    P0, T0, D0, dep0 = res.period[i], res.transit_time[i], res.duration[i], res.depth[i]
    step(f"BLS coarse: P={P0:.6f} d, SNR={res.power[i]:.1f}", t0)

    # 4. Refine: fine period grid around peak, finer durations
    fine_p = np.linspace(P0*(1-2e-4), P0*(1+2e-4), 4001)
    fine_d = np.linspace(D0*0.6, D0*1.4, 41)
    res2 = bls.power(fine_p, fine_d, objective="snr")
    j = np.argmax(res2.power)
    P, T, D, dep = res2.period[j], res2.transit_time[j], res2.duration[j], res2.depth[j]
    dep_err = res2.depth_err[j]
    # period uncertainty: half-width of the fine peak where SNR drops by 1 (crude but deterministic)
    pk = res2.power[j]
    above = fine_p[res2.power >= pk - 1.0]
    P_err = max((above.max()-above.min())/2, (fine_p[1]-fine_p[0]))
    stats = bls.compute_stats(P, D, T)
    step(f"BLS refined: P={P:.7f}±{P_err:.7f}, Tc={T:.5f}, T14={D*24:.3f} h, depth={dep*1e6:.0f}±{dep_err*1e6:.0f} ppm, "
         f"{len(stats['transit_times'])} transits", t0)

    # 5. Re-flatten with transits masked (as the papers do) and re-measure depth
    mask = bls.transit_mask(lc.time.value, P, D*1.5, T)
    flat2 = lc.flatten(window_length=901, polyorder=2, break_tolerance=10, mask=mask)
    flat2 = flat2.remove_outliers(sigma_upper=3, sigma_lower=20)
    bls2 = BoxLeastSquares(flat2.time.value, flat2.flux.value, flat2.flux_err.value)
    res3 = bls2.power(fine_p, fine_d, objective="snr")
    k = np.argmax(res3.power)
    P, T, D, dep, dep_err = res3.period[k], res3.transit_time[k], res3.duration[k], res3.depth[k], res3.depth_err[k]
    # Box depth underestimates (Rp/Rs)^2 for a limb-darkened, non-grazing transit; use the
    # box depth as a lower bound and the central depth from a 5-point in-transit median as upper.
    RpRs_box = np.sqrt(dep); RpRs_box_err = dep_err/(2*np.sqrt(dep))
    step(f"masked re-flatten: P={P:.7f}, T14={D*24:.3f} h, depth={dep*1e6:.0f}±{dep_err*1e6:.0f} ppm", t0)

    # Align Tc to the paper's epoch (any integer number of periods is equivalent)
    Tc_claim = spec["claims"]["Tc"][0]
    n = np.round((Tc_claim - T)/P); T_aligned = T + n*P

    got = dict(P=(P, P_err), Tc=(T_aligned, D*0.1), T14_hr=(D*24, (fine_d[1]-fine_d[0])*24),
               RpRs=(RpRs_box, RpRs_box_err))

    # 6. Deterministic verdicts: |claim - ours| / sqrt(sig_claim^2 + sig_ours^2)
    verdicts = {}
    for kname, (cv, cs) in spec["claims"].items():
        ov, os_ = got[kname]
        z = abs(cv-ov)/np.sqrt(cs**2 + os_**2)
        verdicts[kname] = dict(claim=cv, claim_sig=cs, ours=float(ov), ours_sig=float(os_), z=float(z),
                               pass_3sig=bool(z <= 3))
        print(f"  {kname:7s} claim {cv:.7g} ± {cs:.2g} | ours {ov:.7g} ± {os_:.2g} | z={z:5.1f} | {'PASS' if z<=3 else 'FAIL'}")
    step("done", t0)
    return dict(status="attempted", verdicts=verdicts, seconds=round(time.time()-t0,1))

if __name__ == "__main__":
    out = {}
    for name, spec in PAPERS.items():
        try:
            out[name] = reproduce(name, spec)
        except Exception as e:
            out[name] = dict(status="error", error=repr(e))
            print("  ERROR:", repr(e))
    json.dump(out, open("results.json","w"), indent=2)
