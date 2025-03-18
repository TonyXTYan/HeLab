from __future__ import annotations
import importlib.util
import inspect
import logging
import os
from typing import Dict, List, Optional, Type

from helab.scripts.base import HelabAnalysisScript, ScriptMetadata

class ScriptLoadError(Exception):
    """Raised when there is an error loading a script"""
    pass

class ScriptsManager:
    """Manages loading and organizing HeLab analysis scripts"""

    def __init__(self) -> None:
        self._scripts: Dict[str, Type[HelabAnalysisScript]] = {}
        self._metadata: Dict[str, ScriptMetadata] = {}
        self._groups: Dict[str, List[str]] = {}  # group -> list of script paths

    def load_directory(self, directory: str) -> None:
        """Load all Python files from a directory that contain valid analysis scripts"""
        if not os.path.isdir(directory):
            raise ValueError(f"Not a directory: {directory}")

        # Clear existing scripts from this directory
        self._clear_directory_scripts(directory)

        for filename in os.listdir(directory):
            if not filename.endswith('.py'):
                continue

            file_path = os.path.join(directory, filename)
            try:
                self._load_script_file(file_path)
            except ScriptLoadError as e:
                logging.warning(f"Failed to load script {file_path}: {e}")
            except Exception as e:
                logging.error(f"Unexpected error loading {file_path}: {e}")

    def _clear_directory_scripts(self, directory: str) -> None:
        """Remove all scripts from the specified directory"""
        to_remove = []
        for path in self._scripts.keys():
            if os.path.dirname(path) == directory:
                to_remove.append(path)

        for path in to_remove:
            self._remove_script(path)

    def _remove_script(self, path: str) -> None:
        """Remove a script and its metadata"""
        if path in self._scripts:
            metadata = self._metadata.get(path)
            if metadata and metadata.group in self._groups:
                self._groups[metadata.group].remove(path)
                if not self._groups[metadata.group]:
                    del self._groups[metadata.group]
            del self._scripts[path]
            if path in self._metadata:
                del self._metadata[path]

    def _load_script_file(self, file_path: str) -> None:
        """Load and validate a single script file"""
        try:
            # Import the module
            spec = importlib.util.spec_from_file_location(
                f"helab.scripts.dynamic.{os.path.basename(file_path)}",
                file_path
            )
            if not spec or not spec.loader:
                raise ScriptLoadError("Could not create module spec")
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find HelabAnalysisScript subclasses
            for name, obj in inspect.getmembers(module):
                if (inspect.isclass(obj) and 
                    issubclass(obj, HelabAnalysisScript) and 
                    obj != HelabAnalysisScript):
                    
                    # Create instance to get metadata
                    script = obj()
                    metadata = script.get_metadata()
                    
                    # Validate metadata
                    if not metadata.name or not metadata.group:
                        raise ScriptLoadError("Script metadata missing name or group")
                    
                    # Store script class and metadata
                    self._scripts[file_path] = obj
                    self._metadata[file_path] = metadata
                    
                    # Update groups
                    if metadata.group not in self._groups:
                        self._groups[metadata.group] = []
                    self._groups[metadata.group].append(file_path)
                    
                    logging.info(f"Loaded script {metadata.name} from {file_path}")
                    return

            raise ScriptLoadError("No HelabAnalysisScript subclass found")

        except Exception as e:
            raise ScriptLoadError(f"Failed to load script: {e}")

    def get_groups(self) -> List[str]:
        """Get list of all script groups"""
        return list(self._groups.keys())

    def get_scripts_in_group(self, group: str) -> List[ScriptMetadata]:
        """Get metadata for all scripts in a group"""
        if group not in self._groups:
            return []
        return [self._metadata[path] for path in self._groups[group]]

    def get_script(self, file_path: str) -> Optional[Type[HelabAnalysisScript]]:
        """Get script class by file path"""
        return self._scripts.get(file_path)

    def get_script_metadata(self, file_path: str) -> Optional[ScriptMetadata]:
        """Get script metadata by file path"""
        return self._metadata.get(file_path)