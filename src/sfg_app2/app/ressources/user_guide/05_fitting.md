# Fitting

The **Fitting** tab fits peaks/lineshapes to one spectrum, or to many
at once. Conventional data is fit as
$\lvert \chi_{\mathrm{NR}}\,e^{i\varphi} + \sum_j \chi_j(\omega)\rvert^2$
against measured intensity; phase-resolved data is fit as simultaneous
real/imaginary fits of the same complex χ⁽²⁾ against measured
Real/Imaginary data. The kind is detected from each spectrum.

!!! warning "Experimental"
    The Fitting tab is still under active development — results,
    especially from multi-spectrum (sequential/global) fits, should be
    independently sanity-checked rather than relied on as-is.

## The fitting equation

Every model — however many peaks it has — is built from two kinds of
term, summed *coherently* (as complex numbers, before anything is
squared):

- **Non-resonant term** — a single complex constant (flat across the
  whole spectrum):

    $$\chi_{\mathrm{NR}} = A_{\mathrm{NR}}\,e^{i\varphi_{\mathrm{NR}}}$$

- **Resonant term, one per peak *j*.** Three lineshapes are available,
  chosen per peak. The **Lorentzian** is the plain homogeneously
  broadened line:

    $$\chi_j(\omega) = \frac{A_j}{\omega - \omega_j + i\Gamma_j}$$

    where $\Gamma_j$ is the *half*-width-at-half-max. The Parameters
    table's **Width** column is the *full* width instead (the more usual
    quantity to eyeball on a plot), so internally $\Gamma_j = \text{Width}/2$.

    The **Voigt** is that same line convolved with a Gaussian spread of
    resonance positions — homogeneous *and* inhomogeneous broadening
    together — so it carries two widths: **Lorentzian width** and
    **Gaussian width**, both full widths. The **Gaussian** is its limit
    when the homogeneous part vanishes, i.e. purely inhomogeneous
    broadening.

    All three are complex, not real-valued bumps. A Gaussian line here
    still has a dispersive real part (its Kramers-Kronig partner), which
    matters because the sum below happens before squaring: drop it and
    interference between overlapping peaks comes out wrong. One
    consequence worth expecting — only a Gaussian's *absorption* dies
    away quickly in the wings; its dispersive part decays slowly, much
    like a Lorentzian's.

These sum to one complex susceptibility:

$$\chi_{\mathrm{eff}}(\omega) = \chi_{\mathrm{NR}} + \sum_j \chi_j(\omega)$$

which is where **conventional** and **phase-resolved** fitting diverge:

- **Conventional SFG** only ever measures intensity, so it fits against
  $I(\omega) = \lvert\chi_{\mathrm{eff}}(\omega)\rvert^2$ — the model
  curve you see is this squared magnitude, and the fit itself works on
  the intensity residual.
- **Phase-resolved** measures Real(ω) and Imaginary(ω) directly, so it
  fits Re(χ_eff(ω)) and Im(χ_eff(ω)) simultaneously against them — one
  joint least-squares problem, both channels sharing the same
  parameters, rather than two separate fits.

Because the sum happens *before* squaring, cross-terms between peaks
(and between peaks and the non-resonant background) matter —
$\lvert\chi_a + \chi_b\rvert^2$ is not
$\lvert\chi_a\rvert^2 + \lvert\chi_b\rvert^2$, which is why peaks can
constructively or destructively interfere in a conventional spectrum. It's
also why the per-peak **Peak N** curves (each
peak's $\lvert\chi_j\rvert^2$ in isolation) are a visual aid for
locating a peak, not a literal
decomposition of the total — the real total includes interference terms
that no single curve captures alone.

| Symbol | Parameters-table name | Meaning |
|---|---|---|
| $A_{\mathrm{NR}},\ \varphi_{\mathrm{NR}}$ | Non-resonant → Amplitude, Phase | Non-resonant background amplitude/phase |
| $A_j$ | Peak *j* → Amplitude | Resonant amplitude (sign gives the peak's phase relative to the background) |
| $\omega_j$ | Peak *j* → Center | Resonance position (cm⁻¹) |
| $\Gamma_j$ | Peak *j* → Width, halved | Half-width-at-half-max (the table shows the full width). On a Voigt this column is labelled **Lorentzian width** |
| $\sigma_j$ | Peak *j* → Gaussian width | Inhomogeneous broadening, shown as a full width. Voigt only — the other two shapes have a single width |

## The fit job: four chips and a Fit button

Everything you set up reads as one row of numbered chips along the top
of the tab, followed by a **Fit** button:

**① Spectra · ② Model · ③ Strategy · ④ Fit settings · ▶ Fit**

Each chip shows a one-line summary of its step (for example
"3 spectra", "2 peaks + NR · Lorentzian", "Global · centers, widths
shared"); click it to open that step's controls. A chip that still
needs something is marked ⚠, and a **Start here →** hint sits in front
of the first one, so a new job is simply worked left to right. Once you
know the tab, you can skip straight to **Fit**. Its label always says
what will run: *Fit spectrum*, *Fit 12 independently*, *Fit 12 in
sequence* or *Fit 3 globally*. The first time you open the tab a short
tour points at each chip; the **?** at the end of the bar replays it.

Below the bar is the **workspace**: the **Plot** (Plot 1, with Plot 2
underneath showing the residual by default), the **Parameters** table
next to it, and the **Results** table below. The panels can be moved,
floated or closed (**View → Fitting panels** brings them back).

### ① Spectra

The spectra in the job. Nothing is added automatically:
**Add from library…** opens a checklist of the Spectra Library (with
every metadata field as a column and a filter box, so e.g. typing
"ssp" narrows it down), and **Add file(s)…** loads exported CSVs
directly. **Remove** (or right-click) takes spectra out again.

One spectrum is marked **★**: the one shown in the workspace, on which
you build the model. Double-click another spectrum (or use
**★ Show in workspace**) to look at it instead; the model is the job's
model and stays as it is. With one spectrum in the job, **Fit** simply
fits it.

### ② Model

- **New peaks** lineshape, then **Add peaks**: while it's on, every
  click on Plot 1 places a peak there (Ctrl+click seeds a negative
  amplitude); right-click, **Esc** or the button again stops. The
  starting amplitude and width are estimated from the data around the
  click, against what the model doesn't explain yet.
- The peak list shows each peak's center; change a peak's lineshape
  in place, or **Remove** it.
- **Non-resonant background** is on by default.
- **Amplitude sign rules** (optional, see *Fitting several
  polarizations* below).
- **Templates**: apply a saved model (with its fit range and
  weighting), **Save as…**, or **Manage…** (rename, delete,
  export/import as `.json`).

### ③ Strategy: fitting several spectra

With two or more spectra in the job, choose how they're fit:

- **Independent** — each spectrum is fit on its own, all from the same
  starting model (replicates, unrelated samples).
- **Sequential** — spectra are fit in the order of the ① list (drag to
  reorder; the list then shows the order numbers), each one starting
  from the previous fit's result: for a temperature, concentration or
  time series where peaks drift. **Pause for review** can stop after
  every spectrum or at the ones you tick in ①. While paused, the bar
  shows **Continue ▸** / **Stop**; the paused spectrum's fit is shown in
  the workspace, where you can adjust it and **Refit this spectrum**.
  Continue then seeds the next spectrum from that (possibly refit) row.
- **Global** — all spectra are fit together: parameters marked
  **Shared** take one common value fitted jointly across every
  spectrum, the rest are fit per spectrum. Choosing Global shares the
  peak centers and widths for you (the usual case); the **Share across
  all spectra** checkboxes and the Parameters table's **Shared ⇄**
  column (shown only in Global mode) fine-tune that. **Seed amplitudes
  per spectrum** is explained below.

All spectra in a job must be the same kind (conventional or
phase-resolved).

### ④ Fit settings

- **Fit range** — what actually gets fit, shaded on Plot 1. It's
  independent of the plot's zoom: zooming never changes what gets fit.
  **Use current plot view** copies the visible x-range; **Full range**
  resets it. The range applies to every spectrum in the job.
- **Weighting** — for conventional: None, Statistical (1/√intensity), or
  Measurement error (SEM). For phase-resolved: None or Measurement error
  (95% CI, per channel) — there's no statistical option there, since
  shot-noise weighting doesn't apply to signed real/imaginary values.
  Despite the similar names, the conventional "SEM" and the
  phase-resolved "95% CI" are computed differently (one's a plain
  standard error, the other's 1.96× that) — see the error/uncertainty
  glossary in **Reference & Tips**.

## Parameters

One row per parameter of the non-resonant term and every peak: value,
**±** (its standard error after a fit), min/max bounds, **Fixed**, and,
in Global mode, **Shared ⇄**. Right-click the header to show the
**Expr** column for lmfit expression constraints between parameters.
Edits update the plot live and can be undone (**Edit → Undo**). A value
that ends a fit at one of its bounds is highlighted. An amplitude with
sign rules shows them next to its name, e.g. "Amplitude (ppp −, ssp +)".

Above the table, a line says what you're editing: normally **the
starting model**. Below it are the fit's χ²ᵣ/R²/AIC/BIC,
**Export fit…** (a CSV with full provenance) and **Send to Spectra
Library**, which adds the spectrum with its fit straight to the
library, where the fit curves can be plotted.

Rows can optionally be tinted by peak — **Preferences → Fitting →
Color parameter table by peak**.

## Plot

Plot 1 shows the data, the fit and the shaded fit range; Plot 2 (toggle
**Show Plot 2**) the residual. **Curves…** chooses which curves appear
on which plot — data, fit total/real/imaginary, residual(s), and each
peak — with their color and line style.

## Results

A multi-spectrum fit fills the **Results** table: one row per spectrum
with a status mark (✓ converged, ⚠ did not converge, ✗ failed), χ²ᵣ,
R², and one column per fitted parameter as value ± error (shared ones
marked ⇄). A global fit adds the combined χ²ᵣ and what was shared to
the line above the table; each row's χ²ᵣ is that spectrum's own
diagnostic.

- **Click a row** (or move with ↑/↓) to view that fit in the workspace.
  The line above the Parameters table then reads *Viewing: …*, and the
  starting model is untouched — you can explore and edit the viewed
  values freely. From there: **Refit this spectrum** (fits it again from
  the values shown, with the current fit range and weighting, and
  updates its row), **Use as starting model**, or **Back to starting
  model**.
- **Sort** by any column (e.g. worst χ²ᵣ first) by clicking its header.
- **Right-click a column header** to **Plot trend**: the **Trend** tab
  plots that parameter across the spectra, against their order or any
  numeric metadata field (temperature, concentration, …). **Overlay**
  shows every spectrum with its fit.
- **Refit selected** fits the selected rows again from the starting
  model — e.g. after improving it for a spectrum that failed. Rows of a
  global fit can only be refit together (run the global fit again).
- **Send to Spectra Library** adds the selected fits (all, if none is
  selected); **Export summary…** writes one summary CSV (every row's
  status, statistics and parameter values/errors) plus one fit CSV with
  full provenance per spectrum.

Every run and refit is one undo step.

## Fitting several polarizations of one sample

The same sample measured as ssp, ppp, sps, ... has the same resonances
— so the same peak centers and widths — but amplitudes that can differ
by orders of magnitude or in sign, or nearly vanish in one combination.
That makes a single good starting point hard to find. The workflow:

1. **①** Add every polarization, and build the model on the clearest
   one (★, often ssp).
2. **③** Choose **Global** — peak centers and widths become shared.
3. **Fit**.

With **Seed amplitudes per spectrum** checked (the default), the joint
fit doesn't start every spectrum from the reference's amplitudes.
First, with the shared shapes held fixed, each spectrum's own
amplitudes and non-resonant background are solved on their own. For
phase-resolved data that is an exact linear solve that needs no starting
guess. For conventional data the app tries every combination of
amplitude signs, which is where |χ|² fits usually go wrong. The joint
fit then starts from those values. It also runs once from the plain
starting model, and the better of the two (lower combined χ²ᵣ) is kept,
so seeding never does worse than an unseeded joint fit. The results
line says "amplitudes seeded per spectrum" when the seeded start won.

A peak that is absent in one polarization is fine: its amplitude goes
to about zero there and doesn't disturb the shared shape.

**Sign rules.** If you know a peak's sign in a polarization (for
instance + in ssp and − in ppp), open **②** and pick the metadata field
that holds the polarization under **Polarization field** (from your
filename patterns or metadata edits; a field whose name starts with
"pol" is picked automatically). Then **Sign rules…** shows a grid of
peaks × polarizations where each cell is +, − or free. A rule keeps that
amplitude ≥ 0 or ≤ 0 whenever a spectrum with that polarization is fit,
in every kind of fit. The rules are part of the model, saved in
templates and exported fits. For conventional data, where only |χ|² is
measured and the whole model with every sign flipped fits equally well,
a rule chooses which of those two mirror solutions you get. If a rule
disagrees with the data, the amplitude ends up pinned at 0 and its
value is highlighted as being at a bound — the signal to recheck the
rule.
