import os
import subprocess
import paramiko
import time
from datetime import datetime

# ==========================================
# CONFIGURATION
# ==========================================
REPO_DIR = '/home/sac/Documents/python_script/bihar_flood_automate' 
OPERATION_FILE = os.path.join(REPO_DIR, 'operation.txt')
ZIP_DIR = os.path.join(REPO_DIR, 'bihar_flood_Zip')

# SFTP/SCP Settings
SFTP_HOST = '192.168.2.137'
SFTP_PORT = 22
SFTP_USER = 'sac'
SFTP_PASS = 'sac@123'    # <-- UPDATE THIS
SFTP_REMOTE_DIR = '/home/sac/Documents/new_bihar/bihar_flood_Zip/'

# Loop interval in minutes
INTERVAL_MINUTES = 15
# ==========================================

def run_git_pull():
    """Executes a git pull command in the repository directory."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [+] Executing 'git pull' to check for updates...")
    try:
        result = subprocess.run(
            ['git', 'pull'], 
            cwd=REPO_DIR, 
            check=True, 
            text=True, 
            capture_output=True
        )
        if "Already up to date." not in result.stdout:
            print(result.stdout.strip())
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [+] Git pull downloaded new changes.")
    except subprocess.CalledProcessError as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [-] Git pull failed:\n{e.stderr}")

def check_operation_status():
    """Reads operation.txt to determine if file copying should run."""
    if not os.path.exists(OPERATION_FILE):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [-] {OPERATION_FILE} not found. Defaulting to 'off'.")
        return False

    with open(OPERATION_FILE, 'r') as file:
        status = file.read().strip().lower()

    return status == 'on'

def upload_new_zips():
    """Finds zip files and securely copies only the ones missing from the server."""
    if not os.path.exists(ZIP_DIR):
        return

    zip_files = [f for f in os.listdir(ZIP_DIR) if f.endswith('.zip')]
    if not zip_files:
        return

    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USER, password=SFTP_PASS)
        sftp = paramiko.SFTPClient.from_transport(transport)

        try:
            remote_files = sftp.listdir(SFTP_REMOTE_DIR)
        except IOError:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [-] Remote directory {SFTP_REMOTE_DIR} not found. Creating it...")
            sftp.mkdir(SFTP_REMOTE_DIR)
            remote_files = []

        new_uploads_count = 0
        for zip_name in zip_files:
            if zip_name in remote_files:
                continue 
                
            local_path = os.path.join(ZIP_DIR, zip_name)
            remote_path = f"{SFTP_REMOTE_DIR.rstrip('/')}/{zip_name}"
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [+] Copying new file: {zip_name} to server...")
            sftp.put(local_path, remote_path)
            new_uploads_count += 1
            
        if new_uploads_count > 0:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [+] Successfully copied {new_uploads_count} new file(s).")
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [*] All zip files are already on the server.")

        sftp.close()
        transport.close()
        
    except paramiko.AuthenticationException:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [-] Authentication failed. Check your password.")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [-] Copy failed: {e}")

def main():
    print(f"=== Started Bihar Flood Automation Loop (Checking every {INTERVAL_MINUTES} minutes) ===")
    
    while True:
        try:
            # 1. ALWAYS pull first so we get the latest operation.txt from GitHub
            run_git_pull()
            
            # 2. THEN check if the file says 'on' or 'off'
            if check_operation_status():
                upload_new_zips()
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [*] Operation is OFF. Skipping file copy to server.")
                
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [-] Unexpected error in loop: {e}")
            
        # Wait for 15 minutes before checking GitHub again
        time.sleep(INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    main()
