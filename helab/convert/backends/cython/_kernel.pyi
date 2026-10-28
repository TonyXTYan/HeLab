"""Types of the compiled kernel (``native/cython/_kernel.pyx``; built by ``native/cython/build.py``)."""
import numpy as np
import numpy.typing as npt

SOURCE_SHA256: str


def prepare(channels: npt.NDArray[np.float64], times: npt.NDArray[np.float64], subtract_time_zero: bool,
            dead_channels: npt.NDArray[np.float64], dead_tolerances: npt.NDArray[np.float64],
            ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]: ...


def match(ch: npt.NDArray[np.float64], t: npt.NDArray[np.float64], lo: int, hi: int, start: int,
          search: npt.NDArray[np.intp], window: float, x_limit: float, y_limit: float, xy_limit: float,
          c_x1: float, c_x2: float, c_y1: float, c_y2: float, time_sum_t_x: float, time_sum_t_y: float,
          centred: bool, out: npt.NDArray[np.float64]) -> tuple[int, bool, float, float]: ...


def assemble(pieces: list[tuple[npt.NDArray[np.float64], int]], phantom: bool, phantom_x1: float,
             phantom_x2: float, bin_time: float, v_x: float, v_y: float) -> npt.NDArray[np.float64]: ...
