# ---------------------------------------------------------------------------------------
# Devso (C) 2024 All rights reserved
# File : backup.py
# Description : Back up all mysql/mariadb databases, archive, encrypt and upload to Cloudflare R2

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
import mysql.connector
import configparser
import time
from Crypto.Cipher import AES
import boto3
from datadog import initialize, api


def uploaded_to_cloudflare_r2(encrypted_file_path, file_name):
    try:
        print("Uploading to Cloudflare R2")
        endpoint = config.get("cloudflare_r2", "api_endpoint", fallback='')
        access_key_id = config.get("cloudflare_r2", "access_key_id", fallback='')
        secret_access_key = config.get("cloudflare_r2", "secret_access_key", fallback="")
        upload_prefix = config.get('backup_settings', 'upload_prefix', fallback='')
        bucket_name = config.get('cloudflare_r2', 'bucket_name', fallback='')
        region_name = config.get("cloudflare_r2", "region_name", fallback='')

        if endpoint == '':
            print("No Cloudflare R2 API endpoint specified")
            exit(1)
        if access_key_id == '':
            print("No Cloudflare R2 access key ID specified")
            exit(1)
        if secret_access_key == '':
            print("No Cloudflare R2 secret access key specified")
            exit(1)
        if upload_prefix == '':
            print("No Cloudflare R2 upload prefix specified")
            exit(1)
        if bucket_name == '':
            print("No Cloudflare R2 bucket name specified")
            exit(1)
        if region_name == '':
            print("No Cloudflare R2 region name specified")
            exit(1)

        s3 = boto3.client(
            service_name="s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region_name
        )
        upload_name = f"{upload_prefix}/{file_name}"
        with open(encrypted_file_path, 'rb') as file:
            s3.upload_fileobj(io.BytesIO(file.read()), bucket_name, upload_name)
            print("Successfully uploaded to R2, removing local file")
            os.system(f"rm -f {encrypted_file_path}")
            submitDatadogEvent("Devso Backup Completed", f"Devso backup completed", "success")
            return True
    except Exception as e:
        print(f"Failed to submit to Cloudflare R2. Error: {e}")
        submitDatadogEvent("Devso Database Backup Failed", f"Devso database backup failed: {e}", "error")
        return False


def submitDatadogEvent(title, text, alert_type):
    try:
        print("Submitting event to datadog")
        enabled = config.getboolean("datadog", "enabled", fallback=False)
        if not enabled:
            print("Datadog is not enabled")
            exit(0)

        api_key = config.get('datadog', 'api_key', fallback='')
        app_key = config.get('datadog', 'app_key', fallback='')
        tag = config.get('datadog', 'host_tag', fallback='')

        if api_key == "":
            print("Datadog API key not specified")
            exit(1)
        if app_key == "":
            print("Datadog app key not specified")
            exit(1)

        options = {
            "api_key": api_key,
            "app_key": app_key
        }

        initialize(**options)
        if tag != "":
            tags = [f"host:{tag}"]
        else:
            tags = []

        # Create the event with tags
        event = {
            'title': title,
            'text': text,
            'tags': tags,
            'alert_type': alert_type,
            'host': tag
        }

        api.Event.create(**event)
    except Exception as e:
        print(f"Failed to submit datadog event: {e}")

try:
    config = configparser.ConfigParser()

    config.read('config.ini')

    server = config.get('database', 'server', fallback='localhost')
    user = config.get('database', 'username', fallback='')
    password = config.get('database', 'password', fallback='')
    encryption_key = config.get('backup_settings', 'encryption_key', fallback='')

    if user == "":
        print("Backup username not provided", file=sys.stderr)
        exit(1)
    if password == "":
        print("Backup password not provided", file=sys.stderr)
        exit(1)
    if encryption_key == "":
        print("Encryption key not provided", file=sys.stderr)
        exit(1)

    if len(encryption_key) != 32:
        print("Encryption needs to be 32 characters in length")
        exit(1)

    encryption_key = encryption_key.encode()

    backup_dir = config.get('backup_settings', 'backup_dir', fallback='./backup')

    print("got backup dir: " + backup_dir)

    backup_sql_dir = f"{backup_dir}/sql"

    # Connect to the MySQL database
    cnx = mysql.connector.connect(user=user, password=password, host="localhost", port=3306)
    cursor = cnx.cursor()

    # Get a list of all databases (excluding mysql)
    cursor.execute("SHOW DATABASES")
    databases = [row[0] for row in cursor if row[0] not in ['mysql', 'information_schema', 'performance_schema']]

    # Get the current timestamp
    timestamp = time.strftime("%Y%m%d%H%M%S")

    if not os.path.exists(backup_dir):
        os.mkdir(backup_dir)

    if not os.path.exists(backup_sql_dir):
        os.mkdir(backup_sql_dir)

    # Loop through each database and perform a mysqldump
    for database in databases:
        print(f"Backing up database {database}")
        filename = f"{database}_{timestamp}.sql"
        command = f"mysqldump --routines -u{user} -p{password} {database} > {backup_sql_dir}/{filename}"
        print(command)
        os.system(command)
        os.system(f"gzip {backup_sql_dir}/{filename}")

    print("Closing database")
    # Close the connection to the database
    cursor.close()
    cnx.close()

    print("Creating archive")
    # Now tar all .sql.gz file with the current time and delete the sql.gz files
    unencrypted_backup_file = f"{backup_dir}/db_backup_{timestamp}_unencrypted.tgz"
    encrypted_backup_file = f"{backup_dir}/db_backup_{timestamp}.tgz"
    os.system(f"tar -czvf {unencrypted_backup_file} {backup_sql_dir}/*")
    print("Removing individual backup files")
    os.system(f"rm {backup_sql_dir}/*.sql.gz")

    # encrypt the archive ready for upload
    cipher = AES.new(encryption_key, AES.MODE_GCM)
    # Open the existing unencrypted archive
    with open(unencrypted_backup_file, 'rb') as file:
        unencrypted_data = file.read()

    ciphertext, tag = cipher.encrypt_and_digest(unencrypted_data)

    # Write the encrypted file
    with open(encrypted_backup_file, 'wb') as file:
        [file.write(x) for x in (cipher.nonce, tag, ciphertext)]

    print("File successfully archived, removing unencrypted file")
    endpoint = config.get("cloudflare_r2", "api_endpoint", fallback='')
    access_key_id = config.get("cloudflare_r2", "access_key_id", fallback='')
    secret_access_key = config.get("cloudflare_r2", "secret_access_key", fallback="")
    upload_prefix = config.get('backup_settings', 'upload_prefix', fallback='')
    bucket_name = config.get('cloudflare_r2', 'bucket_name', fallback='')
    region_name = config.get("cloudflare_r2", "region_name", fallback='')

    if endpoint == '':
        print("No Cloudflare R2 API endpoint specified")
        exit(1)
    if access_key_id == '':
        print("No Cloudflare R2 access key ID specified")
        exit(1)
    if secret_access_key == '':
        print("No Cloudflare R2 secret access key specified")
        exit(1)
    if upload_prefix == '':
        print("No Cloudflare R2 upload prefix specified")
        exit(1)
    if bucket_name == '':
        print("No Cloudflare R2 bucket name specified")
        exit(1)
    if region_name == '':
        print("No Cloudflare R2 region name specified")
        exit(1)

    if uploaded_to_cloudflare_r2(encrypted_backup_file, f"db_backup_{timestamp}.tgz"):
        print("Backup completed successfully")
    else:
        print("Backup didn't complete successfully")

    exit(0)
except Exception as e:
    print(f"Failed to complete database backup: {e}")
    submitDatadogEvent("Devso Database Backup Failed", f"Devso database backup failed: {e}", "error")