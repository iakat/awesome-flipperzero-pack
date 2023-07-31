# awesome-flipperzero-pack gets all resources for a flipper zero,
# from https://github.com/djsime1/awesome-flipperzero
# and downloads them to create a zip file with all the resources
# for easy installation on the SD card.
# The zip file is then uploaded to the releases page of this repo.

import requests
import re
import os
import json
import tempfile
import pathlib
import subprocess
import datetime
import asyncio
import concurrent.futures
import shutil


class Main:
    def __init__(self):
        self.TMPDIR = pathlib.Path(tempfile.mkdtemp())
        self.REGEX_CATEGORY = re.compile(r"^## (.*)")
        self.REGEX_LINK = re.compile(r"^- \[(.*)\]\((.*)\)")
        self.REGEX_GITHUB_REPO = re.compile(r"^https://github.com/(.*)/(.*)$")
        self.NOW = datetime.datetime.now()
        self.VERSION = self.NOW.strftime("v0.0.%Y%m%d%H%M")
        self.SEMA = asyncio.Semaphore(30)

        self.PACKAGES = {
            "microsd": [
                "databases-dumps",
                "applications-plugins",
                "graphics-animations",
            ],
            "tweaks": [
                "firmwares-tweaks",
                "modules-cases",
                "off-device-debugging",
                "notes-references",
            ],
        }

    def _urlify(self, string):
        # this removes all non-alphanumeric characters from a string to a dash
        # and makes it lowercase
        # additionally it removes all double dashes and leading and trailing dashes
        return re.sub(
            r"-+",
            "-",
            re.sub(r"^-+|-+$", "", re.sub(r"[^a-zA-Z0-9]+", "-", string.lower())),
        )

    async def _exec_wait(self, *args, **kwargs):
        proc = await asyncio.create_subprocess_exec(
            *args,
            **kwargs,
        )
        await proc.wait()
        return proc.returncode

    def _get_awesome_list(self):
        r = requests.get(
            "https://raw.githubusercontent.com/djsime1/awesome-flipperzero/main/README.md"
        )
        # We want to parse the markdown with mistletoe,
        # then we get a list of links per category.
        # We then want to download all the links.
        # Most links are github, so we can clone the latest default branch,
        # some are some specific path of a github repo, so we can download the latest default branch and only the path.
        # Some are just a link to a zip file, or a PDF, so we can download that.

        # Let's not use a markdown parser, but just regex.

        # Get all item number, names and links per category
        categories = []
        current_category = None
        for i, line in enumerate(r.text.splitlines()):
            if category := self.REGEX_CATEGORY.match(line):
                current_category = category.group(1)
                categories.append(
                    {
                        "name": current_category,
                        "url": self._urlify(current_category),
                        "line": line,
                        "items": [],
                        "_i": str(i + 1).zfill(4),
                    }
                )
            elif link := self.REGEX_LINK.match(line):
                categories[-1]["items"].append(
                    {
                        "name": link.group(1),
                        "url": self._urlify(link.group(1)),
                        "line": line,
                        "link": link.group(2),
                        "_i": str(i + 1).zfill(4),
                    }
                )
        return categories

    async def _download_github_repo(self, url, path):
        async with self.SEMA:
            os.makedirs(path, exist_ok=True)
            proc = await asyncio.create_subprocess_exec(
                "git",
                "clone",
                "--depth",
                "1",
                url,
                str(path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            # wait until exit
            await proc.wait()
            print("downloaded", proc.returncode, url, path)
            # get the return code
            return proc.returncode

    async def _safe_download(self, package, category, item):
        # mkdir /self.TMPDIR/package/i-category/i-link
        # path = pathlib.Path(self.TMPDIR) / package / item["_i"] + "-" + item["url"]
        # not work PosixPath + str
        path = (
            pathlib.Path(self.TMPDIR)
            / package
            / (category["_i"] + "-" + category["url"])
            / (item["_i"] + "-" + item["url"])
        )
        # if the link is a github repo, clone it with depth 1
        if github := self.REGEX_GITHUB_REPO.match(item["link"]):
            res = await self._download_github_repo(item["link"], path)
            if res == 0:
                # success. downloaded.md
                with open(self.TMPDIR / package / "downloaded.md", "a") as f:
                    f.write(item["line"] + "\n")
                # remove .git
                shutil.rmtree(path / ".git")

            else:
                # failed. skipped.md
                with open(self.TMPDIR / package / "skipped.md", "a") as f:
                    f.write(item["line"] + " (failed: " + str(res) + ")\n")
                print("failed", item["link"], path, res)

    async def run(self):
        links = self._get_awesome_list()

        # now we have categories and links
        # let's create a zipfile with all the resources
        # print only categories
        items = []
        for package, categories in self.PACKAGES.items():
            for category_filter in categories:
                for category in links:
                    if category["url"] != category_filter:
                        continue
                    for item in category["items"]:
                        items.append((package, category, item))

        await asyncio.gather(*[self._safe_download(*item) for item in items])

        # zip every package
        tasks = []
        for package in self.PACKAGES.keys():
            # with lowest compression
            tasks.append(
                self._exec_wait(
                    "zip",
                    "-r",
                    "-0",
                    package + ".zip",
                    package,
                    cwd=self.TMPDIR,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            )
        await asyncio.gather(*tasks)

        for package in self.PACKAGES.keys():
            # move the file to proper awesome-flipperzero-pack release name
            new_name = self.TMPDIR / (
                "awesome-flipperzero-pack-" + self.VERSION + "-" + package + ".zip"
            )

            os.rename(
                self.TMPDIR / (package + ".zip"),
                new_name,
            )
            file_tree = subprocess.run(
                [
                    "tree",
                    "-h",
                    "--du",
                    "-L",
                    "3",
                    self.TMPDIR / package,
                ],
                capture_output=True,
                text=True,
            ).stdout
            # write it to files.txt
            with open(self.TMPDIR / package / "files.txt", "w") as f:
                f.write(file_tree)

        body = "\n".join(
            [
                f"# awesome-flipperzero-pack {self.VERSION}\n",
                "awesome-flipperzero-pack is a downloadable toolkit of [the awesome-flipperzero resources](https://github.com/djsime1/awesome-flipperzero).",
                "Two zip files are available:",
                f"- awesome-flipperzero-pack-{self.VERSION}-microsd.zip: for the microsd card (firmwares, databases, plugins, animations)",
                f"- awesome-flipperzero-pack-{self.VERSION}-tweaks.zip: for the tweaks (firmwares, modules, cases, notes)",
                "\n## microsd",
                "\n### downloaded",
                open(self.TMPDIR / "microsd" / "downloaded.md").read(),
                "\n### skipped",
                open(self.TMPDIR / "microsd" / "skipped.md").read(),
                "\n### files",
                "\n```\n",
                open(self.TMPDIR / "microsd" / "files.txt").read(),
                "\n```\n",
                "\n## tweaks",
                "\n### downloaded",
                open(self.TMPDIR / "tweaks" / "downloaded.md").read(),
                "\n### skipped",
                open(self.TMPDIR / "tweaks" / "skipped.md").read(),
                "\n### files",
                "\n```\n",
                open(self.TMPDIR / "tweaks" / "files.txt").read(),
                "\n```\n",
            ]
        )
        # write body.txt to tmpdir/body.txt
        with open(self.TMPDIR / "body.md", "w") as f:
            f.write(body)
        # move tmpdir to cwd/files
        shutil.move(self.TMPDIR, "files")


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(Main().run())
