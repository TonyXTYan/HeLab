from __future__ import annotations
import logging
from typing import Any, List

from helab.scripts.base import HelabAnalysisScript, ScriptMetadata

class BasicAnalysisScript(HelabAnalysisScript):
    """Example analysis script demonstrating the basic protocol"""
    
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="Basic Analysis",
            description="A simple example script demonstrating the analysis protocol",
            group="Examples",
            file_path=__file__
        )
    
    def get_actions(self) -> List[str]:
        return ["Analyze", "Plot"]
        
    def execute_action(self, action_name: str, **kwargs: Any) -> None:
        if action_name == "Analyze":
            self._analyze()
        elif action_name == "Plot":
            self._plot()
        else:
            raise ValueError(f"Unknown action: {action_name}")
    
    def _analyze(self) -> None:
        """Example analysis action"""
        logging.info("Performing basic analysis...")
        # Simulated analysis
        logging.info("Analysis complete!")
    
    def _plot(self) -> None:
        """Example plotting action"""
        logging.info("Creating plot...")
        # Simulated plotting
        logging.info("Plot created!")

class AnotherAnalysisScript(HelabAnalysisScript):
    """Another example script in a different group"""
    
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="Advanced Analysis",
            description="A more complex analysis example",
            group="Advanced",
            file_path=__file__
        )
    
    def get_actions(self) -> List[str]:
        return ["Process", "Visualize"]
        
    def execute_action(self, action_name: str, **kwargs: Any) -> None:
        if action_name == "Process":
            self._process()
        elif action_name == "Visualize":
            self._visualize()
        else:
            raise ValueError(f"Unknown action: {action_name}")
    
    def _process(self) -> None:
        """Example processing action"""
        logging.info("Processing data...")
        # Simulated processing
        logging.info("Processing complete!")
    
    def _visualize(self) -> None:
        """Example visualization action"""
        logging.info("Creating visualization...")
        # Simulated visualization
        logging.info("Visualization created!")