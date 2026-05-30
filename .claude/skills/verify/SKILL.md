---
name: verify
description: Launch the Streamlit app and verify that recent changes work correctly in the UI. Use after any edit to app.py, matrix_builder.py, or other UI-affecting files.
---

You are verifying that this project's Streamlit UI works correctly after recent changes.

## Steps

1. Check for obvious Python syntax errors in recently edited files by reading them quickly.
2. Launch the app with `streamlit run app.py` in the background.
3. Wait a few seconds for the server to start (it listens on http://localhost:8501 by default).
4. Confirm the server started without import errors or tracebacks in the output.
5. Report what was verified:
   - Which files were changed
   - Whether the app started cleanly
   - Any errors or warnings seen in the startup output
   - What the user should manually test in the browser (golden path: upload GeoJSON + Excel → run partisi → check Hasil tab + Peta tab)

## What to flag

- Import errors (missing modules)
- Streamlit deprecation warnings that could break the UI
- Any error in `@st.cache_resource` at startup (the `import_modules()` call)
- CSS / styling regressions (WCAG AA: all text-on-background contrast must be ≥ 4.5:1)

## Notes

- The bundled `/verify` skill also exists — this skill adds project-specific checks on top.
- If the app fails to start, check `requirements.txt` and whether `.venv` is active.
- The app runs in Indonesian — UI labels, alerts, and error messages are in Indonesian.
