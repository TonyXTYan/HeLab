from pathlib import Path
import os
import sys

from setuptools import setup, find_packages
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
from helab._version import __version__
from helab.build_info import BUILD_INFO_FILENAME, write_build_info


class BuildPy(build_py):
    def run(self) -> None:
        super().run()
        write_build_info(ROOT, Path(self.build_lib) / "helab" / BUILD_INFO_FILENAME)

with (ROOT / "README.md").open("r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="helab",
    version=__version__,
    author="Tony Yan",
    author_email="tony.yan@anu.edu.au",
    description="HELIUM Experiment Lab Information Unified Manager",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/TonyXTYan/HeLab",
    packages=find_packages(),
    cmdclass={"build_py": BuildPy},
    include_package_data=True,
    package_data={"helab.resources": ["*.svg"], "helab": [BUILD_INFO_FILENAME]},
    install_requires=[
        "PyQt6>=6.7.1",
        "pytablericons>=1.0.1",
        "Pympler>=1.1",
        "packaging",
        # What helab imports at runtime; requirements.lock pins the tested versions, and
        # requirements.txt adds the development and build tools.
        "PyQt6-WebEngine",
        "blosc",
        "coloredlogs",
        "dash",
        "joblib",
        "matplotlib",
        "numpy",
        "pandas",
        "pillow",
        "plotly",
        "psutil",
        "pyqtgraph",
        "scipy",
        "uncertainties",
        "werkzeug",
    ],
    entry_points={
        "console_scripts": [
            "helab=helab.main:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.09',
    # python_requires='>=3.11',
)
