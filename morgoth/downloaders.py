import os
import time

import luigi
import yaml

import urllib.request
from urllib.error import HTTPError

from morgoth.configuration import morgoth_config
from morgoth.trigger import GBMTriggerFile, OpenGBMFile
from morgoth.utils import file_utils
from morgoth.utils.download_file import BackgroundDownload
from morgoth.utils.env import get_env_value

base_dir = get_env_value("GBM_TRIGGER_DATA_DIR")
lu = [
    "n0",
    "n1",
    "n2",
    "n3",
    "n4",
    "n5",
    "n6",
    "n7",
    "n8",
    "n9",
    "na",
    "nb",
    "b0",
    "b1",
]


class GatherTrigdatDownload(luigi.Task):
    priority = 50
    resources = {"max_workers": 1}
    grb_name = luigi.Parameter()

    def requires(self):
        return OpenGBMFile(grb=self.grb_name)

    def output(self):
        return luigi.LocalTarget(
            os.path.join(base_dir, self.grb_name, f"gather_trigdat_complete.yml")
        )

    def run(self):
        # the time spent waiting so far
        time_spent = 0  # seconds

        while True:
            if DownloadTrigdat(grb_name=self.grb_name, version="v00").complete():
                version = "v00"
                break

            if DownloadTrigdat(grb_name=self.grb_name, version="v01").complete():
                version = "v01"
                break

            if DownloadTrigdat(grb_name=self.grb_name, version="v02").complete():
                version = "v02"
                break

            time.sleep(2)

            # up date the time we have left
            time_spent += 2

        print(f"The total waiting time was: {time_spent}")

        version_dict = {"trigdat_version": version}

        with self.output().open("w") as f:
            yaml.dump(version_dict, f, Dumper=yaml.SafeDumper, default_flow_style=False)


class DownloadTrigdat(luigi.Task):
    """
    Downloads a Trigdat file of a given
    version
    """

    resources = {"max_workers": 1}
    priority = 100
    grb_name = luigi.Parameter()
    version = luigi.Parameter()

    def requires(self):
        return OpenGBMFile(grb=self.grb_name)

    def output(self):
        trigdat = f"glg_trigdat_all_bn{self.grb_name[3:]}_{self.version}.fit"
        return luigi.LocalTarget(
            os.path.join(base_dir, self.grb_name, "trigdat", trigdat)
        )

    def run(self):
        # get the info from the stored yaml file
        info = GBMTriggerFile.from_file(self.input())

        # parse the trigdat
        trigdat = f"glg_trigdat_all_bn{self.grb_name[3:]}_{self.version}.fit"

        uri = os.path.join(info.uri, trigdat)

        store_path = os.path.join(base_dir, info.name, "trigdat")
        dl = BackgroundDownload(
            uri,
            store_path,
            wait_time=float(
                morgoth_config["download"]["trigdat"][self.version]["interval"]
            ),
            max_time=float(
                morgoth_config["download"]["trigdat"][self.version]["max_time"]
            ),
        )
        dl.run()

        # Create the version subfolder when download is done
        file_utils.if_directory_not_existing_then_make(
            os.path.join(base_dir, info.name, "trigdat", self.version)
        )


class DownloadTTEFile(luigi.Task):
    resources = {"max_workers": 1}
    priority = -100
    grb_name = luigi.Parameter()
    version = luigi.Parameter(default="v00")
    detector = luigi.Parameter()

    def requires(self):
        return {
            "gbm_file": OpenGBMFile(grb=self.grb_name),
            "tte_files_avail": DownloadTTEResources(grb_name=self.grb_name),
        }

    def output(self):
        tte = f"glg_tte_{self.detector}_bn{self.grb_name[3:]}_{self.version}.fit"
        return luigi.LocalTarget(
            os.path.join(base_dir, self.grb_name, "tte", "data", tte)
        )

    def run(self):
        info = GBMTriggerFile.from_file(self.input()["gbm_file"])

        print(info)

        tte = f"glg_tte_{self.detector}_bn{self.grb_name[3:]}_{self.version}.fit"
        uri = os.path.join(info.uri, tte)
        print(uri)

        store_path = os.path.join(base_dir, info.name, "tte", "data")
        dl = BackgroundDownload(
            uri,
            store_path,
            wait_time=float(
                morgoth_config["download"]["tte"][self.version]["interval"]
            ),
            max_time=float(morgoth_config["download"]["tte"][self.version]["max_time"]),
        )
        dl.run()

        # Create the version subfolder when download is done
        file_utils.if_directory_not_existing_then_make(
            os.path.join(base_dir, info.name, "tte", self.version)
        )


class DownloadCSPECFile(luigi.Task):
    resources = {"max_workers": 1}
    priority = -100
    grb_name = luigi.Parameter()
    version = luigi.Parameter(default="v01")
    detector = luigi.Parameter()

    def requires(self):
        return {
            "gbm_file": OpenGBMFile(grb=self.grb_name),
            "tte_files_avail": DownloadTTEResources(grb_name=self.grb_name),
        }

    def output(self):
        cspec = f"glg_cspec_{self.detector}_bn{self.grb_name[3:]}_{self.version}.pha"
        return luigi.LocalTarget(
            os.path.join(base_dir, self.grb_name, "tte", "data", cspec)
        )

    def run(self):
        info = GBMTriggerFile.from_file(self.input()["gbm_file"])


        cspec = f"glg_cspec_{self.detector}_bn{self.grb_name[3:]}_{self.version}.pha"

        uri = os.path.join(info.uri, cspec)
        print(uri)

        store_path = os.path.join(base_dir, info.name, "tte", "data")
        dl = BackgroundDownload(
            uri,
            store_path,
            wait_time=float(
                morgoth_config["download"]["cspec"][self.version]["interval"]
            ),
            max_time=float(
                morgoth_config["download"]["cspec"][self.version]["max_time"]
            ),
        )
        dl.run()


class DownloadTTEResources(luigi.Task):
    resources = {"max_workers": 1}
    priority = 100
    grb_name = luigi.Parameter()

    def requires(self):
        return OpenGBMFile(grb=self.grb_name)

    def output(self):
        return luigi.LocalTarget(
            os.path.join(base_dir, self.grb_name, "tte_cspec_avail.txt")
        )

    def run(self):
        base_url = f"https://heasarc.gsfc.nasa.gov/FTP/fermi/data/gbm/triggers/20{self.grb_name.strip('GRB')[:2]}/bn{self.grb_name.strip('GRB')}/current/"
        found_tte = []
        found_cspec = []
        start = time.time()
        while len(found_tte) < len(lu) and len(found_cspec) <len(lu):
            found_one = False
            for d in lu:
                if d not in found_tte:
                    url = (
                        base_url + f"glg_tte_{d}_bn{self.grb_name.strip('GRB')}_v00.fit"
                    )
                    try:
                        urllib.request.urlopen(url)
                        found_tte.append(d)
                        found_one = True
                    except HTTPError:
                        pass
                if d not in found_cspec:
                    url = (
                        base_url
                        + f"glg_cspec_{d}_bn{self.grb_name.strip('GRB')}_v00.pha"
                    )
                    try:
                        urllib.request.urlopen(url)
                        found_cspec.append(d)
                        found_one = True
                    except HTTPError:
                        pass
            if not found_one:
                time.sleep(180)
        with self.output().open("w") as f:
            f.write(str(time.time() - start))
