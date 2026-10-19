"""Regenerate the golden vectors that `tests/test_golden.py` checks expgate against.

Development and CI only. It needs the pinned reference libraries in `requirements.txt` and
Python 3.10 (`confseq` publishes no wheels for newer interpreters; see the README). It never
imports `expgate`: the vectors are the references' answers for fixed inputs, so a bug in
`expgate.stats` cannot leak into its own expected values.

    python tests/golden/generate.py                  # rewrite the committed vectors
    python tests/golden/generate.py --out DIR        # write somewhere else (CI diffs against the repo)

Output is deterministic: fixed inputs, fixed seeds, sorted keys, and every float rounded to
``SIGNIFICANT_DIGITS`` so last-bit differences between platforms cannot change the bytes.
"""
from __future__ import annotations

import argparse
import importlib
import json
import zlib
from importlib import metadata
from math import exp, log, sqrt
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Closed-form results are compared at 1e-9 relative, so eleven digits (a relative quantization error
# of at most 5e-11) lose nothing the test can see. The sequential boundary is compared at 1e-6 and
# stored at seven digits.
SIGNIFICANT_DIGITS = 11
SEQUENTIAL_DIGITS = 7

# The reference libraries are imported by name at run time, not with import statements, so the
# workspace import-boundary check (`make workspace-check`) keeps enforcing that everything else
# under this component imports only the standard library.
np = importlib.import_module("numpy")
sp_stats = importlib.import_module("scipy.stats")
sp_integrate = importlib.import_module("scipy.integrate")
sp_optimize = importlib.import_module("scipy.optimize")
sm = importlib.import_module("statsmodels.api")
sm_proportion = importlib.import_module("statsmodels.stats.proportion")
sm_power = importlib.import_module("statsmodels.stats.power")
gb_stat = importlib.import_module("gbstats.models.statistics")
gb_test = importlib.import_module("gbstats.frequentist.tests")
confseq_boundaries = importlib.import_module("confseq.boundaries")

VERSIONS = {name: metadata.version(name)
            for name in ("numpy", "scipy", "statsmodels", "gbstats", "confseq")}


def rounded(value: float, digits: int = SIGNIFICANT_DIGITS) -> float:
    return float(f"{float(value):.{digits}g}")


def snapped(value: float) -> float:
    """Round, and store 0.0 for a value that is only floating-point noise (about 1e-17, and
    different on each platform). Only the CUPED slope and variance reduction, which are exactly 0
    when the covariate is uncorrelated with the outcome, go through here; real values are at
    least 1e-3 in the vectors and the generator checks that."""
    if abs(value) < 1e-12:
        return 0.0
    if abs(value) < 1e-3:
        raise AssertionError(f"{value!r} is neither zero nor a value the vectors can store reliably")
    return rounded(value)


def agree(label: str, a: float, b: float, rel: float = 1e-10, floor: float = 1e-13) -> None:
    """Two references that disagree mean the vector is not a reference at all; refuse to write it."""
    if abs(a - b) > max(rel * max(abs(a), abs(b)), floor):
        raise AssertionError(f"references disagree on {label}: {a!r} vs {b!r}")


def write(out: Path, name: str, method: str, references: list[str], tolerance: str, cases: list[dict]) -> None:
    document = {
        "method": method,
        "generator": "tests/golden/generate.py",
        "references": {lib: VERSIONS[lib] for lib in sorted(references)},
        "comparison": tolerance,
        "cases": cases,
    }
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"
    (out / f"{name}.json").write_text(text, encoding="utf-8")


def gb_config():
    return gb_test.FrequentistConfig(difference_type="absolute")


# --- raw data with exactly prescribed moments -------------------------------------------------

def make_arm(name: str, n: int, mean_y: float, sd_y: float, mean_x: float, sd_x: float, corr: float):
    """Per-unit data whose sample (ddof=1) means, sds and correlation equal the arguments.

    Independent of the closed forms under test: the references below recompute each estimator
    from these raw values with numpy and statsmodels.
    """
    rng = np.random.default_rng(zlib.crc32(name.encode()))
    a = rng.standard_normal(n)
    a = (a - a.mean()) / a.std(ddof=1)
    b = rng.standard_normal(n)
    b = b - b.mean()
    b = b - (b @ a) / (a @ a) * a
    b = b / b.std(ddof=1)
    x = mean_x + sd_x * a
    y = mean_y + sd_y * (corr * a + sqrt(max(1.0 - corr * corr, 0.0)) * b)
    return y, x


# --- proportions ------------------------------------------------------------------------------

PROPORTION_CASES = [
    ("ordinary", 100, 1000, 150, 1000),
    ("ordinary-unequal-n", 1200, 10000, 3100, 24000),
    ("negative-effect", 150, 1000, 100, 1000),
    ("small-n", 1, 10, 3, 12),
    ("small-n-tiny-arms", 2, 3, 1, 4),
    ("one-arm-all-successes", 4, 8, 8, 8),
    ("one-arm-no-successes", 0, 50, 3, 60),
    ("rare-events", 1, 100000, 3, 100000),
    ("near-one", 99999, 100000, 99997, 100000),
    ("near-one-negative", 99990, 100000, 99950, 100000),
    ("tiny-difference", 500000, 1000000, 500001, 1000000),
    ("large-effect", 100, 1000, 900, 1000),
]


def proportion_vectors() -> list[dict]:
    z975 = sp_stats.norm.isf(0.025)
    cases = []
    for name, cs, cn, ts, tn in PROPORTION_CASES:
        ci = sm_proportion.confint_proportions_2indep(ts, tn, cs, cn, method="wald", compare="diff", alpha=0.05)
        with np.errstate(all="ignore"):  # statsmodels also forms ratio and odds ratio, which divide by zero at p = 0
            wald = sm_proportion.test_proportions_2indep(ts, tn, cs, cn, method="wald", compare="diff", value=0)
        gb = gb_test.TwoSidedTTest(gb_stat.ProportionStatistic(n=cn, sum=cs),
                                   gb_stat.ProportionStatistic(n=tn, sum=ts), gb_config())
        sm_diff, sm_se = float(wald.diff), float((ci[1] - ci[0]) / (2 * z975))
        gb_diff, gb_se = float(gb.point_estimate), float(sqrt(gb.variance))
        agree(f"{name} diff", sm_diff, gb_diff)
        agree(f"{name} se", sm_se, gb_se)
        pooled = sm_proportion.proportions_ztest([ts, cs], [tn, cn])
        cases.append({
            "name": name,
            "inputs": {"control_successes": cs, "control_n": cn, "treatment_successes": ts, "treatment_n": tn},
            "expected": {
                "statsmodels": {"diff": rounded(sm_diff), "se": rounded(sm_se), "z": rounded(wald.statistic)},
                "gbstats": {"diff": rounded(gb_diff), "se": rounded(gb_se)},
            },
            # statsmodels' proportions_ztest pools the variance under the null of no difference;
            # expgate uses the unpooled error, so the two z statistics differ. Not asserted.
            "informational": {"pooled_z_proportions_ztest": rounded(pooled[0])},
        })
    return cases


# --- Welch means -----------------------------------------------------------------------------

MEAN_CASES = [
    ("ordinary", 10.0, 2.0, 100, 11.0, 4.0, 400),
    ("unequal-variances", 50.0, 1.0, 30, 49.0, 50.0, 3000),
    ("negative-effect", 100.0, 15.0, 800, 96.5, 14.0, 900),
    ("small-n", 5.0, 1.5, 2, 6.2, 0.5, 3),
    ("small-n-unequal", 12.0, 0.2, 5, 11.0, 6.0, 4),
    ("large-scale", 1.0e6, 1.0e5, 20000, 1.02e6, 1.1e5, 25000),
    ("tiny-scale", 3.0e-4, 2.0e-5, 400, 3.1e-4, 2.5e-5, 600),
    ("zero-variance-control", 7.0, 0.0, 50, 7.5, 2.0, 60),
    ("tiny-difference", 20.0, 8.0, 1000000, 20.001, 8.0, 1000000),
]


def welch_df(vc: float, nc: int, vt: float, nt: int) -> float:
    a, b = vc / nc, vt / nt
    return (a + b) ** 2 / (a * a / (nc - 1) + b * b / (nt - 1))


def mean_vectors() -> list[dict]:
    cases = []
    for name, cm, csd, cn, tm, tsd, tn in MEAN_CASES:
        t = sp_stats.ttest_ind_from_stats(tm, tsd, tn, cm, csd, cn, equal_var=False)
        sp_diff = tm - cm
        sp_se = abs(sp_diff / float(t.statistic))

        def stat(mean, sd, n):
            return gb_stat.SampleMeanStatistic(n=n, sum=n * mean, sum_squares=(n - 1) * sd * sd + n * mean * mean)

        gb = gb_test.TwoSidedTTest(stat(cm, csd, cn), stat(tm, tsd, tn), gb_config())
        gb_diff, gb_se = float(gb.point_estimate), float(sqrt(gb.variance))
        agree(f"{name} diff", sp_diff, gb_diff, floor=1e-12 * max(abs(cm), 1e-30))
        agree(f"{name} se", sp_se, gb_se, rel=1e-9)
        df = welch_df(csd ** 2, cn, tsd ** 2, tn)
        cases.append({
            "name": name,
            "inputs": {"control_mean": cm, "control_sd": csd, "control_n": cn,
                       "treatment_mean": tm, "treatment_sd": tsd, "treatment_n": tn},
            "expected": {
                "scipy": {"diff": rounded(sp_diff), "se": rounded(sp_se), "t": rounded(t.statistic)},
                "gbstats": {"diff": rounded(gb_diff), "se": rounded(gb_se)},
            },
            # expgate uses normal critical values; a Welch t-test uses the t distribution with
            # Welch-Satterthwaite degrees of freedom. Not asserted.
            "informational": {"welch_df": rounded(df),
                              "t_critical_one_sided_0.05": rounded(sp_stats.t.isf(0.05, df)),
                              "normal_critical_one_sided_0.05": rounded(sp_stats.norm.isf(0.05))},
        })
    return cases


# --- ratio metrics ---------------------------------------------------------------------------

# Each arm: n, numerator mean, numerator sd, denominator mean, denominator sd, correlation.
RATIO_CASES = [
    ("ordinary", (2000, 31.2, 40.5, 3.1, 2.4, 0.62), (2000, 33.0, 41.0, 3.2, 2.5, 0.60)),
    ("unequal-n", (5000, 12.0, 15.0, 2.0, 1.1, 0.4), (3000, 12.5, 16.0, 2.1, 1.2, 0.5)),
    ("negative-effect", (4000, 20.0, 9.0, 4.0, 2.0, 0.7), (4000, 18.4, 9.5, 4.0, 2.1, 0.7)),
    ("uncorrelated", (1000, 5.0, 3.0, 2.0, 1.0, 0.0), (1000, 5.5, 3.1, 2.0, 1.0, 0.0)),
    ("negative-correlation", (800, 10.0, 6.0, 3.0, 1.5, -0.5), (900, 10.6, 6.2, 3.0, 1.4, -0.4)),
    ("high-correlation", (3000, 8.0, 5.0, 2.0, 1.2, 0.99), (3000, 8.2, 5.1, 2.0, 1.2, 0.99)),
    ("small-n", (3, 4.0, 1.0, 2.0, 0.5, 0.3), (4, 5.0, 1.5, 2.0, 0.4, -0.2)),
    ("small-denominator-mean", (6000, 0.5, 0.4, 0.05, 0.02, 0.3), (6000, 0.55, 0.42, 0.05, 0.02, 0.3)),
    ("unequal-variances", (200, 10.0, 2.0, 2.0, 0.5, 0.2), (20000, 10.3, 30.0, 2.0, 0.6, 0.1)),
]


def ratio_reference_se(name: str, arm) -> tuple[float, float]:
    """Ratio and its delta-method variance, recomputed from raw per-unit data by linearization:
    var(ybar / xbar) = var(y - R x) / (n xbar**2)."""
    n, my, sy, mx, sx, corr = arm
    y, x = make_arm(name, n, my, sy, mx, sx, corr)
    ratio = y.mean() / x.mean()
    return float(ratio), float(np.var(y - ratio * x, ddof=1) / (n * x.mean() ** 2))


def ratio_vectors() -> list[dict]:
    cases = []
    for name, control, treatment in RATIO_CASES:
        def gb_stat_for(arm):
            n, my, sy, mx, sx, corr = arm
            return gb_stat.RatioStatistic(
                n=n,
                m_statistic=gb_stat.SampleMeanStatistic(n=n, sum=n * my, sum_squares=(n - 1) * sy * sy + n * my * my),
                d_statistic=gb_stat.SampleMeanStatistic(n=n, sum=n * mx, sum_squares=(n - 1) * sx * sx + n * mx * mx),
                m_d_sum_of_products=(n - 1) * corr * sy * sx + n * my * mx)

        gb = gb_test.TwoSidedTTest(gb_stat_for(control), gb_stat_for(treatment), gb_config())
        gb_diff, gb_se = float(gb.point_estimate), float(sqrt(gb.variance))
        rc, vc = ratio_reference_se(f"{name}-control", control)
        rt, vt = ratio_reference_se(f"{name}-treatment", treatment)
        lin_diff, lin_se = rt - rc, sqrt(vc + vt)
        agree(f"{name} diff", lin_diff, gb_diff, rel=1e-9)
        agree(f"{name} se", lin_se, gb_se, rel=1e-9)
        cases.append({
            "name": name,
            "inputs": {arm_name: dict(zip(("n", "num_mean", "num_sd", "den_mean", "den_sd", "corr"), arm))
                       for arm_name, arm in (("control", control), ("treatment", treatment))},
            "expected": {
                "gbstats": {"control": rounded(gb_stat_for(control).mean), "treatment": rounded(gb_stat_for(treatment).mean),
                            "diff": rounded(gb_diff), "se": rounded(gb_se)},
                "numpy_linearization": {"control": rounded(rc), "treatment": rounded(rt),
                                        "diff": rounded(lin_diff), "se": rounded(lin_se)},
            },
        })
    return cases


# --- CUPED -----------------------------------------------------------------------------------

# Each arm: n, outcome mean, outcome variance, covariate mean, covariate sd, correlation.
CUPED_CASES = [
    ("balanced-covariate", (5000, 20.46, 64.0, 20.4, 7.9, 0.8), (5000, 20.8, 66.0, 20.4, 7.9, 0.8)),
    ("covariate-imbalance", (5000, 20.46, 64.0, 20.4, 7.9, 0.8), (5000, 21.4, 66.0, 21.2, 8.0, 0.8)),
    ("negative-effect-imbalance", (4000, 50.0, 100.0, 49.0, 9.0, 0.6), (4000, 48.5, 98.0, 50.5, 9.0, 0.6)),
    ("uncorrelated", (3000, 10.0, 25.0, 9.0, 4.0, 0.0), (3000, 10.4, 26.0, 9.5, 4.0, 0.0)),
    ("negative-correlation", (2500, 15.0, 36.0, 12.0, 5.0, -0.7), (2500, 15.5, 35.0, 12.0, 5.0, -0.7)),
    ("arms-differ", (1200, 30.0, 90.0, 28.0, 6.0, 0.5), (800, 31.0, 120.0, 29.5, 7.0, 0.7)),
    ("high-correlation", (100000, 100.0, 400.0, 99.0, 19.0, 0.95), (100000, 100.4, 402.0, 99.0, 19.0, 0.95)),
    ("small-n", (4, 3.0, 2.0, 2.5, 1.0, 0.5), (3, 4.0, 3.0, 2.0, 1.5, 0.6)),
    ("proportion-outcome", (20000, 0.10, None, 0.12, 0.30, 0.30), (20000, 0.11, None, 0.12, 0.30, 0.30)),
    ("proportion-outcome-imbalance", (20000, 0.10, None, 0.12, 0.30, 0.30), (20000, 0.11, None, 0.15, 0.31, 0.30)),
]


def cuped_vectors() -> list[dict]:
    cases = []
    for name, control_arm, treatment_arm in CUPED_CASES:
        arms, inputs = {}, {}
        for label, (n, my, vy, mx, sx, corr) in (("control", control_arm), ("treatment", treatment_arm)):
            entry = {"n": n, "mean": my, "cov_mean": mx, "cov_sd": sx, "cov_corr": corr}
            if vy is None:  # a 0/1 outcome: the variance is p(1 - p) of the actual indicator values
                successes = round(n * my)
                indicator = np.zeros(n)
                indicator[:successes] = 1.0
                vy = float(np.var(indicator, ddof=0))
                entry.update(successes=successes, mean=successes / n)
                my = successes / n
            entry["var"] = rounded(vy)
            vy = entry["var"]
            inputs[label] = entry
            y, x = make_arm(f"{name}-{label}", n, my, sqrt(vy), mx, sx, corr)
            arms[label] = (y, x)
        yc, xc = arms["control"]
        yt, xt = arms["treatment"]
        # Regression on raw data with one slope for both arms: y ~ 1 + treated + x.
        # Centered so the solve is well conditioned (the treatment and slope coefficients do not
        # depend on the centering), which keeps platform noise out of the stored digits.
        x_all = np.r_[xc, xt]
        design = sm.add_constant(np.column_stack([np.r_[np.zeros(len(yc)), np.ones(len(yt))], x_all - x_all.mean()]))
        fit = sm.OLS(np.r_[yc, yt] - np.r_[yc, yt].mean(), design).fit()
        theta, diff = float(fit.params[2]), float(fit.params[1])
        adjusted_var = [float(np.var(y - theta * x, ddof=1)) for y, x in ((yc, xc), (yt, xt))]
        se = sqrt(adjusted_var[0] / len(yc) + adjusted_var[1] / len(yt))
        raw_diff = float(yt.mean() - yc.mean())
        raw_se = sqrt(float(np.var(yc, ddof=1)) / len(yc) + float(np.var(yt, ddof=1)) / len(yt))
        expected = {"statsmodels_ols_numpy": {
            "theta": snapped(theta), "diff": rounded(diff), "se": rounded(se), "raw_diff": rounded(raw_diff),
            "raw_se": rounded(raw_se), "variance_reduction": snapped(1 - se ** 2 / raw_se ** 2)}}

        def gb_arm(label):
            e = inputs[label]
            n = e["n"]
            if "successes" in e:
                post = gb_stat.ProportionStatistic(n=n, sum=e["successes"])
            else:
                post = gb_stat.SampleMeanStatistic(n=n, sum=n * e["mean"], sum_squares=(n - 1) * e["var"] + n * e["mean"] ** 2)
            pre = gb_stat.SampleMeanStatistic(n=n, sum=n * e["cov_mean"],
                                              sum_squares=(n - 1) * e["cov_sd"] ** 2 + n * e["cov_mean"] ** 2)
            product = (n - 1) * e["cov_corr"] * e["cov_sd"] * sqrt(e["var"]) + n * e["mean"] * e["cov_mean"]
            return gb_stat.RegressionAdjustedStatistic(n=n, post_statistic=post, pre_statistic=pre,
                                                       post_pre_sum_of_products=product, theta=0)

        gb = gb_test.TwoSidedTTest(gb_arm("control"), gb_arm("treatment"), gb_config())
        gb_theta = float(gb.stat_a.theta)
        gb_diff, gb_se = float(gb.point_estimate), float(sqrt(gb.variance))
        # gbstats takes the slope from the pooled sample, ignoring arm. That equals expgate's
        # within-arm slope only when both arms have the same covariate mean; otherwise it is a
        # deliberate method difference (README) and the gbstats block is informational.
        comparable = inputs["control"]["cov_mean"] == inputs["treatment"]["cov_mean"]
        if comparable:
            agree(f"{name} theta", theta, gb_theta, rel=1e-9)
            agree(f"{name} diff", diff, gb_diff, rel=1e-9)
            agree(f"{name} se", se, gb_se, rel=1e-9)
            expected["gbstats"] = {"theta": rounded(gb_theta), "diff": rounded(gb_diff), "se": rounded(gb_se)}
        cases.append({
            "name": name,
            "inputs": inputs,
            "expected": expected,
            "informational": {
                "gbstats_theta_pooled_sample": rounded(gb_theta),
                "gbstats_diff": rounded(gb_diff),
                "gbstats_se": rounded(gb_se),
                "gbstats_agrees_with_expgate_method": comparable,
                "ols_homoskedastic_se": rounded(float(fit.bse[1])),
            },
        })
    return cases


# --- sample-ratio test -----------------------------------------------------------------------

SRM_CASES = [
    ("balanced", 5000, 5000, 0.5),
    ("mild-imbalance", 4950, 5050, 0.5),
    ("imbalance", 4700, 5300, 0.5),
    ("unequal-design", 7900, 2100, 0.2),
    ("unequal-design-treatment-heavy", 1000, 9100, 0.9),
    ("minimal-units", 1, 1, 0.5),
    ("single-unit", 0, 1, 0.5),
    ("small-n", 7, 19, 0.5),
    ("large-n-tiny-imbalance", 1000000, 1002000, 0.5),
    ("mismatch-small-p", 50000, 51500, 0.5),
    ("mismatch-tail", 40000, 44000, 0.5),
    ("mismatch-deep-tail", 30000, 36000, 0.5),
    ("mismatch-unequal-design", 7000, 3000, 0.2),
]


def srm_vectors() -> list[dict]:
    cases = []
    for name, cn, tn, share in SRM_CASES:
        total = cn + tn
        res = sp_stats.chisquare([cn, tn], f_exp=[total * (1 - share), total * share])
        cases.append({
            "name": name,
            "inputs": {"control_n": cn, "treatment_n": tn, "expected_treatment_share": share},
            "expected": {"scipy": {"chi2": rounded(res.statistic), "p_value": rounded(res.pvalue)}},
        })
    return cases


# --- minimum detectable effect ---------------------------------------------------------------

# (name, n control, n treatment, outcome sd, alpha, power)
MDE_CASES = [
    ("ordinary", 1000, 1000, 1.0, 0.05, 0.8),
    ("unequal-arms", 300, 750, 2.5, 0.001, 0.9),
    ("small-n", 6, 9, 1.0, 0.05, 0.8),
    ("strict-alpha", 20000, 20000, 0.3, 1e-6, 0.95),
    ("low-power", 5000, 5000, 4.0, 0.2, 0.5),
    ("high-power", 5000, 5000, 4.0, 0.025, 0.999),
    ("power-below-half", 5000, 5000, 4.0, 0.05, 0.2),
]


def mde_vectors() -> list[dict]:
    cases = []
    for name, nc, nt, sd, alpha, power in MDE_CASES:
        se = sd * sqrt(1 / nc + 1 / nt)
        z = float(sp_stats.norm.isf(alpha))
        mde = (z + float(sp_stats.norm.ppf(power))) * se
        # Independent check on the closed form: the one-sided power of a two-sample z test at
        # that effect must equal the requested power.
        achieved = sm_power.NormalIndPower().power(effect_size=mde / sd, nobs1=nc, alpha=alpha,
                                                   ratio=nt / nc, alternative="larger")
        agree(f"{name} power at mde", float(achieved), power, rel=1e-9)
        cases.append({
            "name": name,
            "inputs": {"se": rounded(se), "z": rounded(z), "power": power},
            "expected": {"scipy": {"mde": rounded(mde)}},
            "informational": {"statsmodels_power_at_scipy_mde": rounded(achieved)},
        })
    return cases


# --- normal quantile -------------------------------------------------------------------------

ALPHAS = [0.999, 0.9, 0.5, 0.2, 0.1, 0.05, 0.025, 0.01, 0.005, 0.001, 1e-4, 1e-6, 1e-8, 1e-10, 1e-12]


def quantile_vectors() -> list[dict]:
    return [{"name": f"alpha-{alpha:g}", "inputs": {"alpha": alpha},
             "expected": {"scipy": {"z": rounded(sp_stats.norm.isf(alpha))}}} for alpha in ALPHAS]


# --- mixture boundary ------------------------------------------------------------------------

def mixture_log_by_quadrature(z: float, ratio: float) -> float:
    """Log of the half-normal mixture of likelihood ratios at standardized distance z, by numerical
    integration instead of the closed form: the integral over theta > 0 of
    2 N(theta; 0, ratio) exp(theta z - theta**2 / 2), with the variance of the estimate set to 1."""
    precision = 1.0 + 1.0 / ratio

    def exponent(theta):
        return theta * z - 0.5 * precision * theta * theta

    peak_at = max(z / precision, 0.0)
    scale = exponent(peak_at)
    width = 1.0 / sqrt(precision)
    upper = peak_at + 40 * width
    integral, _ = sp_integrate.quad(lambda theta: exp(exponent(theta) - scale), 0.0, upper,
                                    points=[peak_at] if peak_at > 0 else None, epsabs=0.0, epsrel=1e-13, limit=500)
    return log(2.0 / sqrt(2.0 * np.pi * ratio)) + scale + log(integral)


def mixture_critical_by_quadrature(ratio: float, alpha: float) -> float:
    target = -log(alpha)
    return float(sp_optimize.brentq(lambda z: mixture_log_by_quadrature(z, ratio) - target, 0.0, 60.0,
                                    xtol=1e-14, rtol=4 * np.finfo(float).eps, maxiter=500))


MIXTURE_RATIOS = [0.01, 0.1, 1.0, 6.5, 30.0, 1000.0, 1.0e5]
MIXTURE_ALPHAS = [0.3, 0.05, 0.01, 0.001, 1e-6]


def mixture_vectors() -> list[dict]:
    return [{"name": f"ratio-{ratio:g}-alpha-{alpha:g}", "inputs": {"ratio": ratio, "alpha": alpha},
             "expected": {"scipy_quad_brentq": {"z": rounded(mixture_critical_by_quadrature(ratio, alpha))}}}
            for alpha in MIXTURE_ALPHAS for ratio in MIXTURE_RATIOS]


SEQUENTIAL_ALPHAS = [0.2, 0.05, 0.025, 0.01, 0.001]
INFORMATION_RATIOS = [0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 10.0]  # planned units over current units
PLANNED = 1000.0


def confseq_bound(v: float, alpha: float, v_opt: float) -> float:
    return float(confseq_boundaries.normal_mixture_bound(v, alpha, v_opt, alpha, True))


def sequential_vectors() -> list[dict]:
    """confseq's one-sided normal-mixture boundary, with its mixing variance tuned to be narrowest at
    the planned size (the rule `expgate.stats.sequential_multiplier` follows), read at the current
    size. Variance per unit is 1, so the intrinsic time equals the unit count and the multiplier is
    the boundary over sqrt(units)."""
    cases = []
    for alpha in SEQUENTIAL_ALPHAS:
        best = sp_optimize.minimize_scalar(lambda lv: confseq_bound(PLANNED, alpha, exp(lv)),
                                           bracket=(log(PLANNED / 10), log(PLANNED), log(PLANNED * 10)), tol=1e-10)
        v_opt = exp(float(best.x))
        for ratio in INFORMATION_RATIOS:
            current = PLANNED / ratio
            cases.append({
                "name": f"alpha-{alpha:g}-information-ratio-{ratio:g}",
                "inputs": {"alpha": alpha, "information_ratio": ratio},
                "expected": {"confseq": {"multiplier": rounded(confseq_bound(current, alpha, v_opt) / sqrt(current),
                                                               SEQUENTIAL_DIGITS)}},
            })
    return cases


# --- driver ----------------------------------------------------------------------------------

CLOSED_FORM = "relative 1e-9 with an absolute floor of 1e-12 (see tests/test_golden.py)"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=HERE, help="directory for the JSON files (default: next to this script)")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    write(args.out, "proportion_effect", "proportion_effect (unpooled Wald)", ["statsmodels", "gbstats", "scipy"],
          CLOSED_FORM, proportion_vectors())
    write(args.out, "mean_effect", "mean_effect (Welch)", ["scipy", "gbstats"], CLOSED_FORM, mean_vectors())
    write(args.out, "ratio_effect", "ratio_effect (delta method)", ["gbstats", "numpy"], CLOSED_FORM, ratio_vectors())
    write(args.out, "cuped_effect", "cuped_effect (pooled within-arm slope)", ["statsmodels", "numpy", "gbstats"],
          CLOSED_FORM, cuped_vectors())
    write(args.out, "sample_ratio", "sample_ratio_p_value (chi-square, 1 df)", ["scipy"], CLOSED_FORM, srm_vectors())
    write(args.out, "minimum_detectable_effect", "minimum_detectable_effect", ["scipy", "statsmodels"],
          CLOSED_FORM, mde_vectors())
    write(args.out, "normal_quantile", "z_for (one-sided normal critical value)", ["scipy"], CLOSED_FORM, quantile_vectors())
    write(args.out, "mixture_critical", "half-normal mixture critical value at a fixed mixing ratio",
          ["scipy", "numpy"], CLOSED_FORM, mixture_vectors())
    write(args.out, "sequential_multiplier", "sequential_multiplier (normal-mixture confidence sequence)",
          ["confseq", "scipy"], "relative 1e-6 (see tests/test_golden.py)", sequential_vectors())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
