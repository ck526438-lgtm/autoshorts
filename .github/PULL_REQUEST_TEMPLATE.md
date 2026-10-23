## What changed

One paragraph. Link the issue if there is one.

## How you verified it

```
the exact command you ran
```

Paste the stage log. For rendering changes, attach or link the `final.mp4` —
"it should work" is not a reviewable claim here.

## Checklist

- [ ] `pytest -q` passes
- [ ] `ruff check .` is clean
- [ ] No new required dependency (optional extras go in `pyproject` extras and are imported lazily)
- [ ] README/`docs/TROUBLESHOOTING.md` updated if behaviour or flags changed
