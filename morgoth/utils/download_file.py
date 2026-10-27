import os
import shutil
import time
import time
from pathlib import Path

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError

import astropy.utils.data as astro_data

import morgoth.utils.file_utils as file_utils


def download_file(url, path="/tmp"):
    """
    Download a file to the given path
    """

    fname = url.split("/")[-1]
    f = astro_data.download_file(url)

    return f


class BackgroundDownload(object):
    def __init__(
        self,
        url,
        store_path=None,
        wait_time=60,
        max_time=60 * 60,
    ):
        """
        An worker to download objects in the background to avoid blocking the GCN
        listen function.

        If a bot is specfied, it will upload an the image with the bot.


        :param url: The URL to download the file
        :param bot: the optional bot
        :param description: the description for the bot's plot
        :param wait_time: the wait time interval for checking files
        :param max_time: the max time to wait for files
        :returns:
        :rtype:

        """

        self._wait_time = wait_time
        self._max_time = max_time

        self._url = url
        self._store_file = True

        # get the file name  at the end
        self._file_name = url.split("/")[-1]

        self._store_path = store_path

    def run(self):

        # set a flag to kill the job

        flag = True

        # the time spent waiting so far
        time_spent = 0  # seconds

        while flag:

            # try to download the file
            try:

                path = download_file(self._url)

                # create the directory

                file_utils.if_directory_not_existing_then_make(self._store_path)

                # move the file

                shutil.move(path, os.path.join(self._store_path, self._file_name))

                # kill the loop

                flag = False

            except:

                # ok, we have not found a file yet

                # see if we should still wait for the file

                if time_spent >= self._max_time:

                    # we are out of time so give up

                    break

                else:

                    # ok, let's sleep for a bit and then check again

                    time.sleep(self._wait_time)

                    # up date the time we have left

                    time_spent += self._wait_time

        if flag:
            raise AssertionError(
                f"File not found in {self._max_time} seconds. Maybe try a newer version?"
            )

        return path


class BackgroundDownloadAWS:
    def __init__(
        self,
        key: str,
        store_path: str | Path,
        wait_time: float = 30.0,
        max_time: float = 600.0,
        bucket: str = "nasa-heasarc",
    ):
        """
        Download one specific file from a public S3 bucket.

        Parameters
        ----------
        key : str
            Full S3 object key, for example:
            "fermi/data/gbm/triggers/2025/bn250101395/file.fit"

        local_dir : str
            Local directory created below store_path.

        store_path : str | Path
            Base path where the file should be stored.

        wait_time : float
            Seconds to wait between retries if the file is not available.

        max_time : float
            Maximum total number of seconds to wait.

        bucket : str
            S3 bucket name.
        """
        self.bucket = bucket
        self.key = key.lstrip("/")

        self.store_path = Path(store_path)
        self.local_dir = self.store_path

        self.wait_time = wait_time
        self.max_time = max_time

        self.s3 = boto3.client(
            "s3",
            config=Config(signature_version=UNSIGNED),
        )

    @property
    def destination(self) -> Path:
        """Local path of the downloaded file."""
        return self.local_dir / Path(self.key).name

    def _file_exists(self) -> bool:
        """Check whether the object exists in S3."""
        try:
            self.s3.head_object(
                Bucket=self.bucket,
                Key=self.key,
            )
            return True

        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")

            if error_code in {"404", "NoSuchKey", "NotFound"}:
                return False

            raise

    def _wait_for_file(self) -> None:
        """Wait until the file becomes available or max_time is exceeded."""
        start_time = time.monotonic()

        while True:
            try:
                if self._file_exists():
                    return

            except BotoCoreError as exc:
                print(f"S3 request failed: {exc}")

            elapsed = time.monotonic() - start_time

            if elapsed >= self.max_time:
                raise TimeoutError(
                    f"File did not become available within "
                    f"{self.max_time:.0f} seconds: "
                    f"s3://{self.bucket}/{self.key}"
                )

            remaining = self.max_time - elapsed
            sleep_time = min(self.wait_time, remaining)

            print(
                f"File not available yet: "
                f"s3://{self.bucket}/{self.key}. "
                f"Retrying in {sleep_time:.0f} seconds..."
            )

            time.sleep(sleep_time)

    def run(self) -> Path:
        """Wait for the file and download it."""
        self.local_dir.mkdir(parents=True, exist_ok=True)

        self._wait_for_file()

        destination = self.destination

        print(f"Downloading " f"s3://{self.bucket}/{self.key} " f"-> {destination}")

        self.s3.download_file(
            self.bucket,
            self.key,
            str(destination),
        )

        return destination
