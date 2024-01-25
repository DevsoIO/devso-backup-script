# Introduction
This project is the database backup script 
for Devso and Devso related products and 
services. 

The script can backup all MySQL and MariaDB
databases, excluding information_schema and
mysql database. 

It creates an sql file for each database 
and then gzip the file, then creates a tar
archive collecting all sql.gz files together
into a single file. 

Once the tar file has been created, it will
then create an encrypted file of the archive
and delete the unencrypted. The encrypted
file will then be uploaded to Cloudflare 
R2, with an optional event being submitted
to Datadog. 

# Installation
In order to install the script you can git clone
the repository at https://github.com/DevsoIO/devso-backup-script
and then cd into the directory and run the command:

```shell
pip install -r requirements.txt
```

How the script is started is up to you, but scheduled
cron job is probably a good way to schedule when you
want the backups to bedone. 

Before starting the script, though ensure that 
`config.ini.example` has been renamed to `config.ini`.
The available configuration settings are described below:

# Configuration File
There are 4 seconds within the config.ini file as 
described below. It is assumed you already know 
how to set up Datadog API keys and Cloudlare R2 Buckets

## database
**server:** The database server host, probably localhost
**username:** The username to connect to the database
**password:** The password to connect to the database

## backup_settings
**backup_dir:** The temporary location where backup
files are created (e.g. where the sql files and 
sql.gz files are stored)
**encryption_key:** The encryption key to encrypt the 
backup archive file with
**upload_prefix:** The prefix to store the archive in
on Cloudflare R2

## cloudflare_r2
**api_endpoint:** The API endpoint to your cloudflare
bucket. e.g. https://<account-id>.eu.r2.cloudflarestorage.com
**access_key_id:** The access key id from your Cloudflare
R2 account
**secret_access_key:** The secret access key from your
Cloudflare R2 account
**region_name:** The region name, can be one of the 
following:

    * wnan
    * enam
    * weur
    * eeur
    * apac

**bucket_name:** The name of the bucket the file
should be uploaded to

## datadog
**enabled:** Whether event should be submitted to 
datadog, defaults to false
**api_key:** The Datadog API key
**app_key:** The Datadog App key
**host_tag:** The host tag that should be submitted
to datadog for the event

# Restoring 
In the event that you need to restore, there is the restore.py script that downloads 
encrypted file from Cloudflare R2 and uses the encryption key to decrypt the file
and recreate the archive. 

You can call this using `python3 restore.py file_name` where file_name is the name
of the file (without the prefix) that you want to download from Cloudflare R2.

---------------------------------------------------------------------------------------
### **Disclaimer:**

The software is provided "as is", without warranty of any kind, express or implied,
including but not limited to the warranties of merchantability, fitness for a
particular purpose and noninfringement. In no event shall the authors or copyright
holders be liable for any claim, damages or other liability, whether in an action
of contract, tort or otherwise, arising from, out of or in connection with the
software or the use or other dealings in the software.

The user assumes all responsibility for data loss, back-up recovery, service outages
and any other potential issues that may arise from the use of this software.
---------------------------------------------------------------------------------------