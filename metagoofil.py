#!/usr/bin/env python

# Standard Python libraries.
import argparse
import os
import queue
import random
import sys
import threading
import time
import urllib

# Third party Python libraries.
# google == 2.0.1, module author changed import name to googlesearch
# https://github.com/MarioVilas/googlesearch/commit/92309f4f23a6334a83c045f7c51f87b904e7d61d
import googlesearch
import requests

# https://stackoverflow.com/questions/27981545/suppress-insecurerequestwarning-unverified-https-request-is-being-made-in-pytho
from requests.packages.urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

__version__ = "1.1.0"


class DownloadWorker(threading.Thread):

    mg = None

    def __init__(self,mg):
        threading.Thread.__init__(self)
        self.mg = mg

    def run(self):
        while True:
            # Grab URL off the queue.
            url = self.mg.queue.get()

            try:
                headers = {}

                # Assign a User-Agent for each file request.
                # No -u
                if self.mg.user_agent == "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)":
                    headers["User-Agent"] = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
                # -u
                elif self.mg.user_agent is None:
                    user_agent_choice = random.choice(self.mg.random_user_agents).strip()
                    headers["User-Agent"] = f"{user_agent_choice}"
                # -u "My custom user agent 2.0"
                else:
                    headers["User-Agent"] = self.mg.user_agent

                response = requests.get(url, headers=headers, verify=False, timeout=self.mg.url_timeout, stream=True)

                # Download the file.
                if response.status_code == 200:
                    try:
                        size = int(response.headers["Content-Length"])

                    except KeyError as e:
                        print(
                            f"[-] Exception for url: {url} -- {e} does not exist.  Extracting file size from "
                            "response.content length."
                        )
                        size = len(response.content)

                    self.mg.total_bytes += size

                    # Strip any trailing /'s before extracting file name.
                    url_file_name = str(url.strip("/").split("/")[-1])

                    # Decode URL file name if it's encoded.  No harm calling urllib.parse.unquote() if the URL file
                    # name isn't URL encoded.
                    filename = urllib.parse.unquote(url_file_name, encoding="utf-8")

                    print(f'[+] Downloading "{filename}" [{size} bytes] from: {url}')

                    with open(os.path.join(self.mg.save_directory, filename), "wb") as fh:
                        for chunk in response.iter_content(chunk_size=1024):
                            if chunk:  # Filter out keep-alive new chunks.
                                fh.write(chunk)

                else:
                    print(f"[-] URL {url} returned HTTP code {response.status_code}")

            except requests.exceptions.RequestException as e:
                print(f"[-] Exception for url: {url} -- {e}")

            self.mg.queue.task_done()


class Metagoofil:
    """The Metagoofil Class"""

    def __init__(
        self,
        domain,
        delay,
        save_links,
        url_timeout,
        search_max,
        download_file_limit,
        save_directory,
        number_of_threads,
        file_types,
        user_agent,
        download_files,
    ):
        self.domain = domain
        self.delay = delay
        self.save_links = open(save_links, "a") if save_links else None
        self.url_timeout = url_timeout
        self.search_max = search_max
        self.download_file_limit = download_file_limit
        self.save_directory = save_directory

        # Create queue and specify the number of worker threads.
        self.queue = queue.Queue()
        self.number_of_threads = number_of_threads

        self.file_types = file_types

        self.user_agent = user_agent
        # Populate a list of random User-Agents.
        if self.user_agent is None:
            with open("user_agents.txt") as fp:
                self.random_user_agents = fp.readlines()

        self.download_files = download_files
        self.total_bytes = 0

    def go(self):
        # Kickoff the threadpool.
        for i in range(self.number_of_threads):
            thread = DownloadWorker(self)
            thread.daemon = True
            thread.start()

        if "ALL" in self.file_types:
            from itertools import product
            from string import ascii_lowercase

            # Generate all three letter combinations.
            self.file_types = ["".join(i) for i in product(ascii_lowercase, repeat=3)]

        for filetype in self.file_types:
            # Stores URLs with files, clear out for each filetype.
            self.files = []

            # Search for the files to download.
            print(
                f"[*] Searching for {self.search_max} .{filetype} files and waiting {self.delay} seconds between searches"
            )
            query = f"filetype:{filetype} site:{self.domain}"

            try:
                for url in googlesearch.search(
                    query,
                    start=0,
                    stop=self.search_max,
                    num=100,
                    pause=self.delay,
                    extra_params={"filter": "0"},
                    user_agent=self.user_agent,
                ):
                    self.files.append(url)

            except Exception as e:
                print(f"[-] EXCEPTION: {e}")
                if e.code == 429:
                    print(
                        "[*] Google is blocking you for making too many requests.  You will need to spread out the "
                        "Google searches with metagoofil's switches or utilize SSH and dynamic SOCKS proxies.  Don't "
                        "know how to utilize SSH and dynamic SOCKS proxies?  Do yourself a favor and pick up a copy of "
                        "The Cyber Plumber's Handbook and interactive lab (https://gumroad.com/l/cph_book_and_lab) to "
                        "learn all about Secure Shell (SSH) tunneling, port redirection, and bending traffic like a "
                        "boss."
                    )
                    print("[*] Exiting for now...")
                    sys.exit(1)

            # Since googlesearch.search method retrieves URLs in batches of 100, ensure the file list only contains the
            # requested amount.
            if len(self.files) > self.search_max:
                self.files = self.files[: -(len(self.files) - self.search_max)]

            # Download files if specified with -w switch.
            if self.download_files:
                self.download()

            # Otherwise, just display them.
            else:
                print(f"[*] Results: {len(self.files)} .{filetype} files found")
                for file_name in self.files:
                    print(file_name)

            # Save links to output to file.
            if self.save_links:
                for f in self.files:
                    self.save_links.write(f"{f}\n")

        if self.save_links:
            self.save_links.close()

        if self.download_files:
            print(
                "[+] Total download: {} bytes / {:.2f} KB / {:.2f} MB".format(
                    self.total_bytes, self.total_bytes / 1024, self.total_bytes / (1024 * 1024)
                )
            )

    def download(self):
        self.counter = 1
        for url in self.files:
            if self.counter <= self.download_file_limit:
                self.queue.put(url)
                self.counter += 1

        self.queue.join()


def get_timestamp():
    now = time.localtime()
    timestamp = time.strftime("%Y%m%d_%H%M%S", now)
    return timestamp


def csv_list(string):
    return string.split(",")


# http://stackoverflow.com/questions/3853722/python-argparse-how-to-insert-newline-in-the-help-text
class SmartFormatter(argparse.HelpFormatter):
    def _split_lines(self, text, width):
        if text.startswith("R|"):
            return text[2:].splitlines()
        # This is the RawTextHelpFormatter._split_lines
        return argparse.HelpFormatter._split_lines(self, text, width)


def positive_int(value):
    try:
        value_int = type(value)
        assert value_int >= 0
        return value_int
    except (AssertionError, ValueError):
        raise argparse.ArgumentTypeError(f"invalid value '{value}', must be an int >= 0")


def positive_float(value):
    try:
        value_float = type(value)
        assert value_float >= 0
        return value_float
    except (AssertionError, ValueError):
        raise argparse.ArgumentTypeError(f"invalid value '{value}', must be a float >= 0")
