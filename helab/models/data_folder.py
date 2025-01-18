from typing import Dict, Optional

import numpy as np
import numpy.typing as npt

class DataFolder:
    def __init__(self,
                 path: str,
                 dict: Optional[Dict[int, npt.NDArray[np.float64]]] = None
                 ) -> None:
        self.path = path
        self.dict = dict