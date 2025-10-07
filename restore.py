import os
import sys
import boto3
import configparser
from Crypto.Cipher import AES

if len(sys.argv) < 2:
    print("No arguments provided")
    sys.exit(1)

try:
    config = configparser.ConfigParser()
    config.read("config.ini")

    encryption_key = config.get("backup_settings", "encryption_key", fallback="")
    prefix = config.get("backup_settings", "upload_prefix", fallback="")

    if encryption_key == "":
        print("Encryption key not specified")
        sys.exit(1)
    if prefix == "":
        print("Prefix key not specified")
        sys.exit(1)

    download_file_name = sys.argv[1]  # e.g., db_backup_20250101.tgz
    download_path = f"{prefix}/{download_file_name}"
    print("Download path: " + download_path)

    endpoint = config.get("cloudflare_r2", "api_endpoint", fallback="")
    access_key_id = config.get("cloudflare_r2", "access_key_id", fallback="")
    secret_access_key = config.get("cloudflare_r2", "secret_access_key", fallback="")
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
    if bucket_name == "":
        print("No Cloudflare R2 bucket name specified")
        sys.exit(1)
    if region_name == "":
        print("No Cloudflare R2 region name specified")
        sys.exit(1)

    s3 = boto3.client(
        service_name="s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region_name,
    )

    enc_path = "encrypted_file"
    with open(enc_path, "wb") as f:
        s3.download_fileobj(bucket_name, download_path, f)

    # Our encrypted format is: [12-byte nonce][ciphertext...][16-byte tag]
    with open(enc_path, "rb") as f:
        data = f.read()

    if len(data) < 12 + 16:
        raise ValueError("Encrypted file too small")

    nonce = data[:12]
    tag = data[-16:]
    ciphertext = data[12:-16]

    cipher = AES.new(encryption_key.encode(), AES.MODE_GCM, nonce=nonce)
    plaintext = cipher.decrypt_and_verify(ciphertext, tag)

    with open(download_file_name, "wb") as out:
        out.write(plaintext)

    os.remove(enc_path)
    print("Restore completed:", download_file_name)
    sys.exit(0)

except Exception as e:
    print(f"Failed to restore file. Error: {e}")
    sys.exit(1)