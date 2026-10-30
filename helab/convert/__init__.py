"""HeLab's raw DLD → TXY converter (``roadmaps/txy-converter.md``).

Stage 1 is the reference: a plain-Python port of the running path of MATLAB's converter
(``dld_raw_to_txy_counts`` → ``dld_read_5channels_reconst_multi_imp(file, 1, 0, 1, 0)`` →
``dlmwrite(…, 'precision', 8)``), byte for byte, and the harness later backends are measured with.

- ``raw``: a raw ``d<N>.txt`` to channel and time arrays, as MATLAB's ``textscan`` reads it;
- ``profile``: ``DetectorProfile``, every constant MATLAB hard-codes, and the built-in profiles;
- ``reconstruct``: ``reconstruct(pulses, profile, backend=…)`` and the backend registry;
  ``backends/reference.py`` holds the port;
- ``txy``: TXY text exactly as ``dlmwrite`` precision 8 writes it, written atomically;
- ``samples``, ``check``, ``timing``: the sample manifest, the byte checker, the timing harness.

Qt-free: standard library and NumPy only (``PURE`` in ``tests/test_headless_imports.py``).
"""
