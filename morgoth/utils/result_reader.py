from datetime import datetime
import pytz
import urllib

import astropy.io.fits as fits
import astropy.time as astro_time
import numpy as np
import yaml
from chainconsumer import ChainConsumer
from astropy.coordinates import Angle
from astropy.coordinates import SkyCoord

from morgoth.exceptions.custom_exceptions import *
from morgoth.utils.env import get_env_value

from morgoth.utils.swift_check import check_swift

from gbmgeometry.gbm_frame import GBMFrame
from astropy.coordinates import SkyCoord
import astropy.units as unit

from astropy.table import Table
from astropy.coordinates import Angle
import pandas as pd
import os, ssl
import requests

from gbmgeometry import *


base_dir = get_env_value("GBM_TRIGGER_DATA_DIR")


class ResultReader(object):
    def __init__(
        self,
        grb_name,
        report_type,
        version,
        trigger_file,
        time_selection_file,
        background_file,
        post_equal_weights_file,
        result_file,
        trigdat_file,
    ):
        self.grb_name = grb_name
        self.report_type = report_type
        self.version = version

        self._K = None
        self._K_err = None
        self._index = None
        self._index_err = None
        self._xc = None
        self._xc_err = None
        self._alpha = None
        self._alpha_err = None
        self._xp = None
        self._xp_err = None
        self._beta = None
        self._beta_err = None

        # sun separation
        self._sun_sep_center = None
        self._sun_sep_error = None

        # read trigger output
        self._read_trigger(trigger_file)

        # read time selection values
        self._read_time_selection(time_selection_file)

        # read background file
        self._read_background_fit(background_file)

        # read parameter values
        self._read_fit_result(result_file)

        # read parameter values
        self._read_post_equal_weights_file(post_equal_weights_file)

        # Read trigdat file
        self._read_trigdat_file(trigdat_file)

        # Check the GCN Archive for the GRB letter
        try:
            self._grb_name_gcn = check_letter(
                trigger_number=self._trigger_number, grb_name=self.grb_name
            )
        except Exception as e:
            print(e)
            self._grb_name_gcn = "???"

        # Check catalog of bright gamma sources and get separation to GRB position
        self._sep_bright_sources()

        # Check catalog of SGRs and get separation to GRB position
        self._sep_SGRs()

        # Create a report containing all the results of the pipeline
        self._build_report()

    def _read_trigdat_file(self, trigdat_file):
        """
        Read trigdat file for sc_pos and quats, needed to calculate GRB position in sat frame
        :param trigdat_file: Path to trigdat data file
        :return:
        """
        ra_center = self._ra * np.pi / 180
        dec_center = self._dec * np.pi / 180
        if ra_center > np.pi:
            ra_center = ra_center - 2 * np.pi

        if type(trigdat_file) == str:
            with fits.open(trigdat_file) as f:
                quat = f["TRIGRATE"].data["SCATTITD"][0]
                sc_pos = f["TRIGRATE"].data["EIC"][0]
                times = f["TRIGRATE"].data["TIME"][0]

                data_timestamp_goddard = f["PRIMARY"].header["DATE"] + ".000Z"
        else:
            with fits.open(trigdat_file.path) as f:
                quat = f["TRIGRATE"].data["SCATTITD"][0]
                sc_pos = f["TRIGRATE"].data["EIC"][0]
                times = f["TRIGRATE"].data["TIME"][0]

                data_timestamp_goddard = f["PRIMARY"].header["DATE"] + ".000Z"

        datetime_ob_goddard = pytz.timezone("US/Eastern").localize(
            datetime.strptime(data_timestamp_goddard, "%Y-%m-%dT%H:%M:%S.%fZ")
        )

        # datetime_ob_utc = datetime_ob_goddard.astimezone(pytz.timezone("UTC"))

        # self._data_timestamp = datetime_ob_utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        self._data_timestamp = datetime_ob_goddard.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        loc_icrs = SkyCoord(
            ra=ra_center * 180 / np.pi,
            dec=dec_center * 180 / np.pi,
            unit="deg",
            frame="icrs",
        )

        q1, q2, q3, q4 = quat
        scx, scy, scz = sc_pos

        loc_sat = loc_icrs.transform_to(
            GBMFrame(
                quaternion_1=q1,
                quaternion_2=q2,
                quaternion_3=q3,
                quaternion_4=q4,
                sc_pos_X=scx,
                sc_pos_Y=scy,
                sc_pos_Z=scz,
            )
        )

        phi_sat = Angle(loc_sat.lon.deg * unit.degree)
        theta_sat = Angle(loc_sat.lat.deg * unit.degree)
        phi_sat.wrap_at("180d", inplace=True)

        self._phi_sat = phi_sat.value
        self._theta_sat = theta_sat.value

        # calculating sun separation from center
        grb_center = SkyCoord(ra=self._ra, dec=self._dec, unit="deg", frame="icrs")
        sun = gbm_detector_list["n0"](
            quaternion=quat,
            sc_pos=sc_pos,
            time=astro_time.Time(GBMTime.from_MET(times).time.fits),
        ).sun_position_icrs
        self._sun_sep_center = sun.separation(grb_center).deg

        # check if sun is within error of localization
        ra_distance = self._ra - sun.ra.deg
        dec_distance = self._dec - sun.dec.deg
        if (
            np.abs(ra_distance) <= self._ra_err
            and np.abs(dec_distance) <= self._dec_err
        ):
            self._sun_sep_error = True
        else:
            self._sun_sep_error = False

    def _read_fit_result(self, result_file):
        with fits.open(result_file) as f:
            values = f["ANALYSIS_RESULTS"].data["VALUE"]
            pos_error = f["ANALYSIS_RESULTS"].data["POSITIVE_ERROR"]
            neg_error = f["ANALYSIS_RESULTS"].data["NEGATIVE_ERROR"]

        self._ra = values[0]
        self._ra_pos_err = pos_error[0]
        self._ra_neg_err = neg_error[0]

        if np.absolute(self._ra_pos_err) > np.absolute(self._ra_neg_err):
            self._ra_err = np.absolute(self._ra_pos_err)
        else:
            self._ra_err = np.absolute(self._ra_neg_err)

        self._dec = values[1]
        self._dec_pos_err = pos_error[1]
        self._dec_neg_err = neg_error[1]

        if np.absolute(self._dec_pos_err) > np.absolute(self._dec_neg_err):
            self._dec_err = np.absolute(self._dec_pos_err)
        else:
            self._dec_err = np.absolute(self._dec_neg_err)

        if self.report_type == "trigdat":
            self._K = values[2]
            self._K_pos_err = pos_error[2]
            self._K_neg_err = neg_error[2]

            if np.absolute(self._K_pos_err) > np.absolute(self._K_neg_err):
                self._K_err = np.absolute(self._K_pos_err)
            else:
                self._K_err = np.absolute(self._K_neg_err)

            self._index = values[3]
            self._index_pos_err = pos_error[3]
            self._index_neg_err = neg_error[3]

            if np.absolute(self._index_pos_err) > np.absolute(self._index_neg_err):
                self._index_err = np.absolute(self._index_pos_err)
            else:
                self._index_err = np.absolute(self._index_neg_err)

            try:
                self._xc = values[4]
                self._xc_pos_err = pos_error[4]
                self._xc_neg_err = neg_error[4]
                if np.absolute(self._xc_pos_err) > np.absolute(self._xc_neg_err):
                    self._xc_err = np.absolute(self._xc_pos_err)
                else:
                    self._xc_err = np.absolute(self._xc_neg_err)
                self._model = "cpl"
            except:
                self._model = "pl"

        elif self.report_type == "tte":
            self._model = "band"
            self._K = values[2]
            self._K_pos_err = pos_error[2]
            self._K_neg_err = neg_error[2]

            if np.absolute(self._K_pos_err) > np.absolute(self._K_neg_err):
                self._K_err = np.absolute(self._K_pos_err)
            else:
                self._K_err = np.absolute(self._K_neg_err)

            self._alpha = values[3]
            self._alpha_pos_err = pos_error[3]
            self._alpha_neg_err = neg_error[3]

            if np.absolute(self._alpha_pos_err) > np.absolute(self._alpha_neg_err):
                self._alpha_err = np.absolute(self._alpha_pos_err)
            else:
                self._alpha_err = np.absolute(self._alpha_neg_err)

            self._xp = values[4]
            self._xp_pos_err = pos_error[4]
            self._xp_neg_err = neg_error[4]

            if np.absolute(self._xp_pos_err) > np.absolute(self._xp_neg_err):
                self._xp_err = np.absolute(self._xp_pos_err)
            else:
                self._xp_err = np.absolute(self._xp_neg_err)

            self._beta = values[5]
            self._beta_pos_err = pos_error[5]
            self._beta_neg_err = neg_error[5]

            if np.absolute(self._beta_pos_err) > np.absolute(self._beta_neg_err):
                self._beta_err = np.absolute(self._beta_pos_err)
            else:
                self._beta_err = np.absolute(self._beta_neg_err)

        else:
            raise UnkownReportType(
                "The specified report type is not valid. Valid report types: (trigdat, tte)"
            )

    def _read_trigger(self, trigger_file):
        with open(trigger_file, "r") as f:
            data = yaml.safe_load(f)

            self._trigger_number = data["trigger_number"]
            self._trigger_timestamp = data["trigger_time"]

            self._most_likely = f"{data['most_likely']} {data['most_likely_prob']}%"
            self._second_most_likely = (
                f"{data['most_likely_2']} {data['most_likely_prob_2']}%"
            )

            self._swift = check_swift(
                datetime.strptime(self._trigger_timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
            )
            # self._swift = {"ra": convert_to_float(swift[ra]),
            #               "dec": convert_to_float(swift[dec]),
            #               "trigger": int(swift["trigger"])}

    def _read_time_selection(self, time_selection_file):
        with open(time_selection_file, "r") as f:
            data = yaml.safe_load(f)

            self._bkg_neg_start = data["background_time"]["before"]["start"]
            self._bkg_neg_stop = data["background_time"]["before"]["stop"]
            self._bkg_pos_start = data["background_time"]["after"]["start"]
            self._bkg_pos_stop = data["background_time"]["after"]["stop"]
            self._active_time_start = data["active_time"]["start"]
            self._active_time_stop = data["active_time"]["stop"]
            self._poly_order = data["poly_order"]

    def _read_background_fit(self, background_fit_file):
        with open(background_fit_file, "r") as f:
            data = yaml.safe_load(f)
            self._used_detectors = data["use_dets"]

    def _read_post_equal_weights_file(self, post_equal_weights_file):
        # Sometimes chainconsumer does not give an error - In this case we will need the errors from the
        # 3ml fits files
        (
            self._ra,
            ra_err,
            self._dec,
            dec_err,
            self._balrog_one_sig_err_circle,
            self._balrog_two_sig_err_circle,
        ) = get_best_fit_with_errors(post_equal_weights_file, self._model)

        if ra_err is not None:
            self._ra_err = ra_err

        if dec_err is not None:
            self._dec_err = dec_err

    def _sep_bright_sources(self):
        # for the case of certification errror
        if not os.environ.get("PYTHONHTTPSVERIFY", "") and getattr(
            ssl, "_create_unverified_context", None
        ):
            ssl._create_default_https_context = ssl._create_unverified_context

        # read in table from website
        url = "https://swift.gsfc.nasa.gov/results/transients/BAT_current.html"
        table_MN = pd.read_html(url)
        df = table_MN[0]

        # delete unwanted string
        df.rename(columns={"Peak*": "Peak"}, inplace=True)

        # filter by peak value
        df = df.drop(df[df.Peak == "-"].index)
        df = df.astype({"Peak": int})
        df_filtered = df[df["Peak"] > 400]

        # for table of catalog
        table = Table.from_pandas(df_filtered)
        # table.show_in_browser(jsviewer=True)

        # transform input in SkyCoord
        position = SkyCoord(self._ra * unit.deg, self._dec * unit.deg, frame="icrs")

        # transform table data in SkyCoord
        coords = []
        for i in range(len(df_filtered["RA J2000 Degs"])):
            ra = table[i]["RA J2000 Degs"]
            dec = table[i]["Dec J2000 Degs"]
            coords.append(SkyCoord(ra * unit.deg, dec * unit.deg, frame="icrs"))

        # get separation value
        separations = []
        for i in coords:
            z = i.separation(position)
            separations.append(z.to(unit.deg))

        # for table of separations
        table["Separation Degs"] = separations
        table.round(3)
        table.sort("Separation Degs")
        # table.show_in_browser(jsviewer=True)

        # create dictionary
        dic = {}
        for i in range(3):
            # dic[table[i]['Source Name']]={"ra":table[i]['RA J2000 Degs'],
            # "dec":table[i]['Dec J2000 Degs'], "separation":table[i]["Separation Degs"]}
            dic[str(table[i]["Source Name"])] = {
                "ra": float(table[i]["RA J2000 Degs"]),
                "dec": float(table[i]["Dec J2000 Degs"]),
                "separation": float(table[i]["Separation Degs"]),
            }

        self._dic_bright_sources = dic

    def _sep_SGRs(self):
        try:
            # get csv data from website
            url = "http://www.physics.mcgill.ca/~pulsar/magnetar/TabO1.csv"
            r = requests.get(url, allow_redirects=True)
            open("SGRList.csv", "wb").write(r.content)
        except Exception as e:
            print(f"Could not load SGR csv from {url} and failed with {e}")
            pass
        df = pd.read_csv("SGRList.csv")

        # for table of catalog
        table = Table.from_pandas(df)

        # transform table data in SkyCoord
        coords = []
        for i in range(len(df["RA"])):
            hour_ra = Angle(table[i]["RA"] + " hours")
            ra = hour_ra.to(unit.deg)
            arc_dec = table[i]["Decl"]
            dec = Angle(tuple(map(float, arc_dec.split(" "))), unit=unit.deg)
            coords.append(SkyCoord(ra, dec, frame="icrs"))

        # transform input in SkyCoord
        position = SkyCoord(self._ra * unit.deg, self._dec * unit.deg, frame="icrs")

        # get separation value
        separations = []
        for i in coords:
            z = i.separation(position)
            separations.append(z.to(unit.deg))

        # for table of separations
        table["Separation Degs"] = separations
        table["Coords Degs"] = coords
        table.round(3)
        table.sort("Separation Degs")
        # table.show_in_browser(jsviewer=True)

        # create dictionary
        dic = {}
        for i in range(3):
            dic[str(table[i]["Name"])] = {
                "ra": float(round(table[i]["Coords Degs"].ra.degree, 3)),
                "dec": float(round(table[i]["Coords Degs"].dec.degree, 3)),
                "separation": float(table[i]["Separation Degs"]),
            }

        self._dic_SGRs = dic

    def _build_report(self):
        self._report = {
            "general": {
                "grb_name": f"{self.grb_name}",
                "grb_name_gcn": f"{self._grb_name_gcn}",
                "report_type": f"{self.report_type}",
                "version": f"{self.version}",
                "trigger_number": self._trigger_number,
                "trigger_timestamp": self._trigger_timestamp,
                "data_timestamp": self._data_timestamp,
                "localization_timestamp": datetime.utcnow().strftime(
                    "%Y-%m-%dT%H:%M:%S.%fZ"
                ),
                "most_likely": self._most_likely,
                "second_most_likely": self._second_most_likely,
                "swift": self._swift,
            },
            "fit_result": {
                "model": self._model,
                "ra": convert_to_float(self._ra),
                "ra_err": convert_to_float(self._ra_err),
                "dec": convert_to_float(self._dec),
                "dec_err": convert_to_float(self._dec_err),
                "spec_K": convert_to_float(self._K),
                "spec_K_err": convert_to_float(self._K_err),
                "spec_index": convert_to_float(self._index),
                "spec_index_err": convert_to_float(self._index_err),
                "spec_xc": convert_to_float(self._xc),
                "spec_xc_err": convert_to_float(self._xc_err),
                "spec_alpha": convert_to_float(self._alpha),
                "spec_alpha_err": convert_to_float(self._alpha_err),
                "spec_xp": convert_to_float(self._xp),
                "spec_xp_err": convert_to_float(self._xp_err),
                "spec_beta": convert_to_float(self._beta),
                "spec_beta_err": convert_to_float(self._beta_err),
                "sat_phi": convert_to_float(self._phi_sat),
                "sat_theta": convert_to_float(self._theta_sat),
                "balrog_one_sig_err_circle": convert_to_float(
                    self._balrog_one_sig_err_circle
                ),
                "balrog_two_sig_err_circle": convert_to_float(
                    self._balrog_two_sig_err_circle
                ),
            },
            "time_selection": {
                "bkg_neg_start": self._bkg_neg_start,
                "bkg_neg_stop": self._bkg_neg_stop,
                "bkg_pos_start": self._bkg_pos_start,
                "bkg_pos_stop": self._bkg_pos_stop,
                "active_time_start": self._active_time_start,
                "active_time_stop": self._active_time_stop,
                "used_detectors": self._used_detectors,
            },
            "separation_values": {
                "bright_sources": self._dic_bright_sources,
                "SGRs": self._dic_SGRs,
                "Sun": {
                    "sun_separation": convert_to_float(self._sun_sep_center),
                    "sun_within_error": bool(self._sun_sep_error),
                },
            },
        }

    def save_result_yml(self, file_path):
        with open(file_path, "w") as f:
            yaml.dump(self._report, f, default_flow_style=False)

    def __repr__(self):
        """
        Examine the balrog results.
        """

        print(f"Result Reader for {self.grb_name}")
        return self._report

    @property
    def ra(self):
        return self._ra, self._ra_err

    @property
    def dec(self):
        return self._dec, self._dec_err

    @property
    def K(self):
        return self._K, self._K_err

    @property
    def alpha(self):
        return self._alpha, self._alpha_err

    @property
    def xp(self):
        return self._xp, self._xp_err

    @property
    def beta(self):
        return self._beta, self._beta_err

    @property
    def index(self):
        return self._index, self._index_err

    @property
    def xc(self):
        return self._xc, self._xc_err

    @property
    def model(self):
        return self._model


model_param_lookup = {
    "pl": ["ra (deg)", "dec (deg)", "K", "index"],
    "cpl": ["ra (deg)", "dec (deg)", "K", "index", "xc"],
    "sbpl": ["ra (deg)", "dec (deg)", "K", "alpha", "break", "beta"],
    "band": ["ra (deg)", "dec (deg)", "K", "alpha", "xp", "beta"],
    "solar_flare": [
        "ra (deg)",
        "dec (deg)",
        "K-bl",
        "xb-bl",
        "alpha-bl",
        "beta-bl",
        "K-brems",
        "Epiv-brems",
        "kT-brems",
    ],
}


def check_letter(trigger_number, grb_name):
    """Method to get the GRB Name from the GCN Archive"""
    the_alphabet = "abcdefghijklmnopqrstuvwxyz"
    url = "https://gcn.nasa.gov/circulars"

    response = urllib.request.urlopen(url)
    page = response.read().decode()
    split_page = page.split('{"page":1,"items":[')
    # get the hidden json representation
    json_part = split_page[1].split('],"totalPages')[0]
    # get the entries
    l = json_part.split("{")
    # just the ones containing actual data
    ls = l[1:-1]
    # list for all GRBs on first pagge
    grbs = []
    # iterate over the entries
    for x in ls:
        if grb_name.strip("GRB")[:-3] in x:
            grbs.append(x.strip("},"))
    # get the gcn numbers for all grb notices
    gcn_ids = []
    for x in grbs:
        y = x.strip('"')
        y = y.split(",")
        gcn_ids.append(y[0].strip('circularId":"'))

    grbs_today = []
    for x in range(len(gcn_ids) - 1, 0, -1):
        x = gcn_ids[x]
        # open the json file of the gcn
        with urllib.request.urlopen(f"{url}/{x}.json") as f:
            data = json.load(f)
        subject = data["subject"]

        # check if the our grb date is in the subject
        if grb_name[3:-3] in subject:
            # check if its is from the huntsville team
            if "Fermi GBM" in subject:
                # if its from the huntsville team check if the trigger number matches
                # if so we have a direct match
                if trigger_number in data["body"]:
                    gcn = str(data["eventId"]).split()
                    gcn = "".join(gcn)
                    return gcn
            else:
                # check if it has a eventId field (should always be true but if not
                # we show that we are not pleased with it)
                if "eventId" in data.keys():
                    gcn = str(data["eventId"]).split()
                    gcn = "".join(gcn)
                    letter = gcn[-1]
                    # check if the last char is a letter and not yet mentioned before
                    if letter not in grbs_today and letter.lower() in the_alphabet:
                        grbs_today.append(letter.lower())
                else:
                    print("WTF", data)
    # if we do not have any grbs from today we assume it's the first one
    if len(grbs_today) == 0:
        return grb_name[:-3] + "A???"
    else:
        # otherwise we add one to the last mentioned letter
        gt = sorted(grbs_today)
        last = gt[-1]
        last_index = the_alphabet.index(last)
        return grb_name[:-3] + the_alphabet[last_index + 1].upper() + "???"


def get_best_fit_with_errors(post_equal_weigts_file, model):
    """
    load fit results and get best fit and errors
    :return:
    """
    chain = loadtxt2d(post_equal_weigts_file)

    parameter = model_param_lookup[model]

    # RA-DEC plot
    c2 = ChainConsumer()

    c2.add_chain(chain[:, :-1], parameters=parameter).configure(
        plot_hists=False,
        contour_labels="sigma",
        colors="#cd5c5c",
        flip=False,
        max_ticks=3,
    )

    # Calculate err radius #
    chains, parameters, truth, extents, blind, log_scales = c2.plotter._sanitise(
        None, None, None, None, color_p=True, blind=None
    )

    summ = c2.analysis.get_summary(
        parameters=["ra (deg)", "dec (deg)"], chains=chains, squeeze=False
    )[0]
    ra = summ["ra (deg)"][1]
    try:
        ra_pos_err = summ["ra (deg)"][2] - summ["ra (deg)"][1]
        ra_neg_err = summ["ra (deg)"][1] - summ["ra (deg)"][0]

        if np.absolute(ra_pos_err) > np.absolute(ra_neg_err):
            ra_err = np.absolute(ra_pos_err)
        else:
            ra_err = np.absolute(ra_neg_err)

    except:
        ra_err = None

    dec = summ["dec (deg)"][1]

    try:
        dec_pos_err = summ["dec (deg)"][2] - summ["dec (deg)"][1]
        dec_neg_err = summ["dec (deg)"][1] - summ["dec (deg)"][0]

        if np.absolute(dec_pos_err) > np.absolute(dec_neg_err):
            dec_err = np.absolute(dec_pos_err)
        else:
            dec_err = np.absolute(dec_neg_err)

    except:
        dec_err = None

    hist, x_contour, y_contour = c2.plotter._get_smoothed_histogram2d(
        chains[0], "ra (deg)", "dec (deg)"
    )  # ra, dec in deg here

    hist[hist == 0] = 1e-16
    val_contour = c2.plotter._convert_to_stdev(hist.T)

    mask = val_contour < 0.68
    points = []
    for i in range(len(mask)):
        for j in range(len(mask[i])):
            if mask[i][j]:
                points.append([x_contour[j], y_contour[i]])
    points = np.array(points)
    best_fit_point = [ra, dec]
    best_fit_point_vec = [
        np.cos(best_fit_point[1] * np.pi / 180)
        * np.cos(best_fit_point[0] * np.pi / 180),
        np.cos(best_fit_point[1] * np.pi / 180)
        * np.sin(best_fit_point[0] * np.pi / 180),
        np.sin(best_fit_point[1] * np.pi / 180),
    ]
    alpha_largest = 0

    for point_2 in points:
        point_2_vec = [
            np.cos(point_2[1] * np.pi / 180) * np.cos(point_2[0] * np.pi / 180),
            np.cos(point_2[1] * np.pi / 180) * np.sin(point_2[0] * np.pi / 180),
            np.sin(point_2[1] * np.pi / 180),
        ]
        alpha = np.arccos(np.dot(point_2_vec, best_fit_point_vec)) * 180 / np.pi
        if alpha > alpha_largest:
            alpha_largest = alpha
    alpha_one_sigma = alpha_largest

    mask = val_contour < 0.95
    points = []
    for i in range(len(mask)):
        for j in range(len(mask[i])):
            if mask[i][j]:
                points.append([x_contour[j], y_contour[i]])
    points = np.array(points)
    alpha_largest = 0

    for point_2 in points:
        point_2_vec = [
            np.cos(point_2[1] * np.pi / 180) * np.cos(point_2[0] * np.pi / 180),
            np.cos(point_2[1] * np.pi / 180) * np.sin(point_2[0] * np.pi / 180),
            np.sin(point_2[1] * np.pi / 180),
        ]
        alpha = np.arccos(np.dot(point_2_vec, best_fit_point_vec)) * 180 / np.pi
        if alpha > alpha_largest:
            alpha_largest = alpha
    alpha_two_sigma = alpha_largest

    return ra, ra_err, dec, dec_err, alpha_one_sigma, alpha_two_sigma


def loadtxt2d(intext):
    try:
        return np.loadtxt(intext, ndmin=2)
    except:
        return np.loadtxt(intext)


def convert_to_float(value):
    if value is not None:
        return float(value)
    else:
        return None


def utc(met):
    """
    get utc time from met time
    :return:
    """
    time = GBMTime.from_MET(met)
    return time.time.fits
