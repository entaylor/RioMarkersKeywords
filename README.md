# RioMarkersKeywords
Regex-based keyword matching of RioMarkers data with a focus on local implementation and actions that are locally-led.

This repo makes public the code and methods used for the IIED issue paper https://iied.org/22767iied

This project improves and extends on an earlier work ([Treichel et al. 2025](https://iied.org/22764iied)); see [here for more](https://github.com/entaylor/LLAkeywordsearch).

The repo includes a simple Jupyter notebook (riomarkers.ipynb) that shows the calling signature for the workhorse Python script, which is riomarkers.py.

As described in the paper, the data used are the OECD Credit Reporting System (flows) dataset, accessed via the [OECD Data Explorer](https://data-explorer.oecd.org/).  (Search for keyword 'CRS' to find the CRS (flows) dataset, then download the CRS-Parquet file to obtain the full dataset.)  Within the script, the data are limited to 'year' >= 2011 at time of load, and then filtered on the column 'biodiversity' >= 1 before analysis.

For all other implementation details, consult the paper and/or look to the code in this repo.
