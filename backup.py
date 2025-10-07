# ---------------------------------------------------------------------------------------
# Devso (C) 2024 All rights reserved
# File : backup.py
# Description : Back up all mysql/mariadb databases, archive, encrypt and upload to
# Cloudflare R2
#
# ---------------------------------------------------------------------------------------
# Disclaimer:
#
# The software is provided "as is", without warranty of any kind, express or implied,
# including but not limited to the warranties of merchantability, fitness for a
# particular purpose and noninfringement. In no event shall the authors or copyright
# holders be liable for any claim, damages or other liability, whether in an action
# of contract, tort or otherwise, arising from, out of or in connection with the
# software or the use or other dealings in the software.
#
# The user assumes all responsibility for data loss, back-up recovery, service outages
# and any other potential issues that may arise from the use of this software.
# ---------------------------------------------------------------------------------------
# ---------------------------------------------------------------------------------------
import io
import os
import sys
import time
import traceback
import configparser
import mysql.connector
from Crypto.Cipher import AES
import boto3
from datadog import initialize, api

CHUNK_SIZE = 1024 * 1024  # 1 MiB


def uploaded_to_cloudflare_r2(encrypted_file_path: str, file_name: str) -> bool:
    try:
        print("Uploading to Cloudflare R2")
        endpoint = config.get("cloudflare_r2", "api_endpoint", fallback="")
        access_key_id = config.get("cloudflare_r2", "access_key_id", fallback="")
        secret_access_key = config.get("cloudflare_r2", "secret_access_key", fallback="")
        upload_prefix = config.get("backup_settings", "upload_prefix", fallback="")
        bucket_name = config.get("cloudflare_r2", "bucket_name", fallback="")
        region_name = config.get("cloudflare_r2", "region_name", fallback="")

        if endpoint == "":
            print("No Cloudflare R2 API endpoint specified")
            return False
        if access_key_id == "":
            print("No Cloudflare R2 access key ID specified")
            return False
        if secret_access_key == "":
            print("No Cloudflare R2 secret access key specified")
            return False
        if upload_prefix == "":
            print("No Cloudflare R2 upload prefix specified")
            return False
        if bucket_name == "":
            print("No Cloudflare R2 bucket name specified")
            return False
        if region_name == "":
            print("No Cloudflare R2 region name specified")
            return False

        s3 = boto3.client(
            service_name="s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region_name,
        )
        upload_name = f"{upload_prefix}/{file_name}"

        # Stream upload (no in-memory buffering)
        with open(encrypted_file_path, "rb") as f:
            s3.upload_fileobj(f, bucket_name, upload_name)

        print("Successfully uploaded to R2, removing local file")
        try:
            os.remove(encrypted_file_path)
        except Exception as rm_err:
            print(f"Warning: failed to remove local file: {rm_err}")

        submitDatadogEvent(
            "Devso Backup Completed", "Devso backup completed", "success"
        )
        return True
    except Exception as e:
        print(f"Failed to submit to Cloudflare R2. Error: {type(e).__name__}: {e}")
        traceback.print_exc()
        submitDatadogEvent(
            "Devso Database Backup Failed",
            f"Devso database backup failed: {type(e).__name__}: {e}",
            "error",
        )
        return False


def submitDatadogEvent(title: str, text: str, alert_type: str) -> None:
    try:
        print("Submitting event to datadog")
        enabled = config.getboolean("datadog", "enabled", fallback=False)
        if not enabled:
            print("Datadog is not enabled")
            return

        api_key = config.get("datadog", "api_key", fallback="")
        app_key = config.get("datadog", "app_key", fallback="")
        tag = config.get("datadog", "host_tag", fallback="")

        if api_key == "":
            print("Datadog API key not specified")
            return
        if app_key == "":
            print("Datadog app key not specified")
            return

        options = {"api_key": api_key, "app_key": app_key}
        initialize(**options)

        tags = [f"host:{tag}"] if tag else []

        event = {
            "title": title,
            "text": text,
            "tags": tags,
            "alert_type": alert_type,
            "host": tag,
        }

        api.Event.create(**event)
    except Exception as e:
        print(f"Failed to submit datadog event: {type(e).__name__}: {e}")
        traceback.print_exc()


def encrypt_file_gcm_streaming(in_path: str, out_path: str, key: bytes) -> None:
    # Use a 12-byte nonce for GCM
    nonce = os.urandom(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)

    # Write nonce first, then ciphertext chunks, then tag at the end
    with open(in_path, "rb") as fin, open(out_path, "wb") as fout:
        fout.write(nonce)

        while True:
            chunk = fin.read(CHUNK_SIZE)
            if not chunk:
                break
            ct = cipher.encrypt(chunk)
            fout.write(ct)

        tag = cipher.digest()
        fout.write(tag)


try:
    config = configparser.ConfigParser()
    config.read("config.ini")

    server = config.get("database", "server", fallback="localhost")
    user = config.get("database", "username", fallback="")
    password = config.get("database", "password", fallback="")
    encryption_key = config.get("backup_settings", "encryption_key", fallback="")

    if user == "":
        print("Backup username not provided", file=sys.stderr)
        sys.exit(1)
    if password == "":
        print("Backup password not provided", file=sys.stderr)
        sys.exit(1)
    if encryption_key == "":
        print("Encryption key not provided", file=sys.stderr)
        sys.exit(1)

    if len(encryption_key) != 32:
        print("Encryption needs to be 32 characters in length")
        sys.exit(1)

    encryption_key = encryption_key.encode()

    backup_dir = config.get("backup_settings", "backup_dir", fallback="./backup")
    print("got backup dir: " + backup_dir)

    backup_sql_dir = f"{backup_dir}/sql"

    # Connect to the MySQL database with explicit charset
    cnx = mysql.connector.connect(
        user=user,
        password=password,
        host=server or "localhost",
        port=3306,
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
    )
    cursor = cnx.cursor()

    # Get a list of all databases (excluding system schemas)
    cursor.execute("SHOW DATABASES")
    databases = [
        row[0]
        for row in cursor
        if row[0] not in ["mysql", "information_schema", "performance_schema", "sys"]
    ]

    # Timestamp
    timestamp = time.strftime("%Y%m%d%H%M%S")

    # Ensure dirs
    os.makedirs(backup_dir, exist_ok=True)
    os.makedirs(backup_sql_dir, exist_ok=True)

    # Loop through databases and dump + gzip
    for database in databases:
        print(f"Backing up database {database}")
        filename = f"{database}_{timestamp}.sql"
        dump_path = f"{backup_sql_dir}/{filename}"
        cmd = (
            f"mysqldump --routines --default-character-set=utf8mb4 "
            f"-u{user} -p{password} {database} > {dump_path}"
        )
        print(cmd)
        rc = os.system(cmd)
        if rc != 0:
            raise RuntimeError(f"mysqldump failed for {database} with rc={rc}")
        rc = os.system(f"gzip {dump_path}")
        if rc != 0:
            raise RuntimeError(f"gzip failed for {dump_path} with rc={rc}")

    print("Closing database")
    cursor.close()
    cnx.close()

    print("Creating archive")
    # Tar all .sql.gz into a single archive
    unencrypted_backup_file = f"{backup_dir}/db_backup_{timestamp}_unencrypted.tgz"
    encrypted_backup_file = f"{backup_dir}/db_backup_{timestamp}.tgz"
    rc = os.system(f"tar -czvf {unencrypted_backup_file} {backup_sql_dir}/*")
    if rc != 0:
        raise RuntimeError("tar failed to create archive")

    print("Removing individual backup files")
    os.system(f"rm -f {backup_sql_dir}/*.sql.gz")

    # Stream-encrypt the archive to avoid MemoryError
    print("Encrypting archive")
    encrypt_file_gcm_streaming(
        in_path=unencrypted_backup_file,
        out_path=encrypted_backup_file,
        key=encryption_key,
    )

    print("File successfully archived, removing unencrypted file")
    try:
        os.remove(unencrypted_backup_file)
    except Exception as rm_err:
        print(f"Warning: failed to remove unencrypted file: {rm_err}")

    # Upload to R2
    endpoint = config.get("cloudflare_r2", "api_endpoint", fallback="")
    access_key_id = config.get("cloudflare_r2", "access_key_id", fallback="")
    secret_access_key = config.get("cloudflare_r2", "secret_access_key", fallback="")
    upload_prefix = config.get("backup_settings", "upload_prefix", fallback="")
    bucket_name = config.get("cloudflare_r2", "bucket_name", fallback="")
    region_name = config.get("cloudflare_r2", "region_name", fallback="")

    if endpoint == "":
        print("No Cloudflare R2 API endpoint specified")
        sys.exit(1)
    if access_key_id == "":
        print("No Cloudflare R2 access key ID specified")
        sys.exit(1)
    if secret_access_key == "":
        print("No Cloudflare R2 secret access key specified")
        sys.exit(1)
    if upload_prefix == "":
        print("No Cloudflare R2 upload prefix specified")
        sys.exit(1)
    if bucket_name == "":
        print("No Cloudflare R2 bucket name specified")
        sys.exit(1)
    if region_name == "":
        print("No Cloudflare R2 region name specified")
        sys.exit(1)

    if uploaded_to_cloudflare_r2(
        encrypted_backup_file, f"db_backup_{timestamp}.tgz"
    ):
        print("Backup completed successfully")
    else:
        print("Backup didn't complete successfully")

    sys.exit(0)
except Exception as e:
    print(f"Failed to complete database backup: {type(e).__name__}: {e}")
    traceback.print_exc()
    submitDatadogEvent(
        "Devso Database Backup Failed",
        f"Devso database backup failed: {type(e).__name__}: {e}\n{traceback.format_exc()}",
        "error",
    )