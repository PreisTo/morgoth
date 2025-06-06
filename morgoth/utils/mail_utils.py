import os
import imaplib2
import email
import yaml
from morgoth.utils.log import logger
from morgoth.configuration import morgoth_config
import boto3
from botocore import UNSIGNED
from botocore.config import Config
from morgoth.utils.env import get_env_value

bucket_name = "nasa-heasarc"
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


def decode_field(header):
    if header is None:
        return ""
    parts = email.header.decode_header(header)
    return "".join(
        str(t[0], t[1] or "utf-8") if isinstance(t[0], bytes) else t[0] for t in parts
    )


def get_body(message):
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            content_dispo = str(part.get("Content-Disposition"))

            if content_type == "text/plain" and "attachment" not in content_dispo:
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="replace")
    else:
        charset = message.get_content_charset() or "utf-8"
        return message.get_payload(decode=True).decode(charset, errors="replace")


def get_available_versions(file_list, grb_name):
    files_to_download = {}
    trigdat_base = f"glg_trigdat_all_{grb_name.lower().replace('grb','bn')}_"
    max_trigdat_version = 5
    trigdats = {}
    for i in range(max_trigdat_version):
        trigdats[f"trigdat.v0{i}"] = trigdat_base + f"v0{i}.fit"
    for k, v in trigdats.items():
        if v in file_list:
            files_to_download[k] = v

    tte_bases = [
        f"glg_tte_{d}_{grb_name.lower().replace('grb','bn')}_v00.fit" for d in lu
    ]
    cspec_bases = [
        f"glg_cspec_{d}_{grb_name.lower().replace('grb','bn')}_v00.pha" for d in lu
    ]
    flag = True
    for t in tte_bases:
        if t not in file_list:
            flag = False
    for c in cspec_bases:
        if c not in file_list:
            flag = False
    if flag:
        files_to_download["tte.v00"] = tte_bases
        files_to_download["tte.v00"] = cspec_bases
    return files_to_download


def check_mail(from_user, subject, body, grb_name):
    if from_user not in ["vfits_public@gs66-vfits.gsfc.nasa.gov"]:
        return None
    if grb_name.lower().replace("grb", "bn") not in body:
        return None
    s3 = boto3.client(
        "s3", config=Config(signature_version=UNSIGNED), region_name="us-east-1"
    )
    year = f"20{grb_name.lower().replace('grb','')[:2]}"
    bucket_name = "nasa-heasarc"
    prefix = f"fermi/data/gbm/triggers/{year}/{grb_name.lower().replace('grb','bn')}/current/"
    response = s3.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
    if "Contents" in response:
        objs = []
        for obj in response["Contents"]:
            objs.append(str(obj["Key"]).replace(prefix, ""))
        return get_available_versions(objs, grb_name), prefix
    else:
        return None


def idle(config, grb_name):
    IMAP_SERVER = config["server"]
    username = config["user"]
    password = config["password"]
    mail = imaplib2.IMAP4_SSL(IMAP_SERVER)
    mail.login(username, password)
    mail.select(config["mailbox"])
    status, data = mail.search(None, "ALL")
    mail_ids = data[0].split()
    latest_id = int(mail_ids[-1].decode("utf-8"))
    latest_id_tmp = latest_id

    logger.warning("Waiting for new mail...")

    while True:
        try:
            mail.idle()  # defaults to 29min timeout
            status, data = mail.search(None, "ALL")
            mail_ids = data[0].split()
            latest_id = int(mail_ids[-1].decode("utf-8"))
            if latest_id > latest_id_tmp:
                for id in range(latest_id_tmp + 1, latest_id + 1, 1):
                    status, msg_data = mail.fetch(str(id).encode("utf-8"), "(RFC822)")
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    from_user = decode_field(msg["From"])
                    subject = decode_field(msg["Subject"])
                    body = get_body(msg)
            latest_id_tmp = latest_id
            files = check_mail(from_user, subject, body, grb_name)
            if files is not None:
                return files
        except Exception as e:
            logger.info(f"Got exception {e} while waiting for new mail ...")
            logger.info("Will logout and retry")


def mail_listener(grb_name, already_run):
    with open(morgoth_config.mail.env_file, "r") as f:
        config = yaml.safe_load(f)
    new_versions = []
    while len(new_versions) < 1:
        versions, prefix = idle(config, grb_name)
        s3 = boto3.client(
            "s3", config=Config(signature_version=UNSIGNED), region_name="us-east-1"
        )
        for k, v in versions.items():
            if k not in already_run:
                new_versions.append(k)
                dtype, version = k.split(".")
                if dtype == "trigdat":
                    download_path = os.path.join(base_dir, grb_name, dtype, v)
                else:
                    download_path = os.path.join(base_dir, grb_name, dtype, "data", v)
                s3.download_file(bucket_name, prefix + v, download_path)

    return new_versions
