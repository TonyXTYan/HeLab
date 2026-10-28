"""The I/O helper's operations, one module per family, over shared infrastructure (``infra``).

``helab.io_helper`` is the process entry and dispatcher: it imports these modules statically (the
frozen app lists only it as a hidden import), and nothing here imports it, since it may run as
``__main__``. Like the helper, importing these modules must not start Qt or Dash, nor import
numpy, pandas or Blosc: each operation imports those inside the function that needs them.
"""
