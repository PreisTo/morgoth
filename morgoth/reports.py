import luigi
import os

from morgoth.utils.env import get_env_value
from morgoth.upload import UploadReport, UploadAllPlots, UploadAllDataFiles
from morgoth.downloaders import GatherTrigdatDownload

base_dir = get_env_value("GBM_TRIGGER_DATA_DIR")


class CreateAllPages(luigi.WrapperTask):
    resources = {"max_workers": 1}
    grb_name = luigi.Parameter()

    def requires(self):
        return {
            "tte_v00": CreateReportTTE(grb_name=self.grb_name),
            "trigdat_v00": CreateReportTrigdat(grb_name=self.grb_name, version="v00"),
            "trigdat_v01": CreateReportTrigdat(grb_name=self.grb_name, version="v01"),
            "trigdat_v02": CreateReportTrigdat(grb_name=self.grb_name, version="v02"),
        }


class CreateReportTTE(luigi.Task):
    resources = {"max_workers": 1}
    grb_name = luigi.Parameter()
    version = luigi.Parameter(default="v00")

    def requires(self):
        return {
            "trigdat_complete": FinishedTrigdat(grb_name=self.grb_name),
            "report": UploadReport(
                grb_name=self.grb_name, report_type="tte", version=self.version
            ),
            "upload_all_plots": UploadAllPlots(
                grb_name=self.grb_name, report_type="tte", version=self.version
            ),
            "upload_all_data_files": UploadAllDataFiles(
                grb_name=self.grb_name, report_type="tte", version=self.version
            ),
        }

    def output(self):
        filename = f"tte_{self.version}_report_done.txt"
        return luigi.LocalTarget(os.path.join(base_dir, self.grb_name, filename))

    def run(self):
        os.system(f"touch {self.output().path}")


class CreateReportTrigdat(luigi.Task):
    resources = {"max_workers": 1}
    grb_name = luigi.Parameter()
    version = luigi.Parameter(default="v00")
    if version == "v00":
        priority = 100
    else:
        priority = 50

    def requires(self):
        return {
            "report": UploadReport(
                grb_name=self.grb_name, report_type="trigdat", version=self.version
            ),
            "upload_all_plots": UploadAllPlots(
                grb_name=self.grb_name, report_type="trigdat", version=self.version
            ),
            "upload_all_data_files": UploadAllDataFiles(
                grb_name=self.grb_name, report_type="trigdat", version=self.version
            ),
        }

    def output(self):
        filename = f"trigdat_{self.version}_report_done.txt"
        return luigi.LocalTarget(os.path.join(base_dir, self.grb_name, filename))

    def run(self):
        os.system(f"touch {self.output().path}")


class FinishedTrigdat(luigi.Task):
    resources = {"max_worker": 1}
    priority = -100
    grb_name = luigi.Parameter()

    def requires(self):
        return {"gather_trigdat": GatherTrigdatDownload(grb_name=self.grb_name)}

    def output(self):
        filename = "start_tte.txt"
        return os.path.join(base_dir, self.grb_name, filename)

    def run(self):
        flag = True
        while flag:
            for v in ["v00", "v01", "v02"]:
                filename = f"trigdat_{v}_report_done.txt"
                if os.path.exists(os.path.join(base_dir, self.grb_name, filename)):
                    flag = False
                    break
        os.system(f"touch {self.output().path}")
