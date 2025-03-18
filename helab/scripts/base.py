from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Any, Optional

@dataclass
class ScriptMetadata:
    """Metadata for a HeLab analysis script"""
    name: str
    description: str
    group: str
    file_path: str

class HelabAnalysisScript(ABC):
    """Base class for HeLab analysis scripts.
    
    All analysis scripts must inherit from this class and implement its methods.
    """
    
    @abstractmethod
    def get_metadata(self) -> ScriptMetadata:
        """Return metadata about the script"""
        pass
    
    @abstractmethod
    def get_actions(self) -> List[str]:
        """Return list of available action names"""
        pass
        
    @abstractmethod
    def execute_action(self, action_name: str, **kwargs: Any) -> None:
        """Execute a named action with optional parameters"""
        pass

    @classmethod
    def create_metadata(cls,
                       name: str,
                       description: str,
                       group: str,
                       file_path: str) -> ScriptMetadata:
        """Helper to create metadata object"""
        return ScriptMetadata(
            name=name,
            description=description,
            group=group,
            file_path=file_path
        )