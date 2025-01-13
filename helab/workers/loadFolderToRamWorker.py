import pickle
import time
from datetime import datetime, timedelta
from concurrent.futures import thread
import gc
import glob
import io
import logging
import os
from sys import getsizeof
from turtle import update
from typing import List, Any, cast, Dict

import numpy as np
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
from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, QDir
from pandas.core.interchange.dataframe_protocol import DataFrame
from pandas.errors import ParserError

from helab.resources.icons import PercentageIcon
from helab.utils.cachingSetup import data_ram_cache, fnum, status_cache


class LoadFolderToRamWorkerSignals(QObject):
    finished = pyqtSignal(str, list, pd.DataFrame)
    # finished = pyqtSignal(str, list, dict)
    # finished = pyqtSignal(str, list, np.ndarray)  # (folder_path: str, problematic_datasets: List[str], data: DataFrame)
    error = pyqtSignal(str, str) # (folder_path: str, error: str)
    loading = pyqtSignal(str, float)  # (folder_path: str, progress: float)
    # cancelled = pyqtSignal(str, str) # (folder_path: str, message: str)

class LoadFolderToRamWorker(QRunnable):

    _TIMEDELTA_SEC_UPDATE_PROGRESS_MIN = timedelta(seconds=0.5)
    _TIMEDELTA_SEC_UPDATE_PROGRESS_STREAM = timedelta(seconds=0.5)

    CANCEL_MSG_ALREADY_CACHED_AND_NO_LONGER_SELECTED = "cancelled - already cached and no longer selected (user changed selection, cancelled decompress request)"
    CANCEL_MSG_SHUTDOWN_REQUESTED = "cancelled - shutdown requested"
    CANCEL_MSG_NOTHING_HERE = "cancelled - nothing here"

    def __init__(self, folder_path: str):
        super().__init__()
        self.folder_path = folder_path
        self.signals = LoadFolderToRamWorkerSignals()
        self._cancel_requested = False
        self._cancel_message = ""

    
    def run(self) -> None:
        logging.debug(f"LoadFolderToRamWorker: {self.folder_path = }")

        
        def _check_cancel_status() -> bool:
            if self._cancel_requested:
                logging.warning(f"LoadFolderToRamWorker: {self.folder_path = } was canceled.")
                self.signals.error.emit(self.folder_path, self._cancel_message)
                return True
            else: return False
        if _check_cancel_status(): return
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

        if _check_cancel_status(): return
        try:
            # file_pattern = os.path.join(self.folder_path, 'd_txy_forc*.txt')
            file_pattern: str = QDir(self.folder_path).filePath('d_txy_forc*.txt')
            files = glob.glob(file_pattern)
            # logging.critical(f"{len(files) = }")

            if not files:
                logging.error(f"LoadFolderToRamWorker: no files found inside {self.folder_path = }")
                # self.signals.cancelled.emit(self.folder_path, "No files inside")
                self.signals.error.emit(self.folder_path, LoadFolderToRamWorker.CANCEL_MSG_NOTHING_HERE)
                return



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
            update_progress = False
            percentages = PercentageIcon.KEYS_PERCENTAGE

            data_dict = {}
            # data_array = []
            problematic_txy_ns = []
            # for file in files:
            for i, file in enumerate(files):
                if _check_cancel_status(): return
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
                    time.sleep(0.001)  # slight delay to void GIL
                    self.signals.loading.emit(self.folder_path, percentages[-5]*(i+1)/no_total_files)
                    time.sleep(0.001)  # slight delay to void GIL
                    update_progress = True
                if datetime.now() - time_last_debug_print > LoadFolderToRamWorker._TIMEDELTA_SEC_UPDATE_PROGRESS_STREAM:
                    no_loaded_files_since_last_debug_print = 0
                    no_error_files_since_last_debug_print = 0
                    time_last_debug_print = datetime.now()
                    


                # Extract the number using string manipulation or regex

                number_str = basename.split('forc')[1].split('.txt')[0]
                number = int(number_str)
                try:
                    # Load the data into a DataFrame
                    # Adjust the separator if your data uses a different delimiter (e.g., comma, space)
                    df = pd.read_csv(file, sep=',', names=['t', 'x', 'y'], dtype={'t': float, 'x': float, 'y': float})

                    if df.isna().any().any():   # Check for NaN values          # type: ignore[reportAttributeAccessIssue]  #pyright bug?
                        problematic_txy_ns.append(number)
                        logging.error(f"LoadFolderToRamWorker: DataFrame contains NaN or empty values in {file}")
                        logging.critical(f"LoadFolderToRamWorker: {df.isna().sum() = } entries are dropped.")
                        data_dict[number] = df.dropna()
                        # data_dict[number] = df.dropna().values
                        # data_array.append((number, df.dropna().values))

                        no_error_files_since_last_debug_print += 1
                    else:

                        data_dict[number] = df
                        # data_dict[number] = df.values
                        # data_array.append((number, df.values))
                        no_loaded_files_since_last_debug_print += 1
                        pass

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

            if _check_cancel_status(): return
            # update_progress = datetime.now() - time_start_loading > LoadFolderToRamWorker._TIMEDELTA_SEC_UPDATE_PROGRESS_MIN
            if update_progress: self.signals.loading.emit(self.folder_path, percentages[-4])
                # logging.debug(f"LoadFolderToRamWorker: formatting data {self.folder_path}. ")

            logging.debug(f"LoadFolderToRamWorker: loop finished {self.folder_path = }")

            # data_array.sort(key=lambda x: x[0])  # Sort by file number
            # file_numbers, data_values = zip(*data_array)
            # tensor = np.stack(data_values)  # Create a 3D numpy array

            # Add a 'file_number' column to each DataFrame
            for number, df in data_dict.items():
                df['file_number'] = number

            # data_dict = dict(sorted(data_dict.items()))

            if update_progress: self.signals.loading.emit(self.folder_path, percentages[-3])

            # Concatenate all DataFrames
            combined_df = pd.concat(data_dict.values())

            # Set 'file_number' as the index
            combined_df.set_index('file_number', inplace=True)

            # Optional: Sort the index for better organization
            combined_df.sort_index(inplace=True)

            # print(combined_df)


            # compressed_data = self.compress_dict(data_dict)

            logging.debug(f"LoadFolderToRamWorker: compressed {self.folder_path = }")


            # data_ram_cache[self.folder_path] = combined_df
            # saved = data_ram_cache.set(self.folder_path, combined_df, retry=True)


            # buffer = io.BytesIO()
            # with pgzip.open(buffer, 'wb') as f:
            #     combined_df.to_pickle(f)                         # type: ignore[reportArgumentType, unused-ignore]
            #     # buffer_size_bytes = buffer.getbuffer().nbytes
            #     buffer_size_bytes = getsizeof(buffer.getvalue())
            # saved = data_ram_cache.set(self.folder_path, buffer.getvalue(), retry=True)

            if update_progress: self.signals.loading.emit(self.folder_path, percentages[-2])

            compressed_data = self.compress_dataframe(combined_df)
            # compressed_data = self.compress_ndarray(tensor)

            buffer_size_bytes = getsizeof(compressed_data)
            saved = data_ram_cache.set(self.folder_path, compressed_data, retry=True)

            logging.debug(f"LoadFolderToRamWorker: saved to cache {self.folder_path = }")

            if not saved:
                logging.error(f"LoadFolderToRamWorker: failed to cache {self.folder_path = }")

            try:
                # data_files = data_ram_cache.__getitem__(self.file_path)
                data_files = data_ram_cache[self.folder_path]
                if update_progress: self.signals.loading.emit(self.folder_path, percentages[-1])
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

    def cancel(self, message: str = "") -> None:
        self._cancel_requested = True
        self._cancel_message = message


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


class CompressionAlgorithmsDumpsite:


    @staticmethod
    def compress_ndarray(tensor: np.ndarray[Any, Any]) -> bytes:
        buffer = io.BytesIO()
        np.save(buffer, tensor)
        zstd_compressor = zstandard.ZstdCompressor(level=22)
        return zstd_compressor.compress(buffer.getvalue())

    @staticmethod
    def decompress_ndarray(data: bytes) -> np.ndarray[Any, Any]:
        zstd_decompressor = zstandard.ZstdDecompressor()
        decompressed_data = zstd_decompressor.decompress(data)
        buffer = io.BytesIO(decompressed_data)
        # return np.load(buffer, allow_pickle=False)
        return cast(np.ndarray[Any, Any], np.load(buffer, allow_pickle=False))

    @staticmethod
    def compress_dict_ndarray_slow(data: Dict[int, np.ndarray[Any, Any]]) -> bytes:
        buffer = io.BytesIO()
        pickle.dump(data, buffer)
        zstd_compressor = zstandard.ZstdCompressor(level=22)
        return zstd_compressor.compress(buffer.getvalue())

    @staticmethod
    def decompress_dict_ndarray_slow(data: bytes) -> Dict[int, np.ndarray[Any, Any]]:
        zstd_decompressor = zstandard.ZstdDecompressor()
        decompressed_data = zstd_decompressor.decompress(data)
        buffer = io.BytesIO(decompressed_data)
        # return pickle.load(buffer)
        return cast(Dict[int, np.ndarray[Any, Any]], np.load(buffer, allow_pickle=True))

    @staticmethod
    def compress_dict_ndarray_slow2(data: Dict[int, np.ndarray[Any, Any]]) -> bytes:
        """
        Compress a dictionary of numpy arrays efficiently using NumPy serialization and Zstandard.
        """
        buffer = io.BytesIO()
        with zstandard.ZstdCompressor(level=22).stream_writer(buffer) as compressor:
            for key, array in data.items():
                # Serialize each array and its corresponding key
                buffer_key = np.array([key], dtype=np.int32).tobytes()
                buffer_array = array.tobytes()
                compressor.write(buffer_key)
                compressor.write(buffer_array)
        return buffer.getvalue()

    @staticmethod
    def decompress_dict_ndarray_slow2(data: bytes, array_shape: Dict[int, tuple]) -> Dict[int, np.ndarray[Any, Any]]:   # type: ignore
        """
        Decompress a dictionary of numpy arrays serialized by compress_dict_ndarray.
        """
        decompressed_data = {}
        buffer = io.BytesIO(data)
        with zstandard.ZstdDecompressor().stream_reader(buffer) as decompressor:
            stream = io.BytesIO(decompressor.read())
            for key, shape in array_shape.items():
                key_data = int(np.frombuffer(stream.read(4), dtype=np.int32)[0])
                array_data = np.frombuffer(stream.read(np.prod(shape) * np.dtype('float64').itemsize), dtype='float64')
                decompressed_data[key_data] = array_data.reshape(shape)
        return decompressed_data

    @staticmethod
    def compress_dict(data: Dict[int, np.ndarray[Any, Any]]) -> bytes:
        """
        Compress a dictionary of NumPy arrays using Apache Arrow and Zstandard.
        """
        # Prepare metadata and flattened arrays
        keys = []
        arrays = []
        shapes = []
        for key, array in data.items():
            keys.append(key)
            arrays.append(array.flatten())  # Flatten for efficient storage
            shapes.append(array.shape)  # Store the shape for reconstruction

        # Convert keys and shapes to Arrow arrays
        keys_array = pa.array(keys, type=pa.int32())
        shapes_array = pa.array(shapes, type=pa.list_(pa.int32()))
        arrays_array = pa.array(np.concatenate(arrays), type=pa.float64())  # Concatenate all flattened arrays

        # Create an Arrow table
        table = pa.Table.from_arrays([keys_array, shapes_array, arrays_array], names=["key", "shape", "array"])

        # Serialize and compress with Zstandard
        buffer = pa.BufferOutputStream()
        pq.write_table(table, buffer)
        zstd_compressor = zstandard.ZstdCompressor(level=22)
        return zstd_compressor.compress(buffer.getvalue().to_pybytes())

    @staticmethod
    def decompress_dict(data: bytes) -> Dict[int, np.ndarray[Any, Any]]:
        """
        Decompress a dictionary of NumPy arrays serialized by compress_dict.
        """
        # Decompress with Zstandard
        zstd_decompressor = zstandard.ZstdDecompressor()
        decompressed_data = zstd_decompressor.decompress(data)
        buffer = pa.BufferReader(decompressed_data)

        # Read the Arrow table
        table = pq.read_table(buffer)

        # Extract keys, shapes, and arrays
        keys = table["key"].to_numpy()
        shapes = table["shape"].to_pylist()
        arrays = table["array"].to_numpy()

        # Reconstruct the dictionary
        result = {}
        offset = 0
        for key, shape in zip(keys, shapes):
            size = np.prod(shape)
            result[key] = arrays[offset:offset + size].reshape(shape)
            offset += size

        return result
