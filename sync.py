import os
import subprocess
import paramiko
import time
import logging
from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError
from datetime import datetime


# ==========================================
# Logging module configuration 
# ==========================================

logging.basicConfig(
    level=logging.INFO, # Set to INFO in production
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("GitMonitor")
#TODO add file based logger output


# ==========================================
# CONFIGURATION
# ==========================================
REPO_DIR = '/home/sac/Documents/python_script/bihar_flood_automate' 
OPERATION_FILE = os.path.join(REPO_DIR, 'operation.txt')
ZIP_DIR = REPO_DIR #os.path.join(REPO_DIR, 'bihar_flood_Zip')

# SFTP/SCP Settings
SFTP_HOST = '192.168.2.137'
SFTP_PORT = 22
SFTP_USER = 'sac'
SFTP_PASS = 'sac@123'    # <-- UPDATE THIS
SFTP_REMOTE_DIR = '/home/sac/Documents/new_bihar/bihar_flood_Zip/'

# Loop interval in minutes
INTERVAL_MINUTES = 15
# ==========================================



def run_git_pull(repo_dir: str=REPO_DIR) -> bool:
    """
    Executes a git pull operation using GitPython with comprehensive logging,
    and automatically restores any locally deleted .zip files.
    
    Args:
        repo_dir (str): Path to the local git repository.
        
    Returns:
        bool: True if new changes were downloaded or missing files were restored, False otherwise.
    """
    logger.info("Executing 'git pull' to check for updates...")
    state_changed = False
    
    try:
        # Bind to the existing repository
        repo = Repo(repo_dir)
        
        if repo.bare:
            logger.error(f"Repository at {repo_dir} is bare. Cannot perform pull.")
            return False

        origin = repo.remotes.origin
        
        # Store current commit hash to compare after pulling
        old_commit = repo.head.commit

        logger.debug(f"Pulling from remote: {origin.url}...")
        pull_infos = origin.pull()

        new_commit = repo.head.commit

        # Check if the commit pointer actually moved
        if old_commit == new_commit:
            logger.info("Repository is already up to date.")
        else:
            logger.info(f"Git pull downloaded new changes. HEAD moved from {old_commit.hexsha[:7]} to {new_commit.hexsha[:7]}.")
            
            # Granular monitoring of what exactly was pulled
            for info in pull_infos:
                logger.debug(f"Updated ref {info.ref.name} (flags: {info.flags})")
            state_changed = True

        # --- Check for and restore missing .zip files ---
        logger.debug("Scanning working directory for missing .zip files...")
        missing_zips = []
        
        # diff(None) compares the Git index (tracked files) to the actual working tree
        for diff in repo.index.diff(None):
            # 'D' indicates the file was deleted locally
            if diff.change_type == 'D' and diff.a_path.endswith('.zip'):
                missing_zips.append(diff.a_path)

        if missing_zips:
            logger.warning(f"Detected {len(missing_zips)} missing .zip file(s) that exist in the repository:")
            for zip_file in missing_zips:
                logger.info(f" -> Restoring missing file: {zip_file}")
                repo.git.checkout('--', zip_file)
            
            logger.info("All missing .zip files have been successfully restored.")
            state_changed = True
        else:
            logger.debug("No locally tracked .zip files are missing.")

        return state_changed

    except InvalidGitRepositoryError:
        logger.critical(f"The directory '{repo_dir}' is not a valid git repository.")
    except GitCommandError as e:
        logger.error(f"Git pull failed with status code {e.status}.")
        logger.debug(f"Git error stderr: {e.stderr.strip()}")
    except Exception as e:
        logger.exception(f"An unexpected error occurred during git operations: {e}")
        
    return False

def run_git_pull_old():
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
        logger.info(f"ZIP dir not found exiting the execution phase")
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
            logger.info("Phase 1: [STARTED] Git pull and recovery")
            run_git_pull()
            logger.info("Phase 1: [ENDED] Git pull and recovery")
            logger.info("Phase 2: [STARTED] Command detection")
            op_status = check_operation_status()
            logger.info("Phase 2: [ENDED] Command detection")
            # 2. THEN check if the file says 'on' or 'off'
            if op_status:
                logger.info("Phase 3: [STARTED] Command execution")
                upload_new_zips()
                logger.info("Phase 3: [ENDED] Command execution")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [*] Operation is OFF. Skipping file copy to server.")
                
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [-] Unexpected error in loop: {e}")
            
        # Wait for 15 minutes before checking GitHub again
        time.sleep(INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    main()
