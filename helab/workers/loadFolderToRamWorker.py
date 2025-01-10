from datetime import datetime, timedelta
from concurrent.futures import thread
import gc
import glob
import io
import logging
import os
from sys import getsizeof
from typing import List

import pandas as pd
# import dask.dataframe as dd
# logging.getLogger('dask').setLevel(logging.WARNING)
import pandas.errors
import pgzip
import pyarrow
import zstandard
import zstandard as zstd
import pyarrow as pa
import pyarrow.parquet as pq
from PyQt6.QtCore import QObject, pyqtSignal, QRunnable
from pandas.core.interchange.dataframe_protocol import DataFrame
from pandas.errors import ParserError

from helab.utils.cachingSetup import data_ram_cache, fnum, status_cache


class LoadFolderToRamWorkerSignals(QObject):
    finished = pyqtSignal(str, list, pd.DataFrame)  # (folder_path: str, problematic_datasets: List[str], data: DataFrame)
    error = pyqtSignal(str, str) # (folder_path: str, error: str)
    loading = pyqtSignal(str, float)  # (folder_path: str, progress: float)


class LoadFolderToRamWorker(QRunnable):

    _TIMEDELTA_SEC_UPDATE_PROGRESS_MIN = timedelta(seconds=0.5)
    _TIMEDELTA_SEC_UPDATE_PROGRESS_STREAM = timedelta(seconds=0.5)

    def __init__(self, folder_path: str):
        super().__init__()
        self.folder_path = folder_path
        self.signals = LoadFolderToRamWorkerSignals()

    def run(self) -> None:
        logging.debug(f"LoadFolderToRamWorker: {self.folder_path = }")
        try:
            data_files = data_ram_cache[self.folder_path]
            if isinstance(data_files, bytes):
                logging.debug(f"LoadFolderToRamWorker: already in cache (compressed) {fnum(getsizeof(data_files))}B, {self.folder_path = } ")
                self.signals.finished.emit(self.folder_path, [], self.decompress_dataframe(data_files))
                return


                # logging.debug(f"LoadFolderToRamWorker: {self.folder_path = } already in cache")
                # self.signals.finished.emit(self.folder_path, [], data_files)
                # return


                # with io.BytesIO(data_files) as f:                       # type: ignore[reportArgumentType, unused-ignore]
                #     data_files_bytes = getsizeof(data_files)
                #     logging.debug(f"LoadFolderToRamWorker: {fnum(data_files_bytes)}B loaded from cache {self.folder_path = }")
                #     # combined_df = pgzip.open(f, 'rb', thread=10)
                #     with pgzip.open(f, 'rb') as f:
                #         combined_df = pd.read_pickle(f)                 # type: ignore[reportArgumentType, unused-ignore]
                #         logging.debug(f"LoadFolderToRamWorker: {fnum(combined_df.memory_usage(index=True).sum())}B ")    # type: ignore[reportArgumentType, unused-ignore]
                # # logging.debug(f"LoadFolderToRamWorker: {fnum(combined_df.memory_usage(index=True).sum())}B "     # type: ignore[reportArgumentType, unused-ignore]
                # #               f"loaded from {fnum(data_files_bytes)}B cache {self.folder_path = }"
                # self.signals.finished.emit(self.folder_path, [], combined_df)
                # return
        except KeyError:
            pass
        except Exception as e:
            logging.error(f"LoadFolderToRamWorker: error accessing cache for {self.folder_path}: {e}")
            # status_cache.pop(self.folder_path)
            # data_ram_cache.pop(self.folder_path)
            logging.error(f"LoadFolderToRamWorker: flushed cache for {self.folder_path}")
            self.signals.error.emit(self.folder_path, str(e))
            return

        try:
            file_pattern = os.path.join(self.folder_path, 'd_txy_forc*.txt')
            files = glob.glob(file_pattern)
            # logging.debug(f"{files}")

            total_file_size_bytes = sum(os.path.getsize(file) for file in files)
            if total_file_size_bytes > 1<<30:
                logging.error(f"LoadFolderToRamWorker: {self.folder_path = } is too large: {fnum(total_file_size_bytes)}B")
                self.signals.error.emit(self.folder_path, f"Folder too large: {fnum(total_file_size_bytes)}B")
                return

            time_start_loading = datetime.now()
            time_last_debug_print = datetime.now()
            no_loaded_files_since_last_debug_print = 0
            no_error_files_since_last_debug_print = 0
            no_total_files = len(files)

            data_dict = {}
            problematic_txy_ns = []
            # for file in files:
            for i, file in enumerate(files):
                # Extract the base filename
                basename = os.path.basename(file)

                if datetime.now() - time_start_loading > LoadFolderToRamWorker._TIMEDELTA_SEC_UPDATE_PROGRESS_MIN \
                    and datetime.now() - time_last_debug_print > LoadFolderToRamWorker._TIMEDELTA_SEC_UPDATE_PROGRESS_STREAM:
                    # logging.warning(f"LoadFolderToRamWorker: loading {file = } is taking too long")
                    # logging.debug(f"LoadFolderToRamWorker: loading dir {self.folder_path} \t "
                    #              f"tElaps = {round((datetime.now() - time_start_loading).total_seconds())}s, "
                    #              f"tRemng = {round(((datetime.now() - time_start_loading) / (i+1) * (no_total_files-i)).total_seconds())}s, "
                    #              f"nLoadd = {no_loaded_files_since_last_debug_print}/s, "
                    #              f"nError = {no_error_files_since_last_debug_print}/s, "
                    #              f"nTotal = {i+1}/{no_total_files} = {round((i+1)/no_total_files*100,1)}%"
                    #              )
                    self.signals.loading.emit(self.folder_path, (i+1)/no_total_files)
                if datetime.now() - time_last_debug_print > LoadFolderToRamWorker._TIMEDELTA_SEC_UPDATE_PROGRESS_STREAM:
                    no_loaded_files_since_last_debug_print = 0
                    no_error_files_since_last_debug_print = 0
                    time_last_debug_print = datetime.now()


                # Extract the number using string manipulation or regex
                # Here, we'll use string methods
                number_str = basename.split('forc')[1].split('.txt')[0]
                number = int(number_str)
                try:
                    # Load the data into a DataFrame
                    # Adjust the separator if your data uses a different delimiter (e.g., comma, space)
                    df = pd.read_csv(file, sep=',', names=['t', 'x', 'y'])

                    if df.isna().any().any():   # Check for NaN values          # type: ignore[reportAttributeAccessIssue]  #pyright bug?
                        problematic_txy_ns.append(number)
                        logging.error(f"LoadFolderToRamWorker: DataFrame contains NaN or empty values in {file}")
                        logging.critical(f"LoadFolderToRamWorker: {df.isna().sum() = } entries are dropped.")
                        data_dict[number] = df.dropna()
                        no_error_files_since_last_debug_print += 1
                    else:
                        # logging.debug(f"LoadFolderToRamWorker: DataFrame is clean for {file}")
                        data_dict[number] = df
                        no_loaded_files_since_last_debug_print += 1
                        pass

                    # df = dd.read_csv(file, sep=',', names=['t', 'x', 'y'])        # spamming log console
                    # df = df.compute()

                    # Alternatively, if the separator is whitespace:
                    # df = pd.read_csv(file, delim_whitespace=True, names=['t', 'x', 'y'])

                    # Store the DataFrame in the dictionary
                    # data_dict[number] = df
                except pandas.errors.ParserError as e:
                    logging.error(f"LoadFolderToRamWorker: ParseError at {file = }, {e = }")
                    problematic_txy_ns.append(number)
                    no_error_files_since_last_debug_print += 1
                    continue
                except Exception as e:
                    logging.error(f"LoadFolderToRamWorker: failed to load {file = }, {e = }")
                    problematic_txy_ns.append(number)
                    no_error_files_since_last_debug_print += 1
                    continue

            if datetime.now() - time_start_loading > LoadFolderToRamWorker._TIMEDELTA_SEC_UPDATE_PROGRESS_MIN:
                self.signals.loading.emit(self.folder_path, 1.0)
                # logging.debug(f"LoadFolderToRamWorker: formatting data {self.folder_path}. ")

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


            # data_ram_cache[self.folder_path] = combined_df
            # saved = data_ram_cache.set(self.folder_path, combined_df, retry=True)


            # buffer = io.BytesIO()
            # with pgzip.open(buffer, 'wb') as f:
            #     combined_df.to_pickle(f)                         # type: ignore[reportArgumentType, unused-ignore]
            #     # buffer_size_bytes = buffer.getbuffer().nbytes
            #     buffer_size_bytes = getsizeof(buffer.getvalue())
            # saved = data_ram_cache.set(self.folder_path, buffer.getvalue(), retry=True)

            compressed_data = self.compress_dataframe(combined_df)
            buffer_size_bytes = getsizeof(compressed_data)
            saved = data_ram_cache.set(self.folder_path, compressed_data, retry=True)

            if not saved:
                logging.error(f"LoadFolderToRamWorker: failed to cache {self.folder_path = }")

            try:
                # data_files = data_ram_cache.__getitem__(self.file_path)
                data_files = data_ram_cache[self.folder_path]
                if not data_files is None:
                    # logging.debug(f"LoadFolderToRamWorker: everything is fine for {self.folder_path}")
                    pass
                else:
                    logging.fatal(f"LoadFolderToRamWorker: cached None?! {self.folder_path = }")
            except KeyError:
                logging.fatal(f"LoadFolderToRamWorker: KeyError after caching {self.folder_path = }")
                data_files2 = data_ram_cache.get(self.folder_path, retry=True)
                if data_files2 is None:
                    logging.fatal(f"LoadFolderToRamWorker: still bad using .get {self.folder_path = }")
                else:
                    logging.fatal(f"LoadFolderToRamWorker: okay using .get {self.folder_path = }")

            except Exception as e:
                logging.error(f"LoadFolderToRamWorker: error accessing cache for {self.folder_path}: {e}")

            # status_cache.pop(self.folder_path)
            # self.model.fetch_status(self.folder_path)

            logging.debug(f"LoadFolderToRamWorker: successfully loadded {combined_df.shape[0]} rows "
                         f"from {len(files)} files (|problematic| = {len(problematic_txy_ns)}) "
                         f"and size {fnum(combined_df.memory_usage(index=True).sum())}B "
                         f"compressed to {fnum(buffer_size_bytes)}B in path {self.folder_path}")
            gc.collect()
            self.signals.finished.emit(self.folder_path, problematic_txy_ns, combined_df)

        except Exception as e:
            logging.error(f"LoadFolderToRamWorker: {e = }")
            self.signals.error.emit(self.folder_path, str(e))

    @staticmethod
    def compress_dataframe(df: pd.DataFrame) -> bytes:
        """
        Compress a Pandas DataFrame using Arrow and Zstandard.
        """
        # Convert the DataFrame to a PyArrow Table
        table = pa.Table.from_pandas(df)

        # Serialize and compress with Zstandard
        buffer = pa.BufferOutputStream()
        pq.write_table(table, buffer)
        zstd_compressor = zstd.ZstdCompressor(level=22)  # Highest compression level
        return zstd_compressor.compress(buffer.getvalue().to_pybytes())

    @staticmethod
    def decompress_dataframe(data: bytes) -> pd.DataFrame:
        """
        Decompress a Pandas DataFrame stored as bytes.
        """
        zstd_decompressor = zstd.ZstdDecompressor()
        decompressed_data = zstd_decompressor.decompress(data)
        buffer = pa.BufferReader(decompressed_data)
        table = pq.read_table(buffer)
        return table.to_pandas()