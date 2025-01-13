from __future__ import annotations

import lzma
import pickle
import re
import time
import warnings
from datetime import datetime, timedelta
import gc
import glob
import io
import logging
import os
from sys import getsizeof

from typing import List, Any, cast, Dict, Callable

import blosc
import numpy as np
import numpy.typing as npt
import pandas as pd

import pandas.errors
import pgzip
import pyarrow
import zstandard
import zstandard as zstd
import pyarrow as pa
import pyarrow.parquet as pq
from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, QDir

from helab.resources.icons import PercentageIcon
from helab.utils.cachingSetup import data_ram_cache, fnum, status_cache


class LoadFolderToRamWorkerSignals(QObject):
    finished = pyqtSignal(str, list, dict)  # (folder_path: str, problematic_datasets: List[str], data: DataFrame)
    error = pyqtSignal(str, str) # (folder_path: str, error: str)
    loading = pyqtSignal(str, float)  # (folder_path: str, progress: float)

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
                self.signals.finished.emit(self.folder_path, [], self.default_algorithm_decompress(data_files))
                return

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

            problematic_txy_ns = []
            total_rows = 0
            total_bytes = 0

            for i, file in enumerate(files):
                if _check_cancel_status(): return
                # Extract the base filename
                basename = os.path.basename(file)

                if datetime.now() - time_start_loading > LoadFolderToRamWorker._TIMEDELTA_SEC_UPDATE_PROGRESS_MIN \
                    and datetime.now() - time_last_debug_print > LoadFolderToRamWorker._TIMEDELTA_SEC_UPDATE_PROGRESS_STREAM:
                    time.sleep(0.001)  # slight delay to void GIL
                    self.signals.loading.emit(self.folder_path, percentages[-3]*(i+1)/no_total_files)
                    time.sleep(0.001)  # slight delay to void GIL
                    update_progress = True
                if datetime.now() - time_last_debug_print > LoadFolderToRamWorker._TIMEDELTA_SEC_UPDATE_PROGRESS_STREAM:
                    no_loaded_files_since_last_debug_print = 0
                    no_error_files_since_last_debug_print = 0
                    time_last_debug_print = datetime.now()


                # Extract the number using string manipulation or regex

                # number_str = basename.split('forc')[1].split('.txt')[0]
                # match = re.search(r'forc(\d+).txt', basename).group(1)
                match = re.search(r'forc(\d+).txt', basename)
                if match:
                    number_str = match.group(1)
                else:
                    logging.error(f"LoadFolderToRamWorker: failed to extract number from {basename}")
                    continue
                number = int(number_str)
                try:
                    # Load the data into a DataFrame
                    # Adjust the separator if your data uses a different delimiter (e.g., comma, space)
                    df = pd.read_csv(file, sep=',', names=['t', 'x', 'y'], dtype={'t': np.double, 'x': np.double, 'y': np.double})

                    if df.isna().any().any():   # Check for NaN values          # type: ignore[reportAttributeAccessIssue]  #pyright bug?
                        problematic_txy_ns.append(number)
                        # logging.warning(f"LoadFolderToRamWorker: DataFrame contains NaN or empty values in {file}")
                        logging.warning(f"LoadFolderToRamWorker: {df.isna().sum().to_dict() = } entries are dropped.")
                        # data_dict[number] = df.dropna()
                        no_error_files_since_last_debug_print += 1
                    else:

                        # data_dict[number] = df
                        no_loaded_files_since_last_debug_print += 1
                    np_array = np.array(df.dropna())
                    data_dict[number] = np_array
                    total_rows += np_array.shape[0]
                    total_bytes += np_array.nbytes

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
            # if update_progress: self.signals.loading.emit(self.folder_path, percentages[-4])
                # logging.debug(f"LoadFolderToRamWorker: formatting data {self.folder_path}. ")
            logging.debug(f"LoadFolderToRamWorker: loop finished {self.folder_path = }")

            # for number, df in data_dict.items():
            #     df['file_number'] = number
            # if update_progress: self.signals.loading.emit(self.folder_path, percentages[-3])

            # combined_df = pd.concat(data_dict.values())
            # combined_df.set_index('file_number', inplace=True)
            # combined_df.sort_index(inplace=True)
            # logging.debug(f"LoadFolderToRamWorker: compressed {self.folder_path = }")

            if update_progress: self.signals.loading.emit(self.folder_path, percentages[-2])

            # compressed_data = self.compress_dataframe(combined_df)
            compressed_data = self.default_algorithm_compress(data_dict)

            buffer_size_bytes = getsizeof(compressed_data)
            saved = data_ram_cache.set(self.folder_path, compressed_data, retry=True)

            logging.debug(f"LoadFolderToRamWorker: saved to cache {self.folder_path = }")

            if not saved:
                logging.error(f"LoadFolderToRamWorker: failed to cache {self.folder_path = }")

            try:
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

            logging.debug(f"LoadFolderToRamWorker: successfully loadded {total_rows} rows "
                         f"from {len(files)} files (|problematic| = {len(problematic_txy_ns)}) "
                         f"and size ~{fnum(self.get_approx_size_of_dict_of_numpy(data_dict))}B "
                         f"compressed to {fnum(buffer_size_bytes)}B in path {self.folder_path}")
            gc.collect()
            self.signals.finished.emit(self.folder_path, problematic_txy_ns, data_dict)

        except Exception as e:
            logging.error(f"LoadFolderToRamWorker: {e = }")
            self.signals.error.emit(self.folder_path, str(e))

    def cancel(self, message: str = "") -> None:
        self._cancel_requested = True
        self._cancel_message = message


    @staticmethod
    def default_algorithm_compress(data: Dict[int, npt.NDArray[np.float64]]) -> bytes:
        compressed = CompressionAlgorithmsDumpsite.compress_blosc(data)
        if not isinstance(compressed, bytes):
            raise TypeError("compress_blosc must return bytes")
        return compressed

    @staticmethod
    def default_algorithm_decompress(compressed_data: bytes) -> Dict[int, npt.NDArray[np.float64]]:
        data = CompressionAlgorithmsDumpsite.decompress_blosc(compressed_data)
        if not isinstance(data, dict):
            raise TypeError("decompress_blosc must return dict")
        return data
    #TODO convert blosc to lzma to save space

    @staticmethod
    def get_approx_size_of_dict_of_numpy(data: Dict[int, npt.NDArray[np.float64]]) -> int:
        return sum(getsizeof(key) + value.nbytes for key, value in data.items()) + getsizeof(data)

    @staticmethod
    def get_total_rows_in_dict_of_numpy(data: Dict[int, npt.NDArray[np.float64]]) -> int:
        return sum(value.shape[0] for value in data.values())

    @staticmethod
    def valide_cached_health() -> None:
        warnings.warn("valide_cached_health is not implemented yet", RuntimeWarning)
        warnings.warn("should move this to a separate class", RuntimeWarning)
        logging.warn("valide_cached_health is not implemented yet")

class CompressionAlgorithmsDumpsite:
    @staticmethod
    def compress_blosc(data: Any,
                       typesize: int = 8, cname: str = 'zstd', clevel: int = 9, shuffle: int = blosc.NOSHUFFLE) -> Any:
        serialized = pickle.dumps(data)
        compressed = blosc.compress(serialized, typesize=typesize, cname=cname, clevel=clevel, shuffle=shuffle)
        return compressed

    @staticmethod
    def decompress_blosc(compressed_data: bytes) -> Any:
        decompressed = blosc.decompress(compressed_data)
        data = pickle.loads(decompressed)
        return data

    @staticmethod
    def compress_zstd(data: Any, threads: int = 4) -> bytes:
        serialized_data = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
        compressor = zstd.ZstdCompressor(level=22, threads=threads)
        compressed_data = compressor.compress(serialized_data)
        return compressed_data

    @staticmethod
    def decompress_zstd(compressed_data: bytes) -> Any:
        decompressor = zstd.ZstdDecompressor()
        decompressed_data = decompressor.decompress(compressed_data)
        data = pickle.loads(decompressed_data)
        return data

    @staticmethod
    def compress_lzma(data: Any) -> Any:
        serialized_data = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
        compressed_data = lzma.compress(serialized_data, preset=9)
        return compressed_data

    @staticmethod
    def decompress_lzma(compressed_data: Any) -> Any:
        serialized_data = lzma.decompress(compressed_data)
        data = pickle.loads(serialized_data)
        return data


    # DO NOT USE ANYTHING FROM BELOW THIS LINE #####################################################

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
                array_data = np.frombuffer(stream.read(np.prod(shape) * np.dtype('float64').itemsize), dtype='float64') # type: ignore[unused-ignore]
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

