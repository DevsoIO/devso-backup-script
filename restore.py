import io
import os
import sys
import mysql.connector
import configparser
import time
from Crypto.Cipher import AES
import boto3
from Crypto.Random import get_random_bytes

if len(sys.argv) < 2:
    print("No arguments provided")
    exit(1)

try:
    config = configparser.ConfigParser()
    config.read('config.ini')
    encryption_key = config.get('backup_settings', 'encryption_key', fallback='')

    nonce = get_random_bytes(16)

    prefix = config.get('backup_settings', 'upload_prefix', fallback='')

    if encryption_key == '':
        print("Encryption key not specified")
        exit(1)
    if prefix == '':
        print("Prefix key not specified")
        exit(1)

    download_file_name = sys.argv[1]
    download_path = f"{prefix}/{download_file_name}"
    print("Download path: " + download_path)

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

    with open('encrypted_file', 'wb') as file:
        s3.download_fileobj(bucket_name, download_path, file)

    # Read the nonce and tag from the encrypted file
    with open('encrypted_file', 'rb') as file:
        nonce, tag, ciphertext = [file.read(x) for x in (16, 16, -1)]     # Nonce and tag are each 16 bytes

    cipher = AES.new(encryption_key.encode(), AES.MODE_GCM, nonce=nonce)

    plaintext = cipher.decrypt_and_verify(ciphertext, tag)

    with open(download_file_name, 'wb') as file:
        file.write(plaintext)

    # remove the encrypted file
    os.system(f"rm -f encrypted_file")
    exit(0)
except Exception as e:
    print(f"Failed to restore file. Error: {e}")
    exit(1)
