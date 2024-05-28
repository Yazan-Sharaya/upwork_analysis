Upwork Analysis
===============
[![PyPI version](https://badge.fury.io/py/upwork_analysis.svg)](https://badge.fury.io/py/upwork_analysis)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/upwork_analysis)

Upwork is a freelancing platform where clients post jobs and freelancers fight to get hired.
I do freelance work there from time to time and I decided to follow the advice "Work smarter not harder" therefor I created this project.
The aim is to scrape jobs' data on Upwork and conduct data analysis to extract insights from the data.


<!-- TOC -->
* [Objective](#objective)
* [Features](#features)
* [Usage](#usage)
    * [The easy way](#the-easy-way)
    * [Scraping](#scraping)
        * [CLI usage](#cli-usage)
        * [Parameters](#parameters)
        * [Python](#python)
    * [Analysis](#analysis)
        * [CLI usage](#cli-usage-1)
        * [Python](#python-1)
        * [Jupyter](#jupyter)
* [Installation](#installation)
    * [Automatic](#automatic)
    * [Manual](#manual)
* [Documentation](#documentation)
* [Limitations](#limitations)
* [License](#license)
<!-- TOC -->


Objective
---------
This repository aims to perform the following two tasks.
1. Scrape Job listings on Upwork for a specific search query.
2. Analyze the scraped data to find the following:
    1. The countries that pay the most.
    2. Job frequency on different days of the week.
    3. The most asked for skills.
    4. The budget ranges/groups and their frequency.
    5. The skills that correlate with higher budgets.
    6. The relationship between these skills and the number of proposals.


Features
--------
* **Fault tolerance**: The scraper has been built with fault tolerance in mind and has been thoroughly tested to ensure that.
  Even if an error occurs that's not caused by the scraping process like a network error, a captcha or the user closing the
  browser session, the scraper will gracefully stop scraping and it will save any scraped jobs.
* **Retry**: Retrying functionality is baked in, so if a network error occurs or a captcha pops up, the scraper will retry to scrape
  the specific page where the error occurred. This can be controlled by the 'retries' argument.
* **Undetectability**: Upwork is guarded by Cloudflare's various protection mesures, the scraper bypasses these protections,
  and from my many test runs, it didn't trigger any of the protections at all.
* **Concurrency**: The scraping workload can distributed across multiple workers to speed up the scraping process tremendously.
  This can be controlled by the 'workers' argument.
* **No API**: The scraper doesn't need an Upwork account or an API key to work making it more broadly available, especially because
  of hard it is to get an Upwork API key (they ask for more legal documents than when you sign up!)


Usage
-----
There are two main ways to get started with this project, one is through the command
line and the other is by directly importing its functions and classes into your script.
Both achieve the same functionality, choose the one that best suits your needs.

### The easy way
If you installed the package using pip, the easiest and most straightforward way to use is through the entry points.

For scraping
```
scrape-upwork scrape Python Developer -o python_jobs.json --headless
```
For analysis
```
analyze-upwork SAVED/JOBS/FILE.json -o PATH/TO/SAVE/DIR -s
```

Continue reading down below for more methods to use the package.

### Scraping

##### CLI usage
To scrape a new search query from scratch
```
cd PATH/TO/upwork_analysis
python scrape_data.py scrape Python Developer -o python_jobs.json --headless
```
To update existing data for a search query with any new job listings
```
cd PATH/TO/upwork_analysis
python scrape_data.py update Python Developer -o PATH/TO/SAVE/FILE.json --headless
```

##### Parameters

| Parameter              | Options       | Default         | Description                                                                                       |
|------------------------|---------------|-----------------|---------------------------------------------------------------------------------------------------|
| Action                 | scrape/update | scrape          | Scrape new jobs, or update existing scraped data with any new job postings.                       |
| -q / --search-query    | str           | None (Required) | The query to search for.                                                                          |
| -j / --jobs-per-page   | 10, 20, 50    | 10              | How many jobs should be displayed per page.                                                       |
| -s / --start-page      | int           | 1               | The page number to start searching from.                                                          |
| -p / --pages-to-scrape | int           | 10              | How many pages to scrape. If not passed, scrape all the pages.¹                                   |
| -o / --output          | str           | -               | Where to save the scraped data.                                                                   |
| -r / --retries         | int           | 3               | Number of retries when encountering a Captcha or timeout before failing.                          |
| -w / --workers         | int           | 1               | How many webdriver instances to concurrently spin up for scraping.                                |
| -f / --fast            | passed or not | False           | Whether to use the fast scraping method, can be 10 to 50x faster but leaves some information out. |
| --headless             | passed or not | False           | Whether to enable headless mode (slower and more detectable).                                     |

<sup>¹ See the [limitations](#limitations) section</sup>

##### Python
```python
from upwork_analysis.scrape_data import JobsScraper
jobs_scraper = JobsScraper(
    search_query="Python Developer",
    jobs_per_page=10,
    start_page=1,
    pages_to_scrape=10,
    save_path='PATH/TO/SAVE/FILE.json',
    retries=3,
    headless=True,
    workers=2,
    fast=False)
jobs_scraper.scrape_jobs()
jobs_scraper.update_existing()
```

This will scrape all resulting job listings for "Python Developer" from page 1 to page 10 and save the results to
"PATH/TO/SAVE/FILE.json" using a headless browser. It will scrape a total of `jobs_per_page` * `pages_to_scrape` jobs or
100 in this case.

### Analysis
A quick note, even though the analysis might run with as low as 1 data point _(or it might not and throw errors
because there isn't enough data)_, it's better to scrape more data for the results to be meaningful.

##### CLI usage
```
cd PATH/TO/upwork_analysis
python analyize_data.py SAVED/JOBS/FILE.json -o PATH/TO/SAVE/DIR -s
```

##### Python
```python
from upwork_analysis.analyze_data import perform_analysis
perform_analysis(
    dataset_path='SAVED/JOBS/FILE.json',
    save_plots_dir='PATH/TO/SAVE/DIR',
    show_plots=True)
```

##### Jupyter
```jupyter
jupyter notebook data_analysis.ipynb
# Change the 1st line of cell 3 from
dataset_path = ""
# To
dataset_path = "SAVED/JOBS/FILE.json"
```

This will analyze the data saved at "SAVED/JOBS/FILE.json", save the resulting plots "PATH/TO/SAVE/DIR" and
-s (--show, or show_plots=True) will show the resulting plots all at once.

For more documentation about available functions, their parameters and how to use them, see the [Documentation](#documentation) section.


Installation
------------
This package requires python 3.7 or later.

##### Automatic
```
pip install upwork_analysis
```
**Note:** If you encounter an error during installing, update pip using `python -m pip install -U pip` and it should fix the issue.

##### Manual
1. Clone this repository
    ```
    git clone https://github.com/Yazan-Sharaya/upwork_analysis
    ```
2. Download the dependencies
    * If you just want the scraping functionality
    ```
    pip install seleniumbase beautifulsoup4
    ```
    * And additionally for analyzing the data
    ```
    pip install pandas scipy seaborn scikit-learn
    ```
3. Build the package using
    ```
    python -m build -s
    ```
4. Install the package
    ```
    pip install upwork_analysis-1.0.0.tar.gz
    ```


Documentation
-------------
Both modules and all the functions they implement are documented using function and module docstrings.
To save you sometime, here's a list that covers the documentation for 99% of use cases.
* For documentation about scraping, check out the docstrings for `JobsSraper`, `JobsScraper.scrape_jobs` and `JobsScraper.update_existing`.
  **Note:** You can display the documentation of a function, class or module using the build-in `help()` function.
* As for the data analysis part, checkout out `analyze_data` module docstring and `perform_analysis` function.
* For help on command line usage, append `-h` option to `python scrape_data.py` or `python analyze_data.py`.


Limitations
-----------
* Upwork won't load more than 5050 jobs on their website even if the website says there are more.\
  You can still get more than 5050 jobs, first scrape all the data, then keep updating the scraped data routinely.
  For information on how to do this, see [usage](#cli-usage) or [documentation](#documentation) sections. 
* The post data for jobs is relative and its accuracy decreases as you go further into the past.\
  Minute precision for jobs posted up to an hour ago, hour for a day (2 hours ago), days up to a week ago (3 days ago) and so on.\
  This can also be worked around using the same method mentioned in point 1.


License
-------
This project is licensed under the [MIT license](https://github.com/Yazan-Sharaya/upwork_analysis/blob/main/LICENSE)
