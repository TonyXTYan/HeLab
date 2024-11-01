# $\text{HeLab}$
## $\textbf{H}\text{elium } \textbf{E}\text{xperiment } \textbf{L}\text{ab } \textbf{A}\text{nalysis } \textbf{B}\text{oard}$

---


[//]: # (## **H**elium **E**xperiment **L**ab **A**nalysis **B**oard)

[//]: # (**H**elium **E**xperiment **L**ab **I**nformation **U**nified **M**anager)

[![python](https://img.shields.io/badge/python-3.12-blue.svg?style=flat&logo=python&logoColor=white)](https://docs.python.org/3/whatsnew/3.12.html)
[![pyqt6](https://img.shields.io/badge/pyqt6-blue.svg?style=flat&logo=qt&logoColor=white)](https://www.riverbankcomputing.com/static/Docs/PyQt6/introduction.html)
[![tests](https://img.shields.io/github/actions/workflow/status/TonyXTYan/HeLab/ci.yml?label=tests&logo=github&logoColor=white)](https://github.com/TonyXTYan/HeLab/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/actions/workflow/status/TonyXTYan/HeLab/cd.yml?label=release&logo=github&logoColor=white)](https://github.com/TonyXTYan/HeLab/actions/workflows/cd.yml)

[//]: # ([![CI]&#40;https://github.com/TonyXTYan/HeLab/actions/workflows/ci.yml/badge.svg&#41;]&#40;https://github.com/TonyXTYan/HeLab/actions/workflows/ci.yml&#41;)
[//]: # ([![CD]&#40;https://github.com/TonyXTYan/HeLab/actions/workflows/cd.yml/badge.svg&#41;]&#40;https://github.com/TonyXTYan/HeLab/actions/workflows/cd.yml&#41;)


[//]: # ([![Latest Stable Release]&#40;https://img.shields.io/github/v/release/TonyXTYan/HeLab?label=latest%20stable%20release&#41;]&#40;https://github.com/TonyXTYan/HeLab/releases/latest&#41;)
[//]: # ([![Latest Pre-release]&#40;https://img.shields.io/github/v/release/TonyXTYan/HeLab?include_prereleases&label=latest%20pre-release&#41;]&#40;https://github.com/TonyXTYan/HeLab/releases&#41;)

[![latest release](https://img.shields.io/github/v/release/TonyXTYan/HeLab?label=Latest%20Release&)](https://github.com/TonyXTYan/HeLab/releases/latest)

[![license](https://img.shields.io/github/license/TonyXTYan/HeLab?color=blue)]()
[![gitHub issues](https://img.shields.io/github/issues/TonyXTYan/HeLab?&logo=github&logoColor=white)](https://github.com/TonyXTYan/HeLab/issues)


here are some more random badges because they look cool

![nvidia](https://img.shields.io/badge/nVIDIA-76B908.svg?logo=nvidia&logoColor=white)
![apple](https://img.shields.io/badge/apple-000000.svg?logo=apple&logoColor=white) 
![arm](https://img.shields.io/badge/arm-0091BD.svg?logo=arm&logoColor=white)
![dell](https://img.shields.io/badge/dell-007DB8?logo=dell&logoColor=white)
![intel](https://img.shields.io/badge/intel-0071C5?logo=intel&logoColor=white)
![gitHub actions](https://img.shields.io/badge/github%20actions-181717.svg?logo=githubactions&logoColor=white)
![pandas](https://img.shields.io/badge/pandas-150458.svg?logo=pandas&logoColor=white)
![numpy](https://img.shields.io/badge/numpy-013243.svg?logo=numpy&logoColor=white)
![numba](https://img.shields.io/badge/numba-00A3E0.svg?logo=numba&logoColor=white)
![scipy](https://img.shields.io/badge/scipy-8CAAE6.svg?logo=scipy&logoColor=white)
![conda](https://img.shields.io/badge/conda-44Ab33.svg?logo=anaconda&logoColor=white)
![pip](https://img.shields.io/badge/pip-3775A9.svg?logo=pypi&logoColor=white)

![arxiv](https://img.shields.io/badge/arXiv-B31B1B?logo=arxiv&logoColor=white)
![google scholar](https://img.shields.io/badge/Google%20Scholar-4285F4?logo=googlescholar&logoColor=white)
![ORCID](https://img.shields.io/badge/ORCID-a6ce39?logo=orcid&logoColor=white)


[//]: # (![Windows]&#40;https://img.shields.io/badge/Windows-0078D6?logo=microsoft&logoColor=white&#41;)

---

using Python3.12 for its new typing features
maybe it would also work on Python 3.11? See CI run [here](https://github.com/TonyXTYan/HELIUM/actions/runs/11605700722)



comparison with 
https://pypi.org/project/argos/ 
https://github.com/adareau/HAL



random useful links:
https://www.pythonguis.com/faq/built-in-qicons-pyqt/
https://github.com/niklashenning/pytablericons  https://tabler.io/icons https://github.com/tabler/tabler-icons

```bash
pyinstaller HeLab.spec --clean
pyinstaller HeLab.spec --clean -y 
pyinstaller --onefile --windowed --name HELIUM helab/main.py
```




---
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

    



