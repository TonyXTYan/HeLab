# HELIUM
**H**elium **E**xperiment **L**ab **I**nformation **U**nified **M**anager

[![CI](https://github.com/TonyXTYan/HELIUM/actions/workflows/ci.yml/badge.svg)](https://github.com/TonyXTYan/HELIUM/actions/workflows/ci.yml)


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

    



