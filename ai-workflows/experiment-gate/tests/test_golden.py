"""Check `expgate.stats` against vectors computed by reference libraries.

The vectors are committed JSON under `tests/golden/`; `tests/golden/generate.py` produces them
with scipy, statsmodels, gbstats and confseq, and CI regenerates them to detect drift. This
module needs none of those libraries: it reads the JSON and uses the standard library only.
"""
import json
import unittest
from pathlib import Path

from expgate import stats

GOLDEN = Path(__file__).resolve().parent / "golden"

# Closed-form estimators. The references and expgate evaluate the same formulas, so they should
# agree to rounding: 1e-9 relative leaves room for the eleven significant digits the vectors store
# (a relative quantization error of at most 5e-11) and for libm and summation-order differences.
# The comparison is purely relative, so tail probabilities (down to 1e-138 in the vectors) and
# critical values for tiny alpha are held to the same standard as everything else.
REL_TOL = 1e-9

# The one exception: a relative test cannot compare a quantity that is exactly 0 in expgate and
# rounding noise in a reference. With a covariate correlation of 0, expgate's slope is exactly 0
# while the regression on raw data returns 2e-17, and the variance reduction, 0 here, could come out
# as +-1e-16 on another platform. For those two fields values within 1e-12 of each other also
# pass. No other field gets a floor: they are either comfortably non-zero (at least 1e-6, or a tail
# probability compared relatively) or exactly 0 in both implementations (z at alpha = 0.5).
ABS_TOL_FOR_ZERO_NOISE = {"theta": 1e-12, "variance_reduction": 1e-12}

# The sequential boundary is the one quantity the references compute by iteration rather than
# a formula. confseq finds the boundary by numerical root finding and the mixing variance comes
# from scipy's one-dimensional minimizer; the objective is flat at its minimum, so the mixing
# variance is only determined to a few digits. Across the cases here the two implementations
# agreed to 2.6e-7; 1e-6 keeps a safety margin of almost 4 without hiding a wrong boundary, which would
# differ by orders of magnitude more (the plain fixed-horizon value is off by 40%).
SEQUENTIAL_REL_TOL = 1e-6


def load(name):
    with (GOLDEN / f"{name}.json").open(encoding="utf-8") as handle:
        document = json.load(handle)
    assert document["cases"], f"{name}.json has no cases"
    return document["cases"]


class GoldenTestCase(unittest.TestCase):
    def close(self, actual, expected, rel=REL_TOL, floor=0.0, msg=None):
        tolerance = max(rel * max(abs(actual), abs(expected)), floor)
        self.assertLessEqual(abs(actual - expected), tolerance,
                             msg or f"{actual!r} != {expected!r} (tolerance {tolerance:.3g})")

    def compare(self, actual: dict, expected: dict, rel=REL_TOL):
        """Every field a reference supplies must match what expgate computed."""
        for field, value in expected.items():
            with self.subTest(field=field):
                self.close(actual[field], value, rel=rel, floor=ABS_TOL_FOR_ZERO_NOISE.get(field, 0.0))


class ProportionEffectGolden(GoldenTestCase):
    def test_unpooled_wald_against_statsmodels_and_gbstats(self):
        for case in load("proportion_effect"):
            with self.subTest(case=case["name"]):
                effect = stats.proportion_effect(**case["inputs"])
                for library, expected in case["expected"].items():
                    with self.subTest(reference=library):
                        actual = {"diff": effect.diff, "se": effect.se}
                        if "z" in expected:
                            actual["z"] = effect.diff / effect.se
                        self.compare(actual, expected)


class MeanEffectGolden(GoldenTestCase):
    def test_welch_against_scipy_and_gbstats(self):
        for case in load("mean_effect"):
            with self.subTest(case=case["name"]):
                effect = stats.mean_effect(**case["inputs"])
                for library, expected in case["expected"].items():
                    with self.subTest(reference=library):
                        actual = {"diff": effect.diff, "se": effect.se}
                        if "t" in expected:
                            actual["t"] = effect.diff / effect.se
                        self.compare(actual, expected)


class RatioEffectGolden(GoldenTestCase):
    def test_delta_method_against_gbstats_and_linearization(self):
        for case in load("ratio_effect"):
            with self.subTest(case=case["name"]):
                inputs = case["inputs"]
                effect = stats.ratio_effect(stats.RatioArm(**inputs["control"]), stats.RatioArm(**inputs["treatment"]))
                actual = {"control": effect.control, "treatment": effect.treatment, "diff": effect.diff, "se": effect.se}
                for library, expected in case["expected"].items():
                    with self.subTest(reference=library):
                        self.compare(actual, expected)


class CupedEffectGolden(GoldenTestCase):
    def test_pooled_within_arm_slope_against_regression_on_raw_data(self):
        for case in load("cuped_effect"):
            with self.subTest(case=case["name"]):
                arms = {}
                for label, arm in case["inputs"].items():
                    if "successes" in arm:
                        self.close(stats.proportion_variance(arm["successes"], arm["n"]), arm["var"])
                    arms[label] = (arm["mean"], arm["var"], arm["n"],
                                   stats.Covariate(arm["cov_mean"], arm["cov_sd"], arm["cov_corr"]))
                effect, info = stats.cuped_effect(*arms["control"], *arms["treatment"])
                actual = {"theta": info["theta"], "diff": effect.diff, "se": effect.se,
                          "raw_diff": info["raw_diff"], "raw_se": info["raw_se"],
                          "variance_reduction": info["variance_reduction"]}
                for library, expected in case["expected"].items():
                    with self.subTest(reference=library):
                        self.compare(actual, expected)


class SampleRatioGolden(GoldenTestCase):
    def test_chi_square_p_value_against_scipy(self):
        for case in load("sample_ratio"):
            with self.subTest(case=case["name"]):
                inputs = case["inputs"]
                p = stats.sample_ratio_p_value(inputs["control_n"], inputs["treatment_n"],
                                               inputs["expected_treatment_share"])
                self.close(p, case["expected"]["scipy"]["p_value"])


class MinimumDetectableEffectGolden(GoldenTestCase):
    def test_closed_form_against_scipy(self):
        for case in load("minimum_detectable_effect"):
            with self.subTest(case=case["name"]):
                inputs = case["inputs"]
                mde = stats.minimum_detectable_effect(inputs["se"], inputs["z"], inputs["power"])
                self.close(mde, case["expected"]["scipy"]["mde"])


class NormalQuantileGolden(GoldenTestCase):
    def test_critical_value_against_scipy(self):
        for case in load("normal_quantile"):
            with self.subTest(case=case["name"]):
                self.close(stats.z_for(case["inputs"]["alpha"]), case["expected"]["scipy"]["z"])


class MixtureGolden(GoldenTestCase):
    def test_critical_value_at_fixed_mixing_ratio_against_numerical_integration(self):
        for case in load("mixture_critical"):
            with self.subTest(case=case["name"]):
                inputs = case["inputs"]
                z = stats._mixture_critical(inputs["ratio"], inputs["alpha"])
                self.close(z, case["expected"]["scipy_quad_brentq"]["z"])

    def test_sequential_multiplier_against_confseq(self):
        for case in load("sequential_multiplier"):
            with self.subTest(case=case["name"]):
                inputs = case["inputs"]
                z = stats.sequential_multiplier(inputs["alpha"], inputs["information_ratio"])
                self.close(z, case["expected"]["confseq"]["multiplier"], rel=SEQUENTIAL_REL_TOL)


if __name__ == "__main__":
    unittest.main()
