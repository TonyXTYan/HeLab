# $\mathbb{HELIUM}$
**H**elium **E**xperiment **L**ab **I**nformation **U**nified **M**anager

[![python](https://img.shields.io/badge/Python-3.12-blue.svg?style=flat&logo=python&logoColor=white)](https://docs.python.org/3/whatsnew/3.12.html)
[![pyqt6](https://img.shields.io/badge/PyQt6-blue.svg?style=flat&logo=qt&logoColor=white)](https://www.riverbankcomputing.com/static/Docs/PyQt6/introduction.html)
[![CI](https://github.com/TonyXTYan/HELIUM/actions/workflows/ci.yml/badge.svg)](https://github.com/TonyXTYan/HELIUM/actions/workflows/ci.yml)
[![Create Release](https://github.com/TonyXTYan/HELIUM/actions/workflows/cd.yml/badge.svg)](https://github.com/TonyXTYan/HELIUM/actions/workflows/cd.yml)

![Latest Stable Release](https://img.shields.io/github/v/release/TonyXTYan/HELIUM?label=latest%20stable%20release)
![Latest Pre-release](https://img.shields.io/github/v/release/TonyXTYan/HELIUM?include_prereleases&label=latest%20pre-release)

using Python3.12 for its new typing features
maybe it would also work on Python 3.11? See CI run [here](https://github.com/TonyXTYan/HELIUM/actions/runs/11605700722)



comparison with 
https://pypi.org/project/argos/ 
https://github.com/adareau/HAL



random useful links:
https://www.pythonguis.com/faq/built-in-qicons-pyqt/
https://github.com/niklashenning/pytablericons  https://tabler.io/icons https://github.com/tabler/tabler-icons

```bash
pyinstaller HELIUM.spec --clean
pyinstaller --onefile --windowed --name HELIUM helium/main.py
```





# TODO

- [ ] Add auto scan button 

- [x] Add cancel recursive scan button
  - [ ] probably should lock the tree view while scanning
  - [ ] variable recursive scan depth
  
- [ ] nothing folder should be ligher gray, and hidden folder with data is black 

- [ ] typing

- [ ] unit tests

    - [ ] some test experiment data

- [ ] auto build? maybe?

- [ ] cache github actions

    



