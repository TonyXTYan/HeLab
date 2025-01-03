import glob
import logging
import os

import pandas as pd
from PyQt6.QtCore import QObject, pyqtSignal, QRunnable

from helab.utils.cachingSetup import data_ram_cache


class LoadFolderToRamWorkerSignals(QObject):
    finished = pyqtSignal(str)  # (folder_path: str)
    error = pyqtSignal(str, str) # (folder_path: str, error: str)

class LoadFolderToRamWorker(QRunnable):
    def __init__(self, folder_path: str):
        super().__init__()
        self.folder_path = folder_path
        self.signals = LoadFolderToRamWorkerSignals()

    def run(self) -> None:
        logging.debug(f"LoadFolderToRAM: {self.folder_path = }")
        try:
            data_files = data_ram_cache[self.folder_path]
            if not data_files is None:
                logging.debug(f"LoadFolderToRAM: {self.folder_path = } already in cache")
                self.signals.finished.emit(self.folder_path)
                return
        except KeyError:
            pass
        except Exception as e:
            logging.error(f"LoadFolderToRAM: error accessing cache for {self.folder_path}: {e}")
            self.signals.error.emit(self.folder_path, str(e))
            return

        try:
            file_pattern = os.path.join(self.folder_path, 'd_txy_forc*.txt')
            files = glob.glob(file_pattern)
            # logging.debug(f"{files}")
            data_dict = {}
            for file in files:
                # Extract the base filename
                basename = os.path.basename(file)

                # Extract the number using string manipulation or regex
                # Here, we'll use string methods
                number_str = basename.split('forc')[1].split('.txt')[0]
                number = int(number_str)

                # Load the data into a DataFrame
                # Adjust the separator if your data uses a different delimiter (e.g., comma, space)
                df = pd.read_csv(file, sep=',', names=['t', 'x', 'y'])

                # Alternatively, if the separator is whitespace:
                # df = pd.read_csv(file, delim_whitespace=True, names=['t', 'x', 'y'])

                # Store the DataFrame in the dictionary
                data_dict[number] = df

            # Add a 'file_number' column to each DataFrame
            for number, df in data_dict.items():
                df['file_number'] = number

            # Concatenate all DataFrames
            combined_df = pd.concat(data_dict.values())

            # Set 'file_number' as the index
            combined_df.set_index('file_number', inplace=True)

            # Optional: Sort the index for better organization
            combined_df.sort_index(inplace=True)

            # print(combined_df)

            data_ram_cache[self.folder_path] = combined_df

            # status_cache.pop(self.folder_path)
            # self.model.fetch_status(self.folder_path)

            self.signals.finished.emit(self.folder_path)

        except Exception as e:
            logging.error(f"LoadFolderToRAM: {e = }")
            self.signals.error.emit(self.folder_path, str(e))
