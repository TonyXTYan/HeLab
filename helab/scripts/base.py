from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Any, Mapping, Optional, Sequence

from helab.analysis.follow import LivePolicy
from helab.analysis.identity import AnalysisIdentity, file_name
from helab.analysis.dataset_view import DatasetView
from helab.analysis.parameters import ParameterSpec, describe
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.selection import SHOTS, select_shots

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget

@dataclass
class ScriptMetadata:
    """Metadata for a HeLab analysis script"""
    name: str
    description: str
    group: str
    file_path: str
    script_id: str = ""
    # A stable ID that never changes, and a version the author bumps when the output changes.
    analysis_id: str = ""
    version: str = ""
    # SHA-256 of the script file as loaded (set by ScriptsManager; "" if unreadable).
    file_hash: str = ""

    def identity(self) -> AnalysisIdentity:
        return AnalysisIdentity(self.analysis_id or self.script_id or self.name, self.version,
                                file_name(self.file_path), self.file_hash)

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
                       file_path: str,
                       analysis_id: str = "",
                       version: str = "") -> ScriptMetadata:
        """Helper to create metadata object"""
        return ScriptMetadata(
            name=name,
            description=description,
            group=group,
            file_path=file_path,
            analysis_id=analysis_id,
            version=version
        )


class DatasetAnalysis(HelabAnalysisScript):
    """An analysis of one loaded dataset.

    The Scripts panel runs an action on the current tab's dataset view: ``compute`` gets an
    ``AnalysisContext`` (the immutable view and the effective parameters, never the tab) and
    runs in the analysis worker thread, so it must not touch Qt widgets. ``render`` then
    builds the plot dock's content from the result on the GUI thread. Arrays in the view
    are shared and read-only: copy one before changing it.

    A plot of the folder Live watches follows it: HeLab reruns it on each newer revision of the
    view, as the script's ``live_policy`` allows. A script never reads files or watches folders
    itself, and a view may have no shots yet (Live started before the first one): its plot then
    shows that it is empty, not an error.

    Metadata must give ``analysis_id`` and ``version``. Parameter values are plain JSON values
    (numbers, booleans, strings).
    """

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        """The action's parameters (defaults, limits, units)."""
        return []

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        """Two short texts for the plot dock's source lines: what part of the view the run used
        (line 1, after the folder and revision, e.g. "shots 51–60 (10 of 60)"; "" for all of
        it) and its settings in short form (line 2, e.g. "last 10 shots · auto-crop 99 %").
        The dock's tooltip always holds the full record. By default: no selection, and every
        parameter in use as ``title value``."""
        return "", describe(self.parameters(action_name), values)

    def describe_result(self, action_name: str, result: AnalysisResult) -> str:
        """What a completed run found that the dock's settings line should add after
        ``describe_run``'s settings, in short form (e.g. a spectrum's resolution and Nyquist
        frequency, or a bin width chosen from the data); "" for nothing. ``result.data`` may be
        None (a released plot) or another run's state: say nothing then. Default: nothing."""
        return ""

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        """Settings the run could not follow as given, and what it did instead (e.g. "X: min >
        max, using full extent"), for the dock's source line, its record and the settings tab."""
        return []

    def live_policy(self, action_name: str) -> LivePolicy:
        """When a plot following Live reruns by default (the plot's settings can change it):
        on every new shot unless a long analysis declares fewer reruns."""
        return LivePolicy()

    def covered_shots(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> Sequence[int]:
        """The view's shots a run with ``values`` uses, recorded as its coverage: those the shared
        Shots parameters choose (``selection.SHOT_SPECS``) when it has them, else all."""
        return select_shots(view, values) if SHOTS.name in values else view.shot_numbers

    def detected_parameters(self, action_name: str, result: AnalysisResult) -> dict[str, Any]:
        """Parameter values a completed run found in the data (e.g. where peaks are), which the
        plot's settings then show, so switching to manual starts from them. Default: none."""
        return {}

    @abstractmethod
    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        """The numerical result (no Qt). Check ``context.cancelled()`` in long loops."""

    @abstractmethod
    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        """The plot for a completed result (GUI thread)."""

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """Show a newer result in the plot already drawn (``widget``, from ``render``), in place,
        keeping what the user did to the view (e.g. a 3D scatter's camera); GUI thread. Whether
        it did: if not, ``render`` draws the plot anew. Default: not."""
        return False

    def execute_action(self, action_name: str, **kwargs: Any) -> None:
        context = kwargs.get("context")
        if not isinstance(context, AnalysisContext):
            raise ValueError(f"{action_name} needs loaded data: run it from the Scripts panel")
        self.compute(action_name, context)
