import logging
import coloredlogs

def setup_logging() -> None:
    # logging.basicConfig(
    coloredlogs.install(
        level=logging.DEBUG,
        # format='%(asctime)s - %(levelname)s - %(message)s'
        fmt='%(asctime)s - %(levelname)s:\t%(message)s',
    )