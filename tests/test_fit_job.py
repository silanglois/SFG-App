"""The Qt-free fit job behind the Fitting tab's chips bar."""
from dataclasses import dataclass

import pytest

from sfg_app2.app.tabs.fitting import job as jobmod
from sfg_app2.app.tabs.fitting.job import FitJob
from sfg_app2.processing.fitting import FitModelSpec, default_peak


@dataclass(eq=False)
class _Entry:
    label: str
    kind: str = "conventional"
    spectrum: object = None


def _job(n=3, **kw):
    job = FitJob(**kw)
    for i in range(n):
        job.add(_Entry(f"s{i}"))
    return job


def _spec(peaks=2):
    spec = FitModelSpec.empty()
    for c in range(peaks):
        spec.peaks.append(default_peak("lorentzian", 2850.0 + 30 * c, amplitude=1.0, width=10.0))
    return spec


def test_single_spectrum_is_its_own_mode():
    job = _job(1, mode=jobmod.GLOBAL)
    assert job.effective_mode() == jobmod.SINGLE
    assert job.run_label() == "Fit spectrum"
    assert job.strategy_summary(_spec()) == "Single spectrum"


@pytest.mark.parametrize("mode, label", [
    (jobmod.INDEPENDENT, "Fit 3 independently"),
    (jobmod.SEQUENTIAL, "Fit 3 in sequence"),
    (jobmod.GLOBAL, "Fit 3 globally"),
])
def test_fit_button_names_what_will_run(mode, label):
    assert _job(3, mode=mode).run_label() == label


def test_adding_twice_is_ignored_and_reference_follows_its_entry():
    job = _job(3)
    first = job.spectra[0].entry
    assert not job.add(first)
    job.reference = 2
    ref = job.reference_entry()
    job.move(2, 0)
    assert job.reference_entry() is ref and job.reference == 0
    job.remove([1])
    assert job.reference_entry() is ref
    job.remove([0])
    assert job.reference == 0 and len(job.spectra) == 1


def test_problems_and_summaries():
    job = FitJob()
    assert job.problems() == ["Add a spectrum to fit."]
    assert job.spectra_summary() == "Choose spectra"
    job.add(_Entry("a"))
    job.add(_Entry("b", kind="phase_resolved"))
    assert "mixes" in job.problems()[0]
    assert job.spectra_summary() == "2 spectra"
    assert jobmod.model_summary(FitModelSpec.empty()) == "Add peaks"
    assert jobmod.model_summary(_spec(2)) == "2 peaks + NR · Lorentzian"
    assert jobmod.fit_settings_summary((2800.0, 3000.0), "None") == "2800–3000 · None"


def test_pause_flags():
    job = _job(3, mode=jobmod.SEQUENTIAL)
    assert job.pause_flags() == [False, False, False]
    job.pause = jobmod.PAUSE_EACH
    assert job.pause_flags() == [True, True, True]
    job.pause = jobmod.PAUSE_MARKED
    job.spectra[1].pause = True
    assert job.pause_flags() == [False, True, False]


def test_share_groups_and_global_summary():
    spec = _spec(2)
    job = _job(3, mode=jobmod.GLOBAL)
    assert job.strategy_summary(spec) == "Global · nothing shared yet"
    jobmod.set_share(spec, "center", True)
    assert jobmod.share_state(spec, "center") is True
    assert jobmod.share_state(spec, "width") is False
    spec.peaks[0].params["width"].shared = True
    assert jobmod.share_state(spec, "width") is None   # a mix
    assert job.strategy_summary(spec) == "Global · centers, some widths shared"
    assert jobmod.any_shared(spec)
