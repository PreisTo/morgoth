import imaplib2
import email
import yaml
from morgoth.utils.log import logger
from morgoth.utils.mail_utils import create_database_table, get_url, add_entry
from morgoth.configuration import morgoth_config

with open(".env", "r") as f:
    config = yaml.safe_load(f)


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


def check_mail(sender, subject, body):
    """
    Checks the mail if relevant for morgoth
    """
    raise NotImplementedError()
    grb = None
    dtype = None
    det = None
    version = None
    url = None
    # Add check if not
    if get_url(grb, dtype, det, version) is not None:
        add_entry(grb, dtype, det, version, url)


create_database_table()
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

print("Waiting for new mail...")

while True:
    try:
        mail.idle()  # defaults to 29min timeout
        status, data = mail.search(None, "ALL")
        mail_ids = data[0].split()
        latest_id = int(mail_ids[-1].decode("utf-8"))
        if latest_id > latest_id_tmp:
            print("Got mail")
            for id in range(latest_id_tmp + 1, latest_id + 1, 1):
                status, msg_data = mail.fetch(str(id).encode("utf-8"), "(RFC822)")
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                from_user = decode_field(msg["From"])
                subject = decode_field(msg["Subject"])
                body = get_body(msg)
                check_mail()
        latest_id_tmp = latest_id
    except Exception as e:
        logger.info(f"Got exception {e} while waiting for new mail ...")
        logger.info("Will logout and retry")
