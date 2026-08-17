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
    """Manages loading and organizing HeLab analysis scripts.
    
    This class is responsible for:
    1. Loading Python script files containing HeLab analysis scripts
    2. Organizing scripts into groups for easy management
    3. Maintaining metadata about each script
    4. Providing access to script classes and their metadata
    
    The manager maintains three main data structures:
    - _scripts: Maps script ids to script classes
    - _metadata: Maps script ids to script metadata
    - _groups: Maps group names to lists of script ids

    A script id uniquely identifies a HelabAnalysisScript subclass, since a
    single file may define more than one script class (and thus share a
    file_path).
    
    Scripts must be subclasses of HelabAnalysisScript and provide valid metadata
    through the get_metadata() method including a name and group.
    """

    def __init__(self) -> None:
        self._scripts: Dict[str, Type[HelabAnalysisScript]] = {}
        self._metadata: Dict[str, ScriptMetadata] = {}
        self._groups: Dict[str, List[str]] = {}  # group -> list of script paths

    def load_directory(self, directory: str) -> None:
        """Load all Python files from a directory that contain valid analysis scripts.
        
        This method:
        1. Scans the given directory for .py files
        2. Clears any existing scripts from this directory
        3. Attempts to load each .py file as a script
        4. Organizes loaded scripts into groups
        
        Scripts must:
        - Be a .py file
        - Contain a class that inherits from HelabAnalysisScript
        - Provide valid metadata through get_metadata()
        
        Args:
            directory: Path to directory containing Python script files
            
        Raises:
            ValueError: If directory doesn't exist
            ScriptLoadError: If script loading fails
        """
        if not os.path.isdir(directory):
            raise ValueError(f"Not a directory: {directory}")

        # Normalize so re-loading the same directory via a differently
        # spelled (but equivalent) path is recognized as the same directory.
        directory = os.path.normpath(os.path.abspath(directory))

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
        to_remove = [
            script_id for script_id, metadata in self._metadata.items()
            if os.path.dirname(metadata.file_path) == directory
        ]

        for script_id in to_remove:
            self._remove_script(script_id)

    def _remove_script(self, script_id: str) -> None:
        """Remove a script and its metadata"""
        if script_id in self._scripts:
            metadata = self._metadata.get(script_id)
            if metadata and metadata.group in self._groups:
                self._groups[metadata.group].remove(script_id)
                if not self._groups[metadata.group]:
                    del self._groups[metadata.group]
            del self._scripts[script_id]
            if script_id in self._metadata:
                del self._metadata[script_id]

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

            # Find HelabAnalysisScript subclasses. A single file may define
            # more than one script class, so all matches are loaded.
            found_any = False
            for name, obj in inspect.getmembers(module):
                if (inspect.isclass(obj) and
                    issubclass(obj, HelabAnalysisScript) and
                    obj != HelabAnalysisScript and
                    obj.__module__ == module.__name__):

                    # Create instance to get metadata
                    script = obj()
                    metadata = script.get_metadata()

                    # Validate metadata
                    if not metadata.name or not metadata.group:
                        raise ScriptLoadError("Script metadata missing name or group")

                    found_any = True
                    script_id = f"{file_path}::{obj.__qualname__}"
                    metadata.script_id = script_id

                    # Store script class and metadata
                    self._scripts[script_id] = obj
                    self._metadata[script_id] = metadata

                    # Update groups
                    if metadata.group not in self._groups:
                        self._groups[metadata.group] = []
                    self._groups[metadata.group].append(script_id)

                    logging.info(f"Loaded script {metadata.name} from {file_path}")

            if not found_any:
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

    def get_script(self, script_id: str) -> Optional[Type[HelabAnalysisScript]]:
        """Get script class by script id"""
        return self._scripts.get(script_id)

    def get_script_metadata(self, script_id: str) -> Optional[ScriptMetadata]:
        """Get script metadata by script id"""
        return self._metadata.get(script_id)