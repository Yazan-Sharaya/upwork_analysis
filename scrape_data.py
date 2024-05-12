from datetime import datetime, timedelta
import threading
import argparse
import platform
import random
import ctypes
import json
import time

from seleniumbase.common.exceptions import NoSuchElementException as SBNoSuchElementException
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from seleniumbase.undetected import Chrome
from seleniumbase import Driver
from bs4 import BeautifulSoup
from bs4.element import Tag


job_title_selector = ".air3-line-clamp > h2 > a"  # Text could be embedded in the anchor tag or set as text attribute.
post_time_selector = ".job-tile-header div small span:nth-child(2)"
job_skills_selector = 'div[data-test="JobTileDetails"] div.air3-token-container span[data-test="token"] span'  # multi
description_selector = "div.air3-line-clamp.is-clamped > p.mb-0"
proposals_selector = 'section[data-test="ClientActivity"] > ul > li > span.value'  # When opening a specific job.

payment_details_selector = "ul.job-tile-info-list.text-base-sm.mb-4"
job_type_selector = payment_details_selector + " > li:nth-child(1)"
experience_level_selector = payment_details_selector + " > li:nth-child(2)"
time_estimate_or_budget_selector = payment_details_selector + " > li:nth-child(3) > strong:nth-child(2)"
# Could be the time estimate of an hourly job or the budget of a fixed-price job.

client_location_selector = 'ul.ac-items.list-unstyled > li > strong'  # When opening a specific job.
client_spent_selector = 'strong[data-qa="client-spend"] > span'  # When opening a specific job.

job_back_arrow_selector = 'div.air3-slider-header > button.air3-slider-prev-btn.air3-slider-close-desktop > div'


def split_list_into_chunks(lst, num_chunks) -> list[list]:
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
    chunks: list
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


def parse_job_type(job_type: str) -> str:
    """Returns 'Hourly' or 'Fixed'"""
    return job_type.split(':')[0].split()[0]


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


def parse_time_estimate(time_estimate_or_budget: str) -> str | None:
    """Returns the time estimate for hourly jobs (only the month part) or None in case of Fixed job."""
    if "$" not in time_estimate_or_budget:
        return time_estimate_or_budget.split(',')[0]  # Get just the time estimate.
    return None


def parse_budget(job_type: str, time_estimate_or_budget: str) -> int | None:
    """
    Takes the job type (hourly, fixed-price) and time estimate/budget, which might be the budget in $ for a fixed-price
    job or the estimated time of an hourly job.
    Returns the hourly rate for hourly jobs and the budget for fixed-price. Returns None if the hourly rate isn't
    specified.
    """
    job_type = job_type.lower()
    job_type = job_type.replace("$", "")
    time_estimate_or_budget = time_estimate_or_budget.replace("$", "")
    if "hourly" in job_type:
        if ":" in job_type:
            hourly_rate = job_type.split(":")[1]
            min_rate, max_rate = hourly_rate.split(' - ')
            average_rate = int((float(max_rate) + float(min_rate)) / 2)
            return average_rate
        return None
    return int(float(time_estimate_or_budget.replace(',', '')))


def parse_total_spent(total_spent: str) -> int | None:
    """Parses the total spent texts and returns the dollar number as integer."""
    total_spent = total_spent.replace('$', '')
    unit_map = {"K": 1000, "M": 1_000_000}
    for unit, value in unit_map.items():
        if unit in total_spent:
            return int(float(total_spent.replace(unit, '').strip()) * value)
    return int(total_spent)


def parse_one_job(driver: Chrome, job: Tag, index: int) -> dict:
    """
    Parses one job listing (html) and returns a dictionary containing its information. The collected infromation is:
        - Job title
        - Job description
        - Job skills
        - Job post time as a UNIX timestamp
        - Number of proposals
        - Job type (Hourly or Fixed)
        - Experience level (entry, intermediate, expert)
        - Time estimate (the estimated time the job is going to take, for example, 1-3 months for an hourly job
          or None for a fixed-price job)
        - Budget (The budget for a fixed-price job or the average hourly rate or None if it's not specified)
        - Client location
        - Client total spent (if present)

    Parameters
    ----------
    driver: Chrome
        The driver instance to use.
    job: Tag
        Beautiful soup tag containing the job html.
    index: int
        The index of the job with respect to the page.

    Returns
    -------
    job_details: dict
        The job's details.
    """
    job_type = job.select_one(job_type_selector).text.strip()
    job_details = {
        "title": job.select_one(job_title_selector).text,
        "description": job.select_one(description_selector).text,
        "time": parse_time(job.select_one(post_time_selector).text),
        "skills": [skill.text for skill in job.select(job_skills_selector)],
        "type": parse_job_type(job_type),
        "experience_level": job.select_one(experience_level_selector).text,
        "time_estimate": parse_time_estimate(job.select_one(time_estimate_or_budget_selector).text),
        "budget": parse_budget(job_type, job.select_one(time_estimate_or_budget_selector).text.strip()),
    }

    try:
        driver.execute_script("arguments[0].click();", driver.find_element(f"article:nth-child({index})"))
        # Some jobs don't display unless you are logged in, hence the try block.
        driver.wait_for_selector(client_location_selector, timeout=3)
        job_soup = BeautifulSoup(driver.page_source, "html.parser")
        job_details["client_location"] = job_soup.select_one(client_location_selector).text
        total_spent = job_soup.select_one(client_spent_selector)
        if total_spent:
            total_spent = parse_total_spent(total_spent.text)
        job_details["client_total_spent"] = total_spent
    except (SBNoSuchElementException, NoSuchElementException):
        pass
    try:
        driver.wait_for_selector(job_back_arrow_selector, timeout=3)
        driver.find_element(job_back_arrow_selector).click()
    except (SBNoSuchElementException, NoSuchElementException):
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
            workers: int = 1) -> None:
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

        self.link_get_took = 0
        # total_npages = self.get_total_number_of_result_pages()
        total_npages = 111

        # Upwork limits the number of pages the user can access, and the limit is dependent on the number of jobs per
        # page setting. Upwork won't load job listings for any page past the limit (e.g., page 102, jobs_per_page=50).
        allowed_npages = {10: 501, 20: 251, 50: 101}[jobs_per_page]
        self.last_allowed_page = min(total_npages, allowed_npages)
        assert 0 < start_page <= self.last_allowed_page, f"`start_page` must be in [1, {self.last_allowed_page}]"

        maximum_allowed_npages_to_scrape = self.last_allowed_page - self.start_page + 1
        if pages_to_scrape and pages_to_scrape > maximum_allowed_npages_to_scrape:
            raise ValueError(
                f"`pages_to_scrape` can't be larger than {maximum_allowed_npages_to_scrape}, to not go over the last "
                f"allowed page number ({self.last_allowed_page}). See the documentation for this class "
                f"for more info about the limit.")
        self.pages_to_scrape = pages_to_scrape if pages_to_scrape else maximum_allowed_npages_to_scrape

        self.jobs_details = []
        self.failed_pages = set()

        self.seen_titles = set()
        self.should_stop = False  # This is set to True when 5 or more consecutive jobs titles' exist in the list of
        # scraped job titles, meaning the following jobs most probably have been scraped.
        self.seen_page = None  # The page number where the aforementioned condition happened. Used to decide which
        # threads should be terminated.
        self.consecutive_seens = 0
        self.seen_jobs = []

        estimated_number_of_jobs = self.pages_to_scrape * self.jobs_per_page
        # Each job takes at most 3 seconds, and on at least 0.75 seconds, we just take the average of that (~1.8)
        # (workers - 1) * 60 because each new worker apart from the first waits ~7.5 extra seconds before it start.
        time_estimate = round(
            (self.link_get_took * self.pages_to_scrape +
             1.8 * estimated_number_of_jobs +
             (workers - 1) * 7.5) / 60 / workers, 1)
        print(
            f"Scraping spec\n-------------\n"
            f"search query: {self.search_query}\n"
            f"pages to scrape: {self.pages_to_scrape}\n"
            f"estimated total number of jobs: {estimated_number_of_jobs}\n"
            f"Retries when detected: {retries}\n"
            f"Number of workers: {self.workers}\n"
            f"ETA: {time_estimate:,} minutes\n"
            f"{f'Saving to {self.save_path}' if self.save_path else 'Not saving the results'}")

    def create_driver(self) -> Chrome:
        """Create selenium base undetected chrome driver instance."""
        return Driver("chrome", headless=self.headless, uc=True)

    def get_url(self, driver: Chrome,  page_number: int) -> None:
        """
        Loads the `page_number`th result page for the given `search_query` and `jobs_per_page`, then sleeps for a random
        amount of time between 0.5 and 3 seconds after the page loads.

        Parameters
        ----------
        driver: Chrome
            The webdriver instance to use.
        page_number: int
            The page number to get.
        """
        driver.get(construct_url(self.search_query, self.jobs_per_page, page_number))

    def get_total_number_of_result_pages(self) -> int:
        """Gets the total number of result pages for a certain `search_query` and `jobs_per_page`."""
        driver = self.create_driver()
        time_print("Getting the total number of result pages.")
        t = time.time()
        try:
            self.get_url(driver, 1)
        except TimeoutException:
            driver.quit()
            raise ConnectionError(f"Timed out while getting the total number of result pages.")
        self.link_get_took = time.time() - t
        soup = BeautifulSoup(driver.page_source, "html.parser")
        n_pages = soup.select_one('li[data-test="pagination-mobile"].air3-pagination-mobile').text
        driver.quit()

        if not n_pages:
            if self.headless:
                time_print(
                    "Encountered a captcha, terminating the current session and trying normal browser(headless=False).")
                self.headless = False
                return self.get_total_number_of_result_pages()
            else:
                raise NoSuchElementException(
                    "Encountered a captcha, this could mean that your IP reputation is low, try again or add a proxy.")

        return int(n_pages.split()[-1].replace(",", ""))

    def scrape_pages(self, page_numbers: list | set | None = None) -> None:
        """
        Scrapes all the page numbers contained in `page_number` for their job listings details.

        Notes
        -----
        - On Windows, this method prevents the computer from sleeping (but allows the screen to turn off) during
          the scraping process. The reason for this is that when Windows sleeps, the connection to the webdriver
          is severed, and it can't continue running when the PC wakes up resulting in an error.
        - The scraped data is available through `jobs_details` attribute.
        - `scrape_jobs` method should be used instead of this because it offers saving and multi-threading
          functionality. This method is intended for internal use, but can still be used by user code.

        Parameters
        ----------
        page_numbers: list, optional
            A list containing the page numbers to scrape. If None, scrape all the pages from `start_page` to
            `pages_to_scrape`. Default None

        See Also
        --------
        scrape_jobs: The preferred method to call.
        """
        driver = self.create_driver()
        for page in page_numbers or list(range(self.start_page, self.start_page + self.pages_to_scrape)):
            if self.seen_page and page > self.seen_page:
                break
            inhibit_sleep(True)
            # The following code is to achieve retrying functionality, see https://stackoverflow.com/a/7663441/23524006
            for retry in range(self.retries):
                try:
                    time_print(
                        f"Scraping page {page} of {self.start_page + self.pages_to_scrape - 1} "
                        f"(try {retry+1}/{self.retries}).")
                    self.get_url(driver, page)
                    driver.find_element("css selector", "article")
                except NoSuchElementException:
                    time_print(f"Encountered a Captcha scraping page {page}, trying again.")
                    sleep(5, 15)
                except TimeoutException:
                    time_print(f"Timed out waiting for page {page} to load. trying again.")
                    sleep(15, 30)
                else:
                    break
            else:
                self.failed_pages.add(page)
                continue

            if page in self.failed_pages:
                self.failed_pages.remove(page)

            soup = BeautifulSoup(driver.page_source, "html.parser")
            jobs = soup.find_all('article')
            for i, job in enumerate(jobs):
                try:
                    # self.jobs_details.append(parse_one_job(driver, job, i + 1))
                    job = parse_one_job(driver, job, i + 1)
                    if job['title'] in self.seen_titles:
                        self.consecutive_seens += 1
                        self.seen_jobs.append(job)
                    else:
                        for seen_job in self.seen_jobs:
                            self.jobs_details.append(seen_job)
                        self.jobs_details.append(job)
                        self.seen_jobs = []
                        self.consecutive_seens = 0
                    self.seen_titles.add(job['title'])
                    if self.consecutive_seens >= 5:
                        self.seen_page = page
                        break
                except Exception as e:  # noqa
                    # Most exceptions are caught in `parse_one_job`, but every so often an uncounted for exception is
                    # raised, they are caught here to not terminate the whole session if just 1 job couldn't be scraped.
                    pass
        inhibit_sleep(False)
        driver.quit()

    def scrape_jobs(self, page_numbers=None, save=True) -> list[dict]:
        """
        Scrapes `pages_to_scrape` number of pages for their job listings starting at `start_page`. The following
        information is collected about each job listing:
            - Job title
            - Job description
            - Job skills
            - Job post time as a UNIX timestamp
            - Number of proposals
            - Job type (Hourly or Fixed)
            - Experience level (entry, intermediate, expert)
            - Time estimate (the estimated time the job is going to take, for example, 1-3 months for an hourly job
              or None for a fixed-price job)
            - Budget (The budget for a fixed-price job or the average hourly rate or None if it's not specified)
            - Client location
            - Client total spent (if present)

        Notes
        -----
        - On Windows, this method prevents the computer from sleeping (but allows the screen to turn off) during
          the scraping process. The reason for this is that when Windows sleeps, the connection to the webdriver
          is severed, and it can't continue running when the PC wakes up resulting in an error.

        Returns
        -------
        jobs_details: list[dict]
            A list of dictionaries containing information about the jobs.
        """
        if page_numbers is None:
            page_numbers = list(range(self.start_page, self.start_page + self.pages_to_scrape))
        workers = []
        for page_numbers_chunk in split_list_into_chunks(page_numbers, self.workers):
            worker = threading.Thread(target=self.scrape_pages, args=(page_numbers_chunk,))
            worker.start()
            workers.append(worker)
            sleep(5, 10)
        for worker in workers:
            worker.join()

        if self.failed_pages:
            time_print("Waiting 30 to 60 seconds before trying to scrape the failed pages...")
            sleep(30, 60)
            self.scrape_pages(self.failed_pages)
            if self.failed_pages:
                time_print(f"Failed to scrape the following pages: {self.failed_pages}.")

        time_print(f"Scraped {len(self.jobs_details)} jobs.")
        if self.save_path and save:
            with open(self.save_path, 'w') as save_file:
                json.dump(self.jobs_details, save_file)
        time_print(f"Saved the scraped data to {self.save_path}.")

        return self.jobs_details[::]

    def update_existing(self) -> None:
        """Updates the existing scraped data with any new job listings."""
        if not self.jobs_details:
            if not self.save_path:
                raise FileNotFoundError(
                    "The scraped data file was not found and the data isn't in memory."
                    "If you want to scrape new data call `scrape_jobs` instead.")
            with open(self.save_path, 'r') as save_file:
                try:
                    self.jobs_details = json.load(save_file)
                    self.seen_titles = {j['title'] for j in self.jobs_details}
                    self.consecutive_seens = 0
                    self.seen_jobs = []
                    self.seen_page = None
                except json.JSONDecodeError as e:
                    raise RuntimeError(f"The file at {self.save_path} is not a valid JSON file.") from e
        page_numbers = list(range(1, self.last_allowed_page + 1))
        print(split_list_into_chunks(page_numbers, 1))
        quit()
        existing_data = self.jobs_details[::]
        self.jobs_details = []
        self.scrape_jobs(page_numbers, False)
        self.jobs_details.extend(existing_data)
        self.scrape_jobs([], True)  # Just to save.


def scraping_cli_entry_point():
    """The CLI entry point for scraping jobs."""
    parser = argparse.ArgumentParser(
        description='Scrape Upwork job listings for a given search query.')
    parser.add_argument(
        "-q", '--search-query', help='The query to search for.', required=True)
    parser.add_argument(
        "-j", "--jobs-per-page", type=int,
        help="How many jobs should be displayed per page.", choices=[10, 20, 50], default=10)
    parser.add_argument(
        "-s", "--start-page", type=int, help="The page number to start searching from.", default=1)
    parser.add_argument(
        "-p", "--pages-to-scrape", type=int, help="How many pages to scrape. If not specified, scrape all the pages.")
    parser.add_argument(
        "-o", "--output", help="Where to save the scraped data.", default='')
    parser.add_argument(
        "-r", "--retries", type=int, help="Number of retries when encountering a Captcha before failing.", default=3)
    parser.add_argument(
        "--headless", action="store_true", help="Whether to enable headless mode (slower and more detectable).")
    parser.add_argument(
        "-w", "--workers", type=int, help="How many webdriver instances to spin up for scraping.", default=1)
    args = parser.parse_args()
    search_query = args.search_query
    jobs_per_page = args.jobs_per_page
    start_page = args.start_page
    pages_to_scrape = args.pages_to_scrape
    save_path = args.output
    retries = args.retries
    headless = args.headless
    workers = args.workers
    JobsScraper(
        search_query, jobs_per_page, start_page, pages_to_scrape, save_path, retries, headless, workers).scrape_jobs()


if __name__ == '__main__':
    # scraping_cli_entry_point()
    jobs_scraper = JobsScraper("python", 10, 1, 1, 'python_jobs.json', 3, True, 1)
    # jobs_scraper.scrape_jobs()
    jobs_scraper.update_existing()
