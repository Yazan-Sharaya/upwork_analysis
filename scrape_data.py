"""This module implements `JobsScaper` class that aims to scrape Upwork job listings within certain parameters."""
from datetime import datetime, timedelta
import threading
import argparse
import platform
import random
import ctypes
import json
import time

from seleniumbase.common.exceptions import (
    NoSuchElementException as SBNoSuchElementException, WebDriverException as SBWebDriverException)
from seleniumbase.undetected import Chrome
from seleniumbase import Driver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from bs4 import BeautifulSoup
from bs4.element import Tag

job_title_selector = ".air3-line-clamp > h2 > a"  # Text could be embedded in the anchor tag or set as text attribute.
post_time_selector = ".job-tile-header div small span:nth-child(2)"
job_skills_selector = 'div[data-test="JobTileDetails"] div.air3-token-container span[data-test="token"] span'  # multi
description_selector = "div.air3-line-clamp.is-clamped > p.mb-0"

job_details_selector = "ul.job-tile-info-list.text-base-sm.mb-4"
job_type_selector = job_details_selector + " > li:nth-child(1) > strong"
experience_level_selector = job_details_selector + ' > li[data-test="experience-level"] > strong'
time_estimate_selector = job_details_selector + ' > li[data-test="duration-label"] > strong:nth-child(2)'
budget_selector = job_details_selector + ' > li[data-test="is-fixed-price"] > strong:nth-child(2)'

# When opening a specific job.
proposals_selector = 'ul.client-activity-items > li.ca-item > span.value'
client_details_selector = "ul.ac-items.list-unstyled"
client_location_selector = client_details_selector + ' > li:nth-child(1) > strong'
client_jobs_posted_selector = client_details_selector + ' > li[data-qa="client-job-posting-stats"] > strong'
client_hire_rate_selector = client_details_selector + ' > li[data-qa="client-job-posting-stats"] > div'
client_hourly_rate_selector = client_details_selector + ' strong[data-qa="client-hourly-rate"]'
client_spent_selector = client_details_selector + ' strong[data-qa="client-spend"] > span'

job_back_arrow_selector = 'div.air3-slider-header > button.air3-slider-prev-btn.air3-slider-close-desktop > div'


def split_list_into_chunks(lst: list, num_chunks: int) -> list[list]:
    """
    Split a list into `num_chunks` chunks.

    .. note:: The elements in each chunk aren't in the same order as the original list.

    Parameters
    ----------
    lst: list
        The list to split.
    num_chunks: int
        The number of chunks to split. If 1, a list containing `lst` is returned, if larger or equal to the length
        of `lst`, a list containing `len(lst)` chunks (lists) each containing one element is returned.

    Returns
    -------
    chunks: list[list]
        A list of lists (chunks).
    """
    chunks = []
    for i in range(num_chunks):
        # Create a new chunk with elements at positions i, i + num_chunks, i + 2*num_chunks, etc.
        chunk = lst[i::num_chunks]
        if chunk:
            chunks.append(chunk)
    return chunks


def inhibit_sleep(inhibit: bool = False) -> None:
    """
    Prevents a Windows computer from going to sleep while the current thread is running.
    .. note:: This function needs to be called periodically in case of inhibiting sleep.
    """
    # For more information about how this works what are the values user, see:
    # https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate
    es_continues = 0x80000000
    es_system_required = 0x00000001
    if platform.system() == "Windows":
        if inhibit:
            ctypes.windll.kernel32.SetThreadExecutionState(es_continues | es_system_required)
        else:
            ctypes.windll.kernel32.SetThreadExecutionState(es_continues)


def time_print(message: str) -> None:
    """Print a message alongside the current time."""
    print(f"{datetime.now().isoformat(sep=' ', timespec='seconds')}: {message}")


def sleep(a: float = 0.5, b: float = 1) -> None:
    """Sleeps for a random amount between `a` and `b` seconds."""
    time.sleep(random.uniform(a, b))


def construct_url(query: str, jobs_per_page: int = 10, start_page: int = 1) -> str:
    """
    Constructs a search url based on the arguments and deals with spaces in
    `query` and choosing the correct `jobs_per_page`.

    Parameters
    ----------
    query: str
        The query to search for. It could be multiple words or single word.
    jobs_per_page: int
        How many jobs should be displayed per page. Allowed numbers are 10, 20 and 50. In case a different number is
        passed, the closest allowed number to it will be chosen. Default is 10.
    start_page: int
        The page number to start searching from. Default is 1 (the first page).

    Returns
    -------
    url: str
        The complete search url.
    """
    # Only 10, 20 and 50 are valid values to jobs_per_page; this expression takes care of getting the closest allowed
    # number to the input.
    jobs_per_page = min([10, 20, 50], key=lambda x: abs(x - jobs_per_page))
    query = query.replace(" ", "%20")
    return (f"https://www.upwork.com/nx/search/jobs/"
            f"?nbs=1"
            f"&page={start_page}"
            f"&per_page={jobs_per_page}"
            f"&q={query}"
            f"&sort=recency")


def parse_time(relative_time: str) -> float:
    """Upwork jobs post-dates are relative to the local time of the host, this function converts them as Unix time"""
    relative_time = relative_time.lower()
    if relative_time == "yesterday":
        time_delta = timedelta(days=1)
    elif "last week" in relative_time:
        time_delta = timedelta(weeks=1)
    elif "last month" in relative_time:
        time_delta = timedelta(days=30)
    else:
        number, unit = relative_time.split()[:2]
        unit += 's' if not unit.endswith('s') else ''  # Turn minute to minutes, for example.
        if "month" in unit:
            number = int(number) * 30
            unit = "days"
        time_delta = timedelta(**{unit: int(number)})
    absolute_time = datetime.now() - time_delta
    return int(absolute_time.timestamp())


def parse_budget(job_type: str, budget: str | None) -> int | None:
    """
    Takes the job type (hourly, fixed-price) budget, which might be the budget in $ for a fixed-price
    job or the estimated time of an hourly job.
    Returns the hourly rate for hourly jobs and the budget for fixed-price. Returns None if the hourly rate isn't
    specified.
    """
    job_type = job_type.lower()
    job_type = job_type.replace("$", "")
    if "hourly" in job_type:
        if ":" in job_type:
            hourly_rate = job_type.split(":")[1]
            min_rate, max_rate = hourly_rate.split(' - ')
            average_rate = int((float(max_rate) + float(min_rate)) / 2)
            return average_rate
        return None
    if not budget or '$' not in budget:  # If $ isn't in the budget's text, it means it's "not sure".
        return None
    budget = budget.replace("$", "").split()[0]  # `split` is the easiest way to git rid of all whitespace.
    return int(float(budget.replace(',', '')))


def parse_total_spent(total_spent: str) -> int | None:
    """Parses the total spent texts and returns the dollar number as integer."""
    total_spent = total_spent.replace('$', '')
    unit_map = {"K": 1000, "M": 1_000_000}
    for unit, value in unit_map.items():
        if unit in total_spent:
            return int(float(total_spent.replace(unit, '').strip()) * value)
    return int(total_spent)


def parse_one_job(driver: Chrome, job: Tag, index: int, fast: bool = False) -> dict[str, str | int | float | None]:
    """
    Parses one job listing (html) and returns a dictionary containing its information. The collected information is:
        - Job title
        - Job description
        - Job skills
        - Job post time as a UNIX timestamp
        - Job type (Hourly or Fixed)
        - Experience level (entry, intermediate, expert)
        - Time estimate (the estimated time the job is going to take, for example, 1-3 months for an hourly job
          or None for a fixed-price job)
        - Budget (The budget for a fixed-price job or the average hourly rate or None if it's not specified)
    And the following if the listing is public and `fast=False` (only proposals and location are guaranteed to exist):
        - Number of proposals
        - Client location
        - Client number of posted jobs
        - Client hire rate
        - Client average hourly rate
        - Client total spent

    Parameters
    ----------
    driver: Chrome
        The driver instance to use.
    job: Tag
        Beautiful soup tag containing the job html.
    index: int
        The index of the job with respect to the page.
    fast: bool, optional
        Whether to use the fast method. The fast method doesn't click on the job listing to scrape the information about
        the client and number of proposals making it much faster. Default False.

    Returns
    -------
    job_details: dict
        The job's details.
    """
    job_type = job.select_one(job_type_selector).text
    xp_level = job.select_one(experience_level_selector)
    time_estimate = job.select_one(time_estimate_selector)
    budget = job.select_one(budget_selector)

    job_details = {
        "title": job.select_one(job_title_selector).text,
        "description": job.select_one(description_selector).text,
        "time": parse_time(job.select_one(post_time_selector).text),
        "skills": [skill.text for skill in job.select(job_skills_selector)],
        "type": job_type.split(':')[0].split()[0],
        "experience_level": xp_level.text if xp_level else None,
        "time_estimate": time_estimate.text.split(',')[0] if time_estimate else None,
        "budget": parse_budget(job_type, budget.text if budget else None)
    }
    if fast:
        return job_details

    remaining_keys = (
        "proposals", "client_location", "client_jobs_posted",
        "client_hire_rate", "client_hourly_rate", "client_total_spent")
    job_details.update({key: None for key in remaining_keys})  # Default as None because an error might occur.

    try:
        driver.execute_script("arguments[0].click();", driver.find_element(f"article:nth-child({index})"))
        driver.wait_for_selector(client_location_selector, timeout=1.5)
        job_soup = BeautifulSoup(driver.page_source, "html.parser")
        job_details["proposals"] = job_soup.select_one(proposals_selector).text
        job_details["client_location"] = job_soup.select_one(client_location_selector).text
        for key, selector, parse_func in zip(
                remaining_keys[2:],
                (client_jobs_posted_selector, client_hire_rate_selector,
                 client_hourly_rate_selector, client_spent_selector),
                (lambda e: int(e.replace(',', '')), lambda e: float(e[:-1]) / 100,
                 lambda e: float(e[1:]), parse_total_spent)
        ):
            element = job_soup.select_one(selector)
            job_details[key] = parse_func(element.text.split()[0]) if element else element
    except (SBNoSuchElementException, NoSuchElementException):  # In case of a timeout or private job listing.
        pass
    try:
        driver.wait_for_selector(job_back_arrow_selector, timeout=1.5)
        driver.find_element(job_back_arrow_selector).click()
    except (SBWebDriverException, WebDriverException):
        pass
    sleep()  # Wait for the animation to finish.
    return job_details


class JobsScraper:

    def __init__(
            self,
            search_query: str,
            jobs_per_page: int = 10,
            start_page: int = 1,
            pages_to_scrape: int | None = 10,
            save_path: str | None = None,
            retries: int = 3,
            headless: bool = False,
            workers: int = 1,
            fast: bool = False) -> None:
        """
        Scrapes the `jobs_per_page` * `pages_to_scrape` jobs resulting from searching for `search_query`.

        Notes
        -----
        Upwork won't load any job listings after a certain page number, this limit is any page after 101 when jobs per
        page are equal to 50, 251 when 20 and 501 when 10.

        Parameters
        ----------
        search_query: str
            The query to search for.
        jobs_per_page: int, optional
            How many jobs should be displayed per page. Allowed numbers are 10, 20 and 50. Default is 10.
            The higher the number, the fewer requests are made, the better.
        start_page: int, optional
            The page number to start searching from. Default is 1 (the first page). **Note** this can't be larger than a
            certain number, see the `Notes` section.
        pages_to_scrape: int, optional
            How many pages to scrape after (including) `start_page`. If None, scrape all the available pages. For
            example, if `start_page` is 1 and `pages_to_scrape` is 10, then pages 1 through 10 will be scraped.
            Default 10. **Note** this can't be larger than a certain number, see the `Notes` section.
        save_path: str, optional
            Where to save the scraped data.
        retries: int, optional
            How many times to retry scraping the jobs before giving up. The reasons why scraping might fail are because
            of CloudFlair's Captcha and network errors. Default is 3.
        headless: bool, optional
            Whether to use a headless browser. Default is False. An important **note**, if headless is set to True and
            the browser encountered a captcha the first time it tried to get a link, it means that the undetected
            headless browser didn't work for some reason (it usually works). In this case, a new browser instance is
            created with headless=False.
        workers: int, optional
            The number of worker threads to launch, the higher the number, the faster the execution and resource
            consumption. Default is 1 (sequential execution).
        fast: bool, optional
            Whether to use the fast scraping method. This method can be 10 to 50x times faster but leaves out all
            the information related to the client (location, total spent, etc) and number of proposals. Default False.
        """
        assert jobs_per_page in (10, 20, 50), "The allowed values for `jobs_per_page` are 10, 20 and 50."
        self.search_query = search_query
        self.jobs_per_page = jobs_per_page
        self.start_page = start_page
        self.save_path = save_path
        if self.save_path and not self.save_path.endswith('.json'):
            self.save_path += '.json'
        self.retries = retries
        self.headless = headless
        self.workers = workers
        self.fast = fast

        self.link_get_took = 0
        total_npages = self.get_total_number_of_result_pages()

        # Upwork limits the number of pages the user can access, and the limit is dependent on the number of jobs per
        # page setting. Upwork won't load job listings for any page past the limit (e.g., page 102, jobs_per_page=50).
        allowed_npages = {10: 501, 20: 251, 50: 101}[self.jobs_per_page]
        self.last_allowed_page = min(total_npages, allowed_npages)
        assert 0 < self.start_page <= self.last_allowed_page, f"`start_page` must be in [1, {self.last_allowed_page}]"

        maximum_allowed_npages_to_scrape = self.last_allowed_page - self.start_page + 1
        if pages_to_scrape and pages_to_scrape > maximum_allowed_npages_to_scrape:
            raise ValueError(
                f"`pages_to_scrape` can't be larger than {maximum_allowed_npages_to_scrape}, to not go over the last "
                f"allowed page number ({self.last_allowed_page}). See the documentation for this class "
                f"for more info about the limit.")
        self.pages_to_scrape = pages_to_scrape if pages_to_scrape else maximum_allowed_npages_to_scrape

        self.pages_to_jobs: dict[str, dict[int, list[dict[str, str | int | float | None]]]] = {
            'scrape': {}, 'update': {}}
        self.failed_pages = set()

        self.seen_descriptions = set()
        self.seen_page = None

        activate_workers = len(  # To get the actual number of how many workers there will be.
            split_list_into_chunks(list(range(self.start_page, self.start_page + self.pages_to_scrape)), self.workers))
        estimated_number_of_jobs = self.pages_to_scrape * self.jobs_per_page
        # Each job takes at most 4 seconds, and on at least 0.75 seconds, we just take the average of that (~2.4)
        # workers * 7.5 because each new worker waits 5 to 10 extra seconds before it start.
        time_estimate = round(
            (self.link_get_took * self.pages_to_scrape +
             2.4 * estimated_number_of_jobs * (not self.fast) +
             activate_workers * 7.5) / activate_workers / 60, 1)
        print(
            f"Scraping spec\n-------------\n"
            f"search query: {self.search_query}\n"
            f"pages to scrape: {self.pages_to_scrape}\n"
            f"estimated total number of jobs: {estimated_number_of_jobs}\n"
            f"Retries when detected: {self.retries}\n"
            f"Number of workers: {activate_workers}\n"
            f"Fast method: {self.fast}\n"
            f"ETA: {time_estimate} minutes\n"
            f"{f'Saving to {self.save_path}' if self.save_path else 'Not saving the results'}")

    @property
    def scraped_jobs(self) -> list[dict]:
        """A list containing all the scraped jobs in the order they are presented with on Upwork."""
        jobs = []
        for action in ('update', 'scrape'):
            for _, jobs_list in sorted(self.pages_to_jobs[action].items(), key=lambda x: x[0]):
                jobs.extend(jobs_list)
        return jobs

    def create_driver(self) -> Chrome:
        """Create selenium base undetected chrome driver instance."""
        return Driver("chrome", headless=self.headless, uc=True)

    def get_url(self, driver: Chrome,  page_number: int) -> None:
        """
        Loads the `page_number`th result page for the given `search_query` and `jobs_per_page`.

        Parameters
        ----------
        driver: Chrome
            The webdriver instance to use.
        page_number: int
            The page number to get.
        """
        driver.get(construct_url(self.search_query, self.jobs_per_page, page_number))

    def get_url_retry(self, driver: Chrome, page_number: int, msg: str | None = None) -> bool:
        """
        Same as `get_url` but retry the page if it fails whether because of a network error or a captcha.

        Returns
        -------
        success: bool
            True if the page loads successfully, False otherwise.
        """
        # The following code is to achieve retrying functionality, see https://stackoverflow.com/a/7663441/23524006
        for retry in range(self.retries):
            try:
                if msg:
                    time_print(f"{msg} (try {retry + 1}/{self.retries}).")
                self.get_url(driver, page_number)
                driver.find_element("css selector", "article")
            except NoSuchElementException:
                time_print(f"Encountered a Captcha scraping page {page_number}, trying again.")
                sleep(5, 15)
            except TimeoutException:
                time_print(f"Timed out waiting for page {page_number} to load. trying again.")
                sleep(15, 30)
            else:
                break
        else:
            return False
        return True

    def get_total_number_of_result_pages(self) -> int:
        """Gets the total number of result pages for a certain `search_query` and `jobs_per_page`."""
        driver = self.create_driver()
        t = time.time()
        success = self.get_url_retry(driver, 1, "Getting the total number of result pages.")
        self.link_get_took = time.time() - t
        page_source = driver.page_source if success else None
        driver.quit()
        if not success:
            raise TimeoutError(
                "Couldn't get the total number of result pages. If this was due to timeout, please check your"
                "connection and try again. If it was due to a captcha and `headless` is set to True, try setting it to"
                "False and try again.")
        soup = BeautifulSoup(page_source, "html.parser")
        n_pages = soup.select_one('li[data-test="pagination-mobile"].air3-pagination-mobile').text
        return int(n_pages.split()[-1].replace(",", ""))

    def _scrape_pages(self, page_numbers: list, action: str = 'scrape') -> None:
        """
        Scrapes all the page numbers contained in `page_number` for their job listings details.

        Notes
        -----
        - On Windows, this method prevents the computer from sleeping (but allows the screen to turn off) during
          the scraping process. The reason for this is that when Windows sleeps, the connection to the webdriver
          is severed, and it can't continue running when the PC wakes up resulting in an error.
        - The scraped data is available through `jobs_details` property.
        - `scrape_jobs` method should be used instead of this because it offers saving and multi-threading
          functionality. This method is intended for internal use, but can still be used by user code.

        Parameters
        ----------
        page_numbers: list
            A list containing the page numbers to scrape.
        action: str
            The action to perform, "scrape" the data or "update" existing data with any new data. Default "scrape".

        See Also
        --------
        scrape_jobs: The preferred method to call.
        """
        driver = self.create_driver()
        total_pages = self.start_page + self.pages_to_scrape - 1 if action == 'scrape' else self.last_allowed_page
        seen_jobs = []
        consecutive_seens = 0
        for page in page_numbers:
            if self.seen_page and page > self.seen_page:
                break
            inhibit_sleep(True)
            if not self.get_url_retry(
                    driver, page, f"Scraping page {page} of {total_pages}"):
                self.failed_pages.add(page)
                continue
            self.failed_pages.discard(page)

            soup = BeautifulSoup(driver.page_source, "html.parser")
            jobs = soup.find_all('article')
            self.pages_to_jobs[action][page] = []
            t = time.time()
            for i, job in enumerate(jobs):
                job = parse_one_job(driver, job, i + 1, self.fast)
                description = job['description']
                if description in self.seen_descriptions:
                    consecutive_seens += 1
                    seen_jobs.append(job)
                else:
                    consecutive_seens = 0
                    while seen_jobs:
                        self.pages_to_jobs[action][page].append(seen_jobs.pop(0))
                    self.pages_to_jobs[action][page].append(job)
                self.seen_descriptions.add(description)
                if consecutive_seens > 5:
                    self.seen_page = min(page, self.seen_page) if self.seen_page else page
                    break
            print(round(time.time() - t, 3))

        inhibit_sleep(False)
        driver.quit()

    def distribute_work(self, page_numbers: list, action: str = 'scrape') -> None:
        """Distributes the number of pages to scrape across `self.workers` threads. This function is blocking."""
        workers = []
        for page_numbers_chunk in split_list_into_chunks(page_numbers, self.workers):
            worker = threading.Thread(target=self._scrape_pages, args=(page_numbers_chunk, action))
            worker.start()
            workers.append(worker)
            sleep(5, 10)
        for worker in workers:
            worker.join()

    def retry_failed(self, action: str = 'scrape') -> None:
        """Retry to scrape any failed pages."""
        if self.failed_pages:
            time_print("Waiting 30 to 60 seconds before trying to scrape the failed pages...")
            sleep(30, 60)
            self.distribute_work(list(self.failed_pages), action)
            if self.failed_pages:  # Would be empty if all pages were scraped successfully.
                time_print(f"Failed to scrape the following pages: {self.failed_pages}.")

    def save_data(self) -> None:
        """Save the scraped data to `save_path` as json."""
        if self.save_path:
            time_print(f"Saving to {self.save_path}")
            with open(self.save_path, 'w') as save_file:
                json.dump(self.scraped_jobs, save_file)

    def scrape_jobs(self, page_numbers: list | None = None, action: str = 'scrape') -> list[dict]:
        """
        Scrapes `pages_to_scrape` number of pages for their job listings starting at `start_page`. The following
        information is collected about each job listing:
            - Job title
            - Job description
            - Job skills
            - Job post time as a UNIX timestamp
            - Job type (Hourly or Fixed)
            - Experience level (entry, intermediate, expert)
            - Time estimate (the estimated time the job is going to take, for example, 1-3 months for an hourly job
              or None for a fixed-price job)
            - Budget (The budget for a fixed-price job or the average hourly rate or None if it's not specified)
        And the following if the job listing is public (only proposals and location are guaranteed to exist):
            - Number of proposals
            - Client location
            - Client number of posted jobs
            - Client hire rate
            - Client average hourly rate
            - Client total spent

        Notes
        -----
        - On Windows, this method prevents the computer from sleeping (but allows the screen to turn off) during
          the scraping process. The reason for this is that when Windows sleeps, the connection to the webdriver
          is severed, and it can't continue running when the PC wakes up resulting in an error.

        Parameters
        ----------
        page_numbers: list, optional
            A list containing the page numbers to scrape. If None, scrape all the pages from `start_page` to
            `pages_to_scrape`. Default None
        action: str
            The action to perform, "scrape" the data or "update" existing data with any new data. Default "scrape".

        Returns
        -------
        jobs_details: list[dict]
            A list of dictionaries containing information about the jobs in the order they are presented with on Upwork.
        """
        if page_numbers is None:
            page_numbers = list(range(self.start_page, self.start_page + self.pages_to_scrape))
        self.distribute_work(page_numbers, action)
        self.retry_failed(action)
        if action == 'update':
            # list() to make a copy of the keys and avoid raising dict changed size during iteration runtime exception.
            for key in list(self.pages_to_jobs[action]):
                if self.seen_page and key > self.seen_page:
                    self.pages_to_jobs[action].pop(key)
        time_print(f"Scraped {sum(map(len, self.pages_to_jobs[action].values()))} jobs.")
        self.save_data()
        return self.scraped_jobs

    def update_existing(self) -> list[dict]:
        """
        Update the existing data with any new job listings.

        This function can be called without calling `scrape_jobs` if the data has already been scraped before and is
        saved at `save_path.

        This function can be called repeatedly to keep updating the existing data, and it saves the data to `save_path`
        after each call.
        """
        if not self.pages_to_jobs['scrape']:
            if not self.save_path:
                raise FileNotFoundError(
                    "The scraped data isn't saved to a file or loaded in memory."
                    "If you want to scrape the data, use `scrape_jobs` instead.")
            with open(self.save_path, 'r') as save_file:
                loaded_jobs = json.load(save_file)
                self.seen_descriptions = {job['description'] for job in loaded_jobs}
                self.pages_to_jobs['scrape'][1] = loaded_jobs
        self.seen_page = None
        return self.scrape_jobs(list(range(1, self.last_allowed_page + 1)), 'update')


def scraping_cli_entry_point() -> None:
    """The CLI entry point for scraping jobs."""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Scrape Upwork job listings for a given search query.")
    parser.add_argument(
        "action", type=str, choices=("scrape", "update"), default="scrape",
        help="Scrape new jobs, or update existing scraped data with any new job postings")
    parser.add_argument(
        "-q", '--search-query', type=str, required=True,
        help='The query to search for.')
    parser.add_argument(
        "-j", "--jobs-per-page", type=int, choices=[10, 20, 50], default=10,
        help="How many jobs should be displayed per page.")
    parser.add_argument(
        "-s", "--start-page", type=int, default=1,
        help="The page number to start searching from.")
    parser.add_argument(
        "-p", "--pages-to-scrape", type=int,
        help="How many pages to scrape. If not passed, scrape all the pages*"
             "(there's a limit, see the docs for more info).")
    parser.add_argument(
        "-o", "--output", type=str, default='',
        help="Where to save the scraped data.")
    parser.add_argument(
        "-r", "--retries", type=int, default=3,
        help="Number of retries when encountering a Captcha before failing.")
    parser.add_argument(
        "--headless", action="store_true", default=False,
        help="Whether to enable headless mode (slower and more detectable).")
    parser.add_argument(
        "-w", "--workers", type=int, default=1,
        help="How many webdriver instances to spin up for scraping.")
    parser.add_argument(
        "-f", "--fast", action="store_true", default=False,
        help="Whether to use the fast scraping method. It can be 10 to 50x faster "
             "but leaves out all client information and number of proposals.")
    args = parser.parse_args()
    action = args.action
    search_query = args.search_query
    jobs_per_page = args.jobs_per_page
    start_page = args.start_page
    pages_to_scrape = args.pages_to_scrape
    save_path = args.output
    retries = args.retries
    headless = args.headless
    workers = args.workers
    fast = args.fast
    jobs_scraper = JobsScraper(
        search_query, jobs_per_page, start_page, pages_to_scrape, save_path, retries, headless, workers, fast)
    jobs_scraper.scrape_jobs() if action == "scrape" else jobs_scraper.update_existing()


if __name__ == '__main__':
    scraping_cli_entry_point()
    # Direct usage example.
    # jobs_scraper = JobsScraper("python", 10, 1, 4, 'test.json', 3, True, 2, False)
    # jobs_scraper.scrape_jobs()
    # jobs_scraper.update_existing()
