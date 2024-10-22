from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="helab",
    version="0.0.1",
    author="Tony Yan",
    author_email="tony.yan@anu.edu.au",
    description="HELIUM Experiment Lab Information Unified Manager",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/TonyXTYan/HeLab",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "PyQt6>=6.7.1",
        "pytablericons>=1.0.1",
        "pygame>=2.6.1",
        "Pympler>=1.1",
        # Add other dependencies from requirements-pip.txt
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