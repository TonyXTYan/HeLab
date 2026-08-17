import logging
import re

import coloredlogs


# class DaskOpenFileFilter(logging.Filter):
#     """
#     Filter out Dask DEBUG log messages containing 'open file'.
#     """
#     def __init__(self, pattern: str = r"open file", level: int = logging.DEBUG):
#         super().__init__()
#         self.pattern = re.compile(pattern, re.IGNORECASE)
#         self.level = level
#
#     def filter(self, record: logging.LogRecord) -> bool:
#         """
#         Return False to suppress the log record, True otherwise.
#         """
#         if record.levelno == self.level and self.pattern.search(record.getMessage()):
#             # Optionally, print to stderr for debugging the filter
#             # print(f"Suppressed log message: {record.getMessage()}")
#             return False  # Suppress this log message
#         return True  # Allow all other messages
# #
# # # If needed, also attach to distributed logger
# # distributed_logger = logging.getLogger("distributed")
# # distributed_logger.addFilter(DaskOpenFileFilter())

def setup_logging() -> None:
    # logging.basicConfig(
    # logging.getLogger('dask').setLevel(logging.WARNING)
    # logging.getLogger('distributed').setLevel(logging.WARNING)
    coloredlogs.install(
        # level=logging.DEBUG,
        level=logging.INFO,
        # format='%(asctime)s - %(levelname)s - %(message)s'
        fmt='%(asctime)s - %(levelname)s:\t%(message)s',
    )

    # # Instantiate the custom filter
    # dask_filter = DaskOpenFileFilter(pattern=r"open file", level=logging.DEBUG)
    #
    # # Get the Dask and Distributed loggers
    # dask_logger = logging.getLogger("dask")
    # distributed_logger = logging.getLogger("distributed")
    #
    # # Attach the filter to these loggers
    # dask_logger.addFilter(dask_filter)
    # distributed_logger.addFilter(dask_filter)
    #
    # # Optionally, if there are sub-loggers emitting the messages, attach the filter to them as well
    # # For example:
    # # dask_sub_logger = logging.getLogger("dask.submodule")
    # # dask_sub_logger.addFilter(dask_filter)