# Contributing

## Working on the user guide

The in-app **Help → User Guide** is a [MkDocs Material](https://squidfunk.github.io/mkdocs-material/)
site built from Markdown in `src/sfg_app2/app/ressources/user_guide/`.
That folder is the single source of truth: the app opens the built
`site/` in the browser, and falls back to rendering the same `.md`
files in a plain `QTextBrowser` when `site/` isn't present.

### Editing

```bash
uv sync --group dev
uv run mkdocs serve          # live preview at http://127.0.0.1:8000
uv run mkdocs build          # regenerate site/ so the app's menu uses it
```

The app menu always points at `site/index.html`, never the dev server —
run `uv run mkdocs build` when you want your changes wired into the app.

CI runs `uv run mkdocs build --strict` on every change to the guide
(`.github/workflows/docs.yml`), which **fails on broken links or a page
missing from `nav`**. Every new `.md` page must be added to `nav:` in
`mkdocs.yml`.

### Math

Write LaTeX with `pymdownx.arithmatex`: `$...$` inline, `$$...$$` for a
display block. It's typeset offline by a vendored copy of
[KaTeX](https://katex.org/) (MIT) in `user_guide/javascripts/` and
`user_guide/stylesheets/`. Don't reference a CDN — the guide has to
work with no network. Keep `$...$` out of `##` headings (it breaks the
table-of-contents anchors).

### Callouts

Use Material admonitions, not blockquotes:

```markdown
!!! warning "Experimental"
    Body text, indented four spaces.

!!! note
    ...
```

### Screencasts

No `<video>` tags — they don't play from `file://` and aren't in the
offline bundle. Record a short clip and export it as an optimized
**animated GIF or WebP**: aim for under 3 MB, ≤ 720 px wide, under
15 s. Put it in `src/sfg_app2/app/ressources/user_guide/assets/` and
embed it with an explicit width:

```markdown
![What the clip shows](assets/load-match-drag.webp){ width="720" }
```

Then `uv run mkdocs build` and check it renders from `site/index.html`.

### Vendored assets

`user_guide/javascripts/` and `user_guide/stylesheets/` hold vendored
KaTeX and the [iframe-worker](https://github.com/squidfunk/iframe-worker)
search shim (both MIT; license texts sit alongside them). To update
them, replace the files from the upstream `dist/` of a pinned release
and rebuild — don't hand-edit. `katex.min.css` must stay byte-for-byte
so its relative `fonts/` URLs keep resolving.
