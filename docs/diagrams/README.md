# Diagram sources and regeneration

The seven design images are generated from [diagrams.json](diagrams.json) by
[render_visuals.py](render_visuals.py). It also writes the matching `.mmd` sources;
the current guide embeds both each real PNG and its inline Mermaid source.
Pillow is a documentation-only dependency, not an engine dependency.

```bash
python -m pip install pillow
python docs/diagrams/render_visuals.py
python docs/diagrams/check_links.py
```

The workflow GIF and decision still use only values in
[the saved current run](../images/workflow-run.json). To capture new values, run
`kestrel run-all` into a fresh temporary directory as shown in
[testing](../06-testing-and-validation.md), then use `capture_run.py --run-dir DIR`.
It reads that persisted run, checks 420 replays/eight chains, and never signs or sends.
The renderer does not call a model or invent output. Long frame records are
explicitly truncated; the complete observed JSON is retained beside the GIF.

If lifecycle.ALLOWED changes in a future code task, update the case graph's edges
in diagrams.json from that allowlist, then regenerate PNG/Mermaid/inline docs.
Layout is illustrative; it is not a production deployment or capacity diagram.
Graphviz installation was unavailable in this box, so these images use Pillow;
no headless browser or Chrome/dbus workaround is required.
